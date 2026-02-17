from __future__ import annotations

import logging
from telegram.ext import Application, ApplicationBuilder, CommandHandler, MessageHandler, filters

from src.automations_lib.automations.status_finance import StatusFinanceAutomation
from src.automations_lib.automations.status_health import StatusHealthAutomation
from src.automations_lib.automations.status_host import StatusHostAutomation
from src.automations_lib.automations.status_news import StatusNewsAutomation
from src.automations_lib.automations.status_trends import StatusTrendsAutomation
from src.automations_lib.automations.status_weather import StatusWeatherAutomation
from src.automations_lib.orchestrator import StatusOrchestrator
from src.automations_lib.providers.finance_provider import FinanceProvider
from src.automations_lib.providers.health_provider import HealthProvider
from src.automations_lib.providers.host_status_provider import HostStatusProvider
from src.automations_lib.providers.news_provider import NewsProvider
from src.automations_lib.providers.trends_provider import TrendsProvider
from src.automations_lib.providers.voip_probe_provider import VoipProbeProvider
from src.automations_lib.providers.weather_provider import WeatherProvider
from src.automations_lib.registry import AutomationRegistry
from src.config import Settings
from src.handlers import BotHandlers
from src.proactive_service import ProactiveService
from src.reminder_service import ReminderService
from src.state_store import BotStateStore
from src.voip_probe_service import VoipProbeService

logger = logging.getLogger(__name__)


async def _post_init(application: Application) -> None:
    proactive = application.bot_data.get("proactive_service")
    if proactive is not None:
        await proactive.start()
    reminder = application.bot_data.get("reminder_service")
    if reminder is not None:
        await reminder.start()
    voip_probe = application.bot_data.get("voip_probe_service")
    if voip_probe is not None:
        await voip_probe.start()


async def _post_shutdown(application: Application) -> None:
    proactive = application.bot_data.get("proactive_service")
    if proactive is not None:
        await proactive.stop()
    reminder = application.bot_data.get("reminder_service")
    if reminder is not None:
        await reminder.stop()
    voip_probe = application.bot_data.get("voip_probe_service")
    if voip_probe is not None:
        await voip_probe.stop()


async def _error_handler(update, context) -> None:  # pragma: no cover - runtime safety
    logger.exception(
        "unhandled telegram exception",
        exc_info=context.error,
        extra={
            "event": "telegram_unhandled_error",
            "update_type": type(update).__name__ if update is not None else "none",
        },
    )


def build_application(settings: Settings) -> Application:
    state_store = BotStateStore(settings.state_db_path)
    registry = AutomationRegistry()
    registry.register(StatusNewsAutomation(NewsProvider(settings.request_timeout_seconds)))
    registry.register(
        StatusWeatherAutomation(WeatherProvider(settings.request_timeout_seconds))
    )
    registry.register(StatusTrendsAutomation(TrendsProvider(settings.request_timeout_seconds)))
    registry.register(
        StatusFinanceAutomation(FinanceProvider(settings.request_timeout_seconds))
    )
    registry.register(StatusHealthAutomation(HealthProvider(settings.request_timeout_seconds)))
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
    voip_timeout_seconds = max(
        90,
        (settings.voip_call_timeout_seconds * 7) + 20,
    )
    voip_provider = VoipProbeProvider(
        timeout_seconds=voip_timeout_seconds
    )
    bot_handlers = BotHandlers(
        settings=settings,
        orchestrator=orchestrator,
        state_store=state_store,
        voip_provider=voip_provider,
    )
    builder = (
        ApplicationBuilder()
        .token(settings.telegram_bot_token)
        .post_init(_post_init)
        .post_shutdown(_post_shutdown)
    )
    application = builder.build()
    proactive_service = ProactiveService(
        application=application,
        settings=settings,
        orchestrator=orchestrator,
        state_store=state_store,
    )
    reminder_service = ReminderService(
        application=application,
        settings=settings,
        state_store=state_store,
    )
    voip_probe_service = VoipProbeService(
        application=application,
        settings=settings,
        state_store=state_store,
        provider=voip_provider,
    )
    application.bot_data["proactive_service"] = proactive_service
    application.bot_data["reminder_service"] = reminder_service
    application.bot_data["voip_probe_service"] = voip_probe_service

    application.add_handler(CommandHandler("start", bot_handlers.start_handler))
    application.add_handler(CommandHandler("help", bot_handlers.help_handler))
    application.add_handler(CommandHandler("status", bot_handlers.status_handler))
    application.add_handler(CommandHandler("host", bot_handlers.host_handler))
    application.add_handler(CommandHandler("health", bot_handlers.health_handler))
    application.add_handler(CommandHandler("all", bot_handlers.all_handler))
    application.add_handler(CommandHandler("whois", bot_handlers.whois_handler))
    application.add_handler(CommandHandler("cep", bot_handlers.cep_handler))
    application.add_handler(CommandHandler("ping", bot_handlers.ping_handler))
    application.add_handler(CommandHandler("ssl", bot_handlers.ssl_handler))
    application.add_handler(CommandHandler("voip", bot_handlers.voip_handler))
    application.add_handler(CommandHandler("voip_logs", bot_handlers.voip_logs_handler))
    application.add_handler(CommandHandler("note", bot_handlers.note_handler))
    application.add_handler(CommandHandler("lembrete", bot_handlers.lembrete_handler))
    application.add_handler(CommandHandler("logs", bot_handlers.logs_handler))
    application.add_handler(
        MessageHandler(filters.TEXT & ~filters.COMMAND, bot_handlers.text_handler)
    )
    application.add_handler(
        MessageHandler(
            filters.UpdateType.CHANNEL_POST & filters.TEXT,
            bot_handlers.channel_post_handler,
        )
    )
    application.add_error_handler(_error_handler)
    return application
