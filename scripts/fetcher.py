"""正文抓取与本地缓存：批量取 wikitext，按标题哈希落盘，支持断点续跑。"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any, Iterable

import config
from wiki_client import WikiClient, WikiError


def cache_file(title: str) -> Path:
    digest = hashlib.sha1(title.encode("utf-8")).hexdigest()[:16]
    return config.CACHE_DIR / f"{digest}.wikitext"


def load_index() -> dict[str, str]:
    if config.CACHE_INDEX.exists():
        try:
            return json.loads(config.CACHE_INDEX.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            return {}
    return {}


def save_index(index: dict[str, str]) -> None:
    config.CACHE_DIR.mkdir(parents=True, exist_ok=True)
    config.CACHE_INDEX.write_text(
        json.dumps(index, ensure_ascii=False, indent=0), encoding="utf-8"
    )


def all_titles(catalog: dict[str, Any]) -> list[str]:
    titles: list[str] = []
    for category in catalog["categories"]:
        for entry in category["series"]:
            for task in entry["tasks"]:
                titles.append(task["title"])
    titles.extend(item["title"] for item in catalog.get("invitations", []))
    return list(dict.fromkeys(titles))


def read_cached(title: str, index: dict[str, str]) -> str | None:
    name = index.get(title)
    path = config.CACHE_DIR / name if name else cache_file(title)
    if path.exists():
        return path.read_text(encoding="utf-8")
    return None


def fetch_all(
    client: WikiClient,
    titles: Iterable[str],
    force: bool = False,
    limit: int | None = None,
) -> tuple[dict[str, str], list[tuple[str, str]]]:
    """返回 (缓存索引, 失败清单)。"""
    config.CACHE_DIR.mkdir(parents=True, exist_ok=True)
    index = load_index()

    wanted = list(dict.fromkeys(titles))
    if limit is not None:
        wanted = wanted[:limit]

    pending = []
    for title in wanted:
        if force or read_cached(title, index) is None:
            pending.append(title)

    cached = len(wanted) - len(pending)
    print(f"[fetch] 目标 {len(wanted)} 页，已缓存 {cached}，需下载 {len(pending)}")
    failures: list[tuple[str, str]] = []

    batch_size = config.BATCH_SIZE
    for start in range(0, len(pending), batch_size):
        batch = pending[start : start + batch_size]
        done = start + len(batch)
        try:
            contents = client.query_revisions(batch)
        except WikiError as exc:
            for title in batch:
                failures.append((title, str(exc)))
            print(f"[fetch] {done}/{len(pending)} 批次失败：{exc}")
            continue

        for title in batch:
            content = contents.get(title)
            if content is None:
                failures.append((title, "页面不存在或未返回正文"))
                continue
            path = cache_file(title)
            path.write_text(content, encoding="utf-8")
            index[title] = path.name

        save_index(index)
        print(f"[fetch] {done}/{len(pending)}（请求累计 {client.request_count} 次）")

    save_index(index)
    if failures:
        print(f"[fetch] 失败 {len(failures)} 页")
    return index, failures
