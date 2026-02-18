# Bot Telegram com Biblioteca de Automações

Bot em Python para executar automações pelo Telegram com arquitetura separada entre:
- app de Telegram (`src/telegram_app.py`)
- biblioteca de automações (`src/automations_lib/`)

## Funcionalidades
- Comando `status` e `/status`
- Comando `/host` para monitoramento de infraestrutura (Locaweb, Meta e Cisco Umbrella)
- Comando `/health` para latencia e falhas por fonte
- Comando `/all` para executar `status`, `/host` e listar lembretes de hoje/amanha
- Comandos utilitarios:
  - `/whois dominio.com`
  - `/cep 01001000`
  - `/ping host` (ping + traceroute)
  - `/ssl dominio.com[:porta]`
  - `/voips` (lista ramais VoIP conectados via AMI do Issabel/Asterisk)
  - `/note <aba> /<titulo> <texto>`
  - `/lembrete HH:MM texto`
- `/host` inclui Hostinger e monitoramento de sites sem API
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
```powershell
python -m venv .venv
.venv\Scripts\Activate.ps1
pip install -r requirements.txt
copy .env.example .env
```

## Configuracao
Edite `.env`:
- `TELEGRAM_BOT_TOKEN`: token do bot
- `TELEGRAM_ALLOWED_CHAT_ID`: chat autorizado para uso
- `FINANCE_AWESOMEAPI_URL`: endpoint de moedas e bitcoin (AwesomeAPI)
- `FINANCE_YAHOO_B3_URL`: endpoint do IBOV (Yahoo Chart API)
- `LOCAWEB_SUMMARY_URL`, `LOCAWEB_COMPONENTS_URL`, `LOCAWEB_INCIDENTS_URL`: endpoints da Locaweb
- `META_ORGS_URL`, `META_OUTAGES_URL_TEMPLATE`, `META_METRICS_URL_TEMPLATE`: endpoints da Meta
- `UMBRELLA_SUMMARY_URL`, `UMBRELLA_INCIDENTS_URL`: endpoints da Cisco Umbrella
- `HOSTINGER_SUMMARY_URL`, `HOSTINGER_COMPONENTS_URL`, `HOSTINGER_INCIDENTS_URL`, `HOSTINGER_STATUS_PAGE_URL`: endpoints da Hostinger
- `BOT_TIMEZONE`: timezone global para comandos e lembretes
- `HOST_REPORT_TIMEZONE`: timezone usada no filtro de incidentes do dia
- `HOST_SITE_TARGETS_JSON`: lista JSON dos sites privados a monitorar, no formato `[["Nome","https://url"], ...]`
- `NOTE_TAB_CHAT_IDS_JSON`: mapa JSON `aba -> chat_id` para `/note`
- `WHOIS_RDAP_GLOBAL_URL_TEMPLATE`, `WHOIS_RDAP_BR_URL_TEMPLATE`: endpoints RDAP do `/whois`
- `VIACEP_URL_TEMPLATE`: endpoint do `/cep`
- `PING_COUNT`, `PING_TIMEOUT_SECONDS`, `TRACEROUTE_MAX_HOPS`, `TRACEROUTE_TIMEOUT_SECONDS`: limites do `/ping`
- `SSL_TIMEOUT_SECONDS`, `SSL_ALERT_DAYS`, `SSL_CRITICAL_DAYS`: limites do `/ssl`
- `REMINDER_POLL_INTERVAL_SECONDS`, `REMINDER_SEND_RETRY_LIMIT`: despacho e retry de lembretes
- `LOG_LEVEL`: nivel do logger estruturado (`INFO`, `WARNING`, ...)
- `STATE_DB_PATH`: caminho do SQLite para estado persistente e tentativas nao autorizadas
- `PROACTIVE_ENABLED`: habilita/desabilita monitoramento proativo
- `PROACTIVE_CHECK_INTERVAL_SECONDS`: intervalo da checagem periodica
- `PROACTIVE_MORNING_TIME`: horario do resumo da manha (HH:MM)
- `PROACTIVE_NIGHT_TIME`: horario do resumo da noite (HH:MM)
- `PROACTIVE_CALL_REPEAT_COUNT`: repeticoes do alerta reforcado para criticos
- `ALERT_PRIORITY_RULES_JSON`: regras de prioridade por cliente/sistema
- `ISSABEL_AMI_HOST`, `ISSABEL_AMI_PORT`, `ISSABEL_AMI_USERNAME`, `ISSABEL_AMI_SECRET`: acesso ao AMI do Issabel/Asterisk para `/voips`
- `ISSABEL_AMI_TIMEOUT_SECONDS`, `ISSABEL_AMI_USE_TLS`, `ISSABEL_AMI_PEER_NAME_REGEX`: ajustes do `/voips` (timeout, TLS, filtro de ramais)

## Executar
```powershell
python src/main.py
```

## Testes
```powershell
pytest -q
```

## Observacoes de seguranca
- Nao versione `.env`
- Mantenha o token apenas no `.env`
- O token exposto em conversa deve ser rotacionado no BotFather antes de uso em producao
