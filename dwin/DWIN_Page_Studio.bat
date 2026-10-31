@echo off
rem DWIN Page Studio - edit the DWIN display's pages and deploy them to the SD card
cd /d "%~dp0"
python dwin_studio.py
if errorlevel 1 pause
