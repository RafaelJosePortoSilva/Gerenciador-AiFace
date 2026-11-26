# Gestor de Relógios AiFace

Webservice (FastAPI) para listar relógios de ponto **AiFace / AI Biometric Device Management System** em uma lista manual de IPs, ler seus campos e aplicar configurações **personalizadas** ou **modelos padronizados**.

## Como executar

```bat
run.bat
```

O `run.bat` escuta em **0.0.0.0:8000**, então o painel abre localmente em `http://127.0.0.1:8000` e também de outras máquinas da rede em `http://IP-DESTE-PC:8000` (descubra o IP com `ipconfig`). A documentação interativa fica em `/docs`.

Para rodar em outra porta:

```bat
.venv\Scripts\python.exe -m uvicorn app.main:app --host 0.0.0.0 --port 8080
```

**Antes de expor na rede, defina um token** — sem ele, qualquer pessoa na LAN poderá configurar os relógios:

```bat
set WPS_API_TOKEN=um-token-forte
run.bat
```

O painel pede o token no topo e o salva no `localStorage`. Chamadas à API devem enviar o cabeçalho `X-API-Token`. Se o Windows Firewall bloquear o acesso, libere a porta:

```bat
netsh advfirewall firewall add rule name="Gestor AiFace 8000" dir=in action=allow protocol=TCP localport=8000
```

## Configuração

### `config/devices.json`

Lista manual de equipamentos. `defaults` serve para senha, porta, usuário e timeout padrão. Exemplo:

```json
{
  "defaults": { "port": 80, "scheme": "http", "username": "admin", "password": "123", "timeout": 3.0 },
  "devices": [
    { "id": "relogio-01", "host": "192.168.1.38", "label": "Recepção", "location": "Matriz", "tags": ["matriz"], "enabled": true },
    { "id": "J Melo", "host": "192.168.1.43", "label": "J Melo", "enabled": true }
  ]
}
```

Também é possível cadastrar/editar/remover equipamentos pelo painel ou pelas rotas `/api/devices`.

### `config/profiles.json`

Modelos de configuração. Os campos usam valores **legíveis** (IP em pontos, `HH:MM`, `MM/DD`), não os inteiros da API do equipamento:

```json
{
  "name": "padrao-matriz",
  "description": "Padrão da matriz",
  "fields": { "language": 19, "time_format": 0, "serverip": "192.168.1.10", "door_opentime": 5 },
  "company": { "companyname": "Minha Empresa", "companycpny": "" }
}
```

Edite no painel (aba **Modelos**), diretamente no arquivo ou use **Salvar como modelo** na aba Configuração para copiar o estado atual de um equipamento. Nesse caso, os campos secretos são removidos e a origem (equipamento/IP/serial) fica registrada no modelo.

## Funcionamento

1. **Identificação:** `GET /home.html` procura marcadores da interface e `POST /api` com `{"cmd":"getlang"}` confirma a assinatura e devolve o número de série.
2. **Leitura:** `reg`, `getdevinfo` e `getcompanyfile`. IPs, horários e datas são decodificados (`app/codec.py`).
3. **Configuração por categorias:** a aba Configuração reproduz as 13 categorias da tela *Device setup* do equipamento, na mesma ordem: `elevator control`, `Enroll Option`, `Shift`, `Time`, `Bell`, `System=>Device setup`, `System=>Advanced setup`, `lock setting`, `Comm set=>serial`, `Comm set=>server`, `Comm set=>Ethernet`, `Comm set=>WIFI` e `Comm set=>APP Notify`. Cada categoria tem seu botão **Enviar para o Dispositivo**. **Prévia de todas as abas** e **Enviar todas as abas para o Dispositivo** cobrem as 13 categorias e os dados da empresa de uma só vez.
4. **Aplicação personalizada:** os campos informados são mesclados sobre a configuração **atual** lida do equipamento e enviados em `setdevinfo` (com `password`, `cmd` e `nowtime`). Isso evita zerar parâmetros não informados.
5. **Modelo a partir do equipamento:** **Salvar como modelo** lê a configuração atual, remove campos secretos, inclui a empresa quando marcado e grava um modelo reutilizável. A prévia mostra quantidade de campos e alguns valores antes da confirmação.
6. **Biblioteca de firmware:** o botão **Salvar arquivo na biblioteca** grava o `.zip`/`.pkg` em `data/firmware/` com metadados em `data/firmware.json` (nome, tamanho, MD5, descrição e data). Depois é só escolher o arquivo salvo no painel e usar **Enviar arquivo salvo para o Dispositivo**, sem selecionar o arquivo novamente.
7. **Atualizar FW:** aceita `.zip` ou `.pkg` (para `.pkg`, o nome precisa conter `-update-`). O arquivo é enviado em chunks de 1 MiB para `/api/firmware/upload`, com MD5 progressivo e uma última requisição vazia com o MD5 final, exatamente como a página do equipamento. O painel valida o arquivo, mostra progresso e pede confirmação. O envio aceita um arquivo local ou um `firmware_id` da biblioteca.
8. **Aplicação padronizada:** um modelo é aplicado a um ou vários equipamentos; opcionalmente inclui os dados da empresa (`setcompanyfile`).
9. **Segurança:** toda escrita exige `confirm: true` na API; o painel mostra uma prévia e pede confirmação. Todas as aplicações são registradas em `data/history.jsonl`.

### Rotas principais

| Método | Rota | Descrição |
|---|---|---|
| GET | `/api/health` |healthcheck |
| GET | `/api/meta` | campos configuráveis, campos secretos, comandos de leitura |
| GET / POST | `/api/devices` | listar / cadastrar equipamentos |
| POST | `/api/devices/refresh` | sondar todos os equipamentos da lista manual |
| GET | `/api/devices/{id}` | identificação + configuração + empresa |
| GET | `/api/devices/{id}/config` | configuração atual decodificada |
| POST | `/api/devices/{id}/preview` | prévia de alterações (sem gravar) |
| POST | `/api/devices/{id}/apply` | aplicar campos personalizados (`confirm: true`) |
| POST | `/api/devices/{id}/company` | aplicar dados da empresa |
| POST | `/api/devices/{id}/save-profile` | salvar configuração atual como modelo (`confirm: true`) |
| POST | `/api/devices/{id}/command` | comando somente-leitura (ex.: `getrtlog`) |
| POST | `/api/devices/{id}/firmware` | validar/enviar firmware local (`file`) ou salvo (`firmware_id`), `confirm: true` |
| GET | `/api/devices/{id}/firmware/jobs/{job_id}` | progresso/resultado do envio de firmware |
| GET / POST | `/api/firmware` | listar / salvar arquivos na biblioteca (`confirm: true` no POST) |
| DELETE | `/api/firmware/{id}?confirm=true` | excluir arquivo salvo da biblioteca |
| GET | `/api/devices/{id}/diff?profile=nome` | diferenças entre equipamento e modelo |
| GET / POST / DELETE | `/api/profiles` | modelos de configuração |
| POST | `/api/bulk/apply` | aplicar modelo a vários equipamentos |
| GET | `/api/history` | histórico de alterações |

Exemplo de aplicação personalizada:

```bat
curl -X POST http://127.0.0.1:8000/api/devices/relogio-01/apply ^
  -H "Content-Type: application/json" ^
  -d "{\"fields\":{\"language\":19,\"serverip\":\"192.168.1.10\",\"door_opentime\":5},\"confirm\":true,\"operator\":\"joao\"}"
```

Envio de firmware (resposta traz o `job_id` para acompanhamento):

```bat
curl -X POST http://127.0.0.1:8000/api/devices/J%20Melo/firmware ^
  -F "file=@firmware-update-1.0.pkg" ^
  -F "confirm=true" ^
  -F "operator=joao"
```

Salvar na biblioteca e depois enviar o arquivo salvo:

```bat
curl -X POST http://127.0.0.1:8000/api/firmware ^
  -F "file=@firmware-update-1.0.pkg" ^
  -F "description=Versao 2.20" ^
  -F "confirm=true"

curl -X POST http://127.0.0.1:8000/api/devices/J%20Melo/firmware ^
  -F "firmware_id=ID-RETORNADO-ACIMA" ^
  -F "confirm=true" ^
  -F "operator=joao"
```

## Testes

```bat
.venv\Scripts\python.exe tests\smoke_test.py
```

O teste sobe um equipamento AiFace simulado e um servidor isolado em portas próprias, validando identificação, decodificação, prévia e envio de todas as abas, categorias, novos campos, empresa, modelo salvo do equipamento, lote, biblioteca de firmware, upload de firmware local e salvo (chunks, MD5 e progresso) e histórico. Não grava nos arquivos de configuração do projeto nem em equipamentos reais.

Para isolar configurações/dados de outra instância, use as variáveis `WPS_CONFIG_DIR` e `WPS_DATA_DIR`.

## Observações

- O equipamento envia a senha em texto claro no JSON da API e expõe senhas internas em `getdevinfo`. O painel mascara esses campos; o arquivo `config/devices.json` contém as credenciais em texto claro — proteja o acesso ao host.
- O serviço usa apenas a lista manual de IPs (sem varredura automática da rede), conforme definido.
- Antes de aplicar em lote, use **Prévia** para conferir as diferenças.
