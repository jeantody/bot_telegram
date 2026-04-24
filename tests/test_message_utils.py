from __future__ import annotations

from src.message_utils import split_message


def test_split_message_returns_single_chunk_when_short() -> None:
    assert split_message("abc", max_length=10) == ["abc"]


def test_split_message_prefers_newline_boundaries() -> None:
    text = "linha-1\nlinha-2\nlinha-3"

    assert split_message(text, max_length=10) == ["linha-1", "linha-2", "linha-3"]


def test_split_message_falls_back_to_hard_cut_without_newline() -> None:
    assert split_message("abcdefghij", max_length=4) == ["abcd", "efgh", "ij"]


def test_split_message_uses_earlier_line_to_keep_simple_html_balanced() -> None:
    text = "ok\n<i>\nHackread Hoje\n</i>\nresto"

    assert split_message(text, max_length=22) == [
        "ok",
        "<i>\nHackread Hoje\n</i>",
        "resto",
    ]
