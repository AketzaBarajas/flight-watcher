@echo off
rem Arranca el icono de la bandeja (iconos ocultos de la barra de tareas) sin consola.
rem Si ya estaba arrancado, abre directamente el panel.
cd /d "%~dp0.."
start "" ".venv\Scripts\pythonw.exe" -m vigilante.bandeja
