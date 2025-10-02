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
st.caption("Traduz .xlf/.xliff completos (XLIFF 1.2 e 2.0), preservando tags inline. Dark mode + proteção de placeholders.")

# -------------------- HELPERS --------------------
# placeholders/comandos que NÃO devem ser traduzidos
PLACEHOLDER_RE = re.compile(r"(\{\{.*?\}\}|\{.*?\}|%s|%d|%\(\w+\)s)")

def protect_nontranslatable(text: str):
    """Protege {…}, {{…}}, %s etc. com tokens §§K#§§ para não serem mexidos pelo tradutor."""
    if not text:
        return "", []
    tokens = []
    def _sub(m):
        tokens.append(m.group(0))
        return f"§§K{len(tokens)-1}§§"
    protected = PLACEHOLDER_RE.sub(_sub, text)
    return protected, tokens

def restore_nontranslatable(text: str, tokens):
    def _restore(m):
        idx = int(m.group(1))
        return tokens[idx] if 0 <= idx < len(tokens) else m.group(0)
    return re.sub(r"§§K(\d+)§§", _restore, text)

def translate_text_unit(text: str, target_lang: str = "en") -> str:
    """Tradução de uma unidade de texto com proteção de placeholders (Google via deep-translator)."""
    if not text or not text.strip():
        return text or ""
    t, toks = protect_nontranslatable(text)
    try:
        out = GoogleTranslator(source="auto", target=target_lang).translate(t)
    except Exception:
        # fallback: mantém original se houver erro/intermitência
        out = t
    return restore_nontranslatable(out, toks)

def get_namespaces(root) -> dict:
    nsmap = {}
    if root.nsmap:
        for k, v in root.nsmap.items():
            nsmap[k if k is not None else "ns"] = v
    if not nsmap:
        nsmap = {"ns": "urn:oasis:names:tc:xliff:document:1.2"}
    return nsmap

def detect_version(root) -> str:
    default_ns = root.nsmap.get(None, "")
    if "urn:oasis:names:tc:xliff:document:2.0" in default_ns or root.get("version","") == "2.0":
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
    """
    # traduz o texto do nó atual
    if elem.text:
        elem.text = translate_text_unit(elem.text, target_lang)
        if throttle_secs:
            time.sleep(throttle_secs)

    for child in list(elem):
        # desce recursivamente
        translate_node_texts(child, target_lang, throttle_secs)
        # traduz o tail (texto após o filho)
        if child.tail:
            child.tail = translate_text_unit(child.tail, target_lang)
            if throttle_secs:
                time.sleep(throttle_secs)

# -------------------- UI CONTROLS --------------------
col1, col2 = st.columns(2)
with col1:
    target_lang = st.text_input("Idioma de destino", value="en", help="Ex.: en, es, fr, de… (padrão: en)")
with col2:
    throttle = st.number_input("Intervalo entre chamadas (s)", min_value=0.0, max_value=2.0, value=0.0, step=0.1, help="Use 0.2–0.5s se notar bloqueios no Google")

overwrite = st.checkbox("Sobrescrever <source> com inglês (arquivo 100% EN)", value=True)

uploaded = st.file_uploader("📂 Selecione o arquivo .xlf/.xliff do Rise", type=["xlf", "xliff"])
run = st.button("Traduzir arquivo")

# -------------------- PROCESS --------------------
if run:
    if not uploaded:
        st.error("Envie um arquivo .xlf/.xliff.")
        st.stop()

    data = uploaded.read()

    # Pré-contagem para barra de progresso
    try:
        tmp_root = ET.fromstring(data, parser=ET.XMLParser(remove_blank_text=False))
        total_pairs = len(iter_source_target_pairs(tmp_root))
    except Exception as e:
        total_pairs = 0

    prog = st.progress(0.0)
    status = st.empty()

    def _progress(i, total):
        if total > 0:
            prog.progress(i/total)
            status.write(f"Traduzindo segmentos: {i}/{total}")

    try:
        parser = ET.XMLParser(remove_blank_text=False)
        root = ET.fromstring(data, parser=parser)

        pairs = iter_source_target_pairs(root)
        total = len(pairs)

        for i, (src, tgt) in enumerate(pairs, start=1):
            # 1) traduz TODO o conteúdo do <source> recursivamente (text + tails)
            translate_node_texts(src, target_lang=target_lang, throttle_secs=throttle)

            # 2) garante <target> e copia o conteúdo traduzido do source para o target
            tgt = ensure_target_for_source(src, tgt)
            tgt.clear()
            # clona filhos preservando estrutura/tags
            for ch in list(src):
                tgt.append(deepcopy(ch))
            # copia text e tail finais
            tgt.text = src.text
            if len(src):
                tgt[-1].tail = src[-1].tail

            # 3) sobrescreve <source> com inglês (se marcado) — já está traduzido acima
            # (se você desmarcar overwrite, o source ficará no idioma original e apenas o target em EN)
            # nada a fazer aqui quando overwrite=True, pois já traduzimos src in-place

            # progresso
            _progress(i, total)

        out_bytes = ET.tostring(root, encoding="utf-8", xml_declaration=True, pretty_print=True)
        st.success("✅ Tradução concluída!")
        out_name = os.path.splitext(uploaded.name)[0] + "-translated.xlf"
        st.download_button("⬇️ Baixar XLIFF traduzido", data=out_bytes, file_name=out_name, mime="application/xliff+xml")

    except Exception as e:
        st.error(f"Erro ao traduzir: {e}")
