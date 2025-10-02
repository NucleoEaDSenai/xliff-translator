import os
import time
from copy import deepcopy
from typing import List, Tuple, Optional

import streamlit as st
from lxml import etree as ET
from deep_translator import GoogleTranslator
import re

# -------------------- CONFIG UI --------------------
st.set_page_config(page_title="XLIFF → English (Google)", page_icon="🌍", layout="centered")

PRIMARY = "#83c7e5"  # Azul SENAI
st.markdown(f"""
<style>
body {{ background:#000; color:#fff; }}
.block-container {{ padding-top: 1.2rem; max-width: 960px; }}
h1,h2,h3,p,span,div,label {{ color:#fff !important; }}
.stButton>button {{
  background:#333; color:{PRIMARY}; font-weight:700; border:none; border-radius:8px; padding:.6rem 1rem;
}}
.stProgress > div > div > div > div {{ background-color: {PRIMARY}; }}
</style>
""", unsafe_allow_html=True)

st.title("🌍 XLIFF Translator — Google (full content)")
st.caption("Traduz .xlf/.xliff completos (1.2/2.0), preservando tags inline. Sobrescreve source/target, traduz <note> e atributos title/alt/aria-label.")

# -------------------- HELPERS ROBUSTOS --------------------
def safe_str(x) -> str:
    """Garante string (evita None)."""
    return "" if x is None else str(x)

# placeholders/comandos que NÃO devem ser traduzidos
PLACEHOLDER_RE = re.compile(r"(\{\{.*?\}\}|\{.*?\}|%s|%d|%\(\w+\)s)")

def protect_nontranslatable(text: str):
    """Protege {…}, {{…}}, %s etc. com tokens §§K#§§ para não serem mexidos pelo tradutor."""
    text = safe_str(text)
    if not text:
        return "", []
    tokens = []
    def _sub(m):
        tokens.append(m.group(0))
        return f"§§K{len(tokens)-1}§§"
    try:
        protected = PLACEHOLDER_RE.sub(_sub, text)
    except Exception:
        protected = text
    return protected, tokens

def restore_nontranslatable(text: str, tokens):
    text = safe_str(text)
    if not tokens:
        return text
    try:
        def _restore(m):
            idx = int(m.group(1))
            return tokens[idx] if 0 <= idx < len(tokens) else m.group(0)
        return re.sub(r"§§K(\d+)§§", _restore, text)
    except Exception:
        return text

def translate_text_unit(text: str, target_lang: str = "en") -> str:
    """Tradução de uma unidade de texto com proteção de placeholders (Google via deep-translator)."""
    text = safe_str(text)
    if not text.strip():
        return text
    t, toks = protect_nontranslatable(text)
    out = t
    try:
        tr = GoogleTranslator(source="auto", target=target_lang).translate(t)
        out = safe_str(tr)
    except Exception:
        # fallback mantém t
        out = t
    out = restore_nontranslatable(out, toks)
    return safe_str(out)

def get_namespaces(root) -> dict:
    nsmap = {}
    if root.nsmap:
        for k, v in root.nsmap.items():
            nsmap[k if k is not None else "ns"] = v
    if not nsmap:
        nsmap = {"ns": "urn:oasis:names:tc:xliff:document:1.2"}
    return nsmap

def detect_version(root) -> str:
    default_ns = root.nsmap.get(None, "") or ""
    if "urn:oasis:names:tc:xliff:document:2.0" in default_ns or (root.get("version","") == "2.0"):
        return "2.0"
    return "1.2"

def iter_source_target_pairs(root) -> List[Tuple[ET._Element, Optional[ET._Element]]]:
    """
    Retorna pares (source_elem, target_elem) cobrindo XLIFF 1.2 (<trans-unit>) e 2.0 (<unit>/<segment>).
    Traduzindo todos os segmentos (todas páginas/blocos), não só títulos.
    """
    ns = get_namespaces(root)
    version = detect_version(root)
    pairs: List[Tuple[ET._Element, Optional[ET._Element]]] = []

    if version == "2.0":
        units = root.xpath(".//ns:unit", namespaces=ns) or root.findall(".//unit")
        for u in units:
            segments = u.xpath(".//ns:segment", namespaces=ns) or u.findall(".//segment")
            for seg in segments:
                src = seg.find(".//{*}source")
                tgt = seg.find(".//{*}target")
                if src is not None:
                    pairs.append((src, tgt))
    else:
        # 1.2
        units = root.xpath(".//ns:trans-unit", namespaces=ns) or root.findall(".//trans-unit")
        for u in units:
            src = u.find(".//{*}source")
            tgt = u.find(".//{*}target")
            if src is not None:
                pairs.append((src, tgt))
    return pairs

def ensure_target_for_source(src: ET._Element, tgt: Optional[ET._Element]) -> ET._Element:
    """Garante que exista <target> “irmão” do <source>, preservando namespace."""
    if tgt is not None:
        return tgt
    qn = ET.QName(src)
    tag = qn.localname.replace("source", "target")
    return ET.SubElement(src.getparent(), f"{{{qn.namespace}}}{tag}") if qn.namespace else ET.SubElement(src.getparent(), "target")

def translate_node_texts(elem: ET._Element, target_lang: str = "en", throttle_secs: float = 0.0):
    """
    Traduz recursivamente elem.text e, para cada filho, traduz child.text e child.tail.
    NÃO altera nomes de tags/atributos; preserva estrutura e tags inline (<g>, <ph>, <mrk>, etc).
    À prova de None.
    """
    try:
        if elem.text is not None and safe_str(elem.text).strip():
            elem.text = translate_text_unit(elem.text, target_lang)
            if throttle_secs:
                time.sleep(throttle_secs)
    except Exception:
        elem.text = safe_str(elem.text)

    for child in list(elem):
        translate_node_texts(child, target_lang, throttle_secs)
        try:
            if child.tail is not None and safe_str(child.tail).strip():
                child.tail = translate_text_unit(child.tail, target_lang)
                if throttle_secs:
                    time.sleep(throttle_secs)
        except Exception:
            child.tail = safe_str(child.tail)

def translate_all_notes(root: ET._Element, target_lang: str = "en", throttle_secs: float = 0.0):
    """Traduz todo conteúdo de <note> (texto + tails) em qualquer nível."""
    notes = root.findall(".//{*}note")
    for i, note in enumerate(notes, start=1):
        translate_node_texts(note, target_lang, throttle_secs)

def translate_accessibility_attrs(root: ET._Element, target_lang: str = "en", throttle_secs: float = 0.0):
    """
    Traduz apenas atributos 'falantes' de acessibilidade/UX (title, alt, aria-label).
    Não toca em IDs, refs, estados e metadados técnicos.
    """
    ATTRS = ("title", "alt", "aria-label")
    for el in root.iter():
        for key in ATTRS:
            if key in el.attrib:
                val = safe_str(el.attrib.get(key))
                if val.strip():
                    el.attrib[key] = translate_text_unit(val, target_lang)
                    if throttle_secs:
                        time.sleep(throttle_secs)

# -------------------- UI CONTROLS --------------------
col1, col2 = st.columns(2)
with col1:
    target_lang = st.text_input("Idioma de destino", value="en", help="Ex.: en, es, fr, de… (padrão: en)")
with col2:
    throttle = st.number_input("Intervalo entre chamadas (s)", min_value=0.0, max_value=2.0, value=0.0, step=0.1, help="Use 0.2–0.5s se notar bloqueios no Google")

uploaded = st.file_uploader("📂 Selecione o arquivo .xlf/.xliff do Rise", type=["xlf", "xliff"])
run = st.button("Traduzir arquivo")

# -------------------- PROCESS --------------------
if run:
    if not uploaded:
        st.error("Envie um arquivo .xlf/.xliff.")
        st.stop()

    data = uploaded.read()

    # Pré-contagem para barra de progresso (segmentos)
    try:
        tmp_root = ET.fromstring(data, parser=ET.XMLParser(remove_blank_text=False))
        total_pairs = len(iter_source_target_pairs(tmp_root))
    except Exception:
        total_pairs = 0

    prog = st.progress(0.0)
    status = st.empty()

    def _progress(i, total, phase="segments"):
        if total > 0:
            pct = min(max(i/total, 0), 1)
        else:
            pct = 0.0
        prog.progress(pct)
        label = "Traduzindo segmentos" if phase == "segments" else phase
        status.write(f"{label}: {i}/{total}" if total else f"{label}…")

    try:
        parser = ET.XMLParser(remove_blank_text=False)
        root = ET.fromstring(data, parser=parser)

        # 1) SEGMENTOS (source/target) — traduz TUDO e sobrescreve source & target
        pairs = iter_source_target_pairs(root)
        total = len(pairs)

        for i, (src, tgt) in enumerate(pairs, start=1):
            # traduz TODO o conteúdo do <source> recursivamente (text + tails)
            translate_node_texts(src, target_lang=target_lang, throttle_secs=throttle)

            # garante <target> e copia o conteúdo traduzido do source para o target
            tgt = ensure_target_for_source(src, tgt)
            tgt.clear()
            for ch in list(src):
                tgt.append(deepcopy(ch))
            tgt.text = safe_str(src.text)
            if len(src):
                tgt[-1].tail = safe_str(src[-1].tail)

            _progress(i, total, "segments")

        # 2) NOTAS
        notes = root.findall(".//{*}note")
        total_notes = len(notes)
        for j, note in enumerate(notes, start=1):
            translate_node_texts(note, target_lang=target_lang, throttle_secs=throttle)
            _progress(j, total_notes if total_notes else 1, "notes")

        # 3) ATRIBUTOS (title/alt/aria-label)
        # Contagem para progresso
        all_attr_nodes = []
        ATTRS = ("title", "alt", "aria-label")
        for el in root.iter():
            if any(k in el.attrib for k in ATTRS):
                all_attr_nodes.append(el)
        total_attrs = len(all_attr_nodes)

        for k, el in enumerate(all_attr_nodes, start=1):
            for key in ATTRS:
                if key in el.attrib:
                    val = safe_str(el.attrib.get(key))
                    if val.strip():
                        el.attrib[key] = translate_text_unit(val, target_lang)
                        if throttle:
                            time.sleep(throttle)
            _progress(k, total_attrs if total_attrs else 1, "attributes")

        out_bytes = ET.tostring(root, encoding="utf-8", xml_declaration=True, pretty_print=True)
        st.success("✅ Tradução concluída!")
        out_name = os.path.splitext(uploaded.name)[0] + "-translated.xlf"
        st.download_button("⬇️ Baixar XLIFF traduzido", data=out_bytes, file_name=out_name, mime="application/xliff+xml")

    except Exception as e:
        st.error(f"Erro ao traduzir: {e}")
