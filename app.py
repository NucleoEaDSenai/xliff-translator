import os, time, re, base64
from copy import deepcopy
from typing import List, Tuple, Optional
from pathlib import Path

import streamlit as st
from lxml import etree as ET
from deep_translator import GoogleTranslator
import streamlit.components.v1 as components

st.set_page_config(page_title="Tradutor XLIFF • Firjan SENAI", page_icon="🌍", layout="wide")

PRIMARY = "#83c7e5"
st.markdown(f"""
<style>
body { background:#000; color:#fff; }
section.main > div { max-width: 1200px; margin: 0 auto; }
.stButton>button { background:{PRIMARY}; color:#000; font-weight:700; border:none; }
.stProgress > div > div > div > div { background:{PRIMARY}; }
hr { border: 0; border-top: 1px solid #333; margin: 24px 0; }
.footer { opacity: .6; font-size: 12px; margin-top: 12px; }
.codebox { background:#111; border:1px solid #222; padding:12px; border-radius:8px; }
.radio-group label { margin-right:12px; }
</style>
""", unsafe_allow_html=True)

# =================== UI helpers ===================
def show_logo():
    svg = """
    <svg width="64" height="64" viewBox="0 0 24 24" fill="none" xmlns="http://www.w3.org/2000/svg">
      <path d="M12 2L2 7l10 5 10-5-10-5Zm0 7L2 4v13l10 5 10-5V4l-10 5Z" fill="#83c7e5"/>
    </svg>
    """
    st.markdown(f"<div style='display:flex;gap:12px;align-items:center'><div>{svg}</div><h2 style='margin:0'>Tradutor XLIFF</h2></div>", unsafe_allow_html=True)

show_logo()

# =================== Safety ===================
def safe_str(x):
    if x is None:
        return ""
    try:
        return str(x)
    except Exception:
        return ""

# =================== Nontranslatable protection ===================
NONTRANS_PATTERNS = [
    r"https?://\S+",
    r"www\.\S+",
    r"[\w\.-]+@[\w\.-]+\.\w+",
    r"%[^%\n\r]+%",  # Storyline variables
    r"&[#xX]?[0-9A-Fa-f]+;|&[A-Za-z]+;",  # HTML/XML entities
    r"\b\d[\d\.,/:_-]*\b",  # numbers/dates
]

def protect_nontranslatable(text:str):
    """
    Replaces non-translatable tokens with placeholders and returns (text_with_placeholders, tokens).
    """
    text = safe_str(text)
    if not text:
        return "", []
    tokens = []
    def repl(m):
        idx = len(tokens)
        tokens.append(m.group(0))
        return f"__TK{idx}__"
    for pat in NONTRANS_PATTERNS:
        text = re.sub(pat, repl, text)
    return text, tokens

def restore_nontranslatable(text:str, tokens):
    text = safe_str(text)
    if not tokens:
        return text
    for i in range(len(tokens)-1, -1, -1):
        text = text.replace(f"__TK{i}__", tokens[i])
    return text

# =================== Translation core ===================
def translate_text_unit(text:str, target_lang:str)->str:
    text = safe_str(text)
    if not text.strip():
        return text
    t, toks = protect_nontranslatable(text)
    out = t
    try:
        out = safe_str(GoogleTranslator(source="auto", target=target_lang).translate(t))
    except Exception:
        out = t
    return safe_str(restore_nontranslatable(out, toks))

# =================== XLIFF helpers ===================
def get_google_lang_pairs():
    return {
        "Português → Espanhol": ("pt", "es"),
        "Português → Inglês": ("pt", "en"),
        "Inglês → Espanhol": ("en", "es"),
        "Inglês → Português": ("en", "pt"),
        "Espanhol → Português": ("es", "pt"),
        "Espanhol → Inglês": ("es", "en"),
    }

def detect_version(root)->str:
    d = root.nsmap.get(None,"") or ""
    if "urn:oasis:names:tc:xliff:document:2.0" in d or (root.get("version","") == "2.0"):
        return "2.0"
    return "1.2"

def get_namespaces(root):
    nsmap = {}
    if root.nsmap:
        for k,v in root.nsmap.items():
            nsmap[k if k is not None else "ns"] = v
    if not nsmap:
        nsmap = {"ns":"urn:oasis:names:tc:xliff:document:1.2"}
    return nsmap

def iter_source_target_pairs(root)->List[Tuple[ET._Element, Optional[ET._Element]]]:
    ns=get_namespaces(root)
    v=detect_version(root)
    pairs=[]
    if v=="2.0":
        units = root.xpath(".//ns:unit", namespaces=ns) or root.findall(".//unit")
        for u in units:
            segs = u.xpath(".//ns:segment", namespaces=ns) or u.findall(".//segment")
            for s in segs:
                src = s.find(".//{*}source"); tgt = s.find(".//{*}target")
                if src is not None: pairs.append((src,tgt))
    else:
        units = root.xpath(".//ns:trans-unit", namespaces=ns) or root.findall(".//trans-unit")
        for u in units:
            src = u.find(".//{*}source"); tgt = u.find(".//{*}target")
            if src is not None: pairs.append((src,tgt))
    return pairs

def ensure_target_for_source(src, tgt):
    parent = src.getparent()
    if tgt is None:
        tgt = ET.Element("{%s}target" % (parent.nsmap.get(None) or "urn:oasis:names:tc:xliff:document:1.2"))
        parent.append(tgt)
    return tgt

# =================== Text traversal ===================
def translate_node_texts(elem:ET._Element, lang:str):
    if elem.text is not None and elem.text.strip():
        elem.text = translate_text_unit(elem.text, lang)
    for child in list(elem):
        translate_node_texts(child, lang)
        if child.tail is not None and child.tail.strip():
            child.tail = translate_text_unit(child.tail, lang)

# =================== Notes & Accessibility ===================
def translate_all_notes(root, lang):
    for note in root.findall(".//{*}note"):
        if note.text and note.text.strip():
            note.text = translate_text_unit(note.text, lang)

A11Y_ATTRS = ["title","alt","aria-label","aria-placeholder","aria-roledescription","data-title","data-alt"]

def translate_accessibility_attrs(root, lang):
    for el in root.iter():
        for a in A11Y_ATTRS:
            if a in el.attrib and el.attrib[a].strip():
                el.attrib[a] = translate_text_unit(el.attrib[a], lang)

# =================== Spacing fix ===================
def _needs_space(a: str, b: str) -> bool:
    if not a or not b:
        return False
    if a[-1].isalnum() and b[0].isalnum():
        return True
    if a[-1] in ",.;:!?" and b[0].isalnum():
        return True
    return False

def fix_spacing_around_tags(root:ET._Element):
    for el in root.iter():
        kids = list(el)
        if not kids:
            continue
        for i, cur in enumerate(kids):
            prev = kids[i-1] if i>0 else None
            nxt = kids[i+1] if i+1 < len(kids) else None
            if prev is not None:
                if prev.tail and cur.text:
                    if _needs_space(prev.tail, cur.text):
                        prev.tail = prev.tail + " "
                    prev.tail = re.sub(r"\s{2,}", " ", prev.tail)
                elif prev.tail and not cur.text:
                    prev.tail = re.sub(r"\s{2,}", " ", prev.tail)
                elif not prev.tail and cur.text:
                    if _needs_space(safe_str(prev.text), cur.text):
                        cur.text = " " + cur.text
            if nxt is not None:
                if cur.text and nxt.text:
                    if _needs_space(cur.text, nxt.text):
                        cur.tail = safe_str(cur.tail)
                        if not cur.tail:
                            cur.tail = " "
                        elif not cur.tail.startswith((" ", "\n", "\t")):
                            cur.tail = " " + cur.tail
                        cur.tail = re.sub(r"\s{2,}", " ", cur.tail)
                else:
                    cur.tail = safe_str(cur.tail)
                    if cur.tail:
                        if _needs_space(safe_str(cur.text), nxt.text or "") and not cur.tail.startswith((" ", "\n", "\t")):
                            cur.tail = " " + cur.tail
                        cur.tail = re.sub(r"\s{2,}", " ", cur.tail)

# =================== Storyline-specific utilities ===================
# ========= Utilitários específicos para Storyline =========
def set_target_language(root, lang_code: str):
    """
    Define o idioma de destino no XLIFF:
    - XLIFF 1.2: atributo target-language no <file>
    - XLIFF 2.0: atributo trgLang no <xliff>
    Faz um pequeno mapeamento para códigos regionais comuns.
    """
    MAP = {
        "pt": "pt-BR", "en": "en-US", "es": "es-ES", "fr": "fr-FR", "de": "de-DE", "it": "it-IT"
    }
    v = detect_version(root)
    source_lang = None
    if v == "1.2":
        file_el = root.find(".//{*}file")
        if file_el is not None:
            source_lang = file_el.get("source-language")
    else:
        source_lang = root.get("srcLang")
    target = MAP.get(lang_code, lang_code)
    if source_lang and "-" in source_lang and "-" not in target:
        region = source_lang.split("-",1)[1]
        target = f"{lang_code}-{region}"
    if v == "1.2":
        file_el = root.find(".//{*}file")
        if file_el is not None:
            file_el.set("target-language", target)
    else:
        root.set("trgLang", target)

def set_storyline_target_state(root, state_value="translated"):
    for tgt in root.findall(".//{*}target"):
        if "state" not in tgt.attrib:
            tgt.set("state", state_value)

def protect_nontranslatable_storyline(text: str):
    text = "" if text is None else str(text)
    if not text:
        return "", []
    patterns = [
        r'https?://\S+', r'www\.\S+', r'[\w\.-]+@[\w\.-]+\.\w+',
        r'%[^%\n\r]+%', r'&[#xX]?[0-9A-Fa-f]+;|&[A-Za-z]+;', r'\b\d[\d\.,/:_-]*\b',
    ]
    tokens = []
    def repl(m):
        i = len(tokens)
        tokens.append(m.group(0))
        return f"__TK{i}__"
    for pat in patterns:
        text = re.sub(pat, repl, text)
    return text, tokens

def restore_nontranslatable_storyline(text: str, tokens):
    text = "" if text is None else str(text)
    for i in range(len(tokens)-1, -1, -1):
        text = text.replace(f"__TK{i}__", tokens[i])
    return text

def translate_text_unit_storyline(text: str, target_lang: str) -> str:
    text = "" if text is None else str(text)
    if not text.strip():
        return text
    t, toks = protect_nontranslatable_storyline(text)
    out = t
    try:
        out = str(GoogleTranslator(source="auto", target=target_lang).translate(t))
    except Exception:
        out = t
    return restore_nontranslatable_storyline(out, toks)

def _looks_like_pseudo_xml(s: str) -> bool:
    if not s: return False
    s = str(s)
    return bool(re.search(r'(?:<[^>]+>|&lt;[^&]+&gt;)', s))

def _translate_attr_values_in_pseudo_xml(s: str, lang: str) -> str:
    """
    Traduz SOMENTE valores de atributos textuais em strings pseudo-XML:
      Text=  Label=  Alt=  Title=  Tooltip=  Value=
    Preserva nomes de tags, nomes de atributos e qualquer outro conteúdo.
    Funciona tanto com aspas duplas quanto simples.
    """
    if not s: return s
    s = str(s)
    def _tx(text):
        return translate_text_unit_storyline(text, lang)
    attrs = ("Text","Label","Alt","Title","Tooltip","Value")
    for attr in attrs:
        pat_dq = rf'({attr}\s*=\s*")([^\"]*?)(")'
        s = re.sub(pat_dq, lambda m: f'{attr}="{_tx(m.group(2))}"', s)
        pat_sq = rf"({attr}\s*=\s*')([^']*?)(')"
        s = re.sub(pat_sq, lambda m: f"{attr}='{_tx(m.group(2))}'", s)
    return s

def translate_node_texts_storyline(elem, lang: str):
    if elem.text is not None and str(elem.text).strip():
        elem.text = (
            _translate_attr_values_in_pseudo_xml(elem.text, lang)
            if _looks_like_pseudo_xml(elem.text)
            else translate_text_unit_storyline(elem.text, lang)
        )
    for child in list(elem):
        translate_node_texts_storyline(child, lang)
        if child.tail is not None and str(child.tail).strip():
            child.tail = (
                _translate_attr_values_in_pseudo_xml(child.tail, lang)
                if _looks_like_pseudo_xml(child.tail)
                else translate_text_unit_storyline(child.tail, lang)
            )

# =================== Processors ===================
def process(data: bytes, lang_code: str, prog, status):
    parser = ET.XMLParser(remove_blank_text=False)
    root = ET.fromstring(data, parser=parser)
    pairs = iter_source_target_pairs(root)
    total = max(len(pairs), 1)
    status.text("0% concluído…")
    prog.progress(0.0)
    for i, (src, tgt) in enumerate(pairs, start=1):
        tmp = deepcopy(src)  # translate only text
        translate_node_texts(tmp, lang_code)
        tgt = ensure_target_for_source(src, tgt)
        tgt.clear()
        for ch in list(tmp):
            tgt.append(ch)
        tgt.text = safe_str(tmp.text)
        if len(tmp):
            tgt[-1].tail = safe_str(tmp[-1].tail)
        if i == 1 or i % 10 == 0 or i == total:
            frac = i / total
            percent = int(round(frac * 100))
            prog.progress(frac)
            status.text(f"{percent}% concluído…")
    translate_all_notes(root, lang_code)
    translate_accessibility_attrs(root, lang_code)
    fix_spacing_around_tags(root)
    prog.progress(1.0)
    status.text("100% concluído — finalizando arquivo…")
    return ET.tostring(root, encoding="utf-8", xml_declaration=True, pretty_print=True)

def process_storyline(data: bytes, lang_code: str, prog, status):
    parser = ET.XMLParser(remove_blank_text=False)
    root = ET.fromstring(data, parser=parser)
    pairs = iter_source_target_pairs(root)
    total = max(len(pairs), 1)
    status.text("0% concluído…")
    prog.progress(0.0)
    for i, (src, tgt) in enumerate(pairs, start=1):
        tmp = deepcopy(src)
        translate_node_texts_storyline(tmp, lang_code)
        tgt = ensure_target_for_source(src, tgt)
        tgt.clear()
        for ch in list(tmp):
            tgt.append(ch)
        tgt.text = safe_str(tmp.text)
        if len(tmp):
            tgt[-1].tail = safe_str(tmp[-1].tail)
        if "state" not in tgt.attrib:
            tgt.set("state", "translated")
        if i == 1 or i % 10 == 0 or i == total:
            frac = i / total
            percent = int(round(frac * 100))
            prog.progress(frac)
            status.text(f"{percent}% concluído…")
    translate_all_notes(root, lang_code)
    translate_accessibility_attrs(root, lang_code)
    set_target_language(root, lang_code)
    fix_spacing_around_tags(root)
    prog.progress(1.0)
    status.text("100% concluído — finalizando arquivo…")
    return ET.tostring(root, encoding="utf-8", xml_declaration=True, pretty_print=True)

# =================== UI ===================
st.subheader("Tradução de XLIFF (Rise/Storyline)")

pairs = get_google_lang_pairs()
choice = st.selectbox("Selecione o par de idiomas", list(pairs.keys()), index=0)
lang_code = pairs[choice][1]

uploaded = st.file_uploader("Selecione o arquivo .xlf/.xliff do Rise", type=["xlf","xliff"])

# Seletor de formato (mantém Rise intacto; adiciona Storyline)
xliff_flavor = st.radio(
    "Formato do XLIFF",
    ["Articulate Rise (padrão)", "Articulate Storyline"],
    index=0,
    help="O Storyline usa XLIFF com requisitos específicos de cabeçalho/estado."
)

run = st.button("Executar tradução")

if run:
    if not uploaded:
        st.error("Envie um arquivo .xlf/.xliff.")
        st.stop()
    data = uploaded.read()
    try:
        tmp_root = ET.fromstring(data, parser=ET.XMLParser(remove_blank_text=False))
        total_pairs = len(iter_source_target_pairs(tmp_root))
        st.write(f"Segmentos detectados: **{total_pairs}**")
    except:
        total_pairs = 0
    prog = st.progress(0.0)
    status = st.empty()
    try:
        with st.spinner("Traduzindo…"):
            if xliff_flavor == "Articulate Storyline":
                out_bytes = process_storyline(data, lang_code, prog, status)
                base = os.path.splitext(uploaded.name)[0]
                out_name = f"{base}-storyline-{lang_code}.xlf"
            else:
                # Mantém o fluxo original do Rise (process)
                out_bytes = process(data, lang_code, prog, status)
                base = os.path.splitext(uploaded.name)[0]
                out_name = f"{base}-{lang_code}.xlf"
        st.success("Tradução concluída!")
        st.download_button("Baixar XLIFF traduzido", data=out_bytes, file_name=out_name, mime="application/xliff+xml")
    except Exception as e:
        st.error(f"Erro ao traduzir: {e}")


st.markdown("<hr/>", unsafe_allow_html=True)
st.markdown("<div class='footer'>Direitos Reservados à Área de Ensino a Distância - Firjan SENAI Maracanã</div>", unsafe_allow_html=True)
