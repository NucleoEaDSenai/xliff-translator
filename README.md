# Tradutor XLIFF • Firjan SENAI

Aplicação web (Streamlit) para traduzir automaticamente arquivos **XLIFF** (`.xlf` / `.xliff`) exportados do **Articulate Rise** e do **Articulate Storyline**, usando o Google Tradutor.

O arquivo traduzido mantém a estrutura original (tags, formatação, IDs) e pode ser importado de volta na ferramenta da Articulate.

---

## Funcionalidades

- Tradução entre **Português, Inglês e Espanhol** (6 combinações).
- Suporte a **XLIFF 1.2 e 2.0** (detectado automaticamente).
- Dois modos:
  - **Articulate Rise (padrão)**
  - **Articulate Storyline**: além de traduzir, preenche o idioma de destino no cabeçalho (`target-language` / `trgLang`), marca os segmentos como `state="translated"` e traduz textos em atributos como `Text=`, `Label=`, `Alt=`, `Title=`, `Tooltip=` e `Value=`.
- **Protege o que não deve ser traduzido**: URLs, e-mails, variáveis do Storyline (`%Variavel%`), entidades HTML e números/datas.
- Traduz também **notas** (`<note>`) e **textos de acessibilidade** (`alt`, `title`, `aria-label` etc.).
- Corrige espaços perdidos entre trechos com formatação (negrito, itálico, links).
- Barra de progresso e download do arquivo traduzido ao final.

---

## Como usar

1. Na Articulate, exporte o curso para tradução no formato XLIFF.
2. Abra o app e escolha o **par de idiomas**.
3. Envie o arquivo `.xlf` / `.xliff`.
4. Escolha o **formato**: Rise ou Storyline.
5. Clique em **Executar tradução** e aguarde.
6. Clique em **Baixar XLIFF traduzido** e importe o arquivo de volta na Articulate.

Nome do arquivo gerado:

| Formato   | Exemplo de saída                  |
|-----------|-----------------------------------|
| Rise      | `meu-curso-es.xlf`                |
| Storyline | `meu-curso-storyline-es.xlf`      |

> A tradução é automática. **Revise o conteúdo** antes de publicar o curso.

---

## Como rodar localmente

### Requisitos

- [Python 3.9+](https://www.python.org/downloads/)
- Conexão com a internet (a tradução usa o Google Tradutor)

### Windows (forma mais fácil)

Dê dois cliques no arquivo **`iniciar.bat`**.

- Na **primeira execução**, ele cria o ambiente virtual e instala as dependências (pode levar alguns minutos).
- Nas próximas, abre o app direto.
- O navegador abre sozinho em <http://localhost:8501>.
- Para encerrar, feche a janela do terminal.

> Ao instalar o Python no Windows, marque a opção **"Add Python to PATH"**.

### Linux / macOS (ou Windows pelo terminal)

```bash
# 1. Criar e ativar o ambiente virtual (só na primeira vez)
python3 -m venv .venv
source .venv/bin/activate        # Windows: .venv\Scripts\activate

# 2. Instalar as dependências
pip install -r requirements.txt

# 3. Rodar o app
streamlit run app.py
```

O app abre em <http://localhost:8501>. Para parar, use `Ctrl+C`. Para sair do ambiente virtual, use `deactivate`.

---

## Estrutura do projeto

```
xliff-translator/
├── app.py                              # Aplicação Streamlit (interface + lógica de tradução)
├── requirements.txt                    # Dependências Python
├── iniciar.bat                         # Atalho para rodar no Windows
├── firjan_senai_branco_horizontal.png  # Logo
└── .streamlit/
    └── config.toml                     # Tema (modo escuro, cores da marca)
```

### Dependências

| Pacote            | Uso                                      |
|-------------------|------------------------------------------|
| `streamlit`       | Interface web                            |
| `lxml`            | Leitura e escrita do XML/XLIFF           |
| `deep-translator` | Tradução via Google Tradutor             |
| `pandas`          | Manipulação de dados                     |

---

## Observações

- O idioma de **origem** é detectado automaticamente pelo Google. O par escolhido define apenas o idioma de **destino**.
- Se um trecho falhar na tradução (ex.: queda de internet), ele é mantido no idioma original, sem interromper o processo.
- Arquivos grandes podem demorar, pois cada segmento é traduzido individualmente.

---

Direitos Reservados à Área de Ensino a Distância - Firjan SENAI Maracanã
