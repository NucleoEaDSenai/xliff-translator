import os
import re
from copy import deepcopy
from typing import List
import requests
import streamlit as st
from lxml import etree as ET

# ==========================================
# CONFIGURAÇÃO DA INTERFACE
# ==========================================
st.set_page_config(page_title="Tradutor XLIFF • LibreTranslate", layout="wide")
st.title("🌍 Tradutor XLIFF com LibreTranslate (100 % Gratuito)")

st.markdown("""
Use este aplicativo para traduzir arquivos `.xlf` ou `.xliff` do **Articulate Rise** sem precisar de API paga.  
- ✅ Gratuito (usa LibreTranslate)  
- ✅ Mantém tags e placeholders  
- ✅ Suporte a XLIFF 1.2 e 2.0  
- ✅ Funciona em Streamlit Cloud ou localmente
""")

# ==========================================
# FUNÇÕES AUXILIARES
# ==========================================
def safe_str(x): return "" if x is None else str(x)

PLACEHOLDER_RE = re.compile(r"(\{\{.*?\}\}|\{.*?\}|%s|%d|%\(\w+\)s)")

def protect_nontranslatable(text):
    text = safe_str(text)
    tokens = []
    def _sub(m):
        tokens.append(m.group(0))
        return f"§§K{len(tokens)-1}§§"
    return PLACEHOLDER_RE.sub(_sub, text), tokens

def restore_nontranslatable(text, tokens):
    def _r(m):
        i = int(m.group(1))
        return tokens[i] if 0 <= i < len(tokens) else m.group(0)
    return re.sub(r"§§K(\d+)§§", _r, text)

def flatten_text(elem):
    """Extrai todo o texto visível, incluindo conteúdo dentro de <g>, <ph> etc."""
    parts = []
    if elem.text:
        parts.append(elem.text)
    for child in elem:
        parts.append(flatten_text(child))
        if child.tail:
            parts.append(child.tail)
    return "".join(parts)

# ==========================================
# TRADUÇÃO COM LIBRETRANSLATE
# ==========================================
ENDPOINTS = [
    "https://libretranslate.com/translate",
    "https://translate.argosopentech.com/translate",
    "https://libretranslate.de/translate"
]

def translate_text_unit(text, target_lang):
    text = safe_str(text)
    if not text.strip():
        return text
    t, toks = protect_nontranslatable(text)
    out = t

    for url in ENDPOINTS:
        try:
            resp = requests.post(url, json={
                "q": t, "source": "auto", "target": target_lang, "format": "text"
            }, timeout=25)
            if resp.status_code == 200:
                data = resp.json()
                out = data.get("translatedText", t)
                break
            else:
                print(f"[{resp.status_code}] {url}")
        except Exception as e:
            print(f"[Erro LibreTranslate] {url}: {e}")
            continue

    return restore_nontranslatable(out, toks)

# ==========================================
# LEITURA DO XLIFF
# ==========================================
def iter_source_target_pairs(root) -> List:
    """Funciona com XLIFF 1.2 e 2.0 (sem depender de namespace)."""
    pairs = []
    units = root.findall(".//{*}trans-unit") or root.findall(".//{*}unit")
    for u in units:
        src = u.find(".//{*}source")
        tgt = u.find(".//{*}target")
        if src is not None:
            pairs.append((src, tgt))
    return pairs

def ensure_target_for_source(src, tgt):
    if tgt is not None:
        return tgt
    qn = ET.QName(src)
    tag = qn.localname.replace("source", "target")
    return ET.SubElement(src.getparent(), f"{{{qn.namespace}}}{tag}")

def translate_source_element(src, lang):
    full_text = flatten_text(src)
    if not full_text.strip():
        return
    translated = translate_text_unit(full_text, lang)
    for child in list(src):
        src.remove(child)
    src.text = translated

# ==========================================
# INTERFACE STREAMLIT
# ==========================================
langs = {
    "Inglês": "en",
    "Português": "pt",
    "Espanhol": "es",
    "Francês": "fr",
    "Alemão": "de",
    "Italiano": "it"
}
lang_label = st.selectbox("Idioma de destino", list(langs.keys()))
lang_code = langs[lang_label]

uploaded = st.file_uploader("Envie um arquivo XLIFF (.xlf / .xliff)", type=["xlf", "xliff"])

if uploaded and st.button("🚀 Traduzir arquivo"):
    try:
        data = uploaded.read()
        parser = ET.XMLParser(remove_blank_text=False)
        root = ET.fromstring(data, parser=parser)
        pairs = iter_source_target_pairs(root)
        total = len(pairs)
        st.info(f"{total} segmentos encontrados.")
        if total == 0:
            st.warning("Nenhum segmento encontrado. Verifique se o arquivo está no formato XLIFF válido.")
        prog = st.progress(0.0)
        status = st.empty()

        for i, (src, tgt) in enumerate(pairs, start=1):
            translate_source_element(src, lang_code)
            tgt = ensure_target_for_source(src, tgt)
            tgt.clear()
            tgt.text = src.text
            frac = i / max(total, 1)
            prog.progress(frac)
            status.text(f"Traduzindo... {int(frac * 100)}%")

        output = ET.tostring(root, encoding="utf-8", xml_declaration=True, pretty_print=True)
        st.success("Tradução concluída ✅")
        st.download_button(
            label="📥 Baixar XLIFF traduzido",
            data=output,
            file_name=f"{os.path.splitext(uploaded.name)[0]}_{lang_code}.xlf",
            mime="application/xliff+xml",
        )
    except Exception as e:
        st.error(f"Erro ao processar: {e}")

st.markdown("---")
st.caption("💡 Tradutor gratuito com LibreTranslate — Compatível com Articulate Rise XLIFF 1.2 e 2.0.")
