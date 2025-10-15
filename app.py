import os
import re
from copy import deepcopy
from pathlib import Path
from typing import Optional, List
import streamlit as st
from lxml import etree as ET
from openai import OpenAI

# ==============================
# CONFIGURAÇÃO
# ==============================
st.set_page_config(page_title="Tradutor XLIFF GPT", layout="wide")
st.title("🌍 Tradutor de Arquivos XLIFF com ChatGPT")

st.markdown("""
Use este aplicativo para traduzir arquivos do Articulate Rise (.xlf / .xliff) usando sua conta do ChatGPT.
- Mantém **todas as tags** e placeholders intactos.
- Funciona com versões **XLIFF 1.2 e 2.0**.
- Pode traduzir **português ↔ inglês ↔ espanhol ↔ outros idiomas**.
""")

# ==============================
# CONFIGURAR CHAVE OPENAI
# ==============================
# ⚠️ NUNCA COLOQUE SUA CHAVE AQUI DIRETAMENTE
# Defina no terminal ou nas secrets do Streamlit Cloud:
# export OPENAI_API_KEY="sua_chave_aqui"
client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))

# ==============================
# FUNÇÕES AUXILIARES
# ==============================
def safe_str(x) -> str:
    return "" if x is None else str(x)

PLACEHOLDER_RE = re.compile(r"(\{\{.*?\}\}|\{.*?\}|%s|%d|%\(\w+\)s)")

def protect_nontranslatable(text: str):
    """Protege variáveis e placeholders ({{ }}, %s etc.) antes de traduzir."""
    text = safe_str(text)
    tokens = []
    def _sub(m):
        tokens.append(m.group(0))
        return f"§§K{len(tokens)-1}§§"
    protected = PLACEHOLDER_RE.sub(_sub, text)
    return protected, tokens

def restore_nontranslatable(text: str, tokens):
    """Restaura variáveis e placeholders no texto traduzido."""
    def _r(m):
        i = int(m.group(1))
        return tokens[i] if 0 <= i < len(tokens) else m.group(0)
    return re.sub(r"§§K(\d+)§§", _r, text)

def flatten_text(elem):
    """Extrai todo o texto visível de um elemento (incluindo tags <g>, <ph>, etc.)."""
    parts = []
    if elem.text:
        parts.append(elem.text)
    for child in elem:
        parts.append(flatten_text(child))
        if child.tail:
            parts.append(child.tail)
    return "".join(parts)

# ==============================
# FUNÇÃO DE TRADUÇÃO COM GPT
# ==============================
def translate_text_unit(text: str, target_lang: str) -> str:
    text = safe_str(text)
    if not text.strip():
        return text

    t, toks = protect_nontranslatable(text)
    prompt = f"""
Traduza o texto abaixo para {target_lang}.
Mantenha todas as tags, placeholders e formatações intactos.
Use linguagem natural, técnica e coerente com cursos e-learning.
Texto:
{t}
"""
    try:
        response = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[{"role": "user", "content": prompt}],
            temperature=0.2,
        )
        translated = response.choices[0].message.content.strip()
        return safe_str(restore_nontranslatable(translated, toks))
    except Exception as e:
        st.error(f"Erro ao traduzir via GPT: {e}")
        return text

# ==============================
# FUNÇÕES XML
# ==============================
def get_namespaces(root) -> dict:
    nsmap = root.nsmap or {}
    if not nsmap:
        nsmap = {"ns": "urn:oasis:names:tc:xliff:document:1.2"}
    return nsmap

def iter_source_target_pairs(root) -> List:
    """
    Retorna pares (source, target) para XLIFF 1.2 e 2.0.
    Funciona com namespaces padrão (ex: xmlns="urn:oasis:names:tc:xliff:document:1.2").
    """
    pairs = []
    # Busca universal, sem depender de prefixo
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

def translate_source_element(src: ET._Element, lang: str):
    """Traduz o texto inteiro (incluindo aninhamentos) de uma tag <source>."""
    full_text = flatten_text(src)
    if not full_text.strip():
        return
    translated = translate_text_unit(full_text, lang)

    # Limpa filhos antigos e substitui conteúdo traduzido
    for child in list(src):
        src.remove(child)
    src.text = translated

# ==============================
# INTERFACE
# ==============================
langs = {
    "Inglês": "en",
    "Português": "pt",
    "Espanhol": "es",
    "Francês": "fr",
    "Alemão": "de",
    "Italiano": "it"
}
lang_label = st.selectbox("Escolha o idioma de destino", list(langs.keys()))
lang_code = langs[lang_label]

uploaded = st.file_uploader("Envie um arquivo XLIFF (.xlf ou .xliff)", type=["xlf", "xliff"])

if uploaded and st.button("🚀 Traduzir arquivo"):
    try:
        data = uploaded.read()
        parser = ET.XMLParser(remove_blank_text=False)
        root = ET.fromstring(data, parser=parser)
        pairs = iter_source_target_pairs(root)
        total = len(pairs)
        st.info(f"{total} segmentos encontrados.")

        prog = st.progress(0.0)
        status = st.empty()

        for i, (src, tgt) in enumerate(pairs, start=1):
            translate_source_element(src, lang_code)
            tgt = ensure_target_for_source(src, tgt)
            tgt.clear()
            tgt.text = src.text
            frac = i / total
            prog.progress(frac)
            status.text(f"Traduzindo... {int(frac*100)}%")

        output = ET.tostring(root, encoding="utf-8", xml_declaration=True, pretty_print=True)
        st.success("Tradução concluída ✅")
        st.download_button(
            label="📥 Baixar arquivo traduzido",
            data=output,
            file_name=f"{os.path.splitext(uploaded.name)[0]}_{lang_code}.xlf",
            mime="application/xliff+xml",
        )

    except Exception as e:
        st.error(f"Erro ao processar: {e}")

st.markdown("---")
st.caption("💡 Desenvolvido para cursos Articulate Rise — Tradução com OpenAI GPT.")
