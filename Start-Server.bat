@echo off
echo Checking for Python...
python --version >nul 2>&1
if errorlevel 1 (
    echo ERROR: Python is not installed or not on your PATH.
    echo Download Python from https://www.python.org/downloads/
    pause
    exit /b 1
)

echo Installing dependencies...
python -m pip install -r requirements.txt --quiet

echo.
echo Starting iOS App Store Wizard...
echo Open your browser at: http://localhost:5000
echo Press Ctrl+C in this window to stop the server.
echo.
python app.py
pause
