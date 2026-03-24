# Bot Telegram com Biblioteca de Automações

Bot em Python para executar automações pelo Telegram com arquitetura separada entre:
- app de Telegram (`src/telegram_app.py`)
- biblioteca de automações (`src/automations_lib/`)

## Funcionalidades
- Comando `status` e `/status`
- Comando `/host` para monitoramento de infraestrutura (Locaweb, Meta e Cisco Umbrella)
- Comando `/zabbixh` para consultar metricas de hosts configurados no Zabbix
- Comando `/health` para latencia e falhas por fonte
- Comando `/all` para executar `status`, `/host` e listar lembretes de hoje/amanha
- Comandos utilitarios:
  - `/whois dominio.com`
  - `/cep 01001000`
  - `/ping host` (ping + traceroute)
  - `/ssl dominio.com[:porta]`
- `/voip` (teste SIP imediato)
  - executa pre-check `REGISTER` + `OPTIONS` e matriz de chamada (`self`, `target`, `externo`)
- `/voip_logs [quantidade]` (historico de testes VoIP)
  - `/note <aba> /<titulo> <texto>`
  - `/lembrete HH:MM texto`
- `/host` inclui Hostinger e monitoramento de sites sem API
- `/zabbixh` mostra CPU, memoria, uptime e uso do disco `/` por host configurado
- `/zabbixh` informa `nao encontrado` quando um item nao existir ou vier vazio
- `/zabbixh` informa claramente quando um host estiver indisponivel
- Logs estruturados em JSON com `trace_id` por execucao
- Registro de tentativas nao autorizadas, auditoria e estado em SQLite
- Monitoramento proativo:
  - checagem periodica com alerta somente quando houver mudanca real de estado
  - resumo automatico de manha e noite
  - prioridade por cliente/sistema com alerta reforcado para casos criticos
- Envio de 4 mensagens separadas no `status`:
1. Noticias (Top 10 G1, Top 10 TecMundo, ultimas 5 BoletimSec)
2. Clima de Sao Paulo (agora, 12:00, 19:00, 21:00, chuva 17:00-19:00)
3. Trends Brasil (fonte publica alternativa)
4. Cotacoes financeiras:
   - Bitcoin (BTC/BRL)
   - Dolar (USD/BRL)
   - Euro (EUR/BRL)
   - B3 (IBOV)

## Requisitos
- Python 3.10+

## Setup
```bash
python3 -m venv .venv
. .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
```

## Configuracao
Edite `.env` usando os comentarios do `.env.example` como fonte de verdade.

O template:
- lista todas as chaves versionadas no contrato operacional atual do projeto;
- descreve acima de cada chave o que preencher e o formato esperado;
- usa placeholders seguros, sem copiar segredos, senhas, tokens ou hosts reais.

Na inicializacao, o bot valida se o `.env` local contem todas as chaves do template e se os campos obrigatorios nao estao vazios.

### Variaveis do Zabbix
- `ZABBIX_BASE_URL`: URL base do Zabbix, por exemplo `https://exemplo.invalid/zabbix`
- `ZABBIX_API_TOKEN`: token da API do Zabbix; deve existir apenas no `.env`
- `ZABBIX_TIMEOUT_SECONDS`: timeout das chamadas HTTP para a API do Zabbix
- `ZABBIXH_HOST_TARGETS_JSON`: lista JSON com os hosts exibidos por `/zabbixh`

Exemplo seguro de `ZABBIXH_HOST_TARGETS_JSON`:

```json
[
  {"label":"01_TrueNas","hostid":"10679"},
  {"label":"09_ACCBServer","hostid":"10645"},
  {"label":"12_TOKYO-3","hostid":"10677"}
]
```

Esse campo existe para permitir inclusao, exclusao e edicao de hosts monitorados sem alterar codigo. O comando `/zabbixh` usa os `hostids` configurados nesse JSON e tenta resolver, para cada host, CPU, memoria, uptime e uso do disco `/`.

## Executar
```bash
.venv/bin/python src/main.py
```

## Testes
```bash
.venv/bin/python -m pytest -q
```

Para alteracoes no Zabbix, o gate minimo recomendado e:

```bash
.venv/bin/python -m pytest -q tests/test_zabbix_provider.py
.venv/bin/python -m pytest -q tests/test_command_router.py tests/test_telegram_app.py tests/test_config_loading.py
```

## Observacoes de seguranca
- Nao versione `.env`
- Mantenha o token apenas no `.env`
- O token exposto em conversa deve ser rotacionado no BotFather antes de uso em producao

## Ferramenta VoIP Separada
- Ferramenta em `tools/voip_probe/` (uso externo pela equipe de ferramentas).
- Execucao manual:
```powershell
python tools/voip_probe/main.py run-once --json
python tools/voip_probe/main.py logs --limit 5 --json
```
- Pre-requisito: `sipp` instalado no host de execucao.

## Diagnostico rapido
Se `python src/main.py` falhar nesta maquina, verifique primeiro:
- `python` pode nem existir no PATH; use `python3` para criar a venv
- `python3 src/main.py` sem a `.venv` ativa vai falhar por dependencias ausentes
- o comando suportado do projeto e `.venv/bin/python src/main.py`
