"""MoviePilot V3 Prowlarr indexer integration.

The plugin only provides the standard torrent-search module ports.  Latest
items are exposed through the registered RSS URL, so the host's normal browse
and download pipeline remains in charge of those operations.
"""

from __future__ import annotations

import asyncio
import threading
from datetime import datetime
from typing import Any, Optional
from urllib.parse import urlparse

from apscheduler.triggers.cron import CronTrigger

from app.plugins import _PluginBase
from app.sdk.logging import logger
from app.sdk.media import TorrentInfo
from app.sdk.network import RequestUtils, SitesHelper
from app.schemas.types import MediaType


class ProwlarrIndexer(_PluginBase):
    """Register enabled Prowlarr indexers and search them via V3 module ports."""

    plugin_name = "Prowlarr索引器"
    plugin_desc = "通过Prowlarr统一搜索已配置的私有和半公开索引器。"
    plugin_icon = "Prowlarr.png"
    plugin_version = "3.0.1"
    plugin_author = "mitlearn"
    author_url = "https://github.com/mitlearn/MoviePilot-PluginsV2"
    plugin_config_prefix = "prowlarrindexer_"
    plugin_order = 15
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
        """读取配置并注册当前已启用的 Prowlarr 索引器。"""
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
            logger.error("Prowlarr地址格式无效（需要包含 http:// 或 https://）：%s", self._host)
            return
        self._sync_indexers()

    def _headers(self) -> dict[str, str]:
        return {"X-Api-Key": self._api_key, "Accept": "application/json"}

    def _request_json(self, url: str, params: Any = None) -> Any:
        response = RequestUtils(headers=self._headers(), proxies=self._proxy).get_res(
            url=url, params=params, timeout=60
        )
        if not response or response.status_code != 200:
            logger.warning("Prowlarr请求失败：%s", url)
            return None
        try:
            return response.json()
        except (TypeError, ValueError):
            return None

    def _sync_indexers(self) -> bool:
        """同步已启用索引器，并写入宿主站点目录。"""
        raw = self._request_json(f"{self._host}/api/v1/indexer")
        if not isinstance(raw, list):
            # Fix #7: 失败时记录日志
            logger.warning("Prowlarr索引器同步失败：未能获取索引器列表")
            return False
        helper = SitesHelper()
        current: list[dict[str, Any]] = []
        for item in raw:
            if not isinstance(item, dict) or not item.get("enable"):
                continue
            if item.get("privacy", "private") == "public":
                continue
            indexer_id = item.get("id")
            if indexer_id is None:
                continue
            category = self._category(indexer_id)
            # Fix #1: 空字典也跳过（原来只跳过 None，导致解析失败的索引器被错误注册）
            if not category:
                continue
            site = self._site(indexer_id, str(item.get("name") or indexer_id), category)
            current.append(site)
            helper.add_indexer(site["domain"], site)
        # Fix #9: 原子替换，避免搜索线程读到中间状态
        with self._lock:
            self._indexers = current
        logger.info("Prowlarr索引器同步完成，共注册 %d 个", len(current))
        return True

    def _category(self, indexer_id: int) -> Optional[dict[str, list[dict[str, Any]]]]:
        detail = self._request_json(f"{self._host}/api/v1/indexer/{indexer_id}")
        categories = (detail or {}).get("capabilities", {}).get("categories", [])
        result = {"movie": [], "tv": [], "music": []}
        has_xxx = False
        has_content = False
        for item in categories:
            if not isinstance(item, dict):
                continue
            try:
                category_id = int(item.get("id"))
            except (TypeError, ValueError):
                continue
            top = category_id // 1000 * 1000
            if top == 6000:
                has_xxx = True
            if top in (1000, 2000, 3000, 4000, 5000, 7000, 8000):
                has_content = True
            entry = {"id": category_id, "cat": item.get("name", ""), "desc": item.get("name", "")}
            if top == 2000:
                result["movie"].append(entry)
            elif top == 3000:
                result["music"].append(entry)
            elif top == 5000:
                result["tv"].append(entry)
        if has_xxx and not has_content:
            return None
        return {key: value for key, value in result.items() if value}

    def _site(self, indexer_id: int, name: str, category: dict[str, Any]) -> dict[str, Any]:
        domain = f"prowlarr_indexer.{indexer_id}"
        categories = [2000] if "movie" in category else []
        categories += [3000] if "music" in category else []
        categories += [5000] if "tv" in category else []
        rss = f"{self._host}/api/v1/indexer/{indexer_id}/newznab"
        return {
            "id": f"{self.plugin_name}-{name}", "name": f"{self.plugin_name}-{name}",
            "domain": domain, "url": f"{self._host}/api/v1/indexer/{indexer_id}",
            "public": False, "proxy": False, "category": category,
            "rss": f"{rss}?t=search&apikey={self._api_key}&q=&cat={','.join(map(str, categories))}&limit=30",
            "result_num": 100,
        }

    def _search(self, site: dict, keyword: str, mtype: MediaType | None, page: int) -> list[TorrentInfo]:
        if not keyword or not isinstance(site, dict) or not site.get("domain", "").startswith("prowlarr_indexer."):
            return []
        try:
            indexer_id = int(site["domain"].split(".")[-1])
        except (ValueError, IndexError):
            return []
        params: list[tuple[str, Any]] = [
            ("indexerIds", indexer_id),
            ("type", "search"),
            ("limit", 100),
            ("offset", page * 100),
        ]
        # MoviePilot 传入的 IMDb ID 格式为 tt1234567（含 tt 前缀）
        # Prowlarr /api/v1/search 的 imdbId 参数接受纯数字（不含 tt 前缀）
        if (
            mtype in (None, MediaType.MOVIE, MediaType.TV)
            and keyword.startswith("tt")
            and keyword[2:].isdigit()
        ):
            params.append(("imdbId", keyword[2:]))
        else:
            params.append(("query", keyword))
        categories = (
            [2000] if mtype == MediaType.MOVIE else
            [3000] if mtype == MediaType.MUSIC else
            [5000] if mtype == MediaType.TV else
            [2000, 3000, 5000]
        )
        for category in categories:
            params.append(("categories", category))
        raw = self._request_json(f"{self._host}/api/v1/search", params)
        if not isinstance(raw, list):
            return []
        return [self._torrent(item, site) for item in raw if isinstance(item, dict) and item.get("title")]

    @staticmethod
    def _torrent(item: dict, site: dict) -> TorrentInfo:
        # Fix #2: 根据实际 categories 列表判断媒体类型，而非硬编码 "movie"
        raw_cats = item.get("categories") or []
        cat_ids = []
        for c in raw_cats:
            if isinstance(c, dict):
                try:
                    cat_ids.append(int(c.get("id", 0)))
                except (TypeError, ValueError):
                    pass
            elif isinstance(c, int):
                cat_ids.append(c)
        category = None
        if cat_ids:
            tops = {cid // 1000 * 1000 for cid in cat_ids}
            if 2000 in tops:
                category = "movie"
            elif 3000 in tops:
                category = "music"
            elif 5000 in tops:
                category = "tv"
        return TorrentInfo(
            site_name=site.get("name"),
            title=item.get("title"),
            enclosure=item.get("downloadUrl") or item.get("magnetUrl"),
            page_url=item.get("infoUrl") or item.get("guid"),
            size=item.get("size") or 0,
            seeders=item.get("seeders") or 0,
            peers=item.get("leechers") or 0,
            pubdate=ProwlarrIndexer._date(item.get("publishDate")),
            description=item.get("description"),
            category=category,
        )

    @staticmethod
    def _date(value: Any) -> str | None:
        if not value:
            return None
        try:
            return datetime.fromisoformat(str(value).replace("Z", "+00:00")).strftime("%Y-%m-%d %H:%M:%S")
        except ValueError:
            return str(value)

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
            logger.error("Prowlarr索引器同步 Cron 表达式无效：%s — %s", self._cron, e)
            return []
        return [{"id": "ProwlarrIndexer.Sync", "name": "同步Prowlarr索引器",
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
            {"component": "VTextField", "props": {"model": "host", "label": "Prowlarr地址"}},
            {"component": "VTextField", "props": {"model": "api_key", "label": "API Key", "type": "password"}},
            # Fix #4: 补充代理开关
            {"component": "VSwitch", "props": {"model": "proxy", "label": "使用代理"}},
            {"component": "VTextField", "props": {"model": "cron", "label": "索引器同步 Cron"}},
        ]}], {"enabled": False, "host": "", "api_key": "", "proxy": False, "cron": self._cron}

    def get_page(self) -> list[dict]:
        with self._lock:
            count = len(self._indexers)
        return [{"component": "VAlert", "props": {"type": "info", "text": f"已注册 {count} 个Prowlarr索引器。"}}]

    def stop_service(self) -> None:
        with self._lock:
            self._indexers = []
        self._enabled = False
