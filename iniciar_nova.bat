@echo off
cd /d B:\NOVA

:: Watchdog en background (sin consola, se auto-gestiona)
start "" "C:\Users\Alex\AppData\Local\Programs\Python\Python311\pythonw.exe" "B:\NOVA\watchdog.py"

:: Lanzar NOVA en background
start "" "C:\Users\Alex\AppData\Local\Programs\Python\Python311\python.exe" "B:\NOVA\nova.py"

:: Esperar a que el servidor Flask arranque
timeout /t 6 /nobreak >nul

:: Abrir HUD v2 en Chrome a pantalla completa
start "" "C:\Program Files\Google\Chrome\Application\chrome.exe" --start-fullscreen --new-window "http://127.0.0.1:5000/v2"
