from __future__ import annotations

from src.config import _normalize_peer_name_regex, _normalize_rawman_url


def test_normalize_peer_name_regex_unescapes_double_backslash() -> None:
    assert _normalize_peer_name_regex(r"^\\d+$") == r"^\d+$"


def test_normalize_rawman_url_from_base_host() -> None:
    url, port = _normalize_rawman_url("http://coalapabx.ddns.net/")
    assert url == "http://coalapabx.ddns.net:8088/asterisk/rawman"
    assert port == 8088


def test_normalize_rawman_url_keeps_full_endpoint() -> None:
    original = "http://coalapabx.ddns.net:8088/asterisk/rawman"
    url, port = _normalize_rawman_url(original)
    assert url == original
    assert port == 8088

