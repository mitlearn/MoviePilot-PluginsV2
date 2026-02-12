# -*- coding: utf-8 -*-
"""
ProwlarrIndexer Plugin for MoviePilot

This plugin integrates Prowlarr indexer search functionality into MoviePilot.
It allows searching across all indexers configured in Prowlarr through a unified interface.

Version: 0.1.0
Author: Claude
"""

import copy
import re
import traceback
from typing import List, Dict, Optional, Any, Tuple
from datetime import datetime, timedelta
from urllib.parse import urlencode

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger

from app.core.context import MediaInfo, TorrentInfo
from app.core.metainfo import MetaInfo
from app.helper.sites import SitesHelper
from app.log import logger
from app.plugins import _PluginBase
from app.schemas.types import MediaType
from app.utils.http import RequestUtils


class ProwlarrIndexer(_PluginBase):
    """
    Prowlarr Indexer Plugin

    Provides torrent search functionality through Prowlarr API.
    Registers all configured Prowlarr indexers as MoviePilot sites.
    """

    # Plugin metadata
    plugin_name = "Prowlarr索引器"
    plugin_desc = "集成Prowlarr索引器搜索，支持多站点统一搜索。"
    plugin_icon = "Prowlarr.png"
    plugin_version = "0.1.8"
    plugin_author = "Claude"
    author_url = "https://github.com"
    plugin_config_prefix = "prowlarrindexer_"
    plugin_order = 10
    auth_level = 1

    # Private attributes
    _enabled: bool = False
    _host: str = ""
    _api_key: str = ""
    _proxy: bool = False
    _cron: str = "0 0 */6 * *"  # Sync indexers every 6 hours
    _onlyonce: bool = False
    _indexers: List[Dict[str, Any]] = []
    _scheduler: Optional[BackgroundScheduler] = None
    _sites_helper: Optional[SitesHelper] = None
    _last_update: Optional[datetime] = None

    # Domain prefix for indexer identification
    DOMAIN_PREFIX = "prowlarr"

    def init_plugin(self, config: dict = None):
        """
        Initialize the plugin with user configuration.

        Args:
            config: Configuration dictionary from user settings
        """
        logger.info(f"【{self.plugin_name}】开始初始化插件...")

        # Stop existing services
        self.stop_service()

        # Load configuration
        if config:
            self._enabled = config.get("enabled", False)
            self._host = config.get("host", "").rstrip("/")
            self._api_key = config.get("api_key", "")
            self._proxy = config.get("proxy", False)
            self._cron = config.get("cron", "0 0 */6 * *")
            self._onlyonce = config.get("onlyonce", False)

        # Validate configuration
        if not self._enabled:
            logger.info(f"【{self.plugin_name}】插件未启用")
            return

        if not self._host or not self._api_key:
            logger.error(f"【{self.plugin_name}】配置错误：缺少服务器地址或API密钥")
            return

        # Validate host format
        if not self._host.startswith(("http://", "https://")):
            logger.error(f"【{self.plugin_name}】配置错误：服务器地址必须以 http:// 或 https:// 开头")
            return

        # Initialize sites helper
        self._sites_helper = SitesHelper()

        # Setup scheduler for periodic sync
        if self._cron:
            try:
                self._scheduler = BackgroundScheduler(timezone="Asia/Shanghai")
                self._scheduler.add_job(
                    func=self._sync_indexers,
                    trigger=CronTrigger.from_crontab(self._cron),
                    name=f"{self.plugin_name}定时同步"
                )
                self._scheduler.start()
                logger.info(f"【{self.plugin_name}】定时同步任务已启动，周期：{self._cron}")
            except Exception as e:
                logger.error(f"【{self.plugin_name}】定时任务创建失败：{str(e)}")

        # Handle run once flag
        if self._onlyonce:
            self._onlyonce = False
            self.update_config({
                **config,
                "onlyonce": False
            })
            logger.info(f"【{self.plugin_name}】立即运行完成，已关闭立即运行标志")

        # Fetch and register indexers
        if not self._indexers:
            logger.info(f"【{self.plugin_name}】开始获取索引器...")
            self._fetch_and_build_indexers()

        # Register indexers to site management
        registered_count = 0
        for indexer in self._indexers:
            domain = indexer.get("domain", "")
            site_info = self._sites_helper.get_indexer(domain)
            if not site_info:
                new_indexer = copy.deepcopy(indexer)
                self._sites_helper.add_indexer(domain, new_indexer)
                logger.info(f"【{self.plugin_name}】✅ 成功添加到站点管理：{indexer.get('name')} (domain: {domain})")
                registered_count += 1
            else:
                logger.debug(f"【{self.plugin_name}】站点已存在，跳过：{indexer.get('name')} (domain: {domain})")

        logger.info(f"【{self.plugin_name}】插件初始化完成，总计 {len(self._indexers)} 个索引器，新增 {registered_count} 个")

    def _fetch_and_build_indexers(self) -> bool:
        """
        Fetch indexers from Prowlarr and build indexer dictionaries.

        Returns:
            True if successful, False otherwise
        """
        try:
            indexers = self._get_indexers_from_prowlarr()
            if not indexers:
                logger.warning(f"【{self.plugin_name}】未获取到索引器列表")
                return False

            # Build indexer dicts
            self._indexers = []
            for indexer_data in indexers:
                try:
                    indexer_dict = self._build_indexer_dict(indexer_data)
                    self._indexers.append(indexer_dict)
                except Exception as e:
                    logger.error(f"【{self.plugin_name}】构建索引器失败：{str(e)}")
                    continue

            logger.info(f"【{self.plugin_name}】成功获取 {len(self._indexers)} 个索引器")
            return True

        except Exception as e:
            logger.error(f"【{self.plugin_name}】获取索引器异常：{str(e)}\n{traceback.format_exc()}")
            return False

    def _sync_indexers(self) -> bool:
        """
        Periodic sync: fetch indexers and register new ones.

        Returns:
            True if sync successful, False otherwise
        """
        try:
            # Fetch indexers from Prowlarr
            if not self._fetch_and_build_indexers():
                return False

            # Register indexers to site management
            registered_count = 0
            for indexer in self._indexers:
                domain = indexer.get("domain", "")
                site_info = self._sites_helper.get_indexer(domain)
                if not site_info:
                    new_indexer = copy.deepcopy(indexer)
                    self._sites_helper.add_indexer(domain, new_indexer)
                    logger.info(f"【{self.plugin_name}】✅ 成功添加到站点管理：{indexer.get('name')} (domain: {domain})")
                    registered_count += 1

            self._last_update = datetime.now()
            logger.info(f"【{self.plugin_name}】索引器同步完成，总计 {len(self._indexers)} 个，新增 {registered_count} 个")
            return True

        except Exception as e:
            logger.error(f"【{self.plugin_name}】同步索引器异常：{str(e)}\n{traceback.format_exc()}")
            return False

    def _get_indexers_from_prowlarr(self) -> List[Dict[str, Any]]:
        """
        Fetch indexer list from Prowlarr API.

        Returns:
            List of indexer dictionaries from Prowlarr API
        """
        try:
            url = f"{self._host}/api/v1/indexer"
            headers = {
                "X-Api-Key": self._api_key,
                "Content-Type": "application/json",
                "Accept": "application/json"
            }

            logger.debug(f"【{self.plugin_name}】正在获取索引器列表：{url}")

            response = RequestUtils(
                headers=headers,
                proxies=self._proxy
            ).get_res(url, timeout=30)

            if not response:
                logger.error(f"【{self.plugin_name}】API请求失败：无响应")
                return []

            if response.status_code != 200:
                logger.error(f"【{self.plugin_name}】API请求失败：HTTP {response.status_code}")
                logger.debug(f"【{self.plugin_name}】响应内容：{response.text}")
                return []

            try:
                indexers = response.json()
            except Exception as e:
                logger.error(f"【{self.plugin_name}】解析JSON失败：{str(e)}")
                logger.debug(f"【{self.plugin_name}】响应内容：{response.text[:500]}")
                return []

            if not isinstance(indexers, list):
                logger.error(f"【{self.plugin_name}】API返回格式错误：期望列表，得到 {type(indexers)}")
                return []

            # Filter enabled indexers only
            enabled_indexers = [idx for idx in indexers if idx.get("enable", False)]
            logger.info(f"【{self.plugin_name}】获取到 {len(enabled_indexers)} 个启用的索引器（总计 {len(indexers)} 个）")

            return enabled_indexers

        except Exception as e:
            logger.error(f"【{self.plugin_name}】获取索引器列表异常：{str(e)}\n{traceback.format_exc()}")
            return []

    def _build_indexer_dict(self, indexer: Dict[str, Any]) -> Dict[str, Any]:
        """
        Build MoviePilot indexer dictionary from Prowlarr indexer data.

        Args:
            indexer: Prowlarr indexer dictionary

        Returns:
            MoviePilot compatible indexer dictionary
        """
        indexer_id = indexer.get("id")
        indexer_name = indexer.get("name", f"Indexer{indexer_id}")

        # Sanitize indexer_name for domain (remove spaces and special chars, convert to lowercase)
        indexer_name_slug = re.sub(r'[^a-z0-9]+', '-', indexer_name.lower()).strip('-')

        # Build domain identifier with http:// prefix for MoviePilot compatibility
        # Format: http://prowlarr.{indexer_name_slug}.indexer
        domain = f"http://{self.DOMAIN_PREFIX}.{indexer_name_slug}.indexer"

        # Build indexer dictionary with necessary fields for MoviePilot compatibility
        return {
            # Basic identification - use indexer_name for better display
            "id": f"{self.plugin_name}-{indexer_name}",
            "name": f"{self.plugin_name}-{indexer_name}",
            "url": f"{self._host.rstrip('/')}/api/v1/indexer/{indexer_id}",
            "domain": domain,

            # Store original data for display and search
            "indexer_id": indexer_id,
            "indexer_name": indexer_name,

            # Site properties
            "public": True,
            "proxy": self._proxy,

            # Essential flags to prevent MoviePilot from treating this as a regular site
            "render": False,
            "chrome": False,
            "cookie": "",
            "ua": "",
        }

    def get_state(self) -> bool:
        """
        Get plugin enabled state.

        Returns:
            True if plugin is enabled, False otherwise
        """
        return self._enabled

    def stop_service(self):
        """
        Stop plugin services and cleanup resources.
        """
        try:
            # Stop scheduler
            if self._scheduler:
                try:
                    self._scheduler.remove_all_jobs()
                    if self._scheduler.running:
                        self._scheduler.shutdown(wait=False)
                    self._scheduler = None
                    logger.info(f"【{self.plugin_name}】定时任务已停止")
                except Exception as e:
                    logger.error(f"【{self.plugin_name}】停止定时任务失败：{str(e)}")

            # Note: We intentionally do NOT unregister indexers from site management
            # This allows sites to persist between plugin restarts and MoviePilot reboots
            # If you need to remove sites, disable them manually in the site management UI
            if self._indexers:
                logger.info(f"【{self.plugin_name}】服务已停止，{len(self._indexers)} 个索引器保留在站点管理中")
                self._indexers = []

        except Exception as e:
            logger.error(f"【{self.plugin_name}】停止服务异常：{str(e)}")

    def get_module(self) -> Dict[str, Any]:
        """
        Declare module methods to hijack system search.

        Returns:
            Dictionary mapping method names to plugin methods
        """
        logger.info(f"【{self.plugin_name}】get_module 被调用，注册 search_torrents 方法")
        return {
            "search_torrents": self.search_torrents,
        }

    def search_torrents(
        self,
        site: Dict[str, Any],
        keyword: str,
        mtype: Optional[MediaType] = None,
        page: Optional[int] = 0
    ) -> List[TorrentInfo]:
        """
        Search torrents through Prowlarr API.

        This method is called by MoviePilot's module hijacking system.

        Args:
            site: Site/indexer information dictionary
            keyword: Search keyword
            mtype: Media type (MOVIE or TV)
            page: Page number for pagination

        Returns:
            List of TorrentInfo objects
        """
        results = []

        # Debug: Log method call with all parameters
        logger.debug(f"【{self.plugin_name}】search_torrents 被调用：site={site}, keyword={keyword}")

        # Validate inputs first (matching reference implementation pattern)
        if not site:
            logger.debug(f"【{self.plugin_name}】站点参数为空，返回空结果")
            return results

        if not keyword:
            logger.debug(f"【{self.plugin_name}】关键词为空，返回空结果")
            return results

        # Get site name for logging
        site_name = site.get("name", "Unknown")
        logger.debug(f"【{self.plugin_name}】站点名称：{site_name}, plugin_name: {self.plugin_name}")

        # Check if this site belongs to our plugin (matching reference implementation)
        site_prefix = site.get("name", "").split("-")[0]
        logger.debug(f"【{self.plugin_name}】站点前缀：{site_prefix}, 是否匹配：{site_prefix == self.plugin_name}")

        if site_prefix != self.plugin_name:
            logger.debug(f"【{self.plugin_name}】站点不属于本插件，返回空结果")
            return results

        try:
            # Log that method was called
            logger.info(f"【{self.plugin_name}】开始搜索：站点={site_name}, 关键词={keyword}, 类型={mtype}, 页码={page}")

            # Extract indexer ID from site (stored in indexer dict)
            # Domain format is now: http://prowlarr.{indexer_name}.indexer
            # But we get indexer_id directly from site info
            indexer_id = site.get("indexer_id")
            if not indexer_id:
                logger.warning(f"【{self.plugin_name}】站点缺少 indexer_id 字段：{site_name}")
                return results

            logger.debug(f"【{self.plugin_name}】使用索引器ID：{indexer_id}")

            # Build search parameters
            search_params = self._build_search_params(
                keyword=keyword,
                indexer_id=indexer_id,
                mtype=mtype,
                page=page
            )

            # Execute search API call
            api_results = self._search_prowlarr_api(search_params)

            # Parse results to TorrentInfo
            for item in api_results:
                try:
                    torrent_info = self._parse_torrent_info(item, site_name)
                    if torrent_info:
                        results.append(torrent_info)
                except Exception as e:
                    logger.error(f"【{self.plugin_name}】解析种子信息失败：{str(e)}")
                    continue

            logger.info(f"【{self.plugin_name}】搜索完成：{site_name} 返回 {len(results)} 个结果")

        except Exception as e:
            logger.error(f"【{self.plugin_name}】搜索异常：{str(e)}\n{traceback.format_exc()}")

        return results

    def _build_search_params(
        self,
        keyword: str,
        indexer_id: int,
        mtype: Optional[MediaType] = None,
        page: int = 0
    ) -> Dict[str, Any]:
        """
        Build Prowlarr API search parameters.

        Args:
            keyword: Search keyword
            indexer_id: Prowlarr indexer ID
            mtype: Media type for category filtering
            page: Page number

        Returns:
            Dictionary of search parameters
        """
        # Determine categories based on media type
        categories = self._get_categories(mtype)

        # Build parameter list (supports multiple category parameters)
        params = [
            ("query", keyword),
            ("indexerIds", indexer_id),
            ("type", "search"),
            ("limit", 100),
            ("offset", page * 100 if page else 0),
        ]

        # Add category parameters
        for cat in categories:
            params.append(("categories", cat))

        return params

    @staticmethod
    def _get_categories(mtype: Optional[MediaType] = None) -> List[int]:
        """
        Get Torznab category IDs based on media type.

        Args:
            mtype: Media type (MOVIE, TV, or None for all)

        Returns:
            List of category IDs
        """
        if not mtype:
            return [2000, 5000]  # Both movies and TV
        elif mtype == MediaType.MOVIE:
            return [2000]  # Movies
        elif mtype == MediaType.TV:
            return [5000]  # TV shows
        else:
            return [2000, 5000]

    def _search_prowlarr_api(self, params: List[Tuple[str, Any]]) -> List[Dict[str, Any]]:
        """
        Execute Prowlarr API search request.

        Args:
            params: List of (key, value) tuples for query parameters

        Returns:
            List of torrent dictionaries from API response
        """
        try:
            # Build URL with query string
            query_string = urlencode(params)
            url = f"{self._host}/api/v1/search?{query_string}"

            headers = {
                "X-Api-Key": self._api_key,
                "Content-Type": "application/json",
                "Accept": "application/json"
            }

            logger.debug(f"【{self.plugin_name}】API请求：{url}")

            response = RequestUtils(
                headers=headers,
                proxies=self._proxy
            ).get_res(url, timeout=60)

            if not response:
                logger.error(f"【{self.plugin_name}】搜索API请求失败：无响应")
                return []

            if response.status_code != 200:
                logger.error(f"【{self.plugin_name}】搜索API请求失败：HTTP {response.status_code}")
                logger.debug(f"【{self.plugin_name}】响应内容：{response.text}")
                return []

            try:
                data = response.json()
            except Exception as e:
                logger.error(f"【{self.plugin_name}】解析搜索结果JSON失败：{str(e)}")
                return []

            if not isinstance(data, list):
                logger.error(f"【{self.plugin_name}】API返回格式错误：期望列表，得到 {type(data)}")
                return []

            return data

        except Exception as e:
            logger.error(f"【{self.plugin_name}】搜索API异常：{str(e)}\n{traceback.format_exc()}")
            return []

    def _parse_torrent_info(self, item: Dict[str, Any], site_name: str) -> Optional[TorrentInfo]:
        """
        Parse Prowlarr API response item to TorrentInfo object.

        Args:
            item: Single torrent item from API response
            site_name: Site name for attribution

        Returns:
            TorrentInfo object or None if parsing fails
        """
        try:
            # Extract required fields
            title = item.get("title", "")
            if not title:
                logger.debug(f"【{self.plugin_name}】跳过无标题的结果")
                return None

            # Get download URL (prefer direct download over magnet)
            enclosure = item.get("downloadUrl") or item.get("magnetUrl", "")
            if not enclosure:
                logger.debug(f"【{self.plugin_name}】跳过无下载链接的结果：{title}")
                return None

            # Build TorrentInfo object
            torrent = TorrentInfo(
                title=title,
                enclosure=enclosure,
                description=item.get("sortTitle", ""),
                size=item.get("size", 0),
                seeders=item.get("seeders", 0),
                peers=item.get("leechers", 0),
                page_url=item.get("infoUrl") or item.get("guid", ""),
                site_name=site_name,
                pubdate=self._parse_publish_date(item.get("publishDate", "")),
                imdbid=self._format_imdb_id(item.get("imdbId")),
                downloadvolumefactor=0.0 if item.get("indexerFlags", 0) & 1 else 1.0,  # Freeleech flag
                uploadvolumefactor=1.0,
                grabs=item.get("grabs", 0),
            )

            return torrent

        except Exception as e:
            logger.error(f"【{self.plugin_name}】解析种子信息异常：{str(e)}")
            return None

    @staticmethod
    def _parse_publish_date(date_str: str) -> str:
        """
        Parse ISO 8601 date string to MoviePilot format.

        Args:
            date_str: ISO 8601 date string (e.g., "2023-06-15T12:34:56Z")

        Returns:
            Formatted date string (YYYY-MM-DD HH:MM:SS)
        """
        try:
            if not date_str:
                return ""

            # Parse ISO 8601 format
            dt = datetime.fromisoformat(date_str.replace("Z", "+00:00"))

            # Format to MoviePilot standard
            return dt.strftime("%Y-%m-%d %H:%M:%S")

        except Exception:
            return date_str  # Return original if parsing fails

    @staticmethod
    def _format_imdb_id(imdb_id: Any) -> str:
        """
        Format IMDB ID to standard tt prefix format.

        Args:
            imdb_id: IMDB ID (integer or string)

        Returns:
            Formatted IMDB ID string (e.g., "tt0137523")
        """
        try:
            if not imdb_id:
                return ""

            # Convert to string
            imdb_str = str(imdb_id)

            # Add tt prefix if missing
            if not imdb_str.startswith("tt"):
                imdb_str = f"tt{imdb_str}"

            return imdb_str

        except Exception:
            return ""

    def get_form(self) -> Tuple[List[dict], Dict[str, Any]]:
        """
        Get plugin configuration form for web UI.

        Returns:
            Tuple of (form_elements, default_config)
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
                                'props': {'cols': 12, 'md': 6},
                                'content': [
                                    {
                                        'component': 'VSwitch',
                                        'props': {
                                            'model': 'enabled',
                                            'label': '启用插件',
                                            'hint': '开启后将使用Prowlarr进行搜索',
                                            'persistent-hint': True
                                        }
                                    }
                                ]
                            },
                            {
                                'component': 'VCol',
                                'props': {'cols': 12, 'md': 6},
                                'content': [
                                    {
                                        'component': 'VSwitch',
                                        'props': {
                                            'model': 'onlyonce',
                                            'label': '立即运行一次',
                                            'hint': '插件将立即同步索引器列表',
                                            'persistent-hint': True
                                        }
                                    }
                                ]
                            }
                        ]
                    },
                    {
                        'component': 'VRow',
                        'content': [
                            {
                                'component': 'VCol',
                                'props': {'cols': 12, 'md': 6},
                                'content': [
                                    {
                                        'component': 'VTextField',
                                        'props': {
                                            'model': 'host',
                                            'label': '服务器地址',
                                            'placeholder': 'http://127.0.0.1:9696',
                                            'hint': 'Prowlarr服务器地址，如：http://127.0.0.1:9696',
                                            'persistent-hint': True
                                        }
                                    }
                                ]
                            },
                            {
                                'component': 'VCol',
                                'props': {'cols': 12, 'md': 6},
                                'content': [
                                    {
                                        'component': 'VTextField',
                                        'props': {
                                            'model': 'api_key',
                                            'label': 'API密钥',
                                            'placeholder': '',
                                            'hint': '在Prowlarr设置→通用→安全→API密钥中获取',
                                            'persistent-hint': True,
                                            'type': 'password'
                                        }
                                    }
                                ]
                            }
                        ]
                    },
                    {
                        'component': 'VRow',
                        'content': [
                            {
                                'component': 'VCol',
                                'props': {'cols': 12, 'md': 6},
                                'content': [
                                    {
                                        'component': 'VTextField',
                                        'props': {
                                            'model': 'cron',
                                            'label': '同步周期',
                                            'placeholder': '0 0 */6 * *',
                                            'hint': 'Cron表达式，默认每6小时同步一次索引器',
                                            'persistent-hint': True
                                        }
                                    }
                                ]
                            },
                            {
                                'component': 'VCol',
                                'props': {'cols': 12, 'md': 6},
                                'content': [
                                    {
                                        'component': 'VSwitch',
                                        'props': {
                                            'model': 'proxy',
                                            'label': '使用代理',
                                            'hint': '访问Prowlarr时使用系统代理',
                                            'persistent-hint': True
                                        }
                                    }
                                ]
                            }
                        ]
                    },
                    {
                        'component': 'VRow',
                        'content': [
                            {
                                'component': 'VCol',
                                'props': {'cols': 12},
                                'content': [
                                    {
                                        'component': 'VAlert',
                                        'props': {
                                            'type': 'info',
                                            'variant': 'tonal',
                                            'text': '插件将自动同步Prowlarr中已启用的索引器，每个索引器将注册为一个站点。搜索时将通过Prowlarr API进行查询。'
                                        }
                                    }
                                ]
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
            "cron": "0 0 */6 * *",
            "onlyonce": False
        }

    def get_page(self) -> List[dict]:
        """
        拼装插件详情页面，需要返回页面配置，同时附带数据
        """
        # Build status info
        status_info = []
        if self._enabled:
            status_info.append('状态：运行中')
        else:
            status_info.append('状态：已停用')

        if self._last_update:
            status_info.append(f'最后同步：{self._last_update.strftime("%Y-%m-%d %H:%M:%S")}')

        status_info.append(f'索引器数量：{len(self._indexers)}')

        # Build table rows
        items = []
        if self._indexers:
            for site in self._indexers:
                items.append({
                    'component': 'tr',
                    'content': [
                        {
                            'component': 'td',
                            'text': site.get("indexer_name", "Unknown")
                        },
                        {
                            'component': 'td',
                            'text': site.get("domain", "N/A")
                        },
                        {
                            'component': 'td',
                            'text': '是' if site.get("public", False) else '否'
                        }
                    ]
                })

        # Build page elements
        return [
            {
                'component': 'VRow',
                'content': [
                    {
                        'component': 'VCol',
                        'props': {'cols': 12},
                        'content': [
                            {
                                'component': 'VAlert',
                                'props': {
                                    'type': 'success' if self._enabled else 'info',
                                    'variant': 'tonal',
                                    'text': ' | '.join(status_info)
                                }
                            }
                        ]
                    }
                ]
            },
            {
                'component': 'VRow',
                'content': [
                    {
                        'component': 'VCol',
                        'props': {
                            'cols': 12
                        },
                        'content': [
                            {
                                'component': 'VTable',
                                'props': {
                                    'hover': True
                                },
                                'content': [
                                    {
                                        'component': 'thead',
                                        'content': [
                                            {
                                                'component': 'tr',
                                                'content': [
                                                    {
                                                        'component': 'th',
                                                        'props': {
                                                            'class': 'text-start ps-4'
                                                        },
                                                        'text': '索引器名称'
                                                    },
                                                    {
                                                        'component': 'th',
                                                        'props': {
                                                            'class': 'text-start ps-4'
                                                        },
                                                        'text': '站点domain'
                                                    },
                                                    {
                                                        'component': 'th',
                                                        'props': {
                                                            'class': 'text-start ps-4'
                                                        },
                                                        'text': '公开站点？'
                                                    }
                                                ]
                                            }
                                        ]
                                    },
                                    {
                                        'component': 'tbody',
                                        'content': items
                                    }
                                ]
                            }
                        ]
                    }
                ]
            }
        ]

    def get_indexers(self) -> List[Dict[str, Any]]:
        """
        返回插件管理的索引器列表，供系统查询

        Returns:
            List of indexer dictionaries
        """
        return self._indexers if self._indexers else []

    def get_api(self) -> List[Dict[str, Any]]:
        """
        Get plugin API endpoints.

        Returns:
            List of API endpoint definitions
        """
        # 提供 API 端点返回索引器列表
        return [
            {
                "path": "/indexers",
                "endpoint": self.get_indexers,
                "methods": ["GET"],
                "summary": "获取索引器列表",
                "description": "返回所有已注册的 Prowlarr 索引器"
            }
        ]
