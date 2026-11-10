"""渲染层：结构化剧情 -> 纯文本 txt 文件树 + 总索引。"""

from __future__ import annotations

import re
import shutil
from pathlib import Path
from typing import Any
from urllib.parse import quote

import config
import paths
from parser import DialogueLine, Script, parse_script
from wiki_client import WikiClient  # noqa: F401  (类型提示用)

TITLE_RULE = "=" * 60
NOTE_PREFIX = "▷ "
CHOICE_PREFIX = "选项："
TEXT_ENCODING = "utf-8-sig"  # Windows 记事本需要 BOM 才不乱码
TEXT_NEWLINE = "\r\n"
BLANK_RUN = re.compile(r"\n{3,}")


def _emit(text: str, prefix: str) -> str:
    """多行文本按真实换行拆开，首行带标记，其余行原样另起一行。"""
    body = [line.strip() for line in text.splitlines() if line.strip()]
    if not body:
        return ""
    return "\n".join([f"{prefix}{body[0]}", *body[1:]])


def format_line(line: DialogueLine) -> str:
    if line.kind == "note":
        return _emit(line.text, NOTE_PREFIX)
    if line.kind == "choice":
        return _emit(line.text, CHOICE_PREFIX)
    if line.kind == "speech":
        return _emit(line.text, f"{line.speaker}：")
    return _emit(line.text, "")


def render_script(script: Script, url: str) -> str:
    parts: list[str] = [script.title, TITLE_RULE, "", f"来源：{url}", ""]
    for step in script.steps:
        if step.title:
            parts.extend([f"【{step.title}】", ""])
        for line in step.lines:
            rendered = format_line(line)
            if rendered:
                parts.append(rendered)
        parts.append("")
    text = BLANK_RUN.sub("\n\n", "\n".join(parts))
    return text.strip() + "\n"


def page_url(title: str) -> str:
    return f"{config.BASE_URL}/{quote(title, safe='')}"


class OutputTree:
    def __init__(self) -> None:
        self.written = 0
        self.missing: list[tuple[str, str, str, str]] = []
        self.by_category: dict[str, list[dict[str, Any]]] = {}

    def render_task(
        self,
        category: str,
        folder: str,
        title: str,
        display: str,
        number: str,
        wikitext_text: str,
        used_names: set[str],
        invitation: bool = False,
        min_lines: int = 0,
    ) -> None:
        script = parse_script(title, wikitext_text, invitation=invitation)
        script.title = display

        if script.mode == "empty" or not script.steps:
            reason = "页面无「任务剧情」章节" if script.mode == "fallback" else "剧情为空"
            self.missing.append((category, folder, title, reason))
            return
        if script.line_count < min_lines:
            self.missing.append(
                (category, folder, title, f"对话不足 {min_lines} 行（wiki 仅收录路线图/成就）")
            )
            return

        base = paths.safe_filename(display)
        stem = f"{paths.safe_filename(number)}-{base}" if number else base
        stem = paths.unique(stem, used_names)

        target = config.OUTPUT_DIR / category / folder / f"{stem}.txt"
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(
            render_script(script, page_url(title)),
            encoding=TEXT_ENCODING,
            newline=TEXT_NEWLINE,
        )
        self.written += 1

        self.by_category.setdefault(category, []).append(
            {
                "folder": folder,
                "number": number,
                "name": display,
                "path": target,
                "lines": script.line_count,
            }
        )


def build(
    catalog: dict[str, Any],
    contents: dict[str, str],
    clean: bool = True,
) -> OutputTree:
    if clean and config.OUTPUT_DIR.exists():
        shutil.rmtree(config.OUTPUT_DIR)
    config.OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    tree = OutputTree()

    for category in catalog["categories"]:
        used_folders: set[str] = set()
        for entry in category["series"]:
            folder = paths.unique(paths.safe_segment(entry["folder"]), used_folders)
            used_names: set[str] = set()
            for task in entry["tasks"]:
                text = contents.get(task["title"])
                if text is None:
                    tree.missing.append(
                        (category["name"], folder, task["title"], "未取到正文（缓存缺失）")
                    )
                    continue
                tree.render_task(
                    category=category["name"],
                    folder=folder,
                    title=task["title"],
                    display=task["display"],
                    number=task["number"],
                    wikitext_text=text,
                    used_names=used_names,
                )

    used_folders: set[str] = set()
    folder = paths.unique(config.INVITATION_FOLDER, used_folders)
    used_names: set[str] = set()
    for item in catalog.get("invitations", []):
        text = contents.get(item["title"])
        if text is None:
            tree.missing.append(
                (config.INVITATION_CATEGORY, folder, item["title"], "未取到正文（缓存缺失）")
            )
            continue
        tree.render_task(
            category=config.INVITATION_CATEGORY,
            folder=folder,
            title=item["title"],
            display=paths.safe_segment(item["character"], 40),
            number="",
            wikitext_text=text,
            used_names=used_names,
            invitation=True,
            min_lines=10,
        )

    return tree


def write_index(catalog: dict[str, Any], tree: OutputTree) -> Path:
    stats = catalog.get("stats", {})
    lines: list[str] = [
        "原神剧情文本索引",
        TITLE_RULE,
        "",
        f"· 数据来源：{config.BASE_URL}",
        f"· 生成时间：{catalog.get('generated_at', '')}",
        f"· 任务页面：{stats.get('tasks', 0)} 个，邀约事件：{stats.get('invitations', 0)} 个",
        f"· 已生成剧情文件：{tree.written} 个",
        "",
        "【分类统计】",
        "",
        "分类  幕  子任务",
    ]

    for category in catalog["categories"]:
        entries = [e for e in tree.by_category.get(category["name"], [])]
        if not entries:
            continue
        folders = {e["folder"] for e in entries}
        lines.append(f"{category['name']}  {len(folders)}  {len(entries)}")

    inv = tree.by_category.get(config.INVITATION_CATEGORY, [])
    inv_entries = [e for e in inv if e["folder"] == config.INVITATION_FOLDER]
    if inv_entries:
        lines.append(f"邀约事件  1  {len(inv_entries)}")

    lines.append("")

    for category in catalog["categories"]:
        entries = tree.by_category.get(category["name"], [])
        if not entries:
            continue
        grouped: dict[str, list[dict[str, Any]]] = {}
        for item in entries:
            grouped.setdefault(item["folder"], []).append(item)

        lines.extend([f"【{category['name']}】", ""])
        for folder, items in grouped.items():
            lines.append(f"· {folder}（{len(items)} 篇）")
            for item in items:
                label = f"{item['number']} {item['name']}".strip()
                lines.append(f"  · {label}")
        lines.append("")

    if inv_entries:
        lines.extend([f"【{config.INVITATION_CATEGORY} · {config.INVITATION_FOLDER}】", ""])
        for item in inv_entries:
            lines.append(f"· {item['name']}")
        lines.append("")

    index_path = config.OUTPUT_DIR / "index.txt"
    index_path.write_text(
        "\n".join(lines).rstrip() + "\n",
        encoding=TEXT_ENCODING,
        newline=TEXT_NEWLINE,
    )
    return index_path


def write_missing(tree: OutputTree) -> None:
    config.REPORT_DIR.mkdir(parents=True, exist_ok=True)
    lines = ["抓取 / 解析缺失清单", TITLE_RULE, ""]
    if not tree.missing:
        lines.append("无缺失。")
    else:
        lines.append(f"共 {len(tree.missing)} 条：")
        lines.append("")
        lines.append("分类  幕/系列  页面  原因")
        for category, folder, title, reason in tree.missing:
            lines.append(f"{category}  {folder}  {title}  {reason}")
    config.MISSING_REPORT.write_text(
        "\n".join(lines) + "\n",
        encoding=TEXT_ENCODING,
        newline=TEXT_NEWLINE,
    )
