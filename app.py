import os, time, re
from copy import deepcopy
from typing import List, Tuple, Optional

import streamlit as st
from lxml import etree as ET
from deep_translator import GoogleTranslator
from pathlib import Path

st.set_page_config(page_title="Tradutor XLIFF • Firjan SENAI", page_icon="🌍", layout="centered")

PRIMARY = "#83c7e5"
st.markdown(f"""
<style>
body {{ background:#000; color:#fff; }}
.block-container {{ padding-top: 1.2rem; max-width: 1040px; }}
h1,h2,h3,p,span,div,label,small {{ color:#fff !important; }}
.stButton>button {{ background:#333; color:{PRIMARY}; font-weight:700; border:none; border-radius:8px; padding:.6rem 1rem; }}
.stProgress > div > div > div > div {{ background-color: {PRIMARY}; }}
hr {{ border: 0; border-top: 1px solid #222; margin: 24px 0; }}
.footer {{ text-align:center; color:#aaa; font-size:12px; margin-top:32px; }}
.header {{ display:flex; align-items:center; gap:16px; margin-bottom:8px; }}
.logo img {{ display:block; }}
</style>
""", unsafe_allow_html=True)

# ---------- Logo (caminho relativo ao app) ----------
logo_path = Path(__file__).parent / "firjan_senai_branco_horizontal.png"
col_logo, col_title = st.columns([1, 6])
with col_logo:
    if logo_path.exists():
        st.image(str(logo_path), width=220)
    else:
        st.write("")  # silencioso se não achar
with col_title:
    st.markdown("<div class='header'><h1>Tradutor XLIFF</h1></div>", unsafe_allow_html=True)
st.caption("Firjan SENAI · Dark mode · Tradução completa com preservação de tags")

def safe_str(x)->str:
    return "" if x is None else str(x)

PLACEHOLDER_RE = re.compile(r"(\{\{.*?\}\}|\{.*?\}|%s|%d|%\(\w+\)s)")

def protect_nontranslatable(text:str):
    text = safe_str(text)
    if not text: return "", []
    tokens=[]
    def _sub(m):
        tokens.append(m.group(0))
        return f"§§K{len(tokens)-1}§§"
    try:
        protected = PLACEHOLDER_RE.sub(_sub, text)
    except:
        protected = text
    return protected, tokens

def restore_nontranslatable(text:str, tokens):
    text = safe_str(text)
    if not tokens: return text
    try:
        def _r(m):
            i = int(m.group(1))
            return tokens[i] if 0 <= i < len(tokens) else m.group(0)
        return re.sub(r"§§K(\d+)§§", _r, text)
    except:
        return text

def translate_text_unit(text:str, target_lang:str)->str:
    text = safe_str(text)
    if not text.strip(): return text
    t, toks = protect_nontranslatable(text)
    out = t
    try:
        out = safe_str(GoogleTranslator(source="auto", target=target_lang).translate(t))
    except:
        out = t
    return safe_str(restore_nontranslatable(out, toks))

def get_namespaces(root)->dict:
    nsmap={}
    if root.nsmap:
        for k,v in root.nsmap.items():
            nsmap[k if k is not None else "ns"]=v
    if not nsmap:
        nsmap={"ns":"urn:oasis:names:tc:xliff:document:1.2"}
    return nsmap

def detect_version(root)->str:
    d = root.nsmap.get(None,"") or ""
    if "urn:oasis:names:tc:xliff:document:2.0" in d or (root.get("version","")== "2.0"):
        return "2.0"
    return "1.2"

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

def ensure_target_for_source(src:ET._Element, tgt:Optional[ET._Element])->ET._Element:
    if tgt is not None: return tgt
    qn=ET.QName(src); tag=qn.localname.replace("source","target")
    return ET.SubElement(src.getparent(), f"{{{qn.namespace}}}{tag}") if qn.namespace else ET.SubElement(src.getparent(),"target")

def translate_node_texts(elem:ET._Element, lang:str, throttle:float):
    if elem.text is not None and safe_str(elem.text).strip():
        elem.text = translate_text_unit(elem.text, lang)
        if throttle: time.sleep(throttle)
    for child in list(elem):
        translate_node_texts(child, lang, throttle)
        if child.tail is not None and safe_str(child.tail).strip():
            child.tail = translate_text_unit(child.tail, lang)
            if throttle: time.sleep(throttle)

def translate_all_notes(root:ET._Element, lang:str, throttle:float):
    for note in root.findall(".//{*}note"):
        translate_node_texts(note, lang, throttle)

def translate_accessibility_attrs(root:ET._Element, lang:str, throttle:float):
    ATTRS=("title","alt","aria-label")
    for el in root.iter():
        for k in ATTRS:
            if k in el.attrib:
                val=safe_str(el.attrib.get(k))
                if val.strip():
                    el.attrib[k]=translate_text_unit(val, lang)
                    if throttle: time.sleep(throttle)

# ---------- Idiomas dinâmicos (com nome PT para os mais comuns) ----------
pt_overrides = {
    "en": "Inglês",
    "pt": "Português",
    "es": "Espanhol",
    "fr": "Francês",
    "de": "Alemão",
    "it": "Italiano",
    "nl": "Holandês",
    "sv": "Sueco",
    "no": "Norueguês",
    "da": "Dinamarquês",
    "fi": "Finlandês",
    "pl": "Polonês",
    "cs": "Tcheco",
    "sk": "Eslovaco",
    "sl": "Esloveno",
    "hu": "Húngaro",
    "ro": "Romeno",
    "bg": "Búlgaro",
    "el": "Grego",
    "tr": "Turco",
    "ru": "Russo",
    "uk": "Ucraniano",
    "ar": "Árabe",
    "he": "Hebraico",
    "hi": "Hindi",
    "bn": "Bengali",
    "th": "Tailandês",
    "vi": "Vietnamita",
    "id": "Indonésio",
    "ms": "Malaio",
    "zh-CN": "Chinês (Simplificado)",
    "zh-TW": "Chinês (Tradicional)",
    "ja": "Japonês",
    "ko": "Coreano",
    "fa": "Persa (Farsi)",
    "ur": "Urdu",
    "sw": "Suaíli",
    "tl": "Filipino",
    "lv": "Letão",
    "lt": "Lituano",
    "et": "Estoniano",
    "is": "Islandês",
    "ga": "Irlandês (Gaélico)",
    "mt": "Maltês",
    "af": "Africâner",
}

try:
    supported = GoogleTranslator().get_supported_languages(as_dict=True)  # {'en':'english', ...}
except Exception:
    supported = {"en":"english","pt":"portuguese","es":"spanish","fr":"french","de":"german"}

labels_codes = []
for code, name in supported.items():
    name_pt = pt_overrides.get(code, name.capitalize())
    labels_codes.append((name_pt, code))

labels_codes.sort(key=lambda x: x[0])
label_default = next((lbl for lbl, c in labels_codes if c == "en"), labels_codes[0][0])

col_lang, col_throttle = st.columns([2,1])
with col_lang:
    language_label = st.selectbox("Idioma de destino", [lbl for lbl,_ in labels_codes], index=[lbl for lbl,_ in labels_codes].index(label_default))
lang_code = dict(labels_codes)[language_label]
with col_throttle:
    throttle = st.number_input("Intervalo (s)", min_value=0.0, max_value=2.0, value=0.0, step=0.1)

uploaded = st.file_uploader("Selecione o arquivo .xlf/.xliff do Rise", type=["xlf","xliff"])
run = st.button("Traduzir arquivo")

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

    prog = st.progress(0.0); status = st.empty()
    def _p(i,t,phase="segments"):
        pct = min(max(i/ t,0),1) if t>0 else 0.0
        prog.progress(pct); status.write(f"{'Traduzindo' if phase=='segments' else phase}: {i}/{t}" if t else f"{phase}…")

    try:
        parser = ET.XMLParser(remove_blank_text=False)
        root = ET.fromstring(data, parser=parser)

        pairs = iter_source_target_pairs(root); total=len(pairs)
        for i,(src,tgt) in enumerate(pairs, start=1):
            translate_node_texts(src, lang_code, throttle)
            tgt = ensure_target_for_source(src, tgt)
            tgt.clear()
            for ch in list(src): tgt.append(deepcopy(ch))
            tgt.text = safe_str(src.text)
            if len(src): tgt[-1].tail = safe_str(src[-1].tail)
            _p(i,total,"segments")

        notes = root.findall(".//{*}note"); tn=len(notes)
        for j,n in enumerate(notes, start=1):
            translate_node_texts(n, lang_code, throttle); _p(j, tn if tn else 1, "notes")

        attr_nodes=[]; ATTRS=("title","alt","aria-label")
        for el in root.iter():
            if any(a in el.attrib for a in ATTRS): attr_nodes.append(el)
        ta=len(attr_nodes)
        for k,el in enumerate(attr_nodes, start=1):
            for a in ATTRS:
                if a in el.attrib:
                    v=safe_str(el.attrib.get(a))
                    if v.strip():
                        el.attrib[a]=translate_text_unit(v, lang_code)
                        if throttle: time.sleep(throttle)
            _p(k, ta if ta else 1, "attributes")

        out_bytes = ET.tostring(root, encoding="utf-8", xml_declaration=True, pretty_print=True)
        st.success("Tradução concluída!")
        base = os.path.splitext(uploaded.name)[0]
        out_name = f"{base}-{lang_code}.xlf"
        st.download_button("Baixar XLIFF traduzido", data=out_bytes, file_name=out_name, mime="application/xliff+xml")

    except Exception as e:
        st.error(f"Erro ao traduzir: {e}")

st.markdown("<hr/>", unsafe_allow_html=True)
st.markdown("<div class='footer'>Direitos Reservados à Área de Educação a Distância - Firjan SENAI Maracanã</div>", unsafe_allow_html=True)
