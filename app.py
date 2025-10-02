import io
import os
import re
import time
from typing import List, Tuple, Optional

import streamlit as st
from lxml import etree as ET

# Provedores de tradução
from deep_translator import GoogleTranslator
try:
    import deepl  # opcional (requer DEEPL_API_KEY)
except Exception:
    deepl = None

st.set_page_config(page_title="XLIFF → EN Translator", page_icon="🌍", layout="centered")

PRIMARY = "#83c7e5"  # azul SENAI
st.markdown(f"""
<style>
body {{ background:#000; color:#fff; }}
h1,h2,h3,label,span,div,p {{ color:#fff !important; }}
.block-container {{ padding-top: 1.2rem; max-width: 960px; }}
.stButton>button {{
  background:#333; color:{PRIMARY}; font-weight:700; border:none; border-radius:8px; padding:.6rem 1rem;
}}
.stProgress > div > div > div > div {{ background-color: {PRIMARY}; }}
</style>
""", unsafe_allow_html=True)

st.title("🌍 XLIFF Translator (full content, tags preserved)")
st.caption("Traduza .xlf/.xliff completos (1.2/2.0), preservando tags inline. Ideal para cursos Rise.")

# ---------------- Utils (placeholders/tags inline) ----------------
# Protege variáveis e símbolos comuns que NÃO devem ser traduzidos
PLACEHOLDER_RE = re.compile(r"(\{\{.*?\}\}|\{.*?\}|%s|%d|%\(\w+\)s)")

# Token especial para substituir sub-elementos inline (evita <...> no texto traduzido)
INLINE_TOKEN = "§§T{}§§"

def protect_nontranslatable(text: str) -> Tuple[str, List[str]]:
    """Protege {…}, {{…}}, %s, %d etc."""
    if not text:
        return "", []
    tokens = []
    def _sub(m):
        tokens.append(m.group(0))
        return f"§§K{len(tokens)-1}§§"
    protected = PLACEHOLDER_RE.sub(_sub, text)
    return protected, tokens

def restore_nontranslatable(text: str, tokens: List[str]) -> str:
    def _restore(m):
        idx = int(m.group(1))
        return tokens[idx] if 0 <= idx < len(tokens) else m.group(0)
    return re.sub(r"§§K(\d+)§§", _restore, text)

def extract_inner_with_inline_tokens(elem: ET._Element) -> Tuple[str, List[str]]:
    """
    Extrai TODO o conteúdo interno de <source> (texto+inlines), substituindo cada filho por token §§Tn§§.
    Retorna (string_com_tokens, lista_xml_children_serializados).
    """
    parts: List[str] = []
    child_xml: List[str] = []

    if elem.text:
        parts.append(elem.text)

    for i, child in enumerate(list(elem)):
        # serializa o filho (mantém suas tags internas)
        child_xml_str = ET.tostring(child, encoding="unicode")
        child_xml.append(child_xml_str)

        # coloca token para o lugar do filho
        parts.append(INLINE_TOKEN.format(i))

        # inclui o tail (texto após o filho) também
        if child.tail:
            parts.append(child.tail)

    return "".join(parts), child_xml

def rebuild_elem_from_fragment(elem: ET._Element, fragment: str):
    """
    Limpa elem e repovoa seu conteúdo com o fragmento XML (texto + tags inline restauradas).
    """
    # limpa
    for ch in list(elem):
        elem.remove(ch)
    elem.text = None

    # embrulha o fragmento para parsear como XML válido
    wrapper_xml = f"<wrapper>{fragment}</wrapper>"
    try:
        wrapper = ET.fromstring(wrapper_xml)
    except ET.XMLSyntaxError:
        # se der erro por caracteres especiais, como fallback: escape < >
        fragment_safe = fragment.replace("<", "&lt;").replace(">", "&gt;")
        wrapper = ET.fromstring(f"<wrapper>{fragment_safe}</wrapper>")

    # define elem.text e filhos na ordem correta
    elem.text = wrapper.text
    last = None
    for node in list(wrapper):
        wrapper.remove(node)
        elem.append(node)
        last = node
    if last is not None:
        last.tail = wrapper.tail

def translate_string_google(s: str, target_lang: str = "en") -> str:
    if not s or not s.strip():
        return s or ""
    # primeiro protege {…}, {{…}}, %s etc.
    s1, tokens = protect_nontranslatable(s)
    out = GoogleTranslator(source="auto", target=target_lang).translate(s1)
    return restore_nontranslatable(out, tokens)

def translate_string_deepl(s: str, translator, target_lang: str = "EN") -> str:
    if not s or not s.strip():
        return s or ""
    s1, tokens = protect_nontranslatable(s)
    res = translator.translate_text(s1, target_lang=target_lang)
    out = res.text if hasattr(res, "text") else str(res)
    return restore_nontranslatable(out, tokens)

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
    Retorna pares (source_elem, target_elem) para 1.2 e 2.0, cobrindo TODO o conteúdo (todas as páginas).
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
    if tgt is not None:
        return tgt
    qn = ET.QName(src)  # preserva namespace
    tag = qn.localname.replace("source", "target")
    return ET.SubElement(src.getparent(), f"{{{qn.namespace}}}{tag}") if qn.namespace else ET.SubElement(src.getparent(), "target")

def translate_xliff_bytes(
    data: bytes,
    provider: str = "google",
    target_lang: str = "en",
    overwrite_source: bool = True,
    throttle_secs: float = 0.0,
    progress_cb=None
) -> bytes:
    parser = ET.XMLParser(remove_blank_text=False)
    root = ET.fromstring(data, parser=parser)

    deepl_translator = None
    if provider.lower() == "deepl":
        if deepl is None:
            raise RuntimeError("deepl não instalado. Escolha 'google' ou instale e defina DEEPL_API_KEY.")
        api_key = os.environ.get("DEEPL_API_KEY")
        if not api_key:
            raise RuntimeError("Defina DEEPL_API_KEY para usar o DeepL.")
        deepl_translator = deepl.Translator(api_key)

    pairs = iter_source_target_pairs(root)
    total = len(pairs)

    for i, (src, tgt) in enumerate(pairs, start=1):
        # 1) extrai o inner XML do <source>, com tokens para inlines
        inner, inline_xml_list = extract_inner_with_inline_tokens(src)

        # 2) substitui tokens INLINE_TOKEN por marcadores de texto (sem < >) para não quebrar o tradutor
        #    Ex.: §§T0§§, §§T1§§...
        # (já extraímos assim)
        text_for_mt = inner

        # 3) traduz string completa (texto + tails), preservando {…}, %s etc.
        if provider.lower() == "deepl":
            translated = translate_string_deepl(text_for_mt, deepl_translator, target_lang.upper())
        else:
            translated = translate_string_google(text_for_mt, target_lang)

        # 4) restaura inlines: volta §§Tn§§ para o XML original do child
        for idx, child_xml in enumerate(inline_xml_list):
            translated = translated.replace(INLINE_TOKEN.format(idx), child_xml)

        # 5) garante <target> e escreve nele o fragmento traduzido
        tgt = ensure_target_for_source(src, tgt)
        rebuild_elem_from_fragment(tgt, translated)

        # 6) sobrescreve <source> se desejado (arquivo 100% em inglês)
        if overwrite_source:
            rebuild_elem_from_fragment(src, translated)

        # progresso / throttle
        if progress_cb:
            progress_cb(i, total)
        if throttle_secs:
            time.sleep(throttle_secs)

    return ET.tostring(root, encoding="utf-8", xml_declaration=True, pretty_print=True)

# ---------------- UI ----------------
col1, col2 = st.columns(2)
with col1:
    provider = st.selectbox("Provedor", ["google", "deepl"], help="DeepL requer DEEPL_API_KEY.")
with col2:
    target_lang = st.text_input("Idioma destino", value="en")

overwrite = st.checkbox("Sobrescrever <source> (arquivo 100% em inglês)", value=True)
throttle = st.number_input("Intervalo entre chamadas (s)", min_value=0.0, max_value=5.0, value=0.0, step=0.1)

uploaded = st.file_uploader("📂 Selecione o arquivo .xlf/.xliff", type=["xlf", "xliff"])
run = st.button("Traduzir arquivo")

if run:
    if not uploaded:
        st.error("Envie um arquivo .xlf/.xliff.")
        st.stop()

    data = uploaded.read()
    st.write("Analisando XLIFF…")

    # pré-contagem para barra de progresso
    try:
        tmp_root = ET.fromstring(data, parser=ET.XMLParser(remove_blank_text=False))
        total_pairs = len(iter_source_target_pairs(tmp_root))
    except Exception:
        total_pairs = 0

    prog = st.progress(0.0)
    status = st.empty()
    def _progress(i, total):
        if total > 0:
            prog.progress(i/total)
            status.write(f"Traduzindo: {i}/{total} segmentos")

    try:
        out_bytes = translate_xliff_bytes(
            data=data,
            provider=provider,
            target_lang=target_lang,
            overwrite_source=overwrite,
            throttle_secs=throttle,
            progress_cb=_progress if total_pairs>0 else None
        )
        st.success("✅ Tradução concluída!")
        out_name = os.path.splitext(uploaded.name)[0] + "-translated.xlf"
        st.download_button(
            label="⬇️ Baixar XLIFF traduzido",
            data=out_bytes,
            file_name=out_name,
            mime="application/xliff+xml"
        )
    except Exception as e:
        st.error(f"Erro ao traduzir: {e}")
