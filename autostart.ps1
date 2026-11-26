# Inicia o Gestor de Relogios AiFace em segundo plano apos o logon.
# Nao abre janela de console e nao inicia uma segunda instancia se a porta 8000 ja estiver em uso.

$project = Split-Path -Parent $MyInvocation.MyCommand.Definition
$pythonw = Join-Path $project '.venv\Scripts\pythonw.exe'

if (-not (Test-Path -LiteralPath $pythonw)) {
    exit 1
}

$alreadyRunning = Get-NetTCPConnection -LocalPort 8000 -State Listen -ErrorAction SilentlyContinue
if (-not $alreadyRunning) {
    Start-Process -FilePath $pythonw `
        -ArgumentList '-m', 'uvicorn', 'app.main:app', '--host', '0.0.0.0', '--port', '8000' `
        -WorkingDirectory $project `
        -NoNewWindow
}
