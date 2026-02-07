# -*- coding: utf-8 -*-
"""
Prowlarr Indexer Plugin for MoviePilot V2

This plugin extends MoviePilot's search capabilities by integrating with Prowlarr,
a unified indexer manager that aggregates multiple torrent indexer sites.

Author: Claude (based on jtcymc's work)
License: MIT
"""
import copy
import traceback
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional, Tuple
from urllib.parse import quote_plus, urlencode

import pytz
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger

from app.core.config import settings
from app.core.context import TorrentInfo
from app.helper.sites import SitesHelper
from app.log import logger
from app.plugins import _PluginBase
from app.schemas import MediaType
from app.utils.http import RequestUtils
from app.utils.string import StringUtils


class ProwlarrIndexer(_PluginBase):
    """
    Prowlarr Indexer Plugin

    Integrates Prowlarr indexers into MoviePilot's search system,
    allowing users to search across all Prowlarr-configured indexers.
    """

    # Plugin metadata
    plugin_name = "Prowlarr索引器"
    plugin_desc = "扩展MoviePilot搜索功能，支持通过Prowlarr聚合多个索引站点进行资源检索"
    plugin_icon = "Prowlarr.png"
    plugin_version = "2.0"
    plugin_author = "Claude"
    author_url = "https://github.com/anthropics"
    plugin_config_prefix = "prowlarr_indexer_"
    plugin_order = 16
    auth_level = 1

    # Internal state
    _scheduler: Optional[BackgroundScheduler] = None
    _enabled: bool = False
    _host: str = ""
    _api_key: str = ""
    _proxy: bool = False
    _cron: str = "0 0 */24 * *"
    _onlyonce: bool = False
    _indexers: List[Dict[str, Any]] = []
    _sites_helper: Optional[SitesHelper] = None

    # Domain identifier for registered indexers
    DOMAIN_PREFIX = "prowlarr.indexer"

    def init_plugin(self, config: dict = None) -> None:
        """
        Initialize the plugin with user configuration.

        Args:
            config: Plugin configuration dictionary
        """
        self._sites_helper = SitesHelper()

        if config:
            self._enabled = config.get("enabled", False)
            self._host = self._normalize_host(config.get("host", ""))
            self._api_key = config.get("api_key", "")
            self._proxy = config.get("proxy", False)
            self._cron = config.get("cron") or "0 0 */24 * *"
            self._onlyonce = config.get("onlyonce", False)

        # Stop any existing scheduler
        self.stop_service()

        if not self._enabled:
            return

        # Initialize scheduler for periodic indexer updates
        self._scheduler = BackgroundScheduler(timezone=settings.TZ)

        if self._cron:
            logger.info(f"[{self.plugin_name}] 索引更新服务启动，周期: {self._cron}")
            self._scheduler.add_job(
                self._refresh_indexers,
                CronTrigger.from_crontab(self._cron)
            )

        if self._onlyonce:
            logger.info(f"[{self.plugin_name}] 立即执行一次索引器同步")
            self._scheduler.add_job(
                self._refresh_indexers,
                'date',
                run_date=datetime.now(tz=pytz.timezone(settings.TZ)) + timedelta(seconds=3)
            )
            self._onlyonce = False
            self._save_config()

        if self._cron or self._onlyonce:
            self._scheduler.print_jobs()
            self._scheduler.start()

        # Initial indexer load
        if not self._indexers:
            self._refresh_indexers()

        # Register indexers with MoviePilot
        self._register_indexers()

    def _normalize_host(self, host: str) -> str:
        """Normalize the host URL format."""
        if not host:
            return ""
        if not host.startswith(('http://', 'https://')):
            host = f"http://{host}"
        return host.rstrip('/')

    def _save_config(self) -> None:
        """Save current configuration."""
        self.update_config({
            "enabled": self._enabled,
            "host": self._host,
            "api_key": self._api_key,
            "proxy": self._proxy,
            "cron": self._cron,
            "onlyonce": False,
        })

    def _refresh_indexers(self) -> bool:
        """
        Fetch available indexers from Prowlarr.

        Returns:
            True if indexers were successfully retrieved
        """
        if not self._api_key or not self._host:
            logger.warning(f"[{self.plugin_name}] 未配置Prowlarr地址或API Key")
            return False

        self._indexers = self._fetch_indexers()
        self._register_indexers()
        return len(self._indexers) > 0

    def _fetch_indexers(self) -> List[Dict[str, Any]]:
        """
        Fetch indexer list from Prowlarr API.

        Returns:
            List of indexer configurations
        """
        headers = {
            "Content-Type": "application/json",
            "User-Agent": settings.USER_AGENT,
            "X-Api-Key": self._api_key,
            "Accept": "application/json"
        }

        url = f"{self._host}/api/v1/indexerstats"

        try:
            response = RequestUtils(headers=headers).get_res(url)
            if not response:
                logger.warning(f"[{self.plugin_name}] 获取索引器列表无响应")
                return []

            data = response.json()
            if not data or "indexers" not in data:
                logger.warning(f"[{self.plugin_name}] 返回数据格式异常")
                return []

            indexers_raw = data.get("indexers", [])
            if not indexers_raw:
                logger.info(f"[{self.plugin_name}] Prowlarr中未配置任何索引器")
                return []

            indexers = []
            for item in indexers_raw:
                indexer_id = item.get("indexerId")
                indexer_name = item.get("indexerName")
                if not indexer_id or not indexer_name:
                    continue

                indexers.append({
                    "id": f"Prowlarr-{indexer_name}",
                    "name": f"Prowlarr-{indexer_name}",
                    "url": f"{self._host}/api/v1/indexer/{indexer_id}",
                    "domain": f"{self.DOMAIN_PREFIX}.{indexer_id}",
                    "public": True,
                    "proxy": self._proxy,
                    "indexer_id": indexer_id,
                })

            logger.info(f"[{self.plugin_name}] 获取到 {len(indexers)} 个索引器")
            return indexers

        except Exception as e:
            logger.error(f"[{self.plugin_name}] 获取索引器列表失败: {e}")
            return []

    def _register_indexers(self) -> None:
        """Register fetched indexers with MoviePilot's site system."""
        for indexer in self._indexers:
            domain = indexer.get("domain", "")
            if not self._sites_helper.get_indexer(domain):
                self._sites_helper.add_indexer(domain, copy.deepcopy(indexer))

    def get_state(self) -> bool:
        """Return plugin enabled state."""
        return self._enabled

    def stop_service(self) -> None:
        """Stop the scheduler and cleanup resources."""
        try:
            if self._scheduler:
                self._scheduler.remove_all_jobs()
                if self._scheduler.running:
                    self._scheduler.shutdown()
                self._scheduler = None
        except Exception as e:
            logger.error(f"[{self.plugin_name}] 停止服务失败: {e}")

    def get_module(self) -> Dict[str, Any]:
        """
        Register search method to intercept MoviePilot searches.

        This is the key integration point that allows this plugin
        to handle search requests for Prowlarr indexers.
        """
        return {
            "search_torrents": self.search_torrents,
        }

    def search_torrents(
        self,
        site: dict,
        keyword: str,
        mtype: Optional[MediaType] = None,
        page: Optional[int] = 0
    ) -> List[TorrentInfo]:
        """
        Search for torrents using Prowlarr API.

        Args:
            site: Site configuration from MoviePilot
            keyword: Search keyword
            mtype: Media type (Movie/TV)
            page: Page number for pagination

        Returns:
            List of TorrentInfo objects matching the search
        """
        results = []

        if not site or not keyword:
            return results

        # Only handle sites registered by this plugin
        site_name = site.get("name", "")
        if not site_name.startswith("Prowlarr-"):
            return results

        # Extract indexer ID from domain
        domain = StringUtils.get_url_domain(site.get("domain", ""))
        indexer_id = domain.split(".")[-1] if domain else ""
        if not indexer_id:
            logger.warning(f"[{self.plugin_name}] 无法提取索引器ID: {site_name}")
            return results

        headers = {
            "Content-Type": "application/json",
            "User-Agent": settings.USER_AGENT,
            "X-Api-Key": self._api_key,
            "Accept": "application/json"
        }

        # Build category filter based on media type
        categories = self._get_categories(mtype)

        try:
            logger.info(f"[{self.plugin_name}] 开始搜索: {site_name}, 关键词: {keyword}")

            # Build query parameters
            params = [
                ("query", keyword),
                ("indexerIds", indexer_id),
                ("type", "search"),
                ("limit", 150),
                ("offset", page * 150 if page else 0),
            ] + [("categories", cat) for cat in categories]

            query_string = urlencode(params, quote_via=quote_plus)
            api_url = f"{self._host}/api/v1/search?{query_string}"

            response = RequestUtils(headers=headers).get_res(api_url)
            if not response:
                logger.warning(f"[{self.plugin_name}] {site_name} 搜索无响应")
                return results

            data = response.json()
            if not isinstance(data, list):
                logger.warning(f"[{self.plugin_name}] {site_name} 返回数据格式异常")
                return results

            for entry in data:
                torrent = TorrentInfo(
                    title=entry.get("title"),
                    enclosure=entry.get("downloadUrl") or entry.get("magnetUrl"),
                    description=entry.get("sortTitle"),
                    size=entry.get("size"),
                    seeders=entry.get("seeders"),
                    peers=entry.get("leechers"),
                    pubdate=entry.get("publishDate"),
                    page_url=entry.get("infoUrl") or entry.get("guid"),
                    site_name=site_name,
                )
                results.append(torrent)

            logger.info(f"[{self.plugin_name}] {site_name} 返回 {len(results)} 条结果")

        except Exception as e:
            logger.error(f"[{self.plugin_name}] 搜索出错: {e}\n{traceback.format_exc()}")

        return results

    @staticmethod
    def _get_categories(mtype: Optional[MediaType]) -> List[int]:
        """
        Map MediaType to Prowlarr/Newznab category IDs.

        Args:
            mtype: MoviePilot media type

        Returns:
            List of category IDs (2000=Movies, 5000=TV)
        """
        if not mtype:
            return [2000, 5000]
        elif mtype == MediaType.MOVIE:
            return [2000]
        elif mtype == MediaType.TV:
            return [5000]
        return [2000, 5000]

    def get_api(self) -> List[Dict[str, Any]]:
        """Return empty API list - no custom endpoints needed."""
        return []

    def get_form(self) -> Tuple[List[dict], Dict[str, Any]]:
        """
        Build the plugin configuration form UI.

        Returns:
            Tuple of (form structure, default values)
        """
        return [
            {
                'component': 'VForm',
                'content': [
                    {
                        'component': 'VRow',
                        'content': [
                            {
                                'component': 'VCol',
                                'props': {'cols': 12, 'md': 4},
                                'content': [{
                                    'component': 'VSwitch',
                                    'props': {
                                        'model': 'enabled',
                                        'label': '启用插件',
                                    }
                                }]
                            },
                            {
                                'component': 'VCol',
                                'props': {'cols': 12, 'md': 4},
                                'content': [{
                                    'component': 'VSwitch',
                                    'props': {
                                        'model': 'proxy',
                                        'label': '使用代理',
                                    }
                                }]
                            },
                            {
                                'component': 'VCol',
                                'props': {'cols': 12, 'md': 4},
                                'content': [{
                                    'component': 'VSwitch',
                                    'props': {
                                        'model': 'onlyonce',
                                        'label': '立即同步一次',
                                    }
                                }]
                            },
                        ]
                    },
                    {
                        'component': 'VRow',
                        'content': [
                            {
                                'component': 'VCol',
                                'props': {'cols': 12, 'md': 6},
                                'content': [{
                                    'component': 'VTextField',
                                    'props': {
                                        'model': 'host',
                                        'label': 'Prowlarr地址',
                                        'placeholder': 'http://127.0.0.1:9696',
                                        'hint': 'Prowlarr访问地址，如: http://192.168.1.100:9696'
                                    }
                                }]
                            },
                            {
                                'component': 'VCol',
                                'props': {'cols': 12, 'md': 6},
                                'content': [{
                                    'component': 'VTextField',
                                    'props': {
                                        'model': 'api_key',
                                        'label': 'API Key',
                                        'placeholder': '',
                                        'hint': '在 Prowlarr -> Settings -> General -> API Key 中获取'
                                    }
                                }]
                            },
                        ]
                    },
                    {
                        'component': 'VRow',
                        'content': [
                            {
                                'component': 'VCol',
                                'props': {'cols': 12, 'md': 6},
                                'content': [{
                                    'component': 'VTextField',
                                    'props': {
                                        'model': 'cron',
                                        'label': '索引器同步周期',
                                        'placeholder': '0 0 */24 * *',
                                        'hint': '定期从Prowlarr同步索引器列表，5位cron表达式'
                                    }
                                }]
                            },
                        ]
                    },
                    {
                        'component': 'VRow',
                        'content': [
                            {
                                'component': 'VCol',
                                'props': {'cols': 12},
                                'content': [{
                                    'component': 'VAlert',
                                    'props': {
                                        'type': 'success',
                                        'variant': 'tonal',
                                        'text': '使用说明：'
                                                '1. 在Prowlarr中添加并配置好索引器；'
                                                '2. 填写Prowlarr地址和API Key并启用插件；'
                                                '3. 点击"立即同步一次"获取索引器列表；'
                                                '4. 前往 设置->搜索->索引站点 勾选需要启用的Prowlarr索引器；'
                                                '5. 搜索时将自动使用已启用的Prowlarr索引器'
                                    }
                                }]
                            }
                        ]
                    },
                    {
                        'component': 'VRow',
                        'content': [
                            {
                                'component': 'VCol',
                                'props': {'cols': 12},
                                'content': [{
                                    'component': 'VAlert',
                                    'props': {
                                        'type': 'warning',
                                        'variant': 'tonal',
                                        'text': '注意：无需在"站点管理"中手动添加站点！插件会自动注册索引器到搜索系统。'
                                    }
                                }]
                            }
                        ]
                    }
                ]
            }
        ], {
            "enabled": False,
            "host": "",
            "api_key": "",
            "proxy": False,
            "cron": "0 0 */24 * *",
            "onlyonce": False,
        }

    def get_page(self) -> List[dict]:
        """
        Build the plugin data display page.

        Shows all registered Prowlarr indexers in a table.
        """
        if not self._indexers:
            self._refresh_indexers()

        if not self._indexers:
            return [{
                'component': 'VRow',
                'content': [{
                    'component': 'VCol',
                    'props': {'cols': 12},
                    'content': [{
                        'component': 'VAlert',
                        'props': {
                            'type': 'warning',
                            'variant': 'tonal',
                            'text': '未获取到任何索引器，请检查Prowlarr配置'
                        }
                    }]
                }]
            }]

        table_rows = []
        for indexer in self._indexers:
            table_rows.append({
                'component': 'tr',
                'content': [
                    {'component': 'td', 'text': indexer.get("name")},
                    {'component': 'td', 'text': f"https://{indexer.get('domain')}"},
                    {'component': 'td', 'text': str(indexer.get("indexer_id"))},
                ]
            })

        return [
            {
                'component': 'VRow',
                'content': [{
                    'component': 'VCol',
                    'props': {'cols': 12},
                    'content': [{
                        'component': 'VTable',
                        'props': {'hover': True},
                        'content': [
                            {
                                'component': 'thead',
                                'content': [{
                                    'component': 'tr',
                                    'content': [
                                        {'component': 'th', 'props': {'class': 'text-start ps-4'}, 'text': '索引器名称'},
                                        {'component': 'th', 'props': {'class': 'text-start ps-4'}, 'text': '站点域名'},
                                        {'component': 'th', 'props': {'class': 'text-start ps-4'}, 'text': '索引器ID'},
                                    ]
                                }]
                            },
                            {
                                'component': 'tbody',
                                'content': table_rows
                            }
                        ]
                    }]
                }]
            }
        ]
