from __future__ import annotations

import re


_HTML_TAG_RE = re.compile(
    r"<\s*(/?)\s*(a|b|strong|i|em|u|ins|s|strike|del|code|pre)(?=\s|>|/)[^>]*>",
    re.IGNORECASE,
)


def _has_balanced_simple_html(text: str) -> bool:
    stack: list[str] = []
    for match in _HTML_TAG_RE.finditer(text):
        raw_tag = match.group(0)
        is_closing = bool(match.group(1))
        tag_name = match.group(2).lower()
        if raw_tag.rstrip().endswith("/>"):
            continue
        if not is_closing:
            stack.append(tag_name)
            continue
        if not stack or stack[-1] != tag_name:
            return False
        stack.pop()
    return not stack


def _find_split_at(text: str, max_length: int) -> int:
    newline_positions = [
        match.start() for match in re.finditer("\n", text[: max_length + 1])
    ]
    for split_at in reversed(newline_positions):
        if split_at > 0 and _has_balanced_simple_html(text[:split_at]):
            return split_at
    if newline_positions and newline_positions[-1] > 0:
        return newline_positions[-1]
    return max_length


def split_message(text: str, max_length: int = 3900) -> list[str]:
    if len(text) <= max_length:
        return [text]
    chunks: list[str] = []
    remaining = text
    while len(remaining) > max_length:
        split_at = _find_split_at(remaining, max_length)
        chunk = remaining[:split_at].rstrip()
        if not chunk:
            split_at = max_length
            chunk = remaining[:split_at]
        chunks.append(chunk)
        remaining = remaining[split_at:].lstrip("\n")
    if remaining:
        chunks.append(remaining)
    return chunks
