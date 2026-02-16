"""Built-in automations."""

from src.automations_lib.automations.status_finance import StatusFinanceAutomation
from src.automations_lib.automations.status_health import StatusHealthAutomation
from src.automations_lib.automations.status_host import StatusHostAutomation
from src.automations_lib.automations.status_news import StatusNewsAutomation
from src.automations_lib.automations.status_trends import StatusTrendsAutomation
from src.automations_lib.automations.status_weather import StatusWeatherAutomation

__all__ = [
    "StatusFinanceAutomation",
    "StatusHealthAutomation",
    "StatusHostAutomation",
    "StatusNewsAutomation",
    "StatusTrendsAutomation",
    "StatusWeatherAutomation",
]
