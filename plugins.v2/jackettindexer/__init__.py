# -*- coding: utf-8 -*-
"""
JackettIndexer Plugin for MoviePilot

This plugin integrates Jackett indexer search functionality into MoviePilot.
It allows searching across all indexers configured in Jackett through a unified interface.

Version: 0.1.0
Author: Claude
"""

import traceback
import xml.dom.minidom
from typing import List, Dict, Optional, Any, Tuple
from datetime import datetime
from urllib.parse import urlencode

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger

from app.core.context import TorrentInfo
from app.helper.sites import SitesHelper
from app.log import logger
from app.plugins import _PluginBase
from app.schemas.types import MediaType
from app.utils.dom import DomUtils
from app.utils.http import RequestUtils


class JackettIndexer(_PluginBase):
    """
    Jackett Indexer Plugin

    Provides torrent search functionality through Jackett Torznab API.
    Registers all configured Jackett indexers as MoviePilot sites.
    """

    # Plugin metadata
    plugin_name = "Jackett索引器"
    plugin_desc = "集成Jackett索引器搜索，支持Torznab协议多站点搜索。"
    plugin_icon = "Jackett_A.png"
    plugin_version = "0.1.2"
    plugin_author = "Claude"
    author_url = "https://github.com"
    plugin_config_prefix = "jackettindexer_"
    plugin_order = 11
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
    DOMAIN_PREFIX = "jackett"

    # Torznab namespace for XML parsing
    TORZNAB_NS = "http://torznab.com/schemas/2015/feed"

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

        # Sync indexers immediately
        logger.info(f"【{self.plugin_name}】开始同步索引器列表...")
        if self._sync_indexers():
            logger.info(f"【{self.plugin_name}】成功同步 {len(self._indexers)} 个索引器")
            # Log registered indexers for debugging
            for idx in self._indexers:
                logger.debug(f"【{self.plugin_name}】已注册索引器：{idx.get('name')} (domain: {idx.get('domain')})")
        else:
            logger.error(f"【{self.plugin_name}】同步索引器失败")
            return

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

        logger.info(f"【{self.plugin_name}】插件初始化完成")

    def _sync_indexers(self) -> bool:
        """
        Sync indexers from Jackett and register them as MoviePilot sites.

        Returns:
            True if sync successful, False otherwise
        """
        try:
            # Fetch indexers from Jackett
            indexers = self._get_indexers_from_jackett()

            if not indexers:
                logger.warning(f"【{self.plugin_name}】未获取到索引器列表")
                return False

            # Unregister old indexers
            if self._indexers:
                for old_indexer in self._indexers:
                    domain = old_indexer.get("domain")
                    if domain:
                        try:
                            self._sites_helper.delete_indexer(domain)
                        except Exception as e:
                            logger.debug(f"【{self.plugin_name}】删除旧索引器失败 {domain}：{str(e)}")

            # Register new indexers
            self._indexers = []
            for indexer in indexers:
                try:
                    indexer_dict = self._build_indexer_dict(indexer)
                    domain = indexer_dict["domain"]

                    # Register with sites helper
                    self._sites_helper.add_indexer(domain, indexer_dict)
                    self._indexers.append(indexer_dict)

                    logger.debug(f"【{self.plugin_name}】已注册索引器：{indexer_dict['name']}")

                except Exception as e:
                    logger.error(f"【{self.plugin_name}】注册索引器失败：{str(e)}\n{traceback.format_exc()}")
                    continue

            self._last_update = datetime.now()
            logger.info(f"【{self.plugin_name}】索引器同步完成，共 {len(self._indexers)} 个")
            return True

        except Exception as e:
            logger.error(f"【{self.plugin_name}】同步索引器异常：{str(e)}\n{traceback.format_exc()}")
            return False

    def _get_indexers_from_jackett(self) -> List[Dict[str, Any]]:
        """
        Fetch indexer list from Jackett API.

        Returns:
            List of indexer dictionaries from Jackett API
        """
        try:
            url = f"{self._host}/api/v2.0/indexers/all/results/torznab/api"
            params = {
                "apikey": self._api_key,
                "t": "indexers",
                "configured": "true"
            }

            logger.debug(f"【{self.plugin_name}】正在获取索引器列表：{url}")

            response = RequestUtils(proxies=self._proxy).get_res(
                url=url,
                params=params,
                timeout=30
            )

            if not response:
                logger.error(f"【{self.plugin_name}】API请求失败：无响应")
                return []

            if response.status_code != 200:
                logger.error(f"【{self.plugin_name}】API请求失败：HTTP {response.status_code}")
                logger.debug(f"【{self.plugin_name}】响应内容：{response.text}")
                return []

            # Parse XML response
            indexers = self._parse_indexers_xml(response.text)

            logger.info(f"【{self.plugin_name}】获取到 {len(indexers)} 个索引器")

            return indexers

        except Exception as e:
            logger.error(f"【{self.plugin_name}】获取索引器列表异常：{str(e)}\n{traceback.format_exc()}")
            return []

    def _parse_indexers_xml(self, xml_content: str) -> List[Dict[str, Any]]:
        """
        Parse Jackett indexers XML response.

        Args:
            xml_content: XML response string

        Returns:
            List of indexer dictionaries
        """
        try:
            # Parse XML
            dom_tree = xml.dom.minidom.parseString(xml_content)
            root_node = dom_tree.documentElement

            # Check for error response
            if root_node.tagName == "error":
                error_code = root_node.getAttribute("code")
                error_desc = root_node.getAttribute("description")
                logger.error(f"【{self.plugin_name}】Torznab错误 {error_code}：{error_desc}")
                return []

            # Find indexer elements
            indexer_elements = root_node.getElementsByTagName("indexer")

            indexers = []
            for elem in indexer_elements:
                try:
                    indexer = {
                        "id": elem.getAttribute("id"),
                        "title": DomUtils.tag_value(elem, "title", default=""),
                        "type": elem.getAttribute("type"),
                        "language": elem.getAttribute("language") or "en-US",
                    }

                    # Only add if we have required fields
                    if indexer["id"] and indexer["title"]:
                        indexers.append(indexer)

                except Exception as e:
                    logger.debug(f"【{self.plugin_name}】解析索引器失败：{str(e)}")
                    continue

            return indexers

        except Exception as e:
            logger.error(f"【{self.plugin_name}】解析XML失败：{str(e)}")
            return []

    def _build_indexer_dict(self, indexer: Dict[str, Any]) -> Dict[str, Any]:
        """
        Build MoviePilot indexer dictionary from Jackett indexer data.

        Args:
            indexer: Jackett indexer dictionary

        Returns:
            MoviePilot compatible indexer dictionary
        """
        indexer_id = indexer.get("id", "")
        indexer_title = indexer.get("title", f"Indexer-{indexer_id}")

        # Build domain identifier (used for routing) - use clean indexer_id
        domain = f"http://{self.DOMAIN_PREFIX}.{indexer_id.lower().replace(' ', '-')}.indexer"

        # Build complete indexer dictionary
        # CRITICAL: This structure must prevent MoviePilot from using default spider
        return {
            # Basic identification
            "id": f"{self.plugin_name}-{indexer_id}",
            "name": f"{self.plugin_name}-{indexer_title}",
            "domain": domain,
            "url": self._host,

            # Custom fields for our plugin
            "indexer_id": indexer_id,  # Store original Jackett ID
            "indexer_title": indexer_title,

            # Site properties
            "public": indexer.get("type", "") == "public",
            "proxy": self._proxy,
            "language": indexer.get("language", "en-US"),
            "protocol": "torrent",

            # Critical: Mark as API-based indexer
            "type": "indexer",  # Special type for API indexers

            # Disable all spider/crawler features
            "render": False,
            "chrome": False,
            "playwright": False,

            # Explicitly disable site features
            "rss": None,
            "search": None,
            "browse": None,
            "torrents": None,  # No HTML parsing needed
            "parser": None,  # No parser needed

            # Cookie and headers - empty for API access
            "cookie": "",
            "ua": None,
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

            # Unregister indexers
            if self._indexers and self._sites_helper:
                for indexer in self._indexers:
                    domain = indexer.get("domain")
                    if domain:
                        try:
                            self._sites_helper.delete_indexer(domain)
                        except Exception as e:
                            logger.debug(f"【{self.plugin_name}】删除索引器失败 {domain}：{str(e)}")

                logger.info(f"【{self.plugin_name}】已注销 {len(self._indexers)} 个索引器")
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
        Search torrents through Jackett Torznab API.

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

        try:
            # Log that method was called
            logger.debug(f"【{self.plugin_name}】search_torrents 被调用：site={site}, keyword={keyword}, mtype={mtype}, page={page}")

            # Validate inputs
            if not site:
                logger.warning(f"【{self.plugin_name}】站点参数为空")
                return []

            if not keyword:
                logger.warning(f"【{self.plugin_name}】关键词为空")
                return []

            # Check if this site belongs to our plugin
            site_name = site.get("name", "") if isinstance(site, dict) else ""
            if not site_name:
                logger.warning(f"【{self.plugin_name}】站点缺少 name 字段：{site}")
                return []

            if not site_name.startswith(self.plugin_name):
                # Not our site, return empty to let other plugins handle
                logger.debug(f"【{self.plugin_name}】站点 {site_name} 不属于本插件")
                return []

            # Extract indexer information
            domain = site.get("domain")
            if not domain:
                logger.error(f"【{self.plugin_name}】站点缺少 domain 字段：{site_name}")
                return []

            # Get indexer ID from site
            indexer_id = site.get("indexer_id")
            if not indexer_id:
                logger.error(f"【{self.plugin_name}】站点缺少 indexer_id：{site_name}")
                return []

            logger.info(f"【{self.plugin_name}】开始搜索：站点={site_name}, 关键词={keyword}, 类型={mtype}, 页码={page}")

            # Build search parameters
            search_params = self._build_search_params(
                keyword=keyword,
                mtype=mtype,
                page=page
            )

            # Execute search API call
            xml_content = self._search_jackett_api(indexer_id, search_params)

            if not xml_content:
                logger.debug(f"【{self.plugin_name}】搜索未返回结果")
                return []

            # Parse XML results to TorrentInfo
            results = self._parse_torznab_xml(xml_content, site_name)

            logger.info(f"【{self.plugin_name}】搜索完成：{site_name} 返回 {len(results)} 个结果")

        except Exception as e:
            logger.error(f"【{self.plugin_name}】搜索异常：{str(e)}\n{traceback.format_exc()}")

        return results

    def _build_search_params(
        self,
        keyword: str,
        mtype: Optional[MediaType] = None,
        page: int = 0
    ) -> Dict[str, Any]:
        """
        Build Jackett Torznab API search parameters.

        Args:
            keyword: Search keyword
            mtype: Media type for category filtering
            page: Page number

        Returns:
            Dictionary of search parameters
        """
        # Determine categories based on media type
        categories = self._get_categories(mtype)

        # Build parameters
        params = {
            "apikey": self._api_key,
            "t": "search",
            "q": keyword,
            "limit": 100,
            "offset": page * 100 if page else 0,
        }

        # Add categories as comma-separated string
        if categories:
            params["cat"] = ",".join(map(str, categories))

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

    def _search_jackett_api(self, indexer_id: str, params: Dict[str, Any]) -> Optional[str]:
        """
        Execute Jackett Torznab API search request.

        Args:
            indexer_id: Jackett indexer identifier
            params: Query parameters dictionary

        Returns:
            XML response string or None if failed
        """
        try:
            # Build URL for specific indexer
            url = f"{self._host}/api/v2.0/indexers/{indexer_id}/results/torznab/api"

            logger.debug(f"【{self.plugin_name}】API请求：{url}?{urlencode(params)}")

            response = RequestUtils(proxies=self._proxy).get_res(
                url=url,
                params=params,
                timeout=60
            )

            if not response:
                logger.error(f"【{self.plugin_name}】搜索API请求失败：无响应")
                return None

            if response.status_code != 200:
                logger.error(f"【{self.plugin_name}】搜索API请求失败：HTTP {response.status_code}")
                logger.debug(f"【{self.plugin_name}】响应内容：{response.text[:500]}")
                return None

            return response.text

        except Exception as e:
            logger.error(f"【{self.plugin_name}】搜索API异常：{str(e)}\n{traceback.format_exc()}")
            return None

    def _parse_torznab_xml(self, xml_content: str, site_name: str) -> List[TorrentInfo]:
        """
        Parse Torznab XML response to TorrentInfo objects.

        Args:
            xml_content: XML response string
            site_name: Site name for attribution

        Returns:
            List of TorrentInfo objects
        """
        results = []

        try:
            # Parse XML
            dom_tree = xml.dom.minidom.parseString(xml_content)
            root_node = dom_tree.documentElement

            # Check for error response
            if root_node.tagName == "error":
                error_code = root_node.getAttribute("code")
                error_desc = root_node.getAttribute("description")
                logger.error(f"【{self.plugin_name}】Torznab错误 {error_code}：{error_desc}")
                return []

            # Find channel and items
            channel = root_node.getElementsByTagName("channel")
            if not channel:
                logger.debug(f"【{self.plugin_name}】XML响应中未找到 channel 元素")
                return []

            items = channel[0].getElementsByTagName("item")

            for item in items:
                try:
                    torrent_info = self._parse_torznab_item(item, site_name)
                    if torrent_info:
                        results.append(torrent_info)
                except Exception as e:
                    logger.debug(f"【{self.plugin_name}】解析item失败：{str(e)}")
                    continue

        except Exception as e:
            logger.error(f"【{self.plugin_name}】解析XML异常：{str(e)}\n{traceback.format_exc()}")

        return results

    def _parse_torznab_item(self, item, site_name: str) -> Optional[TorrentInfo]:
        """
        Parse single Torznab item element to TorrentInfo.

        Args:
            item: XML item element
            site_name: Site name for attribution

        Returns:
            TorrentInfo object or None if parsing fails
        """
        try:
            # Extract basic fields
            title = DomUtils.tag_value(item, "title", default="")
            if not title:
                return None

            # Get download link
            enclosure_node = item.getElementsByTagName("enclosure")
            if enclosure_node:
                enclosure = enclosure_node[0].getAttribute("url")
            else:
                enclosure = DomUtils.tag_value(item, "link", default="")

            # Try to get magnet link from torznab attributes
            magnet_url = self._get_torznab_attr(item, "magneturl")
            if magnet_url:
                enclosure = magnet_url

            if not enclosure:
                logger.debug(f"【{self.plugin_name}】跳过无下载链接的结果：{title}")
                return None

            # Get size
            size_str = DomUtils.tag_value(item, "size", default="0")
            try:
                size = int(size_str) if size_str.isdigit() else 0
            except Exception:
                size = 0

            # Get seeders and peers from torznab attributes
            seeders = self._get_torznab_attr_int(item, "seeders", 0)
            peers = self._get_torznab_attr_int(item, "peers", 0)

            # Calculate leechers (peers includes seeders in Torznab)
            leechers = max(0, peers - seeders)

            # Get other fields
            pub_date = DomUtils.tag_value(item, "pubDate", default="")
            description = DomUtils.tag_value(item, "description", default="")
            page_url = DomUtils.tag_value(item, "comments", default="") or \
                      DomUtils.tag_value(item, "guid", default="")

            # Get metadata from torznab attributes
            imdb_id = self._get_torznab_attr(item, "imdbid")
            grabs = self._get_torznab_attr_int(item, "grabs", 0)

            # Determine if freeleech (downloadvolumefactor=0)
            download_factor = self._get_torznab_attr_float(item, "downloadvolumefactor", 1.0)

            # Build TorrentInfo
            torrent = TorrentInfo(
                title=title,
                enclosure=enclosure,
                description=description,
                size=size,
                seeders=seeders,
                peers=leechers,
                page_url=page_url,
                site_name=site_name,
                pubdate=self._parse_rfc2822_date(pub_date),
                imdbid=self._format_imdb_id(imdb_id),
                downloadvolumefactor=download_factor,
                uploadvolumefactor=1.0,
                grabs=grabs,
            )

            return torrent

        except Exception as e:
            logger.error(f"【{self.plugin_name}】解析种子信息异常：{str(e)}")
            return None

    def _get_torznab_attr(self, item, attr_name: str, default: str = "") -> str:
        """
        Get Torznab attribute value from item.

        Args:
            item: XML item element
            attr_name: Attribute name to find
            default: Default value if not found

        Returns:
            Attribute value as string
        """
        try:
            attrs = item.getElementsByTagName("torznab:attr")
            for attr in attrs:
                if attr.getAttribute("name") == attr_name:
                    return attr.getAttribute("value")
            return default
        except Exception:
            return default

    def _get_torznab_attr_int(self, item, attr_name: str, default: int = 0) -> int:
        """Get Torznab attribute as integer."""
        try:
            value = self._get_torznab_attr(item, attr_name, str(default))
            return int(value) if value.isdigit() else default
        except Exception:
            return default

    def _get_torznab_attr_float(self, item, attr_name: str, default: float = 0.0) -> float:
        """Get Torznab attribute as float."""
        try:
            value = self._get_torznab_attr(item, attr_name, str(default))
            return float(value)
        except Exception:
            return default

    @staticmethod
    def _parse_rfc2822_date(date_str: str) -> str:
        """
        Parse RFC 2822 date string to MoviePilot format.

        Args:
            date_str: RFC 2822 date string (e.g., "Thu, 15 Jun 2023 12:34:56 +0000")

        Returns:
            Formatted date string (YYYY-MM-DD HH:MM:SS)
        """
        try:
            if not date_str:
                return ""

            # Try to parse RFC 2822 format
            from email.utils import parsedate_to_datetime
            dt = parsedate_to_datetime(date_str)

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
                                            'hint': '开启后将使用Jackett进行搜索',
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
                                            'placeholder': 'http://127.0.0.1:9117',
                                            'hint': 'Jackett服务器地址，如：http://127.0.0.1:9117',
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
                                            'hint': '在Jackett界面点击扳手图标获取API密钥',
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
                                            'hint': '访问Jackett时使用系统代理',
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
                                            'text': '插件将自动同步Jackett中已配置的索引器，每个索引器将注册为一个站点。搜索时将通过Jackett Torznab API进行查询。'
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
        Get plugin detail page for web UI.

        Returns:
            List of page elements
        """
        # Build indexer status table
        indexer_rows = []

        if self._indexers:
            for indexer in self._indexers:
                indexer_rows.append({
                    'site_id': indexer.get('id', 'N/A'),
                    'name': indexer.get('indexer_title', 'Unknown'),
                    'indexer_id': indexer.get('indexer_id', 'N/A'),
                    'domain': indexer.get('domain', 'N/A'),
                    'public': '是' if indexer.get('public', False) else '否',
                    'language': indexer.get('language', 'en-US'),
                })

        # Build status info
        status_info = []

        if self._enabled:
            status_info.append('状态：运行中')
        else:
            status_info.append('状态：已停用')

        if self._last_update:
            status_info.append(f'最后同步：{self._last_update.strftime("%Y-%m-%d %H:%M:%S")}')

        status_info.append(f'索引器数量：{len(self._indexers)}')

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
                        'props': {'cols': 12},
                        'content': [
                            {
                                'component': 'VTable',
                                'props': {
                                    'hover': True,
                                    'density': 'compact',
                                    'headers': [
                                        {'title': '站点ID', 'key': 'site_id'},
                                        {'title': '索引器名称', 'key': 'name'},
                                        {'title': '索引器ID', 'key': 'indexer_id'},
                                        {'title': '域名', 'key': 'domain'},
                                        {'title': '公开', 'key': 'public'},
                                        {'title': '语言', 'key': 'language'},
                                    ],
                                    'items': indexer_rows
                                }
                            }
                        ]
                    }
                ]
            }
        ]

    def get_api(self) -> List[Dict[str, Any]]:
        """
        Get plugin API endpoints.

        Returns:
            List of API endpoint definitions
        """
        return []
