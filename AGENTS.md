# AGENTS.md

## Visao Geral

Este repositorio contem um bot de Telegram em Python para automacoes operacionais. O bot roda por polling, aceita comandos do Telegram, consulta provedores externos, envia respostas formatadas em HTML e grava auditoria/estado em SQLite.

O projeto separa a camada Telegram da biblioteca de automacoes:

- `src/main.py`: ponto de entrada do processo.
- `src/telegram_app.py`: monta a aplicacao `python-telegram-bot`, registra handlers e inicia servicos de background.
- `src/handlers.py`: implementa os comandos do Telegram, validacao de acesso, rate limit, respostas, auditoria e formatacao.
- `src/automations_lib/`: automacoes reutilizaveis, providers HTTP/SIP/AMI/Zabbix e orquestrador.
- `tools/voip_probe/`: ferramenta CLI independente para testes SIP com SIPp.
- `tests/`: suite pytest cobrindo configuracao, roteamento de comandos, providers, estado, VoIP e servicos proativos.

## Como Rodar

Use a venv do projeto:

```bash
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
```

O bot valida `.env.example` contra `.env` antes de iniciar. O `.env` local sempre ganha de variaveis antigas do shell porque `load_dotenv(..., override=True)` e usado em `src/config.py`.

Comandos operacionais locais:

```bash
./bot start
./bot stop
./bot restart
./bot logs
./bot status
./bot test
```

Quando `/usr/local/bin/bot` apontar para este script, os mesmos comandos podem
ser chamados de qualquer diretorio como `bot start`, `bot stop`, `bot logs` e
`bot restart`. Se o PATH global do host estiver somente leitura, use os
comandos locais com `./bot`.

O script `bot` cria:

- `data/bot.pid`: PID do processo em background.
- `logs/bot.log`: stdout/stderr do bot em JSON estruturado.

Funcoes internas do script `bot`:

- `start_bot()`: valida runtime, cria diretorios, inicia `src/main.py` em
  background, grava PID e mostra o caminho do log.
- `stop_bot()`: localiza o processo por PID file ou por busca do comando Python,
  envia `SIGTERM`, aguarda encerramento e usa `SIGKILL` se exceder o timeout.
- `logs_bot()`: executa `tail -f` em `logs/bot.log`, com quantidade inicial
  opcional de linhas.
- `status_bot()`: sincroniza `data/bot.pid` e mostra se o processo esta rodando.
- `test_bot()`: executa a suite oficial local com coverage e exige o gate live
  de link-summary quando o diff atual toca arquivos criticos dessa feature.

Variaveis aceitas pelo script:

- `BOT_PYTHON_BIN`: define o Python usado para iniciar.
- `BOT_LOG_FILE`: define o arquivo de log.
- `BOT_PID_FILE`: define o arquivo de PID.
- `BOT_STARTUP_GRACE_SECONDS`: tempo de espera apos iniciar.
- `BOT_STOP_TIMEOUT_SECONDS`: tempo para SIGTERM antes de SIGKILL.
- `BOT_TDD_BASE_REF`: ref Git usada para detectar mudancas que exigem gate live.

## Arquitetura de Runtime

1. `src/main.py` adiciona a raiz do projeto ao `sys.path`, importa componentes em tempo de execucao e chama `main()`.
2. `load_settings()` em `src/config.py` valida o contrato `.env.example`/`.env`, carrega variaveis e retorna `Settings`.
3. `configure_logging()` em `src/logging_utils.py` configura logs JSON em stdout com redacao de tokens, senhas e segredos.
4. `build_application()` em `src/telegram_app.py` registra automacoes no `AutomationRegistry`, cria providers e instancia `BotHandlers`.
5. A aplicacao Telegram registra `CommandHandler` para comandos slash e `MessageHandler` para textos como `status`, `host`, `health` e `all`.
6. `_post_init()` inicia servicos de background: `ProactiveService`, `ReminderService` e `VoipProbeService`.
7. `_post_shutdown()` para os servicos e fecha `BotStateStore`.

## Comandos do Telegram

Comandos principais:

- `/start`: mensagem de disponibilidade e lista resumida.
- `/help`: lista de comandos.
- `status` ou `/status`: executa automacoes de noticias, clima, trends e financas.
- `/host`: status de Locaweb, Meta, Cisco Umbrella, Hostinger e sites configurados em `HOST_SITE_TARGETS_JSON`.
- `/health`: latencia e falhas por fonte.
- `/all`: executa status, host, VoIP, AMI/net e lembretes de hoje/amanha.

Comandos utilitarios:

- `/whois dominio.com`: consulta RDAP global ou Registro.br.
- `/cep 01001000`: consulta ViaCEP.
- `/ping host`: executa ping e traceroute.
- `/ssl dominio.com[:porta]`: verifica certificado SSL.
- `/voips`: consulta peers SIP via Issabel/Asterisk AMI ou Rawman.
- `/net`: avalia unidades/ramais a partir da visao AMI.
- `/zabbixh`: consulta metricas de hosts configurados no Zabbix.
- `/voip`: executa matriz VoIP imediata.
- `/call numero`: executa chamada SIP para destino especifico.
- `/voip_logs [quantidade]`: historico da ferramenta VoIP.
- `/note <aba> /<titulo> <texto>`: envia anotacao para chat configurado.
- `/lembrete HH:MM texto`: agenda lembrete no timezone do bot.
- `/logs [filtro] [quantidade]`: consulta auditoria no SQLite.
- Link sozinho `http/https`: faz scraping leve, enriquece contexto de repositorio
  GitHub com README quando aplicavel, resume com Gemma4 remoto via Ollama e salva
  no Discord `sites-uteis`.
- Ponte Discord opcional: mensagens de comando/link no canal configurado entram no
  mesmo roteamento do Telegram; respostas do bot sao espelhadas nos dois canais.

Filtros uteis de `/logs`:

- `/logs 20`
- `/logs erro 20`
- `/logs ami 20`
- `/logs voip 20`
- `/logs voip erro 20`

## Controle de Acesso

`TELEGRAM_ALLOWED_CHAT_ID` restringe o uso do bot a um chat. Quando vazio, o bot nao restringe por chat. Tentativas nao autorizadas sao registradas em `unauthorized_attempts` pelo `BotStateStore`.

Quando `DISCORD_BRIDGE_ENABLED=true`, `TELEGRAM_ALLOWED_CHAT_ID` passa a ser obrigatorio para espelhar mensagens entre Discord e Telegram.

O comando `/note` usa `NOTE_TAB_CHAT_IDS_JSON` para mapear abas para chats de destino. Alias existente: `estudo` aponta para `estudos`.

## Configuracao

O contrato de ambiente fica em `.env.example`; o arquivo real `.env` nao deve ser versionado. Nao imprima tokens, senhas, secrets, cookies ou payloads sensiveis em logs, documentos ou respostas.

Grupos de variaveis:

- Telegram: `TELEGRAM_BOT_TOKEN`, `TELEGRAM_ALLOWED_CHAT_ID`.
- Timeouts: `REQUEST_TIMEOUT_SECONDS`, `AUTOMATION_TIMEOUT_SECONDS`.
- Clima: `WEATHER_TIMEZONE`, `WEATHER_CITY_NAME`.
- Trends: `TRENDS_PRIMARY_URL`, `TRENDS_FALLBACK_URL`.
- Financas: `FINANCE_AWESOMEAPI_URL`, `FINANCE_YAHOO_B3_URL`.
- Hosts/status pages: `LOCAWEB_*`, `META_*`, `UMBRELLA_*`, `HOSTINGER_*`, `HOST_SITE_TARGETS_JSON`.
- Utilitarios: `WHOIS_*`, `VIACEP_URL_TEMPLATE`, `PING_*`, `TRACEROUTE_*`, `SSL_*`.
- Estado e logs: `LOG_LEVEL`, `STATE_DB_PATH`.
- Proativo: `PROACTIVE_*`, `ALERT_PRIORITY_RULES_JSON`.
- VoIP/SIPp: `VOIP_*`.
- Issabel/Asterisk: `ISSABEL_AMI_*`.
- Zabbix: `ZABBIX_BASE_URL`, `ZABBIX_API_TOKEN`, `ZABBIX_TIMEOUT_SECONDS`, `ZABBIXH_HOST_TARGETS_JSON`.
- Resumo de links (Gemma4 remoto): `LINK_SUMMARY_OLLAMA_BASE_URL`, `LINK_SUMMARY_OLLAMA_MODEL`, `LINK_SUMMARY_DISCORD_WEBHOOK_URL`, `LINK_SUMMARY_TIMEOUT_SECONDS`, `LINK_SUMMARY_MAX_TEXT_CHARS`.
- Ponte Discord: `DISCORD_BRIDGE_ENABLED`, `DISCORD_BOT_TOKEN`, `DISCORD_BRIDGE_WEBHOOK_URL`, `DISCORD_BRIDGE_CHANNEL_ID`.
- Rate limit: `RATE_LIMIT_PING_SECONDS`, `RATE_LIMIT_VOIP_SECONDS`.

Observacoes importantes:

- `STATE_DB_PATH` e `VOIP_RESULTS_DB_PATH` aceitam caminho relativo; `src.env_contract.resolve_project_path()` resolve pela raiz do projeto.
- `ISSABEL_AMI_RAWMAN_URL` normaliza URL sem path para `/asterisk/rawman` e pode sobrescrever a porta efetiva do AMI.
- `ISSABEL_AMI_PEER_NAME_REGEX` normaliza o erro comum `^\\d+$` para `^\d+$`.
- `ZABBIX_BASE_URL` e `ZABBIX_API_TOKEN` devem ser preenchidos juntos ou deixados vazios juntos.
- A ponte Discord exige `TELEGRAM_ALLOWED_CHAT_ID`, `DISCORD_BOT_TOKEN` e `DISCORD_BRIDGE_WEBHOOK_URL` quando habilitada.
- `LINK_SUMMARY_DISCORD_WEBHOOK_URL` (arquivo `sites-uteis`) e `DISCORD_BRIDGE_WEBHOOK_URL` (sala da ponte) devem ser webhooks distintos.

## Chamadas Externas

O bot faz chamadas HTTP com `httpx` e parsing com `feedparser`/`BeautifulSoup`.

Fontes principais:

- Telegram Bot API via `python-telegram-bot`.
- Open-Meteo geocoding e forecast.
- GetDayTrends e Trends24.
- AwesomeAPI, Yahoo Chart API e fallback HG Brasil para IBOV.
- Feeds de noticias: Tecnoblog, HackRead, BoletimSec, G1 e TecMundo.
- Locaweb Statuspage, Meta Status, Cisco Umbrella Statuspage e Hostinger Statuspage.
- Sites privados configurados em `HOST_SITE_TARGETS_JSON`.
- RDAP global e RDAP Registro.br.
- ViaCEP.
- Zabbix API JSON-RPC quando configurado.
- Issabel/Asterisk por Rawman HTTP ou AMI TCP/TLS.
- SIPp para probes VoIP em `tools/voip_probe/`.
- Ollama remoto `/api/generate` (Gemma4) para resumo de links, incluindo contexto de README de repositorios GitHub.
- Discord webhook para arquivar em `sites-uteis`.
- Discord Gateway via `discord.py` para ler a sala configurada e webhook Discord
  separado para publicar mensagens espelhadas da ponte.

## Estado, Auditoria e Logs

`src/state_store.py` cria e migra tabelas SQLite automaticamente:

- `monitored_state`: estado de checks proativos e rate limit.
- `unauthorized_attempts`: tentativas bloqueadas.
- `audit_log`: eventos dos comandos e servicos.
- `notes`: registros do `/note`.
- `reminders`: lembretes pendentes/enviados.
- `ami_peer_snapshots`: snapshots AMI para comparacoes de ramais.

Logs de aplicacao sao JSON em stdout. O script `./bot` redireciona stdout/stderr para `logs/bot.log`. A redacao de texto e payload fica em `src/redaction.py`.

## Automacoes

Automacoes implementam a interface de `src/automations_lib/base.py` e retornam `AutomationResult`.

Registro atual em `src/telegram_app.py`:

- `StatusNewsAutomation`
- `StatusWeatherAutomation`
- `StatusTrendsAutomation`
- `StatusFinanceAutomation`
- `StatusHealthAutomation`
- `StatusHostAutomation`

`StatusOrchestrator.run_trigger()` executa as automacoes registradas para um trigger, aplica timeout por automacao e transforma excecoes em resultado critico para o usuario.

## Servicos de Background

- `ProactiveService`: checagens periodicas, resumo automatico de manha/noite e alertas por mudanca real de estado.
- `ReminderService`: varre lembretes pendentes e reenvia ate `REMINDER_SEND_RETRY_LIMIT`.
- `VoipProbeService`: executa sonda VoIP periodica quando `VOIP_PROBE_ENABLED=true`.

## Ferramenta VoIP

Uso manual:

```bash
.venv/bin/python tools/voip_probe/main.py run-once --json
.venv/bin/python tools/voip_probe/main.py run-call --number 1102 --json
.venv/bin/python tools/voip_probe/main.py logs --limit 5 --json
```

O ambiente local pode usar `bin/sipp`, um wrapper que carrega bibliotecas de `lib/` antes de executar `bin/sipp.bin`. Quando `VOIP_SIPP_BIN=bin/sipp`, nao e necessario instalar SIPp globalmente no host. Os cenarios XML ficam em `tools/voip_probe/scenarios/`.

## Testes

Comando geral:

```bash
./bot test
```

O comando `./bot test` e o entry point oficial local de TDD. Ele roda a suite
deterministica com coverage minima de 70% e, quando o diff atual toca
`link_summary_provider`, roteamento, bridge ou configuracao relacionada, falha
sem `RUN_LINK_SUMMARY_LIVE_TESTS=1`.

Gates focados:

```bash
.venv/bin/python -m pytest -q tests/test_config_loading.py tests/test_env_contract.py
.venv/bin/python -m pytest -q tests/test_command_router.py tests/test_telegram_app.py
.venv/bin/python -m pytest -q tests/test_zabbix_provider.py
.venv/bin/python -m pytest -q tests/test_voip_probe_main.py tests/test_voip_probe_runner.py tests/test_voip_probe_storage.py
```

Sempre rode pelo menos os testes de configuracao e roteamento quando alterar `.env.example`, `src/config.py`, `src/telegram_app.py` ou `src/handlers.py`.

Para qualquer alteracao no resumo automatico de links, rode tambem o gate TDD obrigatorio:

```bash
RUN_LINK_SUMMARY_LIVE_TESTS=1 ./bot test
```

O teste live usa o `.env` real, chama o Ollama configurado e publica no webhook do Discord.

O workflow versionado em `.github/workflows/tests.yml` roda somente a suite
deterministica com coverage; o gate live continua local por depender da rede e
de segredos reais.

## Manutencao

- Preserve a separacao entre Telegram, orquestracao e providers.
- Nao coloque segredos em arquivos versionados, testes, logs ou documentacao.
- Ao adicionar variavel obrigatoria, atualize `Settings`, `load_settings()`, `.env.example`, README/AGENTS e testes de configuracao.
- Ao adicionar comando Telegram, registre em `src/telegram_app.py`, implemente em `BotHandlers`, atualize `/help`, testes de roteamento e documentacao.
- Ao alterar formato de mensagens, confira `ParseMode.HTML`; escape dados externos com `html.escape`.
- Ao mexer em SQLite, mantenha migracoes incrementais em `BotStateStore._ensure_schema()`.
- Para mudancas em providers externos, prefira fixtures/testes unitarios de parsing para evitar dependencia de rede na suite.
