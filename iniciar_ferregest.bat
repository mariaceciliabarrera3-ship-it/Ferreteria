@echo off
setlocal enabledelayedexpansion
title FerreGest AR
cd /d "%~dp0"

echo ============================================
echo   FerreGest AR - iniciando...
echo ============================================
echo.

REM --- 1. Verificar que Python este instalado ---
python --version >nul 2>&1
if errorlevel 1 (
    echo No se encontro Python instalado en esta computadora.
    echo.
    echo Se va a abrir la pagina de descarga. Instale Python
    echo marcando la casilla "Add Python to PATH" durante la
    echo instalacion, y despues vuelva a abrir este archivo.
    echo.
    start https://www.python.org/downloads/
    pause
    exit /b 1
)

REM --- 2. Crear el entorno virtual, solo la primera vez ---
if not exist ".venv\Scripts\python.exe" (
    echo Primera vez: preparando FerreGest, puede tardar un par
    echo de minutos. Las proximas veces arranca mucho mas rapido.
    echo.
    python -m venv .venv
    if errorlevel 1 (
        echo No se pudo crear el entorno. Revise que Python se
        echo instalo correctamente y vuelva a intentar.
        pause
        exit /b 1
    )
    ".venv\Scripts\python.exe" -m pip install --upgrade pip -q
    ".venv\Scripts\python.exe" -m pip install -r requirements.txt -q
    if errorlevel 1 (
        echo Hubo un problema instalando los componentes. Revise
        echo su conexion a Internet e intente de nuevo.
        pause
        exit /b 1
    )
)

REM --- 3. Configurar el modo de la instalacion ---
REM     Esta copia es la del comercio: funciona completa, con
REM     login propio, sin control de licencia (pago unico).
set FERREGEST_MODE=production
set FERREGEST_REQUIRE_LICENSE=0
set FERREGEST_SETUP_WIZARD=1

REM --- 5. Abrir el navegador cuando el servidor este listo ---
start "" /b cmd /c "timeout /t 3 /nobreak >nul && start http://127.0.0.1:8000"

echo.
echo FerreGest se esta abriendo en su navegador...
echo Si es la primera vez, le va a pedir que cree su propio
echo usuario y contraseña.
echo NO CIERRE ESTA VENTANA mientras este trabajando: si la
echo cierra, el programa se apaga.
echo Para cerrar el programa, cierre esta ventana o presione
echo Ctrl+C.
echo.

REM --- 6. Levantar el servidor (ventana abierta todo el dia) ---
".venv\Scripts\python.exe" run.py

pause
