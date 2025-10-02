import io
import os
import re
import time
from typing import List, Tuple, Optional

import streamlit as st
from lxml import etree as ET

# ------ Provedores de tradução ------
from deep_translator import GoogleTranslator
try:
    import deepl  # opcional, se tiver DEEPL_API_KEY
except Exception:
    deepl = None

st.set_page_config(page_title="XLIFF → EN Translator", page_icon="🌍", layout="centered")

PRIMARY = "#83c7e5"  # azul SENAI
st.markdown(f"""
<style>
body {{ background:#000; color:#fff; }}
h1,h2,h3,label,span,div,p {{ color:#fff !important; }}
.block-container {{ padding-top: 1.5rem; }}
.stButton>button {{
  background:#333; color:{PRIMARY}; font-weight:700; border:none; border-radius:8px; padding:.6rem 1rem;
}}
.stProgress > div > div > div > div {{ background-color: {PRIMARY}; }}
.stSelectbox>div>div>div {{ color:#000 !important; }} /* dropdown itens */
</style>
""", unsafe_allow_html=True)

st.title("🌍 XLIFF Translator (para EN)")
st.caption("Carregue um arquivo .xlf/.xliff, escolha o provedor e baixe o arquivo traduzido. Dark mode friendly ✨")

# ---------------- Utils ----------------
PLACEHOLDER_RE = re.compile(r"(\{\{.*?\}\}|\{.*?\}|%s|%d|%\(\w+\)s|<[^>]+>)")

def protect_placeholders(text: str) -> Tuple[str, List[str]]:
    """Troca placeholders ({{...}}, {…}, %s, tags inline) por <P0>, <P1>… e retorna texto+tokens."""
    if not text:
        return "", []
    tokens = []
    def _sub(m):
        tokens.append(m.group(0))
        return f"<P{len(tokens)-1}>"
    protected = PLACEHOLDER_RE.sub(_sub, text)
    return protected, tokens

def restore_placeholders(text: str, tokens: List[str]) -> str:
    def _restore(m):
        idx = int(m.group(1))
        return tokens[idx] if 0 <= idx < len(tokens) else m.group(0)
    return re.sub(r"<P(\d+)>", _restore, text)

def translate_google(txt: str, target_lang: str = "en") -> str:
    if not txt or not txt.strip():
        return txt or ""
    protected, tokens = protect_placeholders(txt)
    out = GoogleTranslator(source="auto", target=target_lang).translate(protected)
    return restore_placeholders(out, tokens)

def translate_deepl(txt: str, translator, target_lang: str = "EN") -> str:
    if not txt or not txt.strip():
        return txt or ""
    protected, tokens = protect_placeholders(txt)
    res = translator.translate_text(protected, target_lang=target_lang)
    out = res.text if hasattr(res, "text") else str(res)
    return restore_placeholders(out, tokens)

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

def iter_segments(root) -> List[Tuple[ET._Element, Optional[ET._Element]]]:
    """
    Retorna pares (source_elem, target_elem) para XLIFF 1.2 (<trans-unit>) e 2.0 (<unit>/<segment>).
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
        units = root.xpath(".//ns:trans-unit", namespaces=ns) or root.findall(".//trans-unit")
        for u in units:
            src = u.find(".//{*}source")
            tgt = u.find(".//{*}target")
            if src is not None:
                pairs.append((src, tgt))
    return pairs

def set_text(elem: ET._Element, text: str):
    # Simples: mantém apenas elem.text. (Se seu XLF usa muitos inlines, podemos evoluir.)
    elem.text = text

def translate_xliff_bytes(
    data: bytes,
    provider: str = "google",
    target_lang: str = "en",
    overwrite_source: bool = True,
    throttle_secs: float = 0.0,             # pause opcional entre chamadas (evita bloqueios)
    progress_cb=None
) -> bytes:
    parser = ET.XMLParser(remove_blank_text=False)
    root = ET.fromstring(data, parser=parser)

    # opcional: DeepL
    deepl_translator = None
    if provider.lower() == "deepl":
        if deepl is None:
            raise RuntimeError("deepl não está instalado. Remova 'deepl' ou instale e defina DEEPL_API_KEY.")
        api_key = os.environ.get("DEEPL_API_KEY")
        if not api_key:
            raise RuntimeError("Defina a variável DEEPL_API_KEY para usar o DeepL.")
        deepl_translator = deepl.Translator(api_key)

    pairs = iter_segments(root)
    total = len(pairs)
    for i, (src, tgt) in enumerate(pairs, start=1):
        txt = (src.text or "").strip()
        if provider.lower() == "deepl":
            en = translate_deepl(txt, deepl_translator, target_lang.upper())
        else:
            en = translate_google(txt, target_lang)

        # garante <target>
        if tgt is None:
            qname = ET.QName(src)
            tag = qname.localname.replace("source", "target")
            tgt = ET.SubElement(src.getparent(), f"{{{qname.namespace}}}{tag}") if qname.namespace else ET.SubElement(src.getparent(), "target")

        set_text(tgt, en)
        if overwrite_source:
            set_text(src, en)

        if progress_cb:
            progress_cb(i, total)
        if throttle_secs:
            time.sleep(throttle_secs)

    # serializa
    return ET.tostring(root, encoding="utf-8", xml_declaration=True, pretty_print=True)

# ---------------- UI ----------------
col1, col2 = st.columns(2)
with col1:
    provider = st.selectbox("Provedor de tradução", ["google", "deepl"], help="DeepL requer DEEPL_API_KEY no ambiente.")
with col2:
    target_lang = st.text_input("Idioma de destino (ex.: en, es, fr)", value="en")

overwrite = st.checkbox("Sobrescrever <source> com o inglês (arquivo 100% em EN)", value=True)
throttle = st.number_input("Intervalo entre chamadas (segundos) — ajuda a evitar bloqueios", min_value=0.0, max_value=5.0, value=0.0, step=0.1)

uploaded = st.file_uploader("📂 Selecione o arquivo .xlf/.xliff", type=["xlf", "xliff"])

run = st.button("Traduzir arquivo")

if run:
    if not uploaded:
        st.error("Envie um arquivo .xlf primeiro.")
        st.stop()

    data = uploaded.read()
    st.write("Analisando XLIFF…")

    # Pré-contagem para barra de progresso
    try:
        root_tmp = ET.fromstring(data, parser=ET.XMLParser(remove_blank_text=False))
        pairs_tmp = iter_segments(root_tmp)
        total_tmp = len(pairs_tmp)
    except Exception as e:
        total_tmp = 0

    prog = st.progress(0.0)
    status = st.empty()

    def _progress(i, total):
        if total > 0:
            prog.progress(i / total)
            status.write(f"Traduzindo segmentos: {i}/{total}")

    try:
        out = translate_xliff_bytes(
            data=data,
            provider=provider,
            target_lang=target_lang,
            overwrite_source=overwrite,
            throttle_secs=throttle,
            progress_cb=_progress if total_tmp > 0 else None
        )
        st.success("✅ Tradução concluída!")
        out_name = os.path.splitext(uploaded.name)[0] + "-translated.xlf"
        st.download_button(
            label="⬇️ Baixar XLIFF traduzido",
            data=out,
            file_name=out_name,
            mime="application/xliff+xml"
        )
    except Exception as e:
        st.error(f"Erro ao traduzir: {e}")
