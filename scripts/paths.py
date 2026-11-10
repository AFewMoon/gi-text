"""路径与文件名安全化（Windows 友好）。"""

from __future__ import annotations

import hashlib
import re

_INVALID = re.compile(r'[\\/:*?"<>|\x00-\x1f]')
_SPACES = re.compile(r"\s+")
_RESERVED = {
    "CON", "PRN", "AUX", "NUL",
    *(f"COM{i}" for i in range(1, 10)),
    *(f"LPT{i}" for i in range(1, 10)),
}


def _shorten(text: str, limit: int) -> str:
    if len(text) <= limit:
        return text
    digest = hashlib.sha1(text.encode("utf-8")).hexdigest()[:6]
    return f"{text[: max(1, limit - 8)]}-{digest}"


def safe_segment(name: str, limit: int = 60) -> str:
    """目录名安全化。"""
    text = _INVALID.sub("-", (name or "").strip())
    text = _SPACES.sub(" ", text).strip(" .")
    if not text:
        text = "未命名"
    if text.upper() in _RESERVED:
        text = f"_{text}"
    return _shorten(text, limit)


def safe_filename(name: str, limit: int = 90) -> str:
    """文件名安全化（不含扩展名）。"""
    text = _INVALID.sub("-", (name or "").strip())
    text = _SPACES.sub(" ", text).strip(" .")
    if not text:
        text = "未命名"
    if text.upper() in _RESERVED:
        text = f"_{text}"
    return _shorten(text, limit)


def unique(name: str, used: set[str]) -> str:
    """同名冲突时追加序号。"""
    if name not in used:
        used.add(name)
        return name
    index = 2
    while f"{name} ({index})" in used:
        index += 1
    final = f"{name} ({index})"
    used.add(final)
    return final
