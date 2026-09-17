@echo off
cd /d "%~dp0"
echo ============================================
echo   Installation des dependances...
echo ============================================
pip install -r requirements.txt

if "%DISCORD_TOKEN%"=="" (
    echo.
    set /p DISCORD_TOKEN="Colle ton token Discord ici puis appuie sur Entree : "
)

echo.
echo ============================================
echo   Lancement du bot...
echo ============================================
python bot.py

pause
