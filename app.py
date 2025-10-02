import os
import io
import re
import time
import zipfile
from copy import deepcopy
from typing import List, Tuple, Optional, Dict

import streamlit as st
import pandas as pd
from lxml import etree as ET
from deep_translator import GoogleTranslator

# -------------------- CONFIG UI --------------------
st.set_page_config(page_title="XLIFF → Multilingual (Google) + Glossary", page_icon="🌍", layout="centered")

PRIMARY = "#83c7e5"  # Azul SENAI
st.markdown(f"""
<style>
body {{ background:#000; color:#fff; }}
.block-container {{ padding-top: 1.2rem; max-width: 1040px; }}
h1,h2,h3,p,span,div,label {{ color:#fff !important; }}
.stButton>button {{
  background:#333; color:{PRIMARY}; font-weight:700; border:none; border-radius:8px; padding:.6rem 1rem;
}}
.stProgress > div > div > div > div {{ background-color: {PRIMARY}; }}
</style>
""", unsafe_allow_html=True)

st.title("🌍 XLIFF Translator — Multilingual (Google) + Glossary")
st.caption("Traduz .xlf/.xliff completos (1.2/2.0), preservando tags inline. Suporte a várias línguas e glossário com termos bloqueados/ preferidos.")

# -------------------- HELPERS ROBUSTOS --------------------
def safe_str(x) -> str:
    return "" if x is None else str(x)

# placeholders/comandos que NÃO devem ser traduzidos
PLACEHOLDER_RE = re.compile(r"(\{\{.*?\}\}|\{.*?\}|%s|%d|%\(\w+\)s)")

def protect_nontranslatable(text: str):
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

# ---------- Glossário ----------
class Glossary:
    """
    Glossário com termos em origem (source).
    - mode:
        - keep: não traduzir -> restaurar exatamente o source
        - map: substituir pela tradução preferida (preferred)
    - match:
        - word (padrão): casa palavra inteira (respeita fronteiras)
        - substr: substring literal
    Implementação: protegemos os termos ANTES da tradução com placeholders §§G{idx}§§
    e RESTAURAMOS depois com o target (preferred ou source).
    """
    def __init__(self, rows: List[Dict]):
        self.rules = []  # cada item: {pattern, replacement, idx}
        self._build(rows)

    def _build(self, rows: List[Dict]):
        self.rules = []
        idx = 0
        for r in rows:
            src = safe_str(r.get("source", "")).strip()
            if not src:
                continue
            mode = (safe_str(r.get("mode", "keep")).lower()).strip()
            match = (safe_str(r.get("match", "word")).lower()).strip()
            preferred = safe_str(r.get("preferred", "")).strip()  # opcional

            if mode not in ("keep", "map"):
                mode = "keep"
            if match not in ("word", "substr"):
                match = "word"

            # regex para match:
            if match == "word":
                # palavra inteira (boundaries). Escapar src para literal.
                pattern = re.compile(rf"\b{re.escape(src)}\b", flags=re.IGNORECASE)
            else:
                # substring literal
                pattern = re.compile(re.escape(src), flags=re.IGNORECASE)

            replacement = src if mode == "keep" else (preferred if preferred else src)
            self.rules.append({"pattern": pattern, "replacement": replacement, "idx": idx})
            idx += 1

    def protect(self, text: str) -> Tuple[str, Dict[str, str]]:
        """
        Substitui cada termo encontrado por um marcador §§G{n}§§.
        Retorna: (texto_protegido, mapa_de_restauro)
        """
        if not self.rules:
            return text, {}
        out = text
        restore_map: Dict[str, str] = {}
        for r in self.rules:
            token = f"§§G{r['idx']}§§"
            # substitui todas as ocorrências do pattern por token
            out, n = r["pattern"].subn(token, out)
            if n > 0:
                restore_map[token] = r["replacement"]
        return out, restore_map

    @staticmethod
    def restore(text: str, restore_map: Dict[str, str]) -> str:
        if not restore_map:
            return text
        out = text
        for token, val in restore_map.items():
            out = out.replace(token, val)
        return out

def load_glossary_from_csv(file) -> Glossary:
    """
    CSV com colunas: source, preferred (opcional), mode (keep|map), match (word|substr)
    """
    try:
        df = pd.read_csv(file)
    except Exception:
        file.seek(0)
        df = pd.read_csv(file, sep=";")
    # normaliza colunas
    for c in ["source", "preferred", "mode", "match"]:
        if c not in df.columns:
            df[c] = ""
    rows = df[["source", "preferred", "mode", "match"]].to_dict(orient="records")
    return Glossary(rows)

# ---------- Tradução base (Google) com placeholders e glossário ----------
def translate_text_unit(text: str, target_lang: str, glossary: Optional[Glossary] = None) -> str:
    text = safe_str(text)
    if not text.strip():
        return text

    # 1) protege placeholders técnicos
    t, toks = protect_nontranslatable(text)

    # 2) protege termos do glossário
    restore_map = {}
    if glossary:
        t, restore_map = glossary.protect(t)

    # 3) traduz
    out = t
    try:
        tr = GoogleTranslator(source="auto", target=target_lang).translate(t)
        out = safe_str(tr)
    except Exception:
        out = t  # fallback: mantém original

    # 4) restaura glossário (preferidos / não traduzir)
    out = Glossary.restore(out, restore_map)

    # 5) restaura placeholders técnicos
    out = restore_nontranslatable(out, toks)
    return safe_str(out)

# ---------- XLIFF / XML helpers ----------
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
    ns = get_namespaces(root)
    version = detect_version(root)
    pairs: List[Tuple[ET._Element, Optional[ET._Element]]] = []
    if version == "2.0":
        units = root.xpath(".//ns:unit", namespaces=ns) or root.findall(".//unit")
        for u in units:
            segs = u.xpath(".//ns:segment", namespaces=ns) or u.findall(".//segment")
            for seg in segs:
                src = seg.find(".//{*}source")
                tgt = seg.find(".//{*}target")
                if src is not None:
                    pairs.append((src, tgt))
    else:
        units = root.xpath(".//ns:trans-unit", namespaces=ns) or root.findall(".//trans-unit")
        for u in units:
            src = u.find(".//{*}source")
            tgt = u.find(".//{*}target")
            if src is not None:
                pairs.append((src, tgt))
    return pairs

def ensure_target_for_source(src: ET._Element, tgt: Optional[ET._Element]) -> ET._Element:
    if tgt is not None:
        return tgt
    qn = ET.QName(src)
    tag = qn.localname.replace("source", "target")
    return ET.SubElement(src.getparent(), f"{{{qn.namespace}}}{tag}") if qn.namespace else ET.SubElement(src.getparent(), "target")

def translate_node_texts(elem: ET._Element, target_lang: str, glossary: Optional[Glossary], throttle_secs: float = 0.0):
    # traduz o texto do nó
    if elem.text is not None and safe_str(elem.text).strip():
        elem.text = translate_text_unit(elem.text, target_lang, glossary)
        if throttle_secs:
            time.sleep(throttle_secs)

    # percorre filhos
    for child in list(elem):
        translate_node_texts(child, target_lang, glossary, throttle_secs)
        if child.tail is not None and safe_str(child.tail).strip():
            child.tail = translate_text_unit(child.tail, target_lang, glossary)
            if throttle_secs:
                time.sleep(throttle_secs)

def translate_all_notes(root: ET._Element, target_lang: str, glossary: Optional[Glossary], throttle_secs: float = 0.0):
    for note in root.findall(".//{*}note"):
        translate_node_texts(note, target_lang, glossary, throttle_secs)

def translate_accessibility_attrs(root: ET._Element, target_lang: str, glossary: Optional[Glossary], throttle_secs: float = 0.0):
    ATTRS = ("title", "alt", "aria-label")
    for el in root.iter():
        for key in ATTRS:
            if key in el.attrib:
                val = safe_str(el.attrib.get(key))
                if val.strip():
                    el.attrib[key] = translate_text_unit(val, target_lang, glossary)
                    if throttle_secs:
                        time.sleep(throttle_secs)

def translate_xlf_bytes(data: bytes, target_lang: str, throttle: float, glossary: Optional[Glossary]) -> bytes:
    parser = ET.XMLParser(remove_blank_text=False)
    root = ET.fromstring(data, parser=parser)

    # 1) segmentos (<source>/<target>)
    pairs = iter_source_target_pairs(root)
    total = len(pairs)
    for i, (src, tgt) in enumerate(pairs, start=1):
        translate_node_texts(src, target_lang, glossary, throttle)
        tgt = ensure_target_for_source(src, tgt)
        tgt.clear()
        for ch in list(src):
            tgt.append(deepcopy(ch))
        tgt.text = safe_str(src.text)
        if len(src):
            tgt[-1].tail = safe_str(src[-1].tail)

    # 2) notas
    translate_all_notes(root, target_lang, glossary, throttle)

    # 3) atributos de acessibilidade
    translate_accessibility_attrs(root, target_lang, glossary, throttle)

    return ET.tostring(root, encoding="utf-8", xml_declaration=True, pretty_print=True)

# -------------------- UI CONTROLS --------------------
col1, col2 = st.columns(2)
with col1:
    target_langs = st.multiselect(
        "Idiomas de destino",
        options=["en","es","fr","de","it","pt","nl","sv","ru","ja","ko","zh-CN","zh-TW"],
        default=["en"],
        help="Selecione 1 ou mais línguas. Se escolher várias, o app baixará um .zip com todas."
    )
with col2:
    throttle = st.number_input(
        "Intervalo entre chamadas (s)",
        min_value=0.0, max_value=2.0, value=0.0, step=0.1,
        help="Se notar bloqueios do Google, use 0.2–0.5s"
    )

uploaded = st.file_uploader("📂 Selecione o arquivo .xlf/.xliff do Rise", type=["xlf","xliff"])

gloss_file = st.file_uploader(
    "📘 Glossário (CSV opcional) — colunas: source, preferred, mode [keep|map], match [word|substr]",
    type=["csv"]
)

run = st.button("Traduzir arquivo(s)")

# -------------------- PROCESS --------------------
if run:
    if not uploaded:
        st.error("Envie um arquivo .xlf/.xliff.")
        st.stop()
    if not target_langs:
        st.error("Selecione pelo menos um idioma de destino.")
        st.stop()

    data = uploaded.read()

    # Carrega glossário se houver
    glossary = None
    if gloss_file is not None:
        try:
            glossary = load_glossary_from_csv(gloss_file)
            st.success("Glossário carregado com sucesso.")
        except Exception as e:
            st.warning(f"Não foi possível ler o glossário: {e}")

    # Prévia: contagem de segmentos
    try:
        tmp_root = ET.fromstring(data, parser=ET.XMLParser(remove_blank_text=False))
        total_pairs = len(iter_source_target_pairs(tmp_root))
        st.write(f"Segmentos detectados: **{total_pairs}**")
    except Exception:
        total_pairs = 0

    # Uma língua → retorna XLF; várias línguas → ZIP
    if len(target_langs) == 1:
        lang = target_langs[0]
        try:
            out_bytes = translate_xlf_bytes(data, target_lang=lang, throttle=throttle, glossary=glossary)
            st.success(f"✅ Tradução concluída ({lang}).")
            base = os.path.splitext(uploaded.name)[0]
            out_name = f"{base}-{lang}.xlf"
            st.download_button("⬇️ Baixar XLIFF traduzido", data=out_bytes, file_name=out_name, mime="application/xliff+xml")
        except Exception as e:
            st.error(f"Erro ao traduzir: {e}")
    else:
        # múltiplas línguas: cria ZIP em memória
        try:
            mem = io.BytesIO()
            with zipfile.ZipFile(mem, mode="w", compression=zipfile.ZIP_DEFLATED) as zf:
                base = os.path.splitext(uploaded.name)[0]
                for lang in target_langs:
                    out_bytes = translate_xlf_bytes(data, target_lang=lang, throttle=throttle, glossary=glossary)
                    zf.writestr(f"{base}-{lang}.xlf", out_bytes)
            mem.seek(0)
            st.success(f"✅ Traduções concluídas ({', '.join(target_langs)}).")
            st.download_button("⬇️ Baixar ZIP com XLIFFs", data=mem, file_name="xliff-translated-multilang.zip", mime="application/zip")
        except Exception as e:
            st.error(f"Erro ao traduzir: {e}")
