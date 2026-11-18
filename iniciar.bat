@echo off
cd /d "%~dp0"
title BrightBean Studio
if not exist ".venv\Scripts\python.exe" (
  echo Primera vez: preparando entorno, puede tardar unos minutos...
  py -3.12 -m venv .venv || goto error
  ".venv\Scripts\python.exe" -m pip install -r requirements.txt || goto error
  ".venv\Scripts\python.exe" manage.py migrate || goto error
)
start "BrightBean - Tareas programadas" cmd /k ".venv\Scripts\python.exe manage.py process_tasks"
start "BrightBean - Servidor" cmd /k ".venv\Scripts\python.exe manage.py runserver"
timeout /t 8 >nul
start http://localhost:8000
exit /b
:error
echo.
echo Algo fallo. Copia el mensaje de arriba y pasaselo a Claude.
pause
