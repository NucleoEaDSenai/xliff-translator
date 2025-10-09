import os, time, re, base64, html
from copy import deepcopy
from typing import List, Tuple, Optional
from pathlib import Path
import streamlit as st
from lxml import etree as ET
from deep_translator import GoogleTranslator
import streamlit.components.v1 as components

# ==============================
# CONFIGURAÇÃO DE INTERFACE
# ==============================
st.set_page_config(page_title="Tradutor & Revisor XLIFF • Firjan SENAI", page_icon="🌍", layout="wide")
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

def show_logo():
    p = Path(__file__).parent / "firjan_senai_branco_horizontal.png"
    if p.exists():
        b64 = base64.b64encode(p.read_bytes()).decode("utf-8")
        st.markdown(f"""
        <div style="width:100%;display:flex;justify-content:left;margin-bottom:4px;">
          <img src="data:image/png;base64,{b64}" style="max-width:250px;width:100%;height:100px;display:block;" />
        </div>""", unsafe_allow_html=True)
show_logo()

st.markdown("<h1 style='text-align:center; margin-top:0;'>Tradutor e Revisor de Cursos - Articulate Rise</h1>", unsafe_allow_html=True)
st.caption("Tradução e revisão completa de cursos do Rise em formato XLIFF")

# ==============================
# FUNÇÕES AUXILIARES
# ==============================
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

# ==============================
# TRADUÇÃO
# ==============================
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

# ==============================
# REVISÃO (IA OFFLINE)
# ==============================
def revise_text_natural(text:str)->str:
    """Revisão textual leve e natural (offline, sem APIs externas)"""
    text = safe_str(text)
    if not text.strip(): return text
    original = text
    t, toks = protect_nontranslatable(text)

    # Pequenas correções
    t = re.sub(r"\s+", " ", t)  # remover espaços duplos
    t = re.sub(r"\s([?.!,;:])", r"\1", t)  # ajustar pontuação
    t = re.sub(r"\bdeve-se\b", "deve", t)
    t = re.sub(r"\bpara que possa\b", "para que você possa", t)
    t = re.sub(r"\bnecessário\b", "preciso", t)
    t = re.sub(r"\bconsulte, sempre que necessário\b", "consulte sempre que precisar", t)
    t = re.sub(r"\bconsiderando que\b", "como", t)
    t = re.sub(r"\bafim de\b", "para", t)
    t = re.sub(r"\bprossiga\b", "siga", t)
    t = t.strip()
    if t and not t.endswith(('.', '?', '!')):
        t += '.'

    out = restore_nontranslatable(t, toks)
    # Evita perder maiúsculas iniciais
    if original and original[0].isupper() and out:
        out = out[0].upper() + out[1:]
    return out

# ==============================
# XML / XLIFF
# ==============================
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
    if "2.0" in d or (root.get("version","")== "2.0"):
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

# ==============================
# INTERFACE
# ==============================
mode = st.selectbox("Ação desejada", ["Traduzir", "Revisar texto", "Traduzir + Revisar"])

pairs = GoogleTranslator().get_supported_languages(as_dict=True)
options = sorted([(v.capitalize(), k) for k, v in pairs.items()])
language_label = st.selectbox("Idioma de destino (para tradução)", [lbl for lbl,_ in options])
lang_code = dict(options)[language_label]

uploaded = st.file_uploader("Selecione o arquivo .xlf/.xliff do Rise", type=["xlf","xliff"])
run = st.button("Executar")

# ==============================
# PROCESSAMENTO
# ==============================
def process(data: bytes, lang_code: str, prog, status, mode: str):
    parser = ET.XMLParser(remove_blank_text=False)
    root = ET.fromstring(data, parser=parser)
    pairs = iter_source_target_pairs(root)
    total = max(len(pairs), 1)
    status.text("0% concluído…")
    prog.progress(0.0)

    report_rows = []
    for i, (src, tgt) in enumerate(pairs, start=1):
        text_original = safe_str(src.text)
        text_result = text_original

        if mode in ["Traduzir", "Traduzir + Revisar"]:
            text_result = translate_text_unit(text_result, lang_code)
        if mode in ["Revisar texto", "Traduzir + Revisar"]:
            revised = revise_text_natural(text_result)
            if revised != text_result:
                report_rows.append((text_original, revised))
            text_result = revised

        tgt = ensure_target_for_source(src, tgt)
        tgt.clear()
        tgt.text = safe_str(text_result)

        if i == 1 or i % 10 == 0 or i == total:
            frac = i / total
            prog.progress(frac)
            status.text(f"{int(frac*100)}% concluído…")

    prog.progress(1.0)
    status.text("100% concluído — finalizando arquivo…")

    # Gera relatório HTML
    if report_rows:
        html_rows = "".join(
            f"<tr><td>{html.escape(o)}</td><td>{html.escape(r)}</td></tr>"
            for o, r in report_rows
        )
        html_content = f"""
        <html><head><meta charset='utf-8'>
        <style>
        body {{font-family:Arial,sans-serif;background:#111;color:#eee;padding:20px;}}
        table {{width:100%;border-collapse:collapse;}}
        th,td {{border:1px solid #444;padding:8px;vertical-align:top;}}
        th {{background:#222;}}
        tr:nth-child(even) {{background:#1b1b1b;}}
        td:first-child {{color:#f88;}}
        td:last-child {{color:#8f8;}}
        </style></head><body>
        <h2>Relatório de Revisão Textual</h2>
        <table>
        <tr><th>Original</th><th>Revisado</th></tr>
        {html_rows}
        </table></body></html>
        """
        Path("relatorio_revisao.html").write_text(html_content, encoding="utf-8")

    return ET.tostring(root, encoding="utf-8", xml_declaration=True, pretty_print=True)

# ==============================
# EXECUÇÃO
# ==============================
if run:
    if not uploaded:
        st.error("Envie um arquivo .xlf/.xliff.")
        st.stop()
    data = uploaded.read()
    prog = st.progress(0.0)
    status = st.empty()
    try:
        with st.spinner("Processando…"):
            out_bytes = process(data, lang_code, prog, status, mode)
        st.success("Processo concluído com sucesso!")
        base = os.path.splitext(uploaded.name)[0]
        suffix = "revisado" if "Revisar" in mode else lang_code
        out_name = f"{base}-{suffix}.xlf"
        st.download_button("Baixar arquivo processado", data=out_bytes, file_name=out_name, mime="application/xliff+xml")
        if Path("relatorio_revisao.html").exists():
            st.info("Relatório de revisão gerado: relatorio_revisao.html")
            with open("relatorio_revisao.html", "r", encoding="utf-8") as f:
                components.html(f.read(), height=400, scrolling=True)
    except Exception as e:
        st.error(f"Erro ao processar: {e}")

st.markdown("<hr/>", unsafe_allow_html=True)
st.markdown("<div class='footer'>Direitos Reservados à Área de Educação a Distância - Firjan SENAI Maracanã</div>", unsafe_allow_html=True)
