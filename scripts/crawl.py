"""命令行入口：discover -> fetch -> build。

用法示例：
    python scripts/crawl.py                 # 全流程（有缓存则零网络）
    python scripts/crawl.py --force         # 强制重新下载
    python scripts/crawl.py --rebuild       # 只用本地缓存重新生成 txt
    python scripts/crawl.py --only 魔神任务 传说任务
    python scripts/crawl.py --limit 50      # 只抓前 50 页（调试用）
"""

# Copyright (c) 2026 AFewMoon
# SPDX-License-Identifier: GPL-3.0-or-later

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import config  # noqa: E402
import discover  # noqa: E402
import fetcher  # noqa: E402
import render  # noqa: E402
import wikitext  # noqa: E402
from wiki_client import WikiClient, WikiError  # noqa: E402


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="抓取原神 BWIKI 剧情文本并按分类整理为纯文本 txt。"
    )
    parser.add_argument("--only", nargs="*", metavar="分类", help="只处理指定分类")
    parser.add_argument("--limit", type=int, default=None, help="最多抓取多少页（调试用）")
    parser.add_argument("--force", action="store_true", help="忽略缓存，重新下载正文")
    parser.add_argument("--rebuild", action="store_true", help="只用本地缓存重建 txt")
    parser.add_argument("--rediscover", action="store_true", help="强制重新枚举目录")
    parser.add_argument("--no-clean", action="store_true", help="保留 output 目录旧文件")
    parser.add_argument("--interval", type=float, default=config.MIN_INTERVAL, help="请求间隔秒数")
    parser.add_argument("--skip-invitations", action="store_true", help="跳过邀约事件")
    return parser.parse_args(argv)


def load_catalog(only: list[str] | None, skip_invitations: bool) -> dict[str, Any]:
    catalog = json.loads(config.CATALOG_PATH.read_text(encoding="utf-8"))
    if only:
        wanted = set(only)
        catalog["categories"] = [c for c in catalog["categories"] if c["name"] in wanted]
        missing = wanted - {c["name"] for c in catalog["categories"]}
        if missing:
            print(f"[warn] 未知分类：{'、'.join(sorted(missing))}")
    if skip_invitations or (only and config.INVITATION_CATEGORY not in only):
        catalog["invitations"] = []
    return catalog


def collect_titles(catalog: dict[str, Any]) -> list[str]:
    return fetcher.all_titles(catalog)


def do_discover(client: WikiClient, force: bool) -> dict[str, Any]:
    return discover.run(client, force=force)


def do_fetch(
    client: WikiClient,
    catalog: dict[str, Any],
    force: bool,
    limit: int | None,
) -> tuple[dict[str, str], list[tuple[str, str]]]:
    titles = collect_titles(catalog)
    return fetcher.fetch_all(client, titles, force=force, limit=limit)


def load_contents(titles: list[str], index: dict[str, str]) -> dict[str, str]:
    contents: dict[str, str] = {}
    for title in titles:
        text = fetcher.read_cached(title, index)
        if text is not None:
            contents[title] = text
    return contents


def write_unknown_templates() -> None:
    config.REPORT_DIR.mkdir(parents=True, exist_ok=True)
    items = wikitext.UNKNOWN_TEMPLATES.most_common()
    lines = ["未识别模板统计", "=" * 60, ""]
    if not items:
        lines.append("无（所有模板均已覆盖）。")
    else:
        lines.append("以下模板未显式适配，渲染时保留了最后一个参数或丢弃，供人工核查：")
        lines.append("")
        lines.append("模板  出现次数")
        for name, count in items:
            lines.append(f"{name}  {count}")
    config.UNKNOWN_TPL_REPORT.write_text(
        "\n".join(lines) + "\n",
        encoding="utf-8-sig",
        newline="\r\n",
    )
    if items:
        print(f"[report] 未识别模板 {len(items)} 种 -> {config.UNKNOWN_TPL_REPORT}")


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    needs_network = not args.rebuild

    client = WikiClient(min_interval=args.interval) if needs_network else None
    try:
        if needs_network:
            catalog = do_discover(client, force=args.rediscover)
            catalog = load_catalog(args.only, args.skip_invitations)
            index, failures = do_fetch(client, catalog, args.force, args.limit)
            if failures:
                config.REPORT_DIR.mkdir(parents=True, exist_ok=True)
                print(f"[fetch] 抓取失败 {len(failures)} 页（前 5 条）：")
                for title, reason in failures[:5]:
                    print(f"    - {title}: {reason}")
        else:
            catalog = load_catalog(args.only, args.skip_invitations)
            index = fetcher.load_index()

        titles = collect_titles(catalog)
        contents = load_contents(titles, index)
        print(f"[build] 待渲染 {len(titles)} 页，命中缓存 {len(contents)} 页")

        tree = render.build(catalog, contents, clean=not args.no_clean)
        index_path = render.write_index(catalog, tree)
        render.write_missing(tree)
        write_unknown_templates()

        print(f"[build] 生成 {tree.written} 个 txt 文件 -> {config.OUTPUT_DIR}")
        print(f"[build] 索引 -> {index_path}")
        if tree.missing:
            print(f"[build] 缺失 {len(tree.missing)} 条 -> {config.MISSING_REPORT}")
        if client is not None:
            print(f"[stat] 本次共发起 {client.request_count} 次请求")
        return 0
    except WikiError as exc:
        print(f"[error] {exc}", file=sys.stderr)
        return 1
    finally:
        if client is not None:
            client.close()


if __name__ == "__main__":
    raise SystemExit(main())
