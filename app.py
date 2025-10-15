import os, time, re, base64, requests
from copy import deepcopy
from typing import List, Tuple, Optional
from pathlib import Path

import streamlit as st
from lxml import etree as ET
import streamlit.components.v1 as components

# ===============================================
# CONFIGURAÇÃO GERAL
# ===============================================
st.set_page_config(page_title="Tradutor XLIFF • Firjan SENAI", page_icon="🌍", layout="wide")

PRIMARY = "#83c7e5"
st.markdown(f"""
<style>
body {{ background:#000; color:#fff; }}
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

# ===============================================
# LOGO
# ===============================================
def show_logo():
    p = Path(__file__).parent / "firjan_senai_branco_horizontal.png"
    if p.exists():
        b64 = base64.b64encode(p.read_bytes()).decode("utf-8")
        st.markdown(
            f"""
            <div style="width:100%;display:flex;justify-content:left;margin-bottom:4px;">
              <img src="data:image/png;base64,{b64}" style="max-width:250px;width:100%;height:100px;display:block;" />
            </div>
            """,
            unsafe_allow_html=True,
        )

show_logo()
st.markdown("<h1 style='text-align:center; margin-top:0;'>Tradutor de Cursos - Articulate Rise</h1>", unsafe_allow_html=True)
st.caption("Tradução completa de cursos do Português para outras línguas")

# ===============================================
# FUNÇÕES AUXILIARES
# ===============================================
def safe_str(x) -> str:
    return "" if x is None else str(x)

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
    except:
        protected = text
    return protected, tokens

def restore_nontranslatable(text: str, tokens):
    text = safe_str(text)
    if not tokens:
        return text
    try:
        def _r(m):
            i = int(m.group(1))
            return tokens[i] if 0 <= i < len(tokens) else m.group(0)
        return re.sub(r"§§K(\d+)§§", _r, text)
    except:
        return text

# ===============================================
# FUNÇÃO DE TRADUÇÃO VIA LIBRETRANSLATE (COM FALLBACK)
# ===============================================
def translate_text_unit(text: str, target_lang: str) -> str:
    """
    Tradução via LibreTranslate com fallback entre endpoints públicos.
    Mantém placeholders e estrutura XML intacta.
    """
    text = safe_str(text)
    if not text.strip():
        return text

    t, toks = protect_nontranslatable(text)
    out = t

    endpoints = [
        "https://libretranslate.com/translate",  # endpoint principal
        "https://translate.argosopentech.com/translate",  # backup 1
        "https://translate.astian.org/translate",  # backup 2
    ]

    payload = {
        "q": t,
        "source": "auto",  # detecta automaticamente idioma de origem
        "target": target_lang,
        "format": "text"
    }

    headers = {"Content-Type": "application/json"}

    for url in endpoints:
        try:
            resp = requests.post(url, json=payload, headers=headers, timeout=30)
            if resp.status_code == 200 and "translatedText" in resp.json():
                out = resp.json()["translatedText"]
                break
            else:
                print(f"[ERRO {resp.status_code}] em {url}: {resp.text}")
        except Exception as e:
            print(f"[ERRO LIBRETRANSLATE - {url}] {e}")
            continue

    return safe_str(restore_nontranslatable(out, toks))

# ===============================================
# XML E TRADUÇÃO
# ===============================================
def get_namespaces(root) -> dict:
    nsmap = {}
    if root.nsmap:
        for k, v in root.nsmap.items():
            nsmap[k if k is not None else "ns"] = v
    if not nsmap:
        nsmap = {"ns": "urn:oasis:names:tc:xliff:document:1.2"}
    return nsmap

def detect_version(root) -> str:
    d = root.nsmap.get(None, "") or ""
    if "urn:oasis:names:tc:xliff:document:2.0" in d or (root.get("version", "") == "2.0"):
        return "2.0"
    return "1.2"

def iter_source_target_pairs(root) -> List[Tuple[ET._Element, Optional[ET._Element]]]:
    ns = get_namespaces(root)
    v = detect_version(root)
    pairs = []
    if v == "2.0":
        units = root.xpath(".//ns:unit", namespaces=ns) or root.findall(".//unit")
        for u in units:
            segs = u.xpath(".//ns:segment", namespaces=ns) or u.findall(".//segment")
            for s in segs:
                src = s.find(".//{*}source"); tgt = s.find(".//{*}target")
                if src is not None: pairs.append((src, tgt))
    else:
        units = root.xpath(".//ns:trans-unit", namespaces=ns) or root.findall(".//trans-unit")
        for u in units:
            src = u.find(".//{*}source"); tgt = u.find(".//{*}target")
            if src is not None: pairs.append((src, tgt))
    return pairs

def ensure_target_for_source(src: ET._Element, tgt: Optional[ET._Element]) -> ET._Element:
    if tgt is not None:
        return tgt
    qn = ET.QName(src); tag = qn.localname.replace("source", "target")
    return ET.SubElement(src.getparent(), f"{{{qn.namespace}}}{tag}") if qn.namespace else ET.SubElement(src.getparent(), "target")

def translate_node_texts(elem: ET._Element, lang: str):
    if elem.text is not None and safe_str(elem.text).strip():
        elem.text = translate_text_unit(elem.text, lang)
    for child in list(elem):
        translate_node_texts(child, lang)
        if child.tail is not None and safe_str(child.tail).strip():
            child.tail = translate_text_unit(child.tail, lang)

def translate_all_notes(root: ET._Element, lang: str):
    for note in root.findall(".//{*}note"):
        translate_node_texts(note, lang)

def translate_accessibility_attrs(root: ET._Element, lang: str):
    ATTRS = ("title", "alt", "aria-label")
    for el in root.iter():
        for k in ATTRS:
            if k in el.attrib:
                val = safe_str(el.attrib.get(k))
                if val.strip():
                    el.attrib[k] = translate_text_unit(val, lang)

# ===============================================
# INTERFACE
# ===============================================
options = [
    ("Inglês", "en"),
    ("Português", "pt"),
    ("Espanhol", "es"),
    ("Francês", "fr"),
    ("Alemão", "de"),
    ("Italiano", "it"),
]
language_label = st.selectbox("Idioma de destino", [lbl for lbl, _ in options])
lang_code = dict(options)[language_label]

uploaded = st.file_uploader("Selecione o arquivo .xlf/.xliff do Rise", type=["xlf", "xliff"])

components.html("""
<script>
(function () {
  function replaceText(root, matcher, newText) {
    const nodes = root.querySelectorAll("p, span, div");
    for (const n of nodes) {
      const t = (n.textContent || "").trim();
      if (matcher(t)) { n.textContent = newText; return true; }
    }
    return false;
  }
  function inject() {
    const doc = window.parent.document;
    const dz = doc.querySelector('[data-testid="stFileUploaderDropzone"]');
    if (!dz) return false;
    replaceText(dz, t => /drag and drop/i.test(t), "Arraste e solte o arquivo aqui");
    replaceText(dz, t => /limit.*xlf|limit\\s*200\\s*mb/i.test(t), "Limite de 200 MB por arquivo • XLF, XLIFF");
    const btn = doc.querySelector('[data-testid="stFileUploader"] button');
    if (btn) {
      const lbl = btn.querySelector("p, span, div");
      if (lbl) lbl.textContent = "Escolher arquivo";
    }
    return true;
  }
  const id = setInterval(function(){ if (inject()) clearInterval(id); }, 80);
})();
</script>
""", height=0)

# ===============================================
# PROCESSAMENTO
# ===============================================
run = st.button("Traduzir arquivo")

def process(data: bytes, lang_code: str, prog, status):
    parser = ET.XMLParser(remove_blank_text=False)
    root = ET.fromstring(data, parser=parser)
    pairs = iter_source_target_pairs(root)
    total = max(len(pairs), 1)
    status.text("0% concluído…")
    prog.progress(0.0)
    for i, (src, tgt) in enumerate(pairs, start=1):
        translate_node_texts(src, lang_code)
        tgt = ensure_target_for_source(src, tgt)
        tgt.clear()
        for ch in list(src):
            tgt.append(deepcopy(ch))
        tgt.text = safe_str(src.text)
        if len(src):
            tgt[-1].tail = safe_str(src[-1].tail)
        if i == 1 or i % 10 == 0 or i == total:
            frac = i / total
            percent = int(round(frac * 100))
            prog.progress(frac)
            status.text(f"{percent}% concluído…")
    translate_all_notes(root, lang_code)
    translate_accessibility_attrs(root, lang_code)
    prog.progress(1.0)
    status.text("100% concluído — finalizando arquivo…")
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
    prog = st.progress(0.0)
    status = st.empty()
    try:
        with st.spinner("Traduzindo…"):
            out_bytes = process(data, lang_code, prog, status)
        st.success("Tradução concluída!")
        base = os.path.splitext(uploaded.name)[0]
        out_name = f"{base}-{lang_code}.xlf"
        st.download_button("Baixar XLIFF traduzido", data=out_bytes, file_name=out_name, mime="application/xliff+xml")
    except Exception as e:
        st.error(f"Erro ao traduzir: {e}")

st.markdown("<hr/>", unsafe_allow_html=True)
st.markdown("<div class='footer'>Direitos Reservados à Área de Educação a Distância - Firjan SENAI Maracanã</div>", unsafe_allow_html=True)
