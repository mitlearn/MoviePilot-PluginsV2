"""MoviePilot V3 Jackett/Torznab indexer integration."""

from __future__ import annotations

import asyncio
import threading
import xml.etree.ElementTree as ET
from datetime import datetime
from typing import Any
from urllib.parse import urlparse

from apscheduler.triggers.cron import CronTrigger

from app.plugins import _PluginBase
from app.sdk.logging import logger
from app.sdk.media import TorrentInfo
from app.sdk.network import RequestUtils, SitesHelper
from app.schemas.types import MediaType


class JackettIndexer(_PluginBase):
    """Register configured Jackett indexers and translate Torznab results."""

    plugin_name = "Jackett索引器"
    plugin_desc = "通过Jackett/Torznab统一搜索已配置的私有和半公开索引器。"
    plugin_icon = "Jackett_A.png"
    plugin_version = "3.0.1"
    plugin_author = "mitlearn"
    author_url = "https://github.com/mitlearn/MoviePilot-PluginsV2"
    plugin_config_prefix = "jackettindexer_"
    plugin_order = 16
    auth_level = 2

    def __init__(self) -> None:
        super().__init__()
        self._enabled = False
        self._host = ""
        self._api_key = ""
        self._proxy = False
        self._cron = "0 0 */12 * *"
        # Fix #9: 用 _lock 保护 _indexers，_sync_indexers 完成后原子替换
        self._indexers: list[dict[str, Any]] = []
        self._lock = threading.Lock()

    def init_plugin(self, config: dict | None = None) -> None:
        """读取配置并注册 Jackett 已配置索引器。"""
        self.stop_service()
        config = config or {}
        self._enabled = bool(config.get("enabled"))
        self._host = str(config.get("host") or "").rstrip("/")
        self._api_key = str(config.get("api_key") or "")
        self._proxy = config.get("proxy") or False
        self._cron = str(config.get("cron") or self._cron)
        if not self._enabled or not self._host or not self._api_key:
            return
        # Fix #11: 校验 host 格式
        parsed = urlparse(self._host)
        if not parsed.scheme or not parsed.netloc:
            logger.error("Jackett地址格式无效（需要包含 http:// 或 https://）：%s", self._host)
            return
        self._sync_indexers()

    def _request(self, indexer: str, params: dict[str, Any]) -> str | None:
        response = RequestUtils(proxies=self._proxy).get_res(
            url=f"{self._host}/api/v2.0/indexers/{indexer}/results/torznab/api",
            params={**params, "apikey": self._api_key}, timeout=60)
        if not response or response.status_code != 200:
            return None
        return response.text

    def _sync_indexers(self) -> bool:
        response = RequestUtils(proxies=self._proxy).get_res(
            url=f"{self._host}/api/v2.0/indexers/all/results/torznab/api",
            params={"apikey": self._api_key, "t": "indexers", "configured": "true"}, timeout=30)
        if not response or response.status_code != 200:
            # Fix #7: 失败时记录日志
            logger.warning("Jackett索引器同步失败：无法连接到 %s", self._host)
            return False
        try:
            root = ET.fromstring(response.text)
        except ET.ParseError as e:
            logger.warning("Jackett索引器列表解析失败：%s", e)
            return False
        helper = SitesHelper()
        current = []
        for node in root.findall(".//indexer"):
            name = node.get("id")
            title = node.findtext("title")
            if not name or not title or (node.get("type") or "").lower() == "public":
                continue
            category = self._category(name)
            # Fix #1: 空字典也跳过（原来只跳过 None，导致解析失败的索引器被错误注册）
            if not category:
                continue
            site = self._site(name, title, category)
            current.append(site)
            helper.add_indexer(site["domain"], site)
        # Fix #9: 原子替换，避免搜索线程读到中间状态
        with self._lock:
            self._indexers = current
        logger.info("Jackett索引器同步完成，共注册 %d 个", len(current))
        return True

    def _category(self, indexer: str) -> dict[str, list[dict[str, Any]]] | None:
        xml = self._request(indexer, {"t": "caps"})
        if not xml:
            return {}
        try:
            root = ET.fromstring(xml)
        except ET.ParseError:
            return {}
        result = {"movie": [], "tv": [], "music": []}
        xxx = False
        content = False
        for node in root.findall(".//category"):
            try:
                category_id = int(node.get("id"))
            except (TypeError, ValueError):
                continue
            top = category_id // 1000 * 1000
            if top == 6000:
                xxx = True
            if top in (1000, 2000, 3000, 4000, 5000, 7000, 8000):
                content = True
            entry = {"id": category_id, "cat": node.get("name", ""), "desc": node.get("name", "")}
            if top == 2000:
                result["movie"].append(entry)
            elif top == 3000:
                result["music"].append(entry)
            elif top == 5000:
                result["tv"].append(entry)
        if xxx and not content:
            return None
        return {key: value for key, value in result.items() if value}

    def _site(self, indexer: str, title: str, category: dict[str, Any]) -> dict[str, Any]:
        cats = (
            ([2000] if "movie" in category else []) +
            ([3000] if "music" in category else []) +
            ([5000] if "tv" in category else [])
        )
        endpoint = f"{self._host}/api/v2.0/indexers/{indexer}/results/torznab/api"
        cat_str = ",".join(map(str, cats))
        return {
            "id": f"{self.plugin_name}-{title}",
            "name": f"{self.plugin_name}-{title}",
            "domain": f"jackett_indexer.{indexer}",
            "url": endpoint,
            "public": False,
            "proxy": False,
            "category": category,
            "result_num": 100,
            # Fix #3: 使用 t=rss 作为 RSS 浏览端点，而非 t=search&q=
            # Torznab 规范中 t=rss（或省略 t）返回标准 RSS feed，
            # t=search&q= 是搜索端点，部分 Jackett 版本对空查询行为不一致
            "rss": f"{endpoint}?apikey={self._api_key}&t=rss&cat={cat_str}&limit=30",
        }

    def _search(self, site: dict, keyword: str, mtype: MediaType | None, page: int) -> list[TorrentInfo]:
        if not keyword or not isinstance(site, dict) or not site.get("domain", "").startswith("jackett_indexer."):
            return []
        indexer = site["domain"].split(".", 1)[-1]
        categories = (
            [2000] if mtype == MediaType.MOVIE else
            [3000] if mtype == MediaType.MUSIC else
            [5000] if mtype == MediaType.TV else
            [2000, 3000, 5000]
        )

        # MoviePilot 传入的 IMDb ID 格式为 tt1234567（含 tt 前缀）
        # Torznab 规范：imdbid 参数接受纯数字（不含 tt 前缀）
        # Fix #6: mtype=None 时同时尝试 movie 和 tvsearch，避免只搜 movie 漏掉 TV 内容
        if (
            mtype in (None, MediaType.MOVIE, MediaType.TV)
            and keyword.startswith("tt")
            and keyword[2:].isdigit()
        ):
            imdb_num = keyword[2:]
            if mtype == MediaType.TV:
                params_list = [{"t": "tvsearch", "imdbid": imdb_num,
                                "limit": 100, "offset": page * 100}]
            elif mtype == MediaType.MOVIE:
                params_list = [{"t": "movie", "imdbid": imdb_num,
                                "limit": 100, "offset": page * 100}]
            else:
                # mtype 未知：先 movie 再 tvsearch，合并去重
                params_list = [
                    {"t": "movie", "imdbid": imdb_num, "limit": 100, "offset": page * 100},
                    {"t": "tvsearch", "imdbid": imdb_num, "limit": 100, "offset": page * 100},
                ]
        else:
            cat_str = ",".join(map(str, categories))
            params_list = [{"t": "search", "q": keyword, "cat": cat_str,
                            "limit": 100, "offset": page * 100}]

        results = []
        seen_enclosures: set[str] = set()
        for params in params_list:
            xml = self._request(indexer, params)
            if not xml:
                continue
            try:
                root = ET.fromstring(xml)
            except ET.ParseError:
                continue
            for item in root.findall(".//item"):
                title = item.findtext("title")
                enclosure = item.find("enclosure")
                link = item.findtext("link")
                if not title or not (enclosure is not None and enclosure.get("url") or link):
                    continue
                attrs = {node.get("name"): node.get("value") for node in item.findall("{*}attr")}
                enc_url = attrs.get("magneturl") or (enclosure.get("url") if enclosure is not None else link)
                # 去重：多次请求可能返回相同条目
                if enc_url in seen_enclosures:
                    continue
                if enc_url:
                    seen_enclosures.add(enc_url)
                results.append(TorrentInfo(
                    site_name=site.get("name"),
                    title=title,
                    enclosure=enc_url,
                    page_url=item.findtext("comments") or item.findtext("guid"),
                    size=float(enclosure.get("length", 0)) if enclosure is not None else 0,
                    seeders=int(attrs.get("seeders") or 0),
                    peers=int(attrs.get("peers") or 0),
                    description=item.findtext("description"),
                    pubdate=self._date(item.findtext("pubDate")),
                    category="music" if mtype == MediaType.MUSIC else None,
                ))
        return results

    @staticmethod
    def _date(value: str | None) -> str | None:
        if not value:
            return None
        try:
            return datetime.strptime(value[:25], "%a, %d %b %Y %H:%M:%S").strftime("%Y-%m-%d %H:%M:%S")
        except ValueError:
            return value

    def get_module(self) -> dict[str, Any]:
        return {
            "search_torrents": self.search_torrents,
            "async_search_torrents": self.async_search_torrents,
            "get_search_page_size": lambda site, keyword=None: 100 if site is not None else None,
        }

    def search_torrents(self, site: dict, keyword: str, mtype: MediaType | None = None, page: int = 0) -> list[TorrentInfo]:
        return self._search(site, keyword, mtype, page)

    async def async_search_torrents(self, site: dict, keyword: str, mtype: MediaType | None = None, page: int = 0) -> list[TorrentInfo]:
        return await asyncio.to_thread(self._search, site, keyword, mtype, page)

    def get_service(self) -> list[dict[str, Any]]:
        if not self._enabled or not self._cron:
            return []
        # Fix #8（保留原逻辑，cron 验证在此处捕获异常）
        try:
            trigger = CronTrigger.from_crontab(self._cron)
        except ValueError as e:
            logger.error("Jackett索引器同步 Cron 表达式无效：%s — %s", self._cron, e)
            return []
        return [{"id": "JackettIndexer.Sync", "name": "同步Jackett索引器",
                 "trigger": trigger, "func": self._sync_indexers, "kwargs": {}}]

    def get_state(self) -> bool:
        return self._enabled

    @staticmethod
    def get_command() -> list[dict[str, Any]]:
        return []

    def get_api(self) -> list[dict[str, Any]]:
        return []

    def get_form(self) -> tuple[list[dict], dict[str, Any]]:
        return [{"component": "VForm", "content": [
            {"component": "VSwitch", "props": {"model": "enabled", "label": "启用插件"}},
            {"component": "VTextField", "props": {"model": "host", "label": "Jackett地址"}},
            {"component": "VTextField", "props": {"model": "api_key", "label": "API Key", "type": "password"}},
            # Fix #4: 补充代理开关
            {"component": "VSwitch", "props": {"model": "proxy", "label": "使用代理"}},
            {"component": "VTextField", "props": {"model": "cron", "label": "索引器同步 Cron"}},
        ]}], {"enabled": False, "host": "", "api_key": "", "proxy": False, "cron": self._cron}

    def get_page(self) -> list[dict]:
        with self._lock:
            count = len(self._indexers)
        return [{"component": "VAlert", "props": {"type": "info", "text": f"已注册 {count} 个Jackett索引器。"}}]

    def stop_service(self) -> None:
        with self._lock:
            self._indexers = []
        self._enabled = False
