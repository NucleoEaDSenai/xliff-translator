import os, re, base64
from copy import deepcopy
from pathlib import Path
import streamlit as st
from lxml import etree as ET
from deep_translator import GoogleTranslator
import streamlit.components.v1 as components

st.set_page_config(page_title="Tradutor XLIFF • Firjan SENAI", page_icon="🌍", layout="wide")

PRIMARY = "#83c7e5"
st.markdown(f"""
<style>
html, body {{ background:#000; color:#fff; -webkit-user-select:none; -ms-user-select:none; user-select:none; }}
.block-container {{ padding-top: 1.2rem; max-width: 1280px; }}
h1,h2,h3,p,span,div,label,small {{ color:#fff !important; }}
.stButton>button {{ background:#333; color:{PRIMARY}; font-weight:700; border:none; border-radius:8px; padding:.6rem 1rem; }}
.stProgress > div > div > div > div {{ background-color: {PRIMARY}; }}
hr {{ border: 0; border-top: 1px solid #222; margin: 24px 0; }}
.footer {{ text-align:center; color:#aaa; font-size:12px; margin-top:32px; }}
.stSelectbox > div {{ width: 100% !important; }}
div[data-baseweb="select"] {{ min-width: 720px !important; }}
</style>
""", unsafe_allow_html=True)

def show_logo():
    p = Path(__file__).parent / "firjan_senai_branco_horizontal.png"
    if p.exists():
        b64 = base64.b64encode(p.read_bytes()).decode("utf-8")
        st.markdown(
            f"""
            <div style="width:100%;display:flex;justify-content:flex-start;margin-bottom:4px;">
              <img src="data:image/png;base64,{b64}" style="max-width:260px;width:100%;height:auto;display:block;" />
            </div>
            """,
            unsafe_allow_html=True,
        )

show_logo()
st.markdown("<h1 style='text-align:center;margin-top:0;'>Tradutor de Cursos - Articulate Rise</h1>", unsafe_allow_html=True)
st.caption("Tradução completa de cursos do Português para outras línguas")

def safe_str(x): return "" if x is None else str(x)
PLACEHOLDER_RE = re.compile(r"(\{\{.*?\}\}|\{.*?\}|%s|%d|%\(\w+\)s)")

def protect_nontranslatable(text):
    text = safe_str(text)
    if not text: return "", []
    tokens=[]
    def _sub(m):
        tokens.append(m.group(0))
        return f"§§K{len(tokens)-1}§§"
    try: protected = PLACEHOLDER_RE.sub(_sub, text)
    except: protected = text
    return protected, tokens

def restore_nontranslatable(text, tokens):
    text = safe_str(text)
    if not tokens: return text
    try:
        def _r(m):
            i = int(m.group(1))
            return tokens[i] if 0 <= i < len(tokens) else m.group(0)
        return re.sub(r"§§K(\d+)§§", _r, text)
    except: return text

def translate_text_unit(text, target_lang):
    text = safe_str(text)
    if not text.strip(): return text
    t, toks = protect_nontranslatable(text)
    out = t
    try: out = safe_str(GoogleTranslator(source="auto", target=target_lang).translate(t))
    except: out = t
    return safe_str(restore_nontranslatable(out, toks))

def get_namespaces(root):
    nsmap={}
    if root.nsmap:
        for k,v in root.nsmap.items():
            nsmap[k if k is not None else "ns"]=v
    if not nsmap: nsmap={"ns":"urn:oasis:names:tc:xliff:document:1.2"}
    return nsmap

def detect_version(root):
    d = root.nsmap.get(None,"") or ""
    if "urn:oasis:names:tc:xliff:document:2.0" in d or (root.get("version","")== "2.0"): return "2.0"
    return "1.2"

def iter_source_target_pairs(root):
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
    if tgt is not None: return tgt
    qn=ET.QName(src); tag=qn.localname.replace("source","target")
    return ET.SubElement(src.getparent(), f"{{{qn.namespace}}}{tag}") if qn.namespace else ET.SubElement(src.getparent(),"target")

def translate_node_texts(elem, lang):
    if elem.text is not None and safe_str(elem.text).strip():
        elem.text = translate_text_unit(elem.text, lang)
    for child in list(elem):
        translate_node_texts(child, lang)
        if child.tail is not None and safe_str(child.tail).strip():
            child.tail = translate_text_unit(child.tail, lang)

def translate_all_notes(root, lang):
    for note in root.findall(".//{*}note"):
        translate_node_texts(note, lang)

def translate_accessibility_attrs(root, lang):
    for el in root.iter():
        for k in ("title","alt","aria-label"):
            if k in el.attrib:
                v=safe_str(el.attrib.get(k))
                if v.strip():
                    el.attrib[k]=translate_text_unit(v, lang)

PT_FULL = {
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
    "yo":"Iorubá","zu":"Zulu"
}

def get_google_lang_pairs():
    try:
        d = GoogleTranslator().get_supported_languages(as_dict=True)
        k, v = next(iter(d.items()))
        if isinstance(v, str) and (len(v) <= 10 and v.isalpha() or "-" in v):
            pairs = [(v, k)]
            for name, code in list(d.items())[1:]:
                pairs.append((code, name))
        else:
            pairs = list(d.items())
    except Exception:
        pairs = [("en","english"),("pt","portuguese"),("es","spanish"),("fr","french"),("de","german"),("it","italian")]
    return pairs

pairs = get_google_lang_pairs()
options = []
for code, engname in pairs:
    label = PT_FULL.get(code, engname.capitalize())
    options.append((label, code))
options.sort(key=lambda x: x[0])

language_label = st.selectbox("Idioma de destino", [lbl for lbl,_ in options])
lang_code = dict(options)[language_label]

uploaded = st.file_uploader("Selecione o arquivo .xlf/.xliff do Rise", type=["xlf","xliff"])

st.markdown("""
<style>
[data-testid="stFileUploaderDropzone"] { position: relative; }
[data-testid="stFileUploaderDropzone"] span,
[data-testid="stFileUploaderDropzone"] p { visibility: hidden; }
[data-testid="stFileUploaderDropzone"]::before {
  content: "Arraste e solte o arquivo aqui";
  visibility: visible;
  position: absolute;
  left: 56px;
  top: 18px;
  color: #fff;
  font-weight: 600;
}
[data-testid="stFileUploaderDropzone"]::after {
  content: "Limite de 200MB por arquivo • XLF, XLIFF";
  visibility: visible;
  position: absolute;
  left: 56px;
  top: 44px;
  color: #bbb;
  font-size: 0.9rem;
}
</style>
""", unsafe_allow_html=True)

components.html("""
<script>
(function () {
  const block = (e) => {
    if (e.key && (e.ctrlKey || e.metaKey)) {
      const k = e.key.toLowerCase();
      if (["c","x","s","u","p","a"].includes(k)) { e.preventDefault(); return false; }
    }
  };
  const id = setInterval(() => {
    const doc = window.parent.document;
    if (!doc) return;
    doc.addEventListener('contextmenu', e => e.preventDefault(), {passive:false});
    doc.addEventListener('copy', e => e.preventDefault(), {passive:false});
    doc.addEventListener('cut', e => e.preventDefault(), {passive:false});
    doc.addEventListener('keydown', block, {passive:false});
    const up = doc.querySelector('[data-testid="stFileUploader"] button');
    if (up) {
      const n = up.querySelector('p, span, div');
      if (n) n.textContent = 'Escolher arquivo';
    }
    clearInterval(id);
  }, 120);
})();
</script>
""", height=0)

run = st.button("Traduzir arquivo")

def process(data, lang_code):
    parser = ET.XMLParser(remove_blank_text=False)
    root = ET.fromstring(data, parser=parser)
    pairs = iter_source_target_pairs(root)
    for src, tgt in pairs:
        translate_node_texts(src, lang_code)
        tgt = ensure_target_for_source(src, tgt)
        tgt.clear()
        for ch in list(src): tgt.append(deepcopy(ch))
        tgt.text = safe_str(src.text)
        if len(src): tgt[-1].tail = safe_str(src[-1].tail)
    translate_all_notes(root, lang_code)
    translate_accessibility_attrs(root, lang_code)
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
    except: pass
    try:
        out_bytes = process(data, lang_code)
        st.success("Tradução concluída!")
        base = os.path.splitext(uploaded.name)[0]
        out_name = f"{base}-{lang_code}.xlf"
        st.download_button("Baixar XLIFF traduzido", data=out_bytes, file_name=out_name, mime="application/xliff+xml")
    except Exception as e:
        st.error(f"Erro ao traduzir: {e}")

st.markdown("<hr/>", unsafe_allow_html=True)
st.markdown("<div class='footer'>Direitos Reservados à Área de Educação a Distância - Firjan SENAI Maracanã · Uso interno autorizado · Cópia e redistribuição não permitidas</div>", unsafe_allow_html=True)
