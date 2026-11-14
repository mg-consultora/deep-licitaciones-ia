@echo off
REM Doble clic: corre el agente de licitaciones, después el módulo de obras, y abre el tablero (Windows).
cd /d "%~dp0"
python agente.py
python obras.py
start "" "salida\tablero.html"
pause
