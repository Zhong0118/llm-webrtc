@echo off
echo Activating virtual environment...
call .venv\Scripts\activate.bat

echo Starting Uvicorn server with SSL and reload...
uvicorn main_simple:app --host 0.0.0.0 --port 8000 --reload --ssl-keyfile ../frontend/certs/localhost+3-key.pem --ssl-certfile ../frontend/certs/localhost+3.pem

echo Server stopped. Deactivating environment...
call .venv\Scripts\deactivate.bat
pause