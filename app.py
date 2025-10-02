import os, time, re, base64
from copy import deepcopy
from typing import List, Tuple, Optional
from pathlib import Path

import streamlit as st
from lxml import etree as ET
from deep_translator import GoogleTranslator

st.set_page_config(page_title="Tradutor XLIFF • Firjan SENAI", page_icon="🌍", layout="centered")

PRIMARY = "#83c7e5"
st.markdown(f"""
<style>
body {{ background:#000; color:#fff; }}
.block-container {{ padding-top: 1.2rem; max-width: 1080px; }}
h1,h2,h3,p,span,div,label,small {{ color:#fff !important; }}
.stButton>button {{ background:#333; color:{PRIMARY}; font-weight:700; border:none; border-radius:8px; padding:.6rem 1rem; }}
.stProgress > div > div > div > div {{ background-color: {PRIMARY}; }}
hr {{ border: 0; border-top: 1px solid #222; margin: 24px 0; }}
.footer {{ text-align:center; color:#aaa; font-size:12px; margin-top:32px; }}
.header {{ display:flex; align-items:center; gap:16px; margin-bottom:8px; }}
.logo {{ display:flex; align-items:center; }}
</style>
""", unsafe_allow_html=True)

def _load_logo_bytes():
    candidates = [
        Path(__file__).parent / "firjan_senai_branco_horizontal.png",
        Path.cwd() / "firjan_senai_branco_horizontal.png",
    ]
    for p in candidates:
        if p.exists():
            return p.read_bytes()
    return None

with st.container():
    cols = st.columns([1.4, 6])
    with cols[0]:
        logo_bytes = _load_logo_bytes()
        if logo_bytes:
            st.image(logo_bytes, width=280)  # maior e fixo
    with cols[1]:
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

# ---------- Idiomas por extenso em PT ----------
pt_names = {
    "af":"Africâner","sq":"Albanês","am":"Amárico","ar":"Árabe","hy":"Armênio","az":"Azerbaijano",
    "eu":"Basco","be":"Bielorrusso","bn":"Bengali","bs":"Bósnio","bg":"Búlgaro","ca":"Catalão",
    "ceb":"Cebuano","ny":"Chichewa","zh-CN":"Chinês (Simplificado)","zh-TW":"Chinês (Tradicional)",
    "co":"Corso","hr":"Croata","cs":"Tcheco","da":"Dinamarquês","nl":"Holandês","en":"Inglês",
    "eo":"Esperanto","et":"Estoniano","fi":"Finlandês","fr":"Francês","fy":"Frísio","gl":"Galego",
    "ka":"Georgiano","de":"Alemão","el":"Grego","gu":"Guzerate","ht":"Crioulo haitiano",
    "ha":"Hauçá","haw":"Havaiano","he":"Hebraico","hi":"Hindi","hmn":"Hmong","hu":"Húngaro",
    "is":"Islandês","ig":"Igbo","id":"Indonésio","ga":"Irlandês (Gaélico)","it":"Italiano","ja":"Japonês",
    "jw":"Javanês","kn":"Canarim","kk":"Cazaque","km":"Khmer","ko":"Coreano","ku":"Curdo",
    "ky":"Quirguiz","lo":"Lao","la":"Latim","lv":"Letão","lt":"Lituano","lb":"Luxemburguês",
    "mk":"Macedônio","mg":"Malgaxe","ms":"Malaio","ml":"Malaiala","mt":"Maltês","mi":"Maori",
    "mr":"Marati","mn":"Mongol","my":"Myanmar (Birmanês)","ne":"Nepalês","no":"Norueguês",
    "or":"Oriá","ps":"Pachto","fa":"Persa (Farsi)","pl":"Polonês","pt":"Português",
    "pa":"Punjabi","ro":"Romeno","ru":"Russo","sm":"Samoano","gd":"Gaélico escocês","sr":"Sérvio",
    "st":"Sesoto","sn":"Shona","sd":"Sindi","si":"Sinhala","sk":"Eslovaco","sl":"Esloveno",
    "so":"Somali","es":"Espanhol","su":"Sundanês","sw":"Suaíli","sv":"Sueco","tl":"Filipino",
    "tg":"Tadjique","ta":"Tâmil","te":"Télugo","th":"Tailandês","tr":"Turco","uk":"Ucraniano",
    "ur":"Urdu","uz":"Uzbeque","vi":"Vietnamita","cy":"Galês","xh":"Xhosa","yi":"Iídiche",
    "yo":"Iorubá","zu":"Zulu","ka":"Georgiano","kk":"Cazaque","uz":"Uzbeque"
}

try:
    supported = GoogleTranslator().get_supported_languages(as_dict=True)  # {'en': 'english', ...}
except Exception:
    supported = {"en":"english","pt":"portuguese","es":"spanish","fr":"french","de":"german","it":"italian","ja":"japanese","zh-CN":"chinese (simplified)","zh-TW":"chinese (traditional)","ko":"korean"}

labels_codes = []
for code, name in supported.items():
    label = pt_names.get(code, name.capitalize())
    labels_codes.append((label, code))

labels_codes.sort(key=lambda x: x[0])
default_label = next((lbl for lbl, c in labels_codes if c == "en"), labels_codes[0][0])

c_lang, c_thr = st.columns([2,1])
with c_lang:
    language_label = st.selectbox("Idioma de destino", [lbl for lbl,_ in labels_codes],
                                  index=[lbl for lbl,_ in labels_codes].index(default_label))
lang_code = dict(labels_codes)[language_label]
with c_thr:
    throttle = st.number_input("Intervalo (s)", min_value=0.0, max_value=2.0, value=0.0, step=0.1)

uploaded = st.file_uploader("Selecione o arquivo .xlf/.xliff do Rise", type=["xlf","xliff"])
run = st.button("Traduzir arquivo")

def process(data: bytes, lang_code: str, throttle: float):
    parser = ET.XMLParser(remove_blank_text=False)
    root = ET.fromstring(data, parser=parser)
    pairs = iter_source_target_pairs(root)
    for i,(src,tgt) in enumerate(pairs, start=1):
        translate_node_texts(src, lang_code, throttle)
        tgt = ensure_target_for_source(src, tgt)
        tgt.clear()
        for ch in list(src): tgt.append(deepcopy(ch))
        tgt.text = safe_str(src.text)
        if len(src): tgt[-1].tail = safe_str(src[-1].tail)
    translate_all_notes(root, lang_code, throttle)
    translate_accessibility_attrs(root, lang_code, throttle)
    return ET.tostring(root, encoding="utf-8", xml_declaration=True, pretty_print=True)

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
    try:
        out_bytes = process(data, lang_code, throttle)
        prog.progress(1.0)
        st.success("Tradução concluída!")
        base = os.path.splitext(uploaded.name)[0]
        out_name = f"{base}-{lang_code}.xlf"
        st.download_button("Baixar XLIFF traduzido", data=out_bytes, file_name=out_name, mime="application/xliff+xml")
    except Exception as e:
        st.error(f"Erro ao traduzir: {e}")

st.markdown("<hr/>", unsafe_allow_html=True)
st.markdown("<div class='footer'>Direitos Reservados à Área de Educação a Distância - Firjan SENAI Maracanã</div>", unsafe_allow_html=True)
