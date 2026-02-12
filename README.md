# Bot Telegram com Biblioteca de Automações

Bot em Python para executar automações pelo Telegram com arquitetura separada entre:
- app de Telegram (`src/telegram_app.py`)
- biblioteca de automações (`src/automations_lib/`)

## Funcionalidades iniciais
- Comando `status` e `/status`
- Envio de 3 mensagens separadas:
1. Noticias (Top 10 G1, Top 10 TecMundo, ultimas 5 BoletimSec)
2. Clima de Sao Paulo (agora, 12:00, 19:00, 21:00, chuva 17:30-19:00)
3. Trends Brasil (fonte publica alternativa)

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
- O token exposto em conversa deve ser rotacionado no BotFather antes de uso em producao

