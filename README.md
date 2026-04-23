# Bot Telegram com Biblioteca de Automações

Bot em Python para executar automações pelo Telegram com arquitetura separada entre:
- app de Telegram (`src/telegram_app.py`)
- biblioteca de automações (`src/automations_lib/`)

## Funcionalidades
- Comando `status` e `/status`
- Comando `/host` para monitoramento de infraestrutura (Locaweb, Meta e Cisco Umbrella)
- Comando `/zabbixh` para consultar metricas de hosts configurados no Zabbix
- Resumo automatico de link enviado sozinho no Telegram:
  - faz scraping leve da pagina
  - resume com Ollama/Gemma
  - salva no Discord via webhook configurado
- Ponte Telegram/Discord opcional:
  - le comandos e links no canal Discord configurado
  - replica mensagens que acionam o bot e respostas entre Telegram e Discord
  - usa um webhook separado para publicar na sala Discord da ponte
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

### Variaveis de resumo de links
- `LINK_SUMMARY_OLLAMA_BASE_URL`: URL base do Ollama, por exemplo `http://192.168.0.14:11434`
- `LINK_SUMMARY_OLLAMA_MODEL`: modelo usado no `/api/generate`, por exemplo `gemma4:e2b`
- `LINK_SUMMARY_DISCORD_WEBHOOK_URL`: webhook do Discord da sala `sites-uteis`; deve existir apenas no `.env`
- `LINK_SUMMARY_TIMEOUT_SECONDS`: timeout de scraping, Ollama e Discord
- `LINK_SUMMARY_MAX_TEXT_CHARS`: limite de texto extraido enviado ao modelo

O bot processa apenas mensagens autorizadas cujo conteudo seja um unico link `http://` ou `https://`. Textos com link embutido sao ignorados.

### Variaveis da ponte Discord
- `DISCORD_BRIDGE_ENABLED`: habilita a ponte bidirecional Telegram/Discord
- `DISCORD_BOT_TOKEN`: token do bot Discord; exige Message Content Intent habilitado
- `DISCORD_BRIDGE_WEBHOOK_URL`: webhook da sala Discord usada pela ponte
- `DISCORD_BRIDGE_CHANNEL_ID`: opcional; quando vazio, o bot tenta resolver pelo webhook

O webhook de `DISCORD_BRIDGE_WEBHOOK_URL` e separado de `LINK_SUMMARY_DISCORD_WEBHOOK_URL`.
O primeiro serve para a sala unica Telegram/Discord; o segundo arquiva links uteis.

## Executar
```bash
.venv/bin/python src/main.py
```

Ou use o wrapper operacional do projeto:

```bash
./bot start
./bot stop
./bot restart
./bot logs
./bot status
```

## Testes
Entry point oficial local de TDD:

```bash
./bot test
```

Esse comando roda:
- a suite deterministica completa com coverage minima de 70%;
- o gate live de link-summary quando o diff atual toca codigo/config/testes dessa feature.

Se o gate live for exigido, rode:

```bash
RUN_LINK_SUMMARY_LIVE_TESTS=1 ./bot test
```

Para chamadas manuais de pytest, a suite base continua sendo:

```bash
.venv/bin/python -m pytest -q --cov=src --cov=tools/voip_probe --cov-report=term-missing --cov-fail-under=70
```

Para alteracoes no Zabbix, o gate minimo recomendado continua sendo:

```bash
.venv/bin/python -m pytest -q tests/test_zabbix_provider.py
.venv/bin/python -m pytest -q tests/test_command_router.py tests/test_telegram_app.py tests/test_config_loading.py
```

Para alteracoes no resumo de links, o gate TDD obrigatorio inclui os testes unitarios
e o teste live contra Ollama/Discord:

```bash
.venv/bin/python -m pytest -q tests/test_link_summary_provider.py tests/test_command_router.py tests/test_config_loading.py tests/test_logging_utils.py
RUN_LINK_SUMMARY_LIVE_TESTS=1 .venv/bin/python -m pytest -q tests/test_link_summary_live.py
```

O teste live publica uma mensagem de validacao no Discord configurado e falha se o
modelo Ollama nao conseguir gerar resposta.

O GitHub Actions roda apenas a suite deterministica com coverage. O gate live fica
no fluxo local porque depende do `.env` real, do Ollama da rede interna e do webhook
do Discord.

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
- Pre-requisito: `VOIP_SIPP_BIN=bin/sipp` usa o SIPp empacotado no projeto;
  instale `sipp` globalmente apenas se quiser usar `VOIP_SIPP_BIN=sipp`.

## Diagnostico rapido
Se `python src/main.py` falhar nesta maquina, verifique primeiro:
- `python` pode nem existir no PATH; use `python3` para criar a venv
- `python3 src/main.py` sem a `.venv` ativa vai falhar por dependencias ausentes
- o comando suportado do projeto e `.venv/bin/python src/main.py`
