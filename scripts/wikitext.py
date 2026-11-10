"""wikitext 文本清理：把模板、链接、HTML 标签还原成纯文本。

设计原则：
- 只保留人可读的文字，模板参数按「语义」取舍，而不是无脑丢弃或保留；
- 未知模板不静默吞掉，记入计数器，最后汇总到 report/unknown_templates.txt。
"""

from __future__ import annotations

import html as _html
import re
from collections import Counter
from typing import Iterator

# 直接丢弃（纯导航 / 纯装饰 / 纯数据）
DROP_TEMPLATES = {
    "任务导航", "面包屑", "多义词", "需要帮助", "待补充", "系列任务", "多重系列任务",
    "图标", "columns", "世界任务一览", "游逸旅闻一览", "活动任务查询", "邀约事件",
    "任务", "任务描述", "折叠", "图片", "file", "image", "clear", "col-begin",
    "col-end", "col-break", "toc", "目录", "anchor", "锚点", "效果", "数值",
    "图片放大", "背景", "npc图标", "js", "key", "嵌入地图",
}

# 取最后一个位置参数的文字（包裹型模板）
KEEP_LAST_TEMPLATES = {
    "颜色", "着色", "黑幕", "提示", "提示消息", "可折叠", "译名", "注音", "原文",
    "lang", "zh", "em", "strong", "b", "i", "u", "small", "big", "center",
    "折叠框", "折叠面板",
}

# 取第一个位置参数的文字
KEEP_FIRST_TEMPLATES = {"ruby", "rt", "词条", "术语", "下注音", "注音ruby"}

# 「角色：台词」型对话模板
SPEECH_TEMPLATES = {"人物对话", "角色对话", "对话"}

# 简单符号模板：无参数时把模板名当文字
_SYMBOL_TEMPLATES = {"·", "•", "・", "—", "～", "~", "/", "、", "|", "!", "=", "→"}

UNKNOWN_TEMPLATES: Counter[str] = Counter()

_TAG_RE = re.compile(r"<[^>]+>")
_COMMENT_RE = re.compile(r"<!--.*?-->", re.S)
_REF_RE = re.compile(r"<ref[^>/]*?/>|<ref[^>]*>.*?</ref>", re.S | re.I)
_INCLUDE_RE = re.compile(r"</?(?:noinclude|includeonly|onlyinclude|nowiki|pre|math|gallery)\b[^>]*>", re.I)
_BR_RE = re.compile(r"<br\s*/?>", re.I)

_FILE_LINK_RE = re.compile(r"\[\[(?:文件|檔案|档案|file|image|分类|category|特殊|special)\s*:[^\]]*\]\]", re.I)
_LINK_RE = re.compile(r"\[\[([^\[\]]+?)\]\]")
_EXT_LINK_RE = re.compile(r"\[(?:https?:|//)[^\s\]]+\s*([^\]]*)\]")
_EXT_LINK_BARE_RE = re.compile(r"\[(?:https?:|//)[^\]]*\]")
_BOLD_RE = re.compile(r"'{2,5}")
_HEADING_INLINE_RE = re.compile(r"^=+\s*(.*?)\s*=+$")
# wiki 上「注音」模板渲染后残留的字面量：{RUBY#[S]赫瓦格密尔}
_RUBY_ARTIFACT_RE = re.compile(r"\{RUBY#\[S\]([^{}]*)\}")


# ------------------------------------------------------------------ 模板扫描


def find_template(text: str, start: int) -> tuple[int, str]:
    """从 text[start] 处的 '{{' 开始，返回 (结束下标（不含）, 模板内部文本)。"""
    depth = 0
    i = start
    n = len(text)
    while i < n - 1:
        pair = text[i : i + 2]
        if pair == "{{":
            depth += 1
            i += 2
            continue
        if pair == "}}":
            depth -= 1
            i += 2
            if depth == 0:
                return i, text[start + 2 : i - 2]
            continue
        i += 1
    return n, text[start + 2 :]


def split_params(inner: str) -> list[str]:
    """按顶层 '|' 切分模板参数（忽略 [[...]] 与 {{...}} 内部的竖线）。"""
    parts: list[str] = []
    buf: list[str] = []
    link_depth = 0
    brace_depth = 0
    i = 0
    while i < len(inner):
        if inner.startswith("[[", i):
            link_depth += 1
            buf.append("[[")
            i += 2
            continue
        if inner.startswith("]]", i) and link_depth > 0:
            link_depth -= 1
            buf.append("]]")
            i += 2
            continue
        if inner.startswith("{{", i):
            brace_depth += 1
            buf.append("{{")
            i += 2
            continue
        if inner.startswith("}}", i) and brace_depth > 0:
            brace_depth -= 1
            buf.append("}}")
            i += 2
            continue
        char = inner[i]
        if char == "|" and link_depth == 0 and brace_depth == 0:
            parts.append("".join(buf))
            buf = []
        else:
            buf.append(char)
        i += 1
    parts.append("".join(buf))
    return parts


def template_parts(inner: str) -> tuple[str, list[str], dict[str, str]]:
    params = split_params(inner)
    name = params[0].strip()
    positional: list[str] = []
    named: dict[str, str] = {}
    for raw in params[1:]:
        same_level_eq = raw.find("=")
        if same_level_eq > 0 and "[[" not in raw[:same_level_eq]:
            named[raw[:same_level_eq].strip()] = raw[same_level_eq + 1 :].strip()
        else:
            positional.append(raw.strip())
    return name, positional, named


def _render_template(name: str, positional: list[str], named: dict[str, str]) -> str:
    key = name.strip().lstrip("Template:").lstrip("模板:")
    lower = key.lower()

    if key.startswith("#") or ":" in key:
        return ""
    if key in SPEECH_TEMPLATES:
        values = [v for v in positional if v.strip()]
        if len(values) >= 3:
            return f"{values[1]}：{values[2]}"
        if len(values) == 2:
            return f"{values[0]}：{values[1]}"
        return values[0] if values else ""
    if key in {"剧情选项", "选项", "对话选项", "分支选项"}:
        options = [value for field, value in named.items() if field.strip().startswith("选项")]
        options = [inline(value) for value in options if inline(value)]
        return "；".join(options) if options else ""
    if key == "!":
        return "|"
    if key in ("=", "=="):
        return "="
    if lower in DROP_TEMPLATES or key in DROP_TEMPLATES:
        return ""
    if lower in KEEP_FIRST_TEMPLATES:
        return positional[0] if positional else ""
    if lower in KEEP_LAST_TEMPLATES:
        values = [v for v in positional if v.strip()]
        if named:
            for field in ("内容", "文本", "文字", "title", "text"):
                if field in named and named[field]:
                    return named[field]
        return values[-1] if values else ""
    if key in _SYMBOL_TEMPLATES:
        return key
    if not positional and not named:
        return ""  # {{PAGENAME}} 之类

    # 未知模板：保留最后一个位置参数，避免丢剧情文字
    values = [v for v in positional if v.strip()]
    if values:
        UNKNOWN_TEMPLATES[key] += 1
        return values[-1]
    UNKNOWN_TEMPLATES[key] += 1
    return ""


def expand_templates(text: str, max_rounds: int = 40) -> str:
    """由内向外反复展开模板。"""
    for _ in range(max_rounds):
        start = text.find("{{")
        if start < 0:
            return text
        out: list[str] = []
        i = 0
        replaced = False
        while True:
            start = text.find("{{", i)
            if start < 0:
                out.append(text[i:])
                break
            out.append(text[i:start])
            end, inner = find_template(text, start)
            if "{{" in inner:  # 还没到最内层，整体后移
                out.append(text[start : start + 2])
                i = start + 2
                continue
            name, positional, named = template_parts(inner)
            out.append(_render_template(name, positional, named))
            i = end
            replaced = True
        text = "".join(out)
        if not replaced:
            return text
    return text


# ------------------------------------------------------------------ 其它清理


def strip_html(text: str) -> str:
    text = _COMMENT_RE.sub("", text)
    text = _REF_RE.sub("", text)
    text = _INCLUDE_RE.sub("", text)
    text = _BR_RE.sub("\n", text)
    text = _TAG_RE.sub("", text)
    text = _html.unescape(text)
    return text.replace("\u00a0", " ")


def strip_links(text: str) -> str:
    text = _FILE_LINK_RE.sub("", text)

    def _link(match: re.Match[str]) -> str:
        inner = match.group(1)
        if "|" in inner:
            return inner.rsplit("|", 1)[-1]
        return inner.split("#", 1)[0] if inner.startswith("#") else inner

    text = _LINK_RE.sub(_link, text)
    text = _EXT_LINK_RE.sub(lambda m: m.group(1) or "", text)
    text = _EXT_LINK_BARE_RE.sub("", text)
    return text


def strip_markup(text: str) -> str:
    text = _RUBY_ARTIFACT_RE.sub(r"（\1）", text)
    text = _BOLD_RE.sub("", text)
    text = text.replace("__TOC__", "").replace("__NOTOC__", "")
    text = re.sub(r"[ \t]+\n", "\n", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text


def clean(text: str) -> str:
    """一次性把任意 wikitext 片段转成纯文本。"""
    if not text:
        return ""
    text = strip_html(text)
    text = expand_templates(text)
    text = strip_links(text)
    text = strip_markup(text)
    # 源码里偶有多写的大括号（作者笔误），残留的单独 {{ / }} 直接剔除
    text = text.replace("{{", "").replace("}}", "")
    return text.strip()


def inline(text: str) -> str:
    """清理后压平为单行，用于标题、单元格等场景。"""
    return re.sub(r"\s+", " ", clean(text)).strip()


def heading_title(raw: str) -> str:
    return inline(_HEADING_INLINE_RE.sub(r"\1", raw.strip()))


def iter_template_blocks(text: str, names: set[str]) -> Iterator[tuple[int, int, str, dict[str, str], list[str]]]:
    """遍历指定名称的模板块，产出 (start, end, name, named, positional)。"""
    i = 0
    while True:
        start = text.find("{{", i)
        if start < 0:
            return
        end, inner = find_template(text, start)
        name, positional, named = template_parts(inner)
        key = name.strip().lstrip("Template:").lstrip("模板:")
        if key in names:
            yield start, end, key, named, positional
            i = end
        else:
            i = start + 2


def reset_unknown() -> None:
    UNKNOWN_TEMPLATES.clear()


_SMW_SPAN_RE = re.compile(
    r"<span[^>]*(?:smw-highlighter|smwttcontent|smwtticon)[^>]*>(?:(?!<span)[\s\S])*?</span>",
    re.I,
)


def strip_smw(text: str) -> str:
    """SMW 会把说明文字塞进 <span class="smw-highlighter"> 工具提示里，先整块删掉再剥标签。"""
    if not text:
        return ""
    for _ in range(6):
        new_text = _SMW_SPAN_RE.sub("", text)
        if new_text == text:
            break
        text = new_text
    text = _TAG_RE.sub("", text)
    return _html.unescape(text).strip()
