@echo off
cd /d "%~dp0"
if not exist ".venv\Scripts\python.exe" (
  echo Instale as dependencias antes: .venv\Scripts\python.exe -m pip install -r requirements.txt
  exit /b 1
)
echo.
echo Painel neste PC: http://127.0.0.1:8000
echo Painel na rede: http://IP-DESTE-PC:8000  ^(descubra com ipconfig^)
echo Documentacao da API: http://127.0.0.1:8000/docs
if "%WPS_API_TOKEN%"=="" echo AVISO: defina WPS_API_TOKEN antes de expor o servico na rede.
echo.
".venv\Scripts\python.exe" -m uvicorn app.main:app --host 0.0.0.0 --port 8000
