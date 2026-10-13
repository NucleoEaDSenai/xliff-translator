@echo off
title Tradutor XLIFF - Firjan SENAI
cd /d "%~dp0"

rem Usa o launcher "py" se existir; senao, "python"
where py >nul 2>nul && (set "PY=py") || (set "PY=python")

rem Primeira execucao: cria o ambiente virtual
if not exist ".venv\Scripts\python.exe" (
    echo Criando ambiente virtual...
    %PY% -m venv .venv
    if errorlevel 1 (
        echo.
        echo [ERRO] Python nao encontrado. Instale em https://www.python.org/downloads/
        echo        e marque a opcao "Add Python to PATH" durante a instalacao.
        pause
        exit /b 1
    )
)

rem Instala as dependencias (so na primeira vez ou se a instalacao anterior falhou)
if not exist ".venv\.instalado" (
    echo Instalando dependencias...
    ".venv\Scripts\python.exe" -m pip install --upgrade pip
    ".venv\Scripts\python.exe" -m pip install -r requirements.txt
    if errorlevel 1 (
        echo.
        echo [ERRO] Falha ao instalar as dependencias. Verifique sua internet.
        pause
        exit /b 1
    )
    echo ok> ".venv\.instalado"
)

echo.
echo Iniciando o app... o navegador vai abrir em http://localhost:8501
echo Para encerrar, feche esta janela ou pressione Ctrl+C.
echo.
".venv\Scripts\python.exe" -m streamlit run app.py

pause
