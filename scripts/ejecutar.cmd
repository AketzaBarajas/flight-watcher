@echo off
rem Lo que lanza el Programador de tareas (al iniciar sesion y cada hora de 08:00 a 24:00).
rem --una-vez-al-dia: si hoy ya hubo una ejecucion buena, sale sin consultar nada.
rem La salida se acumula en data\ultima_ejecucion.log
cd /d "%~dp0.."
".venv\Scripts\python.exe" -m vigilante --una-vez-al-dia >> "data\ultima_ejecucion.log" 2>&1
