from __future__ import annotations

from src import main as app_main


class FakeApplication:
    def __init__(self, calls: list[str]) -> None:
        self._calls = calls

    def run_polling(self) -> None:
        self._calls.append("run_polling")


class FakeSettings:
    log_level = "WARNING"


def test_main_bootstrap_calls_dependencies_in_order(monkeypatch) -> None:
    calls: list[str] = []
    settings = FakeSettings()
    application = FakeApplication(calls)

    def fake_load_settings():
        calls.append("load_settings")
        return settings

    def fake_configure_logging(level: str) -> None:
        calls.append(f"configure_logging:{level}")

    def fake_build_application(received_settings):
        assert received_settings is settings
        calls.append("build_application")
        return application

    monkeypatch.setattr(app_main, "load_settings", fake_load_settings)
    monkeypatch.setattr(app_main, "configure_logging", fake_configure_logging)
    monkeypatch.setattr(app_main, "build_application", fake_build_application)

    app_main.main()

    assert calls == [
        "load_settings",
        "configure_logging:WARNING",
        "build_application",
        "run_polling",
    ]
