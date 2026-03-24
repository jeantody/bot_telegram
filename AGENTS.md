# AGENTS.md

## Objetivo deste arquivo
Este arquivo define regras e contexto especificos deste projeto para agentes que trabalhem neste repositorio. Ele complementa a personalizacao global do Codex e, por isso, evita repetir regras gerais de comportamento, edicao ou colaboracao que ja existam fora deste projeto.

## Visao geral do projeto
- Este repositorio implementa um bot Telegram em Python com arquitetura modular.
- O runtime principal comeca em `src/main.py`.
- A aplicacao Telegram e montada em `src/telegram_app.py`.
- A biblioteca de automacoes fica em `src/automations_lib/`.
- O bot possui integracao com Zabbix para consulta manual via comando `/zabbixh`.
- O projeto possui uma ferramenta VoIP separada em `tools/voip_probe/`, executada via subprocesso e integrada ao bot por JSON.
- Persistencia local e feita com SQLite em `data/`.
- Producao roda em Ubuntu com `systemd`.
- O ambiente remoto de producao existe, mas credenciais e enderecos de acesso nao devem ser documentados neste arquivo.

## Stack real do projeto
- Linguagem: Python 3.10+.
- Runtime principal: `python-telegram-bot`, `httpx`, `python-dotenv`.
- Coleta e parsing auxiliar: `feedparser`, `beautifulsoup4`, `googletrans`.
- Testes: `pytest`, `pytest-asyncio`.
- Persistencia: SQLite local.
- VoIP: `sipp` instalado no host.
- AMI/Issabel: integracao propria por provider no bot.
- Docker: nao existe fluxo Docker oficial neste repositorio hoje.

## Arquitetura
- `src/main.py`: bootstrap do processo.
- `src/telegram_app.py`: monta o `Application`, registra comandos e sobe ou derruba servicos internos.
- `src/handlers.py`: camada de comandos Telegram, respostas e agregacoes como `/all` e `/zabbixh`.
- `src/config.py`: leitura, normalizacao e validacao de configuracao via `.env`.
- `src/automations_lib/`: providers, automations, orchestrator, modelos e integracoes externas, incluindo Zabbix.
- `src/state_store.py`: auditoria, snapshots, rate limit e estado persistente.
- `src/proactive_service.py`, `src/reminder_service.py`, `src/voip_probe_service.py`: loops programados.
- `tools/voip_probe/`: ferramenta separada para REGISTER, OPTIONS, INVITE, parsing e historico proprio.
- `tests/`: suite principal. Alteracoes funcionais devem nascer junto com teste.

## Comandos de trabalho
### Setup local no Windows
```powershell
python -m venv .venv
.venv\Scripts\Activate.ps1
pip install -r requirements.txt
```

### Execucao local
```powershell
python src/main.py
```

### Ferramenta VoIP separada
```powershell
python tools/voip_probe/main.py run-once --json
python tools/voip_probe/main.py run-call --number 1102 --json
python tools/voip_probe/main.py logs --limit 5 --json
```

### Testes
```powershell
pytest -q
pytest -q tests/test_arquivo.py
```

### Gate de regressao recomendado
Use esta sequencia antes de fechar uma tarefa:
```powershell
# 1. Testes do subsistema alterado
pytest -q tests/test_arquivo.py

# 2. Se mexeu em bootstrap, configuracao ou composicao do app
pytest -q tests/test_main.py tests/test_telegram_app.py tests/test_config_loading.py

# 3. Se mexeu em /all, AMI, VoIP ou servicos programados
pytest -q tests/test_command_router.py tests/test_proactive_ami_service.py

# 4. Se tocou mais de um subsistema, ou antes de concluir entrega maior
pytest -q
```

Interpretacao pratica do gate:
- `tests/test_main.py`, `tests/test_telegram_app.py` e `tests/test_config_loading.py` protegem bootstrap, wiring e carregamento de configuracao.
- `tests/test_command_router.py` e `tests/test_proactive_ami_service.py` protegem os fluxos agregados mais sensiveis, incluindo `/all`, AMI e VoIP.
- Se algum desses testes falhar, trate como regressao estrutural mesmo que a mudanca pareca localizada.

### Busca no codigo
```powershell
rg "termo"
rg --files
```

### Operacao no Ubuntu
O servico de producao relevante e o global:
```bash
systemctl status bot-telegram.service
systemctl restart bot-telegram.service
journalctl -u bot-telegram -n 100 --no-pager
```

## Regras de desenvolvimento
- Toda mudanca funcional deve vir com teste novo ou ajuste de teste existente.
- Mudancas em comandos ou handlers Telegram normalmente exigem ajuste em `tests/test_command_router.py`.
- Mudancas em providers devem manter ou ampliar testes do provider e, quando aplicavel, da automacao que o consome.
- Mudancas no comando `/zabbixh` devem manter alinhados `tests/test_command_router.py` e `tests/test_zabbix_provider.py`.
- Mudancas em persistencia, auditoria, snapshots ou rate limit devem atualizar `tests/test_state_store.py`.
- Mudancas em VoIP devem manter sincronizados:
  - `tools/voip_probe/`
  - provider do bot
  - testes relacionados a parser, runner, provider, service e command router
- Antes de concluir uma tarefa de codigo, rode no minimo o subconjunto relevante de testes.
- Quando a mudanca tocar multiplos subsistemas, prefira validar com `pytest -q`.
- Mudancas em bootstrap, `load_settings()` ou composicao de handlers devem validar tambem:
  - `tests/test_main.py`
  - `tests/test_telegram_app.py`
  - `tests/test_config_loading.py`
- Mudancas na configuracao do Zabbix ou na injecao do provider no app devem validar tambem:
  - `tests/test_config_loading.py`
  - `tests/test_telegram_app.py`
  - `tests/test_zabbix_provider.py`
- Mudancas em `/all`, AMI, VoIP ou servicos programados devem validar tambem:
  - `tests/test_command_router.py`
  - `tests/test_proactive_ami_service.py`

## TDD e expectativa de qualidade
- O projeto segue TDD pragmatico: teste nao e burocracia, e parte da mudanca.
- Prefira comecar pelo teste do comportamento alterado quando a regra for clara.
- Em correcoes pequenas, ao menos reproduza com teste antes de fechar o trabalho.
- Nao quebre contratos existentes sem atualizar testes e consumidores.
- Para JSONs internos consumidos por outras camadas, trate compatibilidade como parte da entrega.

## Regras especificas deste projeto
- `.env` e obrigatorio em runtime e nunca deve ser commitado.
- `.env.example` documenta variaveis, mas nao deve receber segredos reais.
- A integracao Zabbix usa `ZABBIX_BASE_URL`, `ZABBIX_API_TOKEN`, `ZABBIX_TIMEOUT_SECONDS` e `ZABBIXH_HOST_TARGETS_JSON`.
- Os hosts monitorados por `/zabbixh` devem ficar em `ZABBIXH_HOST_TARGETS_JSON`; nao hardcode novos hostids no codigo quando a necessidade for apenas incluir, excluir ou editar servidores.
- Este repositorio ja teve uso manual de artefatos como `.tar.gz`, `.bundle` e afins; nao os inclua em commit por padrao.
- O deploy atual de producao e Ubuntu + `systemd`, nao Docker.
- O servico esperado em producao e `bot-telegram.service`.
- O projeto usa `load_dotenv(override=True)`; tenha cuidado com variaveis stale de shell ou ambiente.
- Logs e auditoria ja tem redaction; qualquer nova area de log deve preservar esse padrao.
- Comandos pesados como `/voip`, `/call` e `/ping` tem preocupacao operacional e devem respeitar rate limit e custo de execucao.

## Seguranca e segredos
- Nunca colocar tokens, senhas SIP, segredos AMI ou `.env` no Git.
- Nunca copiar segredos reais para testes, fixtures, snapshots ou documentacao.
- Se tocar em logs, auditoria ou mensagens de erro, preserve a redaction central.
- Se encontrar segredo exposto em arquivo versionado, interrompa o fluxo normal e sinalize antes de seguir.
- Ao fazer commit ou push com Git, verificar se nao esta sendo exposto conteudo sigiloso ou sensivel.

## Docker
- Hoje este projeto nao possui `Dockerfile`, `docker-compose` ou fluxo Docker oficial.
- Nao assuma containerizacao como padrao de desenvolvimento ou deploy.
- Nao criar Docker como parte natural de uma tarefa, a menos que o pedido do usuario seja explicitamente sobre containerizacao.
- Se surgir demanda de Docker, trate como trabalho novo e separado.

## Convencoes praticas para agentes neste repositorio
- Faca mudancas especificas e localizadas; evite refactors amplos sem necessidade clara.
- Preserve contratos dos comandos existentes: `/status`, `/host`, `/health`, `/all`, `/whois`, `/cep`, `/ping`, `/ssl`, `/voips`, `/voip`, `/call`, `/voip_logs`, `/note`, `/lembrete`, `/logs`, `/zabbixh`.
- Ao mexer em `/all`, valide impacto em blocos agregados e na auditoria.
- Ao mexer em AMI, valide tambem filtros e visao em `/voips`.
- Ao mexer em `/zabbixh`, preserve a saida legivel para chat, o fallback `nao encontrado` e a leitura de hosts a partir do `.env`.
- Ao mexer em VoIP, considere diferencas entre:
  - ferramenta separada em `tools/voip_probe`
  - integracao manual do bot (`/voip` e `/call`)
  - execucao programada em `src/voip_probe_service.py`

## Validacao esperada ao alterar documentacao deste arquivo
- O conteudo deve permanecer em portugues.
- O conteudo deve continuar especifico para este projeto.
- Os comandos citados aqui devem existir no repositorio atual.
- A documentacao de operacao deve continuar apontando para `bot-telegram.service`.
- Este arquivo nao deve incluir segredos reais nem valores copiados do `.env`.
