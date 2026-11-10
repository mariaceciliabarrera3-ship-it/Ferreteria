#!/usr/bin/env bash
# Lanzador FerreGest AR - Mac/Linux (espejo logico de iniciar_ferregest.bat)
set -e
cd "$(dirname "$0")"

echo "============================================"
echo "  FerreGest AR - iniciando..."
echo "============================================"
echo

# --- 1. Verificar que Python este instalado ---
if ! command -v python3 >/dev/null 2>&1; then
    echo "No se encontro Python 3 instalado en esta computadora."
    echo "Instalelo desde https://www.python.org/downloads/ y vuelva a intentar."
    exit 1
fi

# --- 2. Crear el entorno virtual, solo la primera vez ---
if [ ! -f ".venv/bin/python3" ]; then
    echo "Primera vez: preparando FerreGest, puede tardar un par de minutos."
    echo "Las proximas veces arranca mucho mas rapido."
    echo
    python3 -m venv .venv
    .venv/bin/python3 -m pip install --upgrade pip -q
    .venv/bin/python3 -m pip install -r requirements.txt -q
fi

# --- 3. Configurar el modo de la instalacion ---
export FERREGEST_MODE=production
export FERREGEST_REQUIRE_LICENSE=0
export FERREGEST_SETUP_WIZARD=1

# --- 5. Abrir el navegador cuando el servidor este listo ---
(
    sleep 3
    if command -v open >/dev/null 2>&1; then
        open http://127.0.0.1:8000        # macOS
    elif command -v xdg-open >/dev/null 2>&1; then
        xdg-open http://127.0.0.1:8000    # Linux
    fi
) &

echo
echo "FerreGest se esta abriendo en su navegador..."
echo "NO CIERRE ESTA TERMINAL mientras este trabajando."
echo "Para cerrar el programa, presione Ctrl+C."
echo

# --- 6. Levantar el servidor ---
.venv/bin/python3 run.py
