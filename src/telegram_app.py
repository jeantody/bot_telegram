from __future__ import annotations

from telegram.ext import Application, CommandHandler, MessageHandler, filters

from src.automations_lib.automations.status_finance import StatusFinanceAutomation
from src.automations_lib.automations.status_host import StatusHostAutomation
from src.automations_lib.automations.status_news import StatusNewsAutomation
from src.automations_lib.automations.status_trends import StatusTrendsAutomation
from src.automations_lib.automations.status_weather import StatusWeatherAutomation
from src.automations_lib.orchestrator import StatusOrchestrator
from src.automations_lib.providers.finance_provider import FinanceProvider
from src.automations_lib.providers.host_status_provider import HostStatusProvider
from src.automations_lib.providers.news_provider import NewsProvider
from src.automations_lib.providers.trends_provider import TrendsProvider
from src.automations_lib.providers.weather_provider import WeatherProvider
from src.automations_lib.registry import AutomationRegistry
from src.config import Settings
from src.handlers import BotHandlers


def build_application(settings: Settings) -> Application:
    registry = AutomationRegistry()
    registry.register(StatusNewsAutomation(NewsProvider(settings.request_timeout_seconds)))
    registry.register(
        StatusWeatherAutomation(WeatherProvider(settings.request_timeout_seconds))
    )
    registry.register(StatusTrendsAutomation(TrendsProvider(settings.request_timeout_seconds)))
    registry.register(
        StatusFinanceAutomation(FinanceProvider(settings.request_timeout_seconds))
    )
    registry.register(
        StatusHostAutomation(
            HostStatusProvider(
                timeout_seconds=settings.request_timeout_seconds,
                report_timezone=settings.host_report_timezone,
                site_targets=settings.host_site_targets,
            )
        )
    )

    orchestrator = StatusOrchestrator(registry, settings.automation_timeout_seconds)
    bot_handlers = BotHandlers(settings=settings, orchestrator=orchestrator)

    application = Application.builder().token(settings.telegram_bot_token).build()
    application.add_handler(CommandHandler("start", bot_handlers.start_handler))
    application.add_handler(CommandHandler("help", bot_handlers.help_handler))
    application.add_handler(CommandHandler("status", bot_handlers.status_handler))
    application.add_handler(CommandHandler("host", bot_handlers.host_handler))
    application.add_handler(CommandHandler("all", bot_handlers.all_handler))
    application.add_handler(
        MessageHandler(filters.TEXT & ~filters.COMMAND, bot_handlers.text_handler)
    )
    return application
