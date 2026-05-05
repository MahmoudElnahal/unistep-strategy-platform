@echo off
REM UNISTEP Platform v9 — Windows Run Script

cd /d "%~dp0"

if "%OPENAI_API_KEY%"=="" (
    if exist .env (
        echo Loading .env...
        for /f "tokens=*" %%i in (.env) do set %%i
    ) else (
        echo OPENAI_API_KEY not set!
        echo Run: set OPENAI_API_KEY=sk-...
        exit /b 1
    )
)

echo Starting UNISTEP Platform v9...
echo Browser: http://localhost:8000
echo Wizard:  http://localhost:8000/wizard
echo API:     http://localhost:8000/docs
echo.

set PYTHONPATH=.
uvicorn api.main:app --host 0.0.0.0 --port 8000 --reload --reload-dir core --reload-dir steps --reload-dir api
