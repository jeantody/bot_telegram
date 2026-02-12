# Bot Telegram com Biblioteca de Automações

Bot em Python para executar automações pelo Telegram com arquitetura separada entre:
- app de Telegram (`src/telegram_app.py`)
- biblioteca de automações (`src/automations_lib/`)

## Funcionalidades
- Comando `status` e `/status`
- Envio de 4 mensagens separadas:
1. Noticias (Top 10 G1, Top 10 TecMundo, ultimas 5 BoletimSec)
2. Clima de Sao Paulo (agora, 12:00, 19:00, 21:00, chuva 17:30-19:00)
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
