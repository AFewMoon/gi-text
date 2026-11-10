"""剧情提取：从任务页 wikitext 中抽出「任务剧情」章节的台词 / 选项 / 旁白。"""

# Copyright (c) 2026 AFewMoon
# SPDX-License-Identifier: GPL-3.0-or-later

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Literal

import config
import wikitext as wx

Kind = Literal["speech", "narration", "choice", "note"]

HEADING_RE = re.compile(r"^(={2,6})\s*(.+?)\s*\1\s*$")
BULLET_RE = re.compile(r"^([*#]+)\s*(.*)$")
COLON_RE = re.compile(r"^(::*|:+)\s*(.*)$")
HR_RE = re.compile(r"^-{3,}$")
SPEAKER_RE = re.compile(r"^([^：:\n]{1,16}?)\s*[：:]\s*(.+)$")
TABLE_BLOCK_RE = re.compile(r"^\{\|.*?^\|\}", re.S | re.M)
NOTE_MARK = "@@NOTE@@"
CHOICE_MARK = "@@CHOICE@@"
INFO_TEMPLATES = {"任务", "系列任务", "邀约事件", "多重系列任务", "世界任务", "活动任务"}
_FLAG_CHARS = "，。！？、；,.;!?【】《》[]"

STRAY_PARAM_RE = re.compile(r"^\|[^|=\s]{1,20}\s*=|^\|-+\|?$")


@dataclass
class DialogueLine:
    kind: Kind
    text: str
    speaker: str | None = None
    depth: int = 0


@dataclass
class Step:
    title: str
    lines: list[DialogueLine] = field(default_factory=list)


@dataclass
class Script:
    title: str
    steps: list[Step] = field(default_factory=list)
    mode: str = "section"  # section | invitation | fallback | empty

    @property
    def line_count(self) -> int:
        return sum(len(step.lines) for step in self.steps)


# ------------------------------------------------------------------ 章节定位


def strip_leading_info(text: str) -> str:
    """去掉页面顶部的 {{任务}} / {{系列任务}} / {{邀约事件}} 信息框。"""
    stripped = text.lstrip()
    offset = len(text) - len(stripped)
    if not stripped.startswith("{{"):
        return text
    end, inner = wx.find_template(stripped, 0)
    name, _, _ = wx.template_parts(inner)
    key = name.strip().lstrip("Template:").lstrip("模板:")
    if key in INFO_TEMPLATES:
        return text[offset + end :]
    return text


def extract_section(text: str, headings: tuple[str, ...]) -> str | None:
    """取出所有同名二级章节的内容（个别页面会把「任务剧情」写两遍）。"""
    lines = text.splitlines()
    bodies: list[list[str]] = []
    collecting = False
    for line in lines:
        match = HEADING_RE.match(line.strip())
        if match and len(match.group(1)) == 2:
            collecting = wx.inline(match.group(2)) in headings
            if collecting:
                bodies.append([])
            continue
        if match and len(match.group(1)) < 2:
            collecting = False
            continue
        if collecting and bodies:
            bodies[-1].append(line)

    if not bodies:
        return None
    return "\n".join("\n".join(body) for body in bodies if any(b.strip() for b in body))


# ------------------------------------------------------------------ 块级预处理


def _replace_folded(text: str) -> str:
    """把 {{折叠|标题=|内容=}} 展开为带 @@NOTE@@ 标记的原始行。"""
    out: list[str] = []
    i = 0
    while True:
        start = text.find("{{", i)
        if start < 0:
            out.append(text[i:])
            break
        end, inner = wx.find_template(text, start)
        name, positional, named = wx.template_parts(inner)
        key = name.strip().lstrip("Template:").lstrip("模板:")
        if key not in {"折叠", "可折叠", "隐藏", "剧情折叠", "折叠框", "折叠面板"}:
            out.append(text[i : start + 2])
            i = start + 2
            continue

        out.append(text[i:start])
        content = named.get("内容") or (positional[-1] if positional else "")
        title = named.get("标题") or named.get("title") or ""
        title = wx.inline(title)
        if title:
            out.append(f"\n{NOTE_MARK}{title}\n")
        out.append("\n" + content + "\n")
        i = end
    return "".join(out)


CHOICE_TEMPLATES = {"剧情选项", "选项", "对话选项", "分支选项"}


def _replace_choices(text: str) -> str:
    """把 {{剧情选项|选项1=|剧情1=|...}} 展开为「选项 + 分支剧情」的行。"""
    out: list[str] = []
    i = 0
    while True:
        start = text.find("{{", i)
        if start < 0:
            out.append(text[i:])
            break
        end, inner = wx.find_template(text, start)
        name, positional, named = wx.template_parts(inner)
        key = name.strip().lstrip("Template:").lstrip("模板:")
        if key not in CHOICE_TEMPLATES:
            out.append(text[i : start + 2])
            i = start + 2
            continue

        out.append(text[i:start])
        slots: dict[int, dict[str, str]] = {}
        for field, value in named.items():
            match = re.match(r"^选项(\d+)$", field.strip())
            if match:
                slots.setdefault(int(match.group(1)), {})["text"] = value
                continue
            match = re.match(r"^剧情(\d+)$", field.strip())
            if match:
                slots.setdefault(int(match.group(1)), {})["branch"] = value

        chunks: list[str] = []
        if slots:
            for index in sorted(slots):
                item = slots[index]
                label = wx.inline(item.get("text", ""))
                if label:
                    chunks.append(f"{CHOICE_MARK}{label}")
                branch = item.get("branch", "").strip()
                if branch:
                    chunks.append(branch)
        else:
            for value in positional:
                label = wx.inline(value)
                if label:
                    chunks.append(f"{CHOICE_MARK}{label}")

        out.append("\n" + "\n".join(chunks) + "\n")
        i = end
    return "".join(out)


def _table_to_lines(match: re.Match[str]) -> str:
    rows: list[str] = []
    for raw in match.group(0).splitlines():
        line = raw.strip()
        if not line or line.startswith("{|") or line.startswith("|}"):
            continue
        if line.startswith("|-"):
            continue
        if not line.startswith(("|", "!")):
            continue
        body = line[1:]
        if "|" in body:
            head, _, tail = body.partition("|")
            if "=" in head and not head.strip().startswith("[["):
                body = tail
        cells = [wx.inline(cell) for cell in re.split(r"\|\||!!", body)]
        cells = [cell for cell in cells if cell]
        if cells:
            rows.append(" / ".join(cells))
    return "\n" + "\n".join(rows) + "\n" if rows else ""


def _segment_key(name: str) -> tuple[int, ...]:
    return tuple(int(part) for part in re.findall(r"\d+", name)) or (0,)


TABBER_KEYS = {"#tag:tabber", "tabber", "#tag:tabberx"}
TEXT_BLOCK_KEYS = {"提示", "提示消息", "可折叠", "隐藏", "剧情折叠"}


def _expand_multiline(text: str) -> str:
    """展开跨行模板，避免首尾大括号被逐行清洗后残留成文本。"""
    out: list[str] = []
    i = 0
    while True:
        start = text.find("{{", i)
        if start < 0:
            out.append(text[i:])
            break
        end, inner = wx.find_template(text, start)
        if "\n" not in inner:
            out.append(text[i : start + 2])
            i = start + 2
            continue

        name, positional, named = wx.template_parts(inner)
        key = name.strip().lstrip("Template:").lstrip("模板:")
        out.append(text[i:start])

        if key in TABBER_KEYS or key.startswith("#tag:tabber"):
            body = inner.split("|", 1)[1] if "|" in inner else ""
            body = body.replace("{{!}}", "|")
            lines: list[str] = []
            for raw in body.splitlines():
                stripped = raw.strip()
                if not stripped or stripped.startswith("|-"):
                    continue
                if stripped.endswith("=") and len(stripped) <= 40 and not stripped.startswith(("*", "|")):
                    lines.append(f"{NOTE_MARK}{stripped[:-1].strip()}")
                else:
                    lines.append(raw)
            out.append("\n" + "\n".join(lines) + "\n")
        elif key in TEXT_BLOCK_KEYS:
            content = named.get("内容") or (positional[-1] if positional else "")
            title = wx.inline(named.get("标题", ""))
            if title:
                out.append(f"\n{NOTE_MARK}{title}\n")
            out.append("\n" + content + "\n")
        elif any(field.startswith("段落名称") for field in named):
            # 活动任务页常见的「段落名称N.M / 内容N.M」结构
            segments = {
                field[len("段落名称") :] for field in named if field.startswith("段落名称")
            } | {field[len("内容") :] for field in named if field.startswith("内容")}
            parts: list[str] = []
            for segment in sorted(segments, key=_segment_key):
                title = wx.inline(named.get(f"段落名称{segment}", ""))
                if title:
                    parts.append(f"{NOTE_MARK}{title}")
                content = named.get(f"内容{segment}", "").strip()
                if content:
                    parts.append(content)
            out.append("\n" + "\n".join(parts) + "\n")
        elif key.startswith("#") or ":" in key:
            out.append("")
        else:
            content = positional[-1] if positional else ""
            out.append("\n" + content + "\n")
        i = end
    return "".join(out)


TABBER_TAG_RE = re.compile(r"<tabber>(.*?)</tabber>", re.S | re.I)


def _tabber_tag(match: re.Match[str]) -> str:
    """`<tabber>标签=内容|-|标签=内容</tabber>` 里，标签行转引用、分隔行丢弃。"""
    lines: list[str] = []
    for raw in match.group(1).splitlines():
        stripped = raw.strip()
        if not stripped or stripped.startswith("|-"):
            continue
        if (
            stripped.endswith("=")
            and len(stripped) <= 40
            and not stripped.startswith(("*", "|"))
        ):
            lines.append(f"{NOTE_MARK}{stripped[:-1].strip()}")
        else:
            lines.append(raw)
    return "\n" + "\n".join(lines) + "\n"


def preprocess(text: str) -> str:
    for _ in range(4):
        new_text = _expand_multiline(_replace_choices(_replace_folded(text)))
        if new_text == text:
            break
        text = new_text
    text = TABBER_TAG_RE.sub(_tabber_tag, text)
    text = TABLE_BLOCK_RE.sub(lambda m: _table_to_lines(m), text)
    text = re.sub(r"\{\{(?:提示|提示消息|clear)[^{}]*\}\}", "", text)
    return text


# ------------------------------------------------------------------ 行解析


def _split_speaker(text: str) -> tuple[str | None, str]:
    match = SPEAKER_RE.match(text)
    if not match:
        return None, text
    speaker, rest = match.group(1).strip(), match.group(2).strip()
    if not speaker or not rest:
        return None, text
    if len(speaker) > 12 or any(ch in _FLAG_CHARS for ch in speaker):
        return None, text
    return speaker, rest


def _note_of_template(raw: str) -> str | None:
    stripped = raw.lstrip()
    if not stripped.startswith("{{"):
        return None
    end, inner = wx.find_template(stripped, 0)
    name, positional, named = wx.template_parts(inner)
    key = name.strip()
    if key != "任务描述":
        return None
    desc = wx.inline(positional[0]) if positional else ""
    loc = wx.inline(positional[1]) if len(positional) > 1 else ""
    location = named.get("地点", "")
    target = loc or wx.inline(location)
    if target:
        return f"地点：{target}"
    return desc or None


def parse_lines(raw_lines: list[str]) -> list[DialogueLine]:
    lines: list[DialogueLine] = []
    for raw in raw_lines:
        stripped = raw.strip()
        if not stripped:
            continue
        if stripped.startswith(NOTE_MARK):
            title = wx.inline(stripped[len(NOTE_MARK) :])
            if title:
                lines.append(DialogueLine("note", title))
            continue
        if stripped.startswith(CHOICE_MARK):
            label = wx.inline(stripped[len(CHOICE_MARK) :])
            if label:
                lines.append(DialogueLine("choice", label))
            continue
        if HR_RE.match(stripped):
            continue
        # wiki 编辑残片：正文里孤立的多余参数行（如 `|内容3.10=`、`|折叠=是`、`|-|`）
        if STRAY_PARAM_RE.match(stripped):
            continue

        note = _note_of_template(stripped)
        if note:
            lines.append(DialogueLine("note", note))
            continue

        depth = 0
        content = stripped
        bullet = BULLET_RE.match(stripped)
        colon = COLON_RE.match(stripped)
        is_choice = False
        if bullet:
            depth = min(len(bullet.group(1)) - 1, 3)
            content = bullet.group(2)
        elif colon and not stripped.startswith("::"):
            is_choice = True
            content = colon.group(2)
        elif colon:
            is_choice = True
            depth = min(len(colon.group(1)) - 1, 3)
            content = colon.group(2)

        text = wx.clean(content)
        if not text:
            continue
        text = re.sub(r"\n{2,}", "\n", text).strip()
        if not text:
            continue

        if is_choice:
            lines.append(DialogueLine("choice", text, depth=depth))
            continue

        speaker, rest = _split_speaker(text)
        if speaker:
            lines.append(DialogueLine("speech", rest.strip(), speaker=speaker, depth=depth))
        else:
            lines.append(DialogueLine("narration", text, depth=depth))
    return lines


# ------------------------------------------------------------------ 主入口


def parse_script(title: str, wikitext_text: str, invitation: bool = False) -> Script:
    headings = (config.INVITATION_HEADING,) if invitation else config.STORY_HEADINGS
    body = strip_leading_info(wikitext_text)
    section = extract_section(body, headings)

    mode = "section"
    if section is None:
        if invitation or invitation_fallback(body):
            section = body
            mode = "invitation" if invitation else "fallback"
        else:
            section = body
            mode = "fallback"

    section = preprocess(section)
    script = Script(title=title, mode=mode)

    current_title = ""
    buffer: list[str] = []

    def flush() -> None:
        parsed = parse_lines(buffer)
        if parsed:
            script.steps.append(Step(current_title, parsed))

    for line in section.splitlines():
        match = HEADING_RE.match(line.strip())
        if match and len(match.group(1)) >= 3:
            flush()
            buffer = []
            current_title = wx.inline(match.group(2))
            continue
        buffer.append(line)
    flush()

    if not script.steps:
        script.mode = "empty"
    return script


def invitation_fallback(text: str) -> bool:
    return "剧情分支" in text
