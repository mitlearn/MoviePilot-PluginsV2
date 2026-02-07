# -*- coding: utf-8 -*-
"""
Jackett Indexer Plugin for MoviePilot V2

This plugin extends MoviePilot's search capabilities by integrating with Jackett,
a proxy server that translates queries to tracker-site-specific requests.

Author: Claude (based on jtcymc's work)
License: MIT
"""
import copy
import traceback
import xml.dom.minidom
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional, Tuple
from urllib.parse import quote_plus, urlencode

import pytz
import requests
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger

from app.core.config import settings
from app.core.context import TorrentInfo
from app.helper.sites import SitesHelper
from app.log import logger
from app.plugins import _PluginBase
from app.schemas import MediaType
from app.utils.dom import DomUtils
from app.utils.http import RequestUtils
from app.utils.string import StringUtils


class JackettIndexer(_PluginBase):
    """
    Jackett Indexer Plugin

    Integrates Jackett indexers into MoviePilot's search system,
    allowing users to search across all Jackett-configured indexers
    using the Torznab API format.
    """

    # Plugin metadata
    plugin_name = "Jackett索引器"
    plugin_desc = "扩展MoviePilot搜索功能，支持通过Jackett聚合多个索引站点进行资源检索"
    plugin_icon = "Jackett_A.png"
    plugin_version = "2.2"
    plugin_author = "Claude"
    author_url = "https://github.com/anthropics"
    plugin_config_prefix = "jackett_indexer_"
    plugin_order = 15
    auth_level = 1

    # Internal state
    _scheduler: Optional[BackgroundScheduler] = None
    _enabled: bool = False
    _host: str = ""
    _api_key: str = ""
    _password: str = ""
    _proxy: bool = False
    _cron: str = "0 0 */24 * *"
    _onlyonce: bool = False
    _indexers: List[Dict[str, Any]] = []
    _sites_helper: Optional[SitesHelper] = None

    # Domain identifier for registered indexers
    DOMAIN_PREFIX = "jackett.indexer"

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
            self._password = config.get("password", "")
            self._proxy = config.get("proxy", False)
            self._cron = config.get("cron") or "0 0 */24 * *"
            self._onlyonce = config.get("onlyonce", False)

        # Stop any existing scheduler
        self.stop_service()

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

        # Initial indexer load and register
        if not self._indexers:
            self._refresh_indexers()

        # Register indexers with MoviePilot (always, regardless of _enabled)
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
            "password": self._password,
            "proxy": self._proxy,
            "cron": self._cron,
            "onlyonce": False,
        })

    def _refresh_indexers(self) -> bool:
        """
        Fetch available indexers from Jackett.

        Returns:
            True if indexers were successfully retrieved
        """
        if not self._api_key or not self._host:
            logger.warning(f"[{self.plugin_name}] 未配置Jackett地址或API Key")
            return False

        self._indexers = self._fetch_indexers()
        self._register_indexers()
        return len(self._indexers) > 0

    def _fetch_indexers(self) -> List[Dict[str, Any]]:
        """
        Fetch indexer list from Jackett API.

        Returns:
            List of indexer configurations
        """
        headers = {
            "Content-Type": "application/json",
            "User-Agent": settings.USER_AGENT,
            "Accept": "application/json"
        }

        # Jackett may require password authentication
        cookie = self._authenticate()

        url = f"{self._host}/api/v2.0/indexers?configured=true"

        try:
            response = RequestUtils(
                headers=headers,
                cookies=cookie
            ).get_res(
                url,
                proxies=settings.PROXY if self._proxy else None
            )

            if not response or not response.json():
                logger.warning(f"[{self.plugin_name}] 获取索引器列表无响应")
                return []

            indexers_raw = response.json()
            indexers = []

            for item in indexers_raw:
                indexer_id = item.get("id")
                indexer_name = item.get("name")
                if not indexer_id or not indexer_name:
                    continue

                indexers.append({
                    "id": f"Jackett-{indexer_name}",
                    "name": f"Jackett-{indexer_name}",
                    "url": f"{self._host}/api/v2.0/indexers/{indexer_id}/results/torznab/",
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

    def _authenticate(self) -> Optional[dict]:
        """
        Authenticate with Jackett if password is configured.

        Returns:
            Cookie dictionary if authentication successful, None otherwise
        """
        if not self._password:
            return None

        headers = {
            "Content-Type": "application/x-www-form-urlencoded",
            "User-Agent": settings.USER_AGENT,
        }

        session = requests.session()
        login_url = f"{self._host}/UI/Dashboard"
        login_data = {"password": self._password}

        try:
            RequestUtils(headers=headers, session=session).post_res(
                url=login_url,
                data=login_data,
                params=login_data,
                proxies=settings.PROXY if self._proxy else None
            )

            if session.cookies:
                return session.cookies.get_dict()

        except Exception as e:
            logger.warning(f"[{self.plugin_name}] 认证失败: {e}")

        return None

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
        to handle search requests for Jackett indexers.
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
        Search for torrents using Jackett Torznab API.

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
        if not site_name.startswith("Jackett-"):
            return results

        # Extract indexer ID from domain
        domain = StringUtils.get_url_domain(site.get("domain", ""))
        if not domain:
            logger.warning(f"[{self.plugin_name}] 无法解析站点域名")
            return results

        indexer_id = domain.split(".")[-1]
        categories = self._get_categories(mtype)

        try:
            logger.info(f"[{self.plugin_name}] 开始搜索: {site_name}, 关键词: {keyword}")

            # Build Torznab query parameters
            params = {
                "apikey": self._api_key,
                "t": "search",
                "q": keyword,
                "cat": ",".join(map(str, categories))
            }
            query_string = urlencode(params, quote_via=quote_plus)
            api_url = f"{self._host}/api/v2.0/indexers/{indexer_id}/results/torznab/?{query_string}"

            # Parse Torznab XML response
            results = self._parse_torznab_response(api_url, site_name)

            if results:
                logger.info(f"[{self.plugin_name}] {site_name} 返回 {len(results)} 条结果")
            else:
                logger.info(f"[{self.plugin_name}] {site_name} 未找到匹配结果")

        except Exception as e:
            logger.error(f"[{self.plugin_name}] 搜索出错: {e}\n{traceback.format_exc()}")

        return results

    def _parse_torznab_response(self, url: str, site_name: str) -> List[TorrentInfo]:
        """
        Parse Torznab XML response into TorrentInfo objects.

        Args:
            url: Torznab API URL
            site_name: Name of the site for attribution

        Returns:
            List of parsed TorrentInfo objects
        """
        torrents = []

        try:
            response = RequestUtils(timeout=60).get_res(
                url,
                proxies=settings.PROXY if self._proxy else None
            )

            if not response or not response.text:
                return []

            xml_text = response.text

            # Parse XML
            dom_tree = xml.dom.minidom.parseString(xml_text)
            root_node = dom_tree.documentElement
            items = root_node.getElementsByTagName("item")

            for item in items:
                try:
                    # Extract basic fields
                    title = DomUtils.tag_value(item, "title", default="")
                    if not title:
                        continue

                    enclosure = DomUtils.tag_value(item, "enclosure", "url", default="")
                    if not enclosure:
                        continue

                    description = DomUtils.tag_value(item, "description", default="")
                    size = DomUtils.tag_value(item, "size", default=0)
                    page_url = DomUtils.tag_value(item, "comments", default="")

                    pubdate = DomUtils.tag_value(item, "pubDate", default="")
                    if pubdate:
                        pubdate = StringUtils.unify_datetime_str(pubdate)

                    # Extract torznab attributes
                    seeders = 0
                    peers = 0
                    imdbid = ""
                    downloadvolumefactor = 1.0
                    uploadvolumefactor = 1.0

                    torznab_attrs = item.getElementsByTagName("torznab:attr")
                    for attr in torznab_attrs:
                        name = attr.getAttribute('name')
                        value = attr.getAttribute('value')

                        if name == "seeders":
                            seeders = int(value) if value else 0
                        elif name == "peers":
                            peers = int(value) if value else 0
                        elif name == "downloadvolumefactor":
                            downloadvolumefactor = float(value) if value else 1.0
                        elif name == "uploadvolumefactor":
                            uploadvolumefactor = float(value) if value else 1.0
                        elif name == "imdbid":
                            imdbid = value

                    # Create TorrentInfo object
                    torrent = TorrentInfo(
                        title=title,
                        enclosure=enclosure,
                        description=description,
                        size=size,
                        seeders=seeders,
                        peers=peers,
                        page_url=page_url,
                        pubdate=pubdate,
                        imdbid=imdbid,
                        site_name=site_name,
                        downloadvolumefactor=downloadvolumefactor,
                        uploadvolumefactor=uploadvolumefactor,
                    )
                    torrents.append(torrent)

                except Exception as e:
                    logger.debug(f"[{self.plugin_name}] 解析单条结果失败: {e}")
                    continue

        except Exception as e:
            logger.error(f"[{self.plugin_name}] 解析Torznab响应失败: {e}")

        return torrents

    @staticmethod
    def _get_categories(mtype: Optional[MediaType]) -> List[int]:
        """
        Map MediaType to Torznab category IDs.

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
                                        'label': 'Jackett地址',
                                        'placeholder': 'http://127.0.0.1:9117',
                                        'hint': 'Jackett访问地址，如: http://192.168.1.100:9117'
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
                                        'hint': '在Jackett管理界面右上角复制API Key'
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
                                        'model': 'password',
                                        'label': '管理密码',
                                        'placeholder': '',
                                        'hint': 'Jackett管理密码（如已设置）',
                                        'type': 'password'
                                    }
                                }]
                            },
                            {
                                'component': 'VCol',
                                'props': {'cols': 12, 'md': 6},
                                'content': [{
                                    'component': 'VTextField',
                                    'props': {
                                        'model': 'cron',
                                        'label': '索引器同步周期',
                                        'placeholder': '0 0 */24 * *',
                                        'hint': '定期从Jackett同步索引器列表，5位cron表达式'
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
                                                '1. 在Jackett中添加并配置好索引器；'
                                                '2. 填写Jackett地址、API Key和管理密码（如已设置）；'
                                                '3. 启用插件并点击"立即同步一次"获取索引器列表；'
                                                '4. 前往 设置->搜索->索引站点 勾选需要启用的Jackett索引器；'
                                                '5. 搜索时将自动使用已启用的Jackett索引器'
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
            "password": "",
            "proxy": False,
            "cron": "0 0 */24 * *",
            "onlyonce": False,
        }

    def get_page(self) -> List[dict]:
        """
        Build the plugin data display page.

        Shows all registered Jackett indexers in a table.
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
                            'text': '未获取到任何索引器，请检查Jackett配置'
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
