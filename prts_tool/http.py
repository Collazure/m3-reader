#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""网络层：prts.wiki 的 MediaWiki API 客户端（纯标准库）。

prts.wiki 前置了 WAF（Tengine）：浏览器 UA 有时会被拦，但 `Accept-Language` 必须带；
另外不要抓 /w/xxx 这类 HTML 页面（会命中反机器人挑战页），
取文本统一走 api.php（action=query / cargoquery）或 index.php?action=raw。
"""

from __future__ import annotations

import json
import time
from dataclasses import dataclass
from typing import Any, Iterable, Iterator
from urllib.error import HTTPError, URLError
from urllib.parse import quote, urlencode
from urllib.request import Request, urlopen

BASE = "https://prts.wiki"

# 注意：不要用 Mozilla 开头的 UA —— 会被 CDN 直接 403；Accept-Language 则必须带上。
HEADERS = {
    "User-Agent": "PRTS-Text-Archiver/2.0 (personal offline archive; python-urllib)",
    "Accept-Language": "zh-CN,zh;q=0.9",
    "Accept": "application/json, text/plain, */*",
}

BATCH = 50          # MediaWiki titles= 单次上限（普通用户）


class PrtsError(RuntimeError):
    pass


class PrtsNotFound(PrtsError):
    """页面不存在（404）。"""


@dataclass
class PageRecord:
    title: str
    revid: int = 0
    timestamp: str = ""
    content: str = ""


class PrtsClient:
    """带重试、限速的 API 客户端。"""

    def __init__(self, delay: float = 0.3, timeout: int = 60, retries: int = 5, log=print):
        self.delay = delay
        self.timeout = timeout
        self.retries = retries
        self.log = log
        self._last = 0.0
        self.requests = 0

    # ---------------- 低层 ----------------
    def _throttle(self) -> None:
        wait = self.delay - (time.time() - self._last)
        if wait > 0:
            time.sleep(wait)

    def _fetch(self, url: str, data: bytes | None = None) -> bytes:
        last: Exception | None = None
        for attempt in range(1, self.retries + 1):
            try:
                self._throttle()
                req = Request(url, data=data, headers=HEADERS)
                if data is not None:
                    req.add_header("Content-Type", "application/x-www-form-urlencoded; charset=utf-8")
                with urlopen(req, timeout=self.timeout) as resp:
                    body = resp.read()
                self._last = time.time()
                self.requests += 1
                return body
            except HTTPError as exc:
                if exc.code == 404:                     # 页面不存在，不必重试
                    raise PrtsNotFound(f"404 Not Found: {url}") from exc
                last = exc
                # 503/429 时优先遵守服务端的 Retry-After；否则指数退避。
                wait = min(2 ** attempt, 20)
                retry_after = (exc.headers or {}).get("Retry-After") if exc.headers else None
                if retry_after:
                    try:
                        wait = max(wait, min(int(retry_after), 120))
                    except ValueError:
                        pass
                self.log(f"  ! 请求失败（{attempt}/{self.retries}）：{exc}，{wait}s 后重试")
                time.sleep(wait)
            except (URLError, TimeoutError, OSError) as exc:
                last = exc
                wait = min(2 ** attempt, 20)
                self.log(f"  ! 请求失败（{attempt}/{self.retries}）：{exc}，{wait}s 后重试")
                time.sleep(wait)
        raise PrtsError(f"请求反复失败：{last}")

    # ---------------- API ----------------
    def api(self, **params: Any) -> dict:
        params.setdefault("format", "json")
        params.setdefault("formatversion", 2)
        payload = urlencode({k: v for k, v in params.items() if v is not None}).encode("utf-8")
        raw = self._fetch(f"{BASE}/api.php", data=payload)
        try:
            data = json.loads(raw.decode("utf-8"))
        except json.JSONDecodeError as exc:
            raise PrtsError(f"返回不是 JSON（可能又被 WAF 拦了）：{exc}") from exc
        if "error" in data:
            err = data["error"]
            raise PrtsError(f"API 错误：{err.get('code')} - {err.get('info')}")
        return data

    def raw(self, title: str) -> str:
        """单页 wikitext（action=raw）；页面不存在时返回空串。"""
        url = f"{BASE}/index.php?action=raw&title={quote(title)}"
        try:
            return self._fetch(url).decode("utf-8", "replace")
        except PrtsNotFound:
            self.log(f"  ! 页面不存在：{title}")
            return ""

    # ---------------- 批量取页面 ----------------
    def pages(self, titles: Iterable[str], with_content: bool = True) -> dict[str, PageRecord]:
        """批量取页面（含 revid / 时间戳 / 可选正文），一次 50 个。"""
        titles = [t for t in titles if t]
        out: dict[str, PageRecord] = {}
        for start in range(0, len(titles), BATCH):
            chunk = titles[start:start + BATCH]
            params: dict[str, Any] = {
                "action": "query", "prop": "revisions", "rvslots": "main",
                "rvprop": "content|ids|timestamp" if with_content else "ids|timestamp",
                "titles": "|".join(chunk), "redirects": 1,
            }
            data = self.api(**params)
            query = data.get("query", {})
            alias: dict[str, str] = {n["from"]: n["to"] for n in query.get("normalized", [])}
            alias.update({r["from"]: r["to"] for r in query.get("redirects", [])})
            for page in query.get("pages", []):
                title = page.get("title", "")
                if page.get("missing"):
                    record = PageRecord(title=title)
                else:
                    revs = page.get("revisions") or []
                    if not revs:
                        continue
                    rev = revs[0]
                    content = ""
                    if with_content:
                        content = (rev.get("slots", {}).get("main", {}) or {}).get("content", "")
                    record = PageRecord(title, int(rev.get("revid", 0)), rev.get("timestamp", ""), content)
                out[title] = record
                for frm, to in alias.items():
                    if to == title:
                        out[frm] = record
        return out

    def raw_many(self, titles: Iterable[str]) -> dict[str, str]:
        return {t: r.content for t, r in self.pages(titles, with_content=True).items() if r.content}

    def revids(self, titles: Iterable[str]) -> dict[str, PageRecord]:
        return self.pages(titles, with_content=False)

    # ---------------- Cargo ----------------
    def cargo(self, tables: str, fields: str = "_pageName=PAGE", where: str | None = None,
              limit: int = 500, offset: int = 0, order_by: str | None = None) -> list[dict]:
        """action=cargoquery。坑：`_pageName` 必须写成 `_pageName=PAGE`（别名），
        且返回的列名里下划线会变成空格。"""
        data = self.api(
            action="cargoquery", tables=tables, fields=fields,
            where=where, limit=min(limit, 500), offset=offset,
            **({"order by": order_by} if order_by else {}),
        )
        return [row["title"] for row in data.get("cargoquery", [])]

    def cargo_all(self, tables: str, fields: str, where: str | None = None,
                  order_by: str | None = None, page: int = 500) -> Iterator[dict]:
        offset = 0
        while True:
            batch = self.cargo(tables, fields, where=where, limit=page, offset=offset, order_by=order_by)
            if not batch:
                return
            yield from batch
            if len(batch) < min(page, 500):
                return
            offset += len(batch)

    # ---------------- 列表 ----------------
    def _paginate(self, key: str, **params: Any) -> Iterator[str]:
        cont: dict = {}
        while True:
            data = self.api(action="query", **params, **cont)
            for item in data.get("query", {}).get(key, []):
                yield item["title"]
            if "continue" not in data:
                return
            cont = data["continue"]

    def category(self, name: str) -> list[str]:
        """分类成员（name 不带 Category: 前缀）。"""
        return list(self._paginate("categorymembers", list="categorymembers",
                                   cmtitle="分类:" + name, cmlimit=500, cmnamespace=0))

    def embedded_in(self, template: str, namespace: int = 0) -> list[str]:
        """所有嵌入了某模板的页面（枚举剧情页/关卡页/家具页的权威入口）。"""
        return list(self._paginate("embeddedin", list="embeddedin",
                                   eititle="模板:" + template, einamespace=namespace, eilimit=500))

    def search(self, query: str, limit: int = 20) -> list[str]:
        data = self.api(action="query", list="search", srsearch=query, srlimit=limit)
        return [r["title"] for r in data.get("query", {}).get("search", [])]

    # ---------------- 文件 ----------------
    def file_info(self, names: Iterable[str]) -> dict[str, dict]:
        """批量取文件信息（url / 大小 / sha1 / mime），一次 50 个。

        names 可带或不带「文件:」前缀，返回 {文件名: {...}}。
        """
        titles = [n if n.startswith(("文件:", "File:")) else "文件:" + n for n in names if n]
        out: dict[str, dict] = {}
        for start in range(0, len(titles), BATCH):
            chunk = titles[start:start + BATCH]
            data = self.api(action="query", prop="imageinfo",
                            iiprop="url|size|mime|sha1", titles="|".join(chunk))
            query = data.get("query", {})
            alias: dict[str, str] = {n["from"]: n["to"] for n in query.get("normalized", [])}
            for page in query.get("pages", []):
                title = page.get("title", "")
                info = (page.get("imageinfo") or [{}])[0]
                record = {
                    "title": title,
                    "name": title.split(":", 1)[-1],
                    "url": info.get("url", ""),
                    "size": int(info.get("size", 0) or 0),
                    "mime": info.get("mime", ""),
                    "sha1": info.get("sha1", ""),
                    "missing": bool(page.get("missing")),
                }
                out[record["name"]] = record
                for frm, to in alias.items():
                    if to == title:
                        out[frm.split(":", 1)[-1]] = record
        return out

    def download(self, url: str, dest) -> int:
        """下载文件到 dest（先写 .part 再改名，中断不会留下半个文件）。"""
        from pathlib import Path
        dest = Path(dest)
        data = self._fetch(url)
        if dest.is_file() and dest.read_bytes() == data:
            return len(data)
        dest.parent.mkdir(parents=True, exist_ok=True)
        tmp = dest.with_name(dest.name + ".part")
        tmp.write_bytes(data)
        tmp.replace(dest)
        return len(data)
