"""目录发现：用 SMW 语义查询枚举全部任务与幕级页面，产出 data/catalog.json。"""

# Copyright (c) 2026 AFewMoon
# SPDX-License-Identifier: GPL-3.0-or-later

from __future__ import annotations

import datetime as _dt
import json
import re
from typing import Any

import config
import wikitext
from wiki_client import WikiClient

TASK_QUERY = "[[分类:任务]]|?任务类型|?系列任务|?任务编号|?任务地区|?所属版本"
SERIES_QUERY = "[[分类:系列任务]]|?系列任务名|?任务类型|?副标题|?任务地区"

_CN_DIGITS = {
    "零": 0, "一": 1, "二": 2, "三": 3, "四": 4,
    "五": 5, "六": 6, "七": 7, "八": 8, "九": 9,
}
_MONTH_INDEX = {c: i for i, c in enumerate("一二三四五六七八", start=1)}


def cn_number(text: str) -> int | None:
    """把「十二」「二十」「三」这类中文数字转成 int。"""
    text = text.strip()
    if not text:
        return None
    if text.isdigit():
        return int(text)
    if "百" in text:
        head, _, tail = text.partition("百")
        base = _CN_DIGITS.get(head, 1) * 100 if head else 100
        return base + (cn_number(tail) or 0)
    if text == "十":
        return 10
    if text.startswith("十"):
        return 10 + (_CN_DIGITS.get(text[1:], 0) if len(text) > 1 else 0)
    if "十" in text:
        head, _, tail = text.partition("十")
        return _CN_DIGITS.get(head, 0) * 10 + (cn_number(tail) or 0)
    return _CN_DIGITS.get(text)


def version_key(version: str) -> tuple[int, int]:
    """版本号排序键；「月之X」映射到 6.x 系列。"""
    version = (version or "").strip()
    match = re.match(r"^(\d+)(?:\.(\d+))?", version)
    if match:
        return (int(match.group(1)), int(match.group(2) or 0))
    match = re.match(r"^月之(.)", version)
    if match and match.group(1) in _MONTH_INDEX:
        return (6, _MONTH_INDEX[match.group(1)] - 1)
    return (999, 0)


def chapter_act(subtitle: str) -> tuple[int, float]:
    """从副标题解析（章, 幕）序号。间章排到最后，幕间介于两幕之间。"""
    text = subtitle or ""
    if "间章" in text:
        chapter = 200
    elif "序章" in text or "序奏" in text:
        chapter = 0
    elif "空月之歌" in text:
        chapter = 6
    else:
        match = re.search(r"第(.+?)章", text)
        chapter = cn_number(match.group(1)) if match else 0
        if chapter is None:
            chapter = 1 if "章" in text else 0

    if "序奏" in text or "序幕" in text:
        act: float = 0
    else:
        match = re.search(r"第(.+?)幕", text)
        act = float(cn_number(match.group(1)) or 0) if match else 0.0
        if not match and "幕间" in text:
            act = 4.5
    return chapter, act


def normalize_number(number: str) -> str:
    """任务编号统一补零到两位，保证文件名排序一致（2 -> 02）。"""
    text = (number or "").strip()
    return text.zfill(2) if text.isdigit() else text


def number_key(number: str) -> tuple[int, str]:
    digits = re.sub(r"\D", "", number or "")
    return (int(digits) if digits else 9999, number or "")


def strip_display_suffix(title: str) -> str:
    for suffix in config.TITLE_SUFFIXES:
        if title.endswith(suffix):
            return title[: -len(suffix)]
    return title


_EMPTY_MARKERS = {"", "None", "none", "无", "—", "-"}


def _value(raw: Any) -> str:
    text = wikitext.strip_smw(str(raw))
    return "" if text in _EMPTY_MARKERS else text


def _first(printouts: dict[str, Any], key: str, default: str = "") -> str:
    values = printouts.get(key) or []
    if isinstance(values, list):
        for value in values:
            cleaned = _value(value)
            if cleaned:
                return cleaned
        return default
    return _value(values) or default


def _list(printouts: dict[str, Any], key: str) -> list[str]:
    values = printouts.get(key) or []
    if not isinstance(values, list):
        values = [values]
    return [cleaned for cleaned in (_value(v) for v in values) if cleaned]


def resolve_series_key(series_list: list[str], series_meta: dict[str, Any]) -> str:
    """系列任务字段可能是 [总系列, 幕] 也可能是 [幕, 总系列]。

    章级页面（如「序章」）也在 分类:系列任务 里但没有副标题，所以要优先取
    「存在且带副标题」的那个，否则会把整幕任务并到大章下面。
    """
    with_subtitle = [
        name
        for name in series_list
        if name in series_meta and (series_meta[name].get("subtitle") or "").strip()
    ]
    if with_subtitle:
        return with_subtitle[-1]
    for name in series_list:
        if name in series_meta:
            return name
    for name in reversed(series_list):
        if name:
            return name
    return ""


def fetch_tasks(client: WikiClient) -> dict[str, dict[str, Any]]:
    print("[discover] 查询 [[分类:任务]] ...")
    raw = client.ask(TASK_QUERY)
    print(f"[discover] 任务页 {len(raw)} 条")
    tasks: dict[str, dict[str, Any]] = {}
    for title, printouts in raw.items():
        if title in config.EXCLUDED_TITLES:
            continue
        types = [t for t in _list(printouts, "任务类型") if t]
        primary = types[0] if types else ""
        series = _list(printouts, "系列任务")
        tasks[title] = {
            "title": title,
            "display": strip_display_suffix(title),
            "types": types,
            "type": primary,
            "series": series,
            "series_key": series[-1] if series else "",
            "number": normalize_number(_first(printouts, "任务编号")),
            "region": _first(printouts, "任务地区"),
            "version": _first(printouts, "所属版本"),
        }
    return tasks


def fetch_series(client: WikiClient) -> dict[str, dict[str, Any]]:
    print("[discover] 查询 [[分类:系列任务]] ...")
    raw = client.ask(SERIES_QUERY)
    print(f"[discover] 幕级页面 {len(raw)} 条")
    series: dict[str, dict[str, Any]] = {}
    for title, printouts in raw.items():
        name = _first(printouts, "系列任务名") or title
        series[name] = {
            "page": title,
            "name": name,
            "subtitle": _first(printouts, "副标题"),
            "type": _first(printouts, "任务类型"),
            "region": _first(printouts, "任务地区"),
        }
    return series


def fetch_invitations(client: WikiClient) -> list[dict[str, str]]:
    print(f"[discover] 枚举 {config.INVITATION_PREFIX}* ...")
    titles = client.allpages(config.INVITATION_PREFIX)
    print(f"[discover] 邀约事件页 {len(titles)} 条")
    return [
        {
            "title": title,
            "character": title[len(config.INVITATION_PREFIX):].strip(),
        }
        for title in titles
    ]


HEADING_LINK_RE = re.compile(r"^==\s*\[\[([^\]\|#]+)(?:#[^\]\|]*)?(?:\|[^\]]*)?\]\]\s*==\s*$", re.M)


def fetch_entry_orders(client: WikiClient) -> dict[str, dict[str, int]]:
    """从入口页按出现顺序抽取幕名，得到官方剧情顺序。

    兼容两种写法：`{{图标|任务|地区|序号|幕名|任务名}}` 与 `==[[任务名]]==` 独立标题。
    """
    pages = list(dict.fromkeys(config.ENTRY_PAGES.values()))
    contents = client.query_revisions(pages)
    orders: dict[str, dict[str, int]] = {}
    for category, page in config.ENTRY_PAGES.items():
        text = contents.get(page)
        if not text:
            continue

        events: list[tuple[int, str]] = []
        i = 0
        while True:
            start = text.find("{{", i)
            if start < 0:
                break
            end, inner = wikitext.find_template(text, start)
            name, positional, _ = wikitext.template_parts(inner)
            if (
                name.strip() == "图标"
                and len(positional) >= 5
                and positional[0].strip() == "任务"
            ):
                series = strip_display_suffix(wikitext.inline(positional[4]))
                if series:
                    events.append((start, series))
            i = end
        for match in HEADING_LINK_RE.finditer(text):
            events.append((match.start(), strip_display_suffix(match.group(1).strip())))

        sequence: dict[str, int] = {}
        for _, name in sorted(events, key=lambda item: item[0]):
            if name and name not in sequence:
                sequence[name] = len(sequence)

        if sequence:
            orders[category] = sequence
            print(f"[discover] {page} 提供 {len(sequence)} 条顺序")
    return orders


def folder_name(series_meta: dict[str, Any] | None, series_key: str) -> str:
    if not series_key:
        return config.UNSORTED_FOLDER
    if not series_meta:
        return series_key
    subtitle = (series_meta.get("subtitle") or "").strip()
    name = (series_meta.get("name") or series_key).strip()
    if subtitle and subtitle != name:
        return f"{subtitle} {name}"
    return name


def sort_key(
    category: str,
    subtitle: str,
    name: str,
    version: str,
    rank: int | None = None,
) -> tuple:
    chapter, act = chapter_act(subtitle or name)
    if rank is not None:
        return (rank, (0, 0), chapter, act, name)
    if category == "魔神任务":
        return (10**6, (0, 0), chapter, act, name)
    return (10**6, version_key(version), chapter, act, name)


def fallback_folder(category: str, task: dict[str, Any]) -> str:
    """没有系列任务归属时的兜底分组。

    主线/传说里的独立任务单独成幕（否则会被塞进地区目录），其余按地区或版本兜底，
    避免几千个文件挤在「未归类」里。
    """
    if category in {"魔神任务", "传说任务"}:
        return task.get("display") or task.get("title") or config.UNSORTED_FOLDER
    region = (task.get("region") or "").strip()
    version = (task.get("version") or "").strip()
    if category == "活动任务" and version:
        return f"{version} 版本"
    if region:
        return region
    if version:
        return f"{version} 版本"
    return config.UNSORTED_FOLDER


def build_catalog(
    tasks: dict[str, dict[str, Any]],
    series: dict[str, dict[str, Any]],
    invitations: list[dict[str, str]],
    orders: dict[str, dict[str, int]] | None = None,
) -> dict[str, Any]:
    orders = orders or {}
    grouped: dict[str, dict[str, dict[str, Any]]] = {}
    for task in tasks.values():
        category = config.TYPE_TO_CATEGORY.get(task["type"], config.DEFAULT_CATEGORY)
        task["category"] = category
        series_key = resolve_series_key(task["series"], series)
        task["series_key"] = series_key

        if series_key:
            meta = series.get(series_key)
            folder = folder_name(meta, series_key)
            subtitle = (meta or {}).get("subtitle", "")
            group_key = f"series:{series_key}"
        else:
            folder = fallback_folder(category, task)
            subtitle = ""
            group_key = f"fallback:{folder}"

        bucket = grouped.setdefault(category, {}).setdefault(
            group_key,
            {"folder": folder, "subtitle": subtitle, "series": series_key, "tasks": []},
        )
        bucket["tasks"].append(task)

    categories: list[dict[str, Any]] = []
    order = {name: i for i, name in enumerate(config.CATEGORY_ORDER)}
    for category in sorted(grouped, key=lambda c: (order.get(c, 99), c)):
        entries = []
        category_order = orders.get(category, {})
        for group_key, group in grouped[category].items():
            members = group["tasks"]
            subtitle = group["subtitle"]
            folder = group["folder"]
            rank = category_order.get(group["series"] or group["folder"])
            versions = [m["version"] for m in members if m["version"]]
            version = sorted(versions, key=version_key)[0] if versions else ""
            members.sort(key=lambda m: (number_key(m["number"]), m["display"]))
            entries.append(
                {
                    "key": group_key,
                    "folder": folder,
                    "subtitle": subtitle,
                    "version": version,
                    "sort": list(sort_key(category, subtitle, folder, version, rank)),
                    "tasks": members,
                }
            )
        entries.sort(key=lambda e: (tuple(e["sort"]), e["folder"]))
        categories.append(
            {
                "name": category,
                "series": entries,
                "task_count": sum(len(e["tasks"]) for e in entries),
            }
        )

    invitations.sort(key=lambda item: item["character"])
    return {
        "generated_at": _dt.datetime.now().isoformat(timespec="seconds"),
        "site": config.BASE_URL,
        "stats": {
            "tasks": len(tasks),
            "series_pages": len(series),
            "invitations": len(invitations),
        },
        "categories": categories,
        "invitations": invitations,
    }


def run(client: WikiClient, force: bool = False) -> dict[str, Any]:
    if config.CATALOG_PATH.exists() and not force:
        print(f"[discover] 复用已有目录 {config.CATALOG_PATH}")
        return json.loads(config.CATALOG_PATH.read_text(encoding="utf-8"))

    tasks = fetch_tasks(client)
    series = fetch_series(client)
    invitations = fetch_invitations(client)
    orders = fetch_entry_orders(client)
    catalog = build_catalog(tasks, series, invitations, orders)

    config.DATA_DIR.mkdir(parents=True, exist_ok=True)
    config.CATALOG_PATH.write_text(
        json.dumps(catalog, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(
        "[discover] 写出 "
        f"{config.CATALOG_PATH}（{catalog['stats']['tasks']} 任务 / "
        f"{len(catalog['categories'])} 分类 / {len(invitations)} 邀约）"
    )
    return catalog
