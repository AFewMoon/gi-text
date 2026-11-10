"""唯一的出网点：封装 MediaWiki / Semantic MediaWiki API。

对外只暴露四个方法：
    ask()              语义查询（目录枚举）
    query_revisions()  批量按标题取 wikitext
    allpages()         按前缀枚举页面
    parse_text()       单页渲染 HTML（兜底用）

限速、重试、请求头集中在这里，其它模块禁止自行发请求。
"""

# Copyright (c) 2026 AFewMoon
# SPDX-License-Identifier: GPL-3.0-or-later

from __future__ import annotations

import time
from typing import Any, Iterable

import requests

import config


class WikiError(RuntimeError):
    """网络或 API 层异常。"""


class WikiClient:
    def __init__(
        self,
        min_interval: float = config.MIN_INTERVAL,
        max_retry: int = config.MAX_RETRY,
        verbose: bool = True,
    ) -> None:
        self.session = requests.Session()
        self.session.headers.update(config.HEADERS)
        self.min_interval = max(0.0, min_interval)
        self.max_retry = max(1, max_retry)
        self.verbose = verbose
        self._last_request = 0.0
        self.request_count = 0

    # ------------------------------------------------------------ 基础设施
    def __enter__(self) -> "WikiClient":
        return self

    def __exit__(self, *exc_info: object) -> None:
        self.close()

    def close(self) -> None:
        self.session.close()

    def _throttle(self) -> None:
        gap = time.monotonic() - self._last_request
        if gap < self.min_interval:
            time.sleep(self.min_interval - gap)
        self._last_request = time.monotonic()

    def _call(self, params: dict[str, Any], use_post: bool = False) -> dict[str, Any]:
        last_error = "未知错误"
        for attempt in range(1, self.max_retry + 1):
            self._throttle()
            try:
                if use_post:
                    resp = self.session.post(config.API_URL, data=params, timeout=config.TIMEOUT)
                else:
                    resp = self.session.get(config.API_URL, params=params, timeout=config.TIMEOUT)
                self.request_count += 1

                if resp.status_code == 200:
                    data = resp.json()
                    if not isinstance(data, dict):
                        raise WikiError("响应不是 JSON 对象")
                    if "error" in data:
                        err = data["error"]
                        raise WikiError(f"API 错误 {err.get('code')}: {err.get('info')}")
                    return data

                last_error = f"HTTP {resp.status_code}"
                if resp.status_code in config.RETRY_STATUS:
                    raise _Retryable(last_error)
                raise WikiError(f"{last_error}：{config.API_URL}")
            except _Retryable as exc:
                last_error = str(exc)
            except (requests.RequestException, ValueError) as exc:
                last_error = f"{type(exc).__name__}: {exc}"

            if attempt < self.max_retry:
                wait = min(30.0, max(self.min_interval, 1.0) * (2 ** (attempt - 1)))
                if self.verbose:
                    print(f"    [retry {attempt}/{self.max_retry}] {last_error} → 等待 {wait:.1f}s")
                time.sleep(wait)

        raise WikiError(f"请求失败（已重试 {self.max_retry} 次）：{last_error}")

    # ------------------------------------------------------------ API
    def ask(self, query: str, limit: int = config.ASK_LIMIT) -> dict[str, dict[str, Any]]:
        """SMW 语义查询，返回 {页面标题: printouts}。"""
        results: dict[str, dict[str, Any]] = {}
        offset = 0
        while True:
            params = {
                "action": "ask",
                "query": f"{query}|limit={limit}|offset={offset}",
                "format": "json",
                "formatversion": "2",
            }
            data = self._call(params)
            body = data.get("query", {})
            chunk = body.get("results") or {}
            if isinstance(chunk, list):  # 空结果时 SMW 返回 []
                break
            for title, item in chunk.items():
                results[title] = item.get("printouts", {}) or {}
            nxt = body.get("query-continue-offset")
            if nxt is None:
                break
            offset = int(nxt)
            if offset <= 0 or len(chunk) == 0:
                break
        return results

    def query_revisions(self, titles: Iterable[str]) -> dict[str, str]:
        """批量取页面 wikitext，返回 {标题: 正文}；不存在的标题不会出现在结果里。"""
        wanted = [t for t in dict.fromkeys(titles) if t]
        out: dict[str, str] = {}
        for start in range(0, len(wanted), config.BATCH_SIZE):
            batch = wanted[start : start + config.BATCH_SIZE]
            params = {
                "action": "query",
                "prop": "revisions",
                "rvprop": "content",
                "rvslots": "main",
                "titles": "|".join(batch),
                "redirects": "1",
                "format": "json",
                "formatversion": "2",
            }
            data = self._call(params, use_post=True)
            body = data.get("query", {})

            redirects = {
                r.get("from"): r.get("to") for r in body.get("redirects", []) if r.get("from")
            }
            normalized = {
                n.get("from"): n.get("to") for n in body.get("normalized", []) if n.get("from")
            }

            fetched: dict[str, str] = {}
            for page in body.get("pages", []):
                title = page.get("title")
                if not title or page.get("missing"):
                    continue
                revs = page.get("revisions") or []
                if not revs:
                    continue
                slots = revs[0].get("slots") or {}
                main = slots.get("main") or {}
                content = main.get("content")
                if content is None:
                    content = revs[0].get("content")
                if content is None:
                    continue
                fetched[title] = content

            for original in batch:
                candidate = original
                if candidate in fetched:
                    out[original] = fetched[candidate]
                    continue
                candidate = normalized.get(original, original)
                candidate = redirects.get(candidate, candidate)
                if candidate in fetched:
                    out[original] = fetched[candidate]
        return out

    def allpages(self, prefix: str) -> list[str]:
        """按前缀枚举主命名空间页面标题。"""
        titles: list[str] = []
        cont: dict[str, Any] = {}
        while True:
            params = {
                "action": "query",
                "list": "allpages",
                "apprefix": prefix,
                "apnamespace": "0",
                "aplimit": "max",
                "format": "json",
                "formatversion": "2",
            }
            params.update(cont)
            data = self._call(params)
            body = data.get("query", {})
            for item in body.get("allpages", []):
                title = item.get("title")
                if title:
                    titles.append(title)
            if "continue" not in data:
                break
            cont = dict(data["continue"])
        return titles

    def parse_text(self, title: str) -> str:
        """渲染后的 HTML（解析兜底用）。"""
        params = {
            "action": "parse",
            "page": title,
            "prop": "text",
            "format": "json",
            "formatversion": "2",
        }
        data = self._call(params)
        return data.get("parse", {}).get("text", "") or ""


class _Retryable(Exception):
    """内部标记：可重试的 HTTP 状态。"""
