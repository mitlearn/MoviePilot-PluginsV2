# -*- coding: utf-8 -*-
"""
JackettIndexer Plugin for MoviePilot

This plugin integrates Jackett indexer search functionality into MoviePilot.
It allows searching across all indexers configured in Jackett through a unified interface.

Version: 0.1.0
Author: Claude
"""

import copy
import re
import traceback
import xml.dom.minidom
from typing import List, Dict, Optional, Any, Tuple
from datetime import datetime
from urllib.parse import urlencode
import unicodedata

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger

from app.core.context import TorrentInfo
from app.helper.sites import SitesHelper
from app.log import logger
from app.plugins import _PluginBase
from app.schemas.types import MediaType
from app.utils.dom import DomUtils
from app.utils.http import RequestUtils
from app.utils.string import StringUtils


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
    plugin_version = "0.6.0"
    plugin_author = "Claude"
    author_url = "https://github.com"
    plugin_config_prefix = "jackettindexer_"
    plugin_order = 15
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

    # Domain identifier for indexer (matching reference implementation pattern)
    # Format: plugin_name.author
    JACKETT_DOMAIN = "jackett_indexer.claude"

    # Torznab namespace for XML parsing
    TORZNAB_NS = "http://torznab.com/schemas/2015/feed"

    def init_plugin(self, config: dict = None):
        """
        Initialize the plugin with user configuration.

        Args:
            config: Configuration dictionary from user settings
        """
        logger.info(f"【{self.plugin_name}】★★★ 开始初始化插件 ★★★")
        logger.debug(f"【{self.plugin_name}】收到配置：{config}")

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

        # IMPORTANT: Clean up old indexers first (one-time cleanup for v0.3.0)
        # This ensures old站点 with incorrect structure are removed
        for indexer in self._indexers:
            domain = indexer.get("domain", "")
            try:
                if self._sites_helper.get_indexer(domain):
                    self._sites_helper.delete_indexer(domain)
                    logger.info(f"【{self.plugin_name}】清理旧站点：{indexer.get('name')} (domain: {domain})")
            except Exception as e:
                logger.debug(f"【{self.plugin_name}】清理站点失败（可能不存在）：{str(e)}")

        # Register indexers to site management (matching reference implementation)
        registered_count = 0
        for indexer in self._indexers:
            domain = indexer.get("domain", "")
            site_info = self._sites_helper.get_indexer(domain)
            if not site_info:
                new_indexer = copy.deepcopy(indexer)
                self._sites_helper.add_indexer(domain, new_indexer)
                logger.info(f"【{self.plugin_name}】✅ 新增到站点管理：{indexer.get('name')} (domain: {domain})")
                registered_count += 1
            else:
                logger.debug(f"【{self.plugin_name}】站点已存在，跳过：{indexer.get('name')} (domain: {domain})")

        logger.info(f"【{self.plugin_name}】插件初始化完成，总计 {len(self._indexers)} 个索引器，新增 {registered_count} 个")

    def _fetch_and_build_indexers(self) -> bool:
        """
        Fetch indexers from Jackett and build indexer dictionaries.

        Returns:
            True if successful, False otherwise
        """
        try:
            indexers = self._get_indexers_from_jackett()
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
            # Fetch indexers from Jackett
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
                        logger.debug(f"【{self.plugin_name}】解析到索引器：id={indexer['id']}, title={indexer['title']}")

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
        indexer_type = indexer.get("type", "")

        # Build domain identifier (matching JackettExtend reference implementation)
        # Replace author part with indexer_id: "jackett_indexer.claude" -> "jackett_indexer.{indexer_id}"
        domain = self.JACKETT_DOMAIN.replace(self.plugin_author.lower(), str(indexer_id))

        # Detect if indexer is public or private based on type
        # Jackett types: "public", "semi-public", "private"
        is_public = indexer_type.lower() in ["public", "semi-public"]

        # Log type detection
        logger.debug(f"【{self.plugin_name}】索引器 {indexer_title} 类型：{indexer_type} -> {'公开' if is_public else '私有'}")

        # Build indexer dictionary (matching JackettExtend reference implementation exactly)
        return {
            "id": f"{self.plugin_name}-{indexer_title}",
            "name": f"{self.plugin_name}-{indexer_title}",
            "url": f"{self._host.rstrip('/')}/api/v2.0/indexers/{indexer_id}/results/torznab/",
            "domain": domain,
            "public": is_public,
            "proxy": False,
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
        if not self._enabled:
            logger.debug(f"【{self.plugin_name}】get_module 被调用，但插件未启用，返回空字典")
            return {}

        # Register BOTH search_torrents and async_search_torrents
        # The system actually calls async_search_torrents
        result = {
            "search_torrents": self.search_torrents,
            "async_search_torrents": self.async_search_torrents,
        }
        logger.info(f"【{self.plugin_name}】get_module 被调用，注册 search_torrents 和 async_search_torrents 方法")
        return result

    async def async_search_torrents(
        self,
        site: Dict[str, Any],
        keyword: str,
        mtype: Optional[MediaType] = None,
        page: Optional[int] = 0
    ) -> List[TorrentInfo]:
        """
        Async wrapper for search_torrents.
        This is the actual method called by MoviePilot's async search system.
        """
        # CRITICAL: Log IMMEDIATELY at method entry
        import sys
        sys.stderr.write(f"=== JACKETT async_search_torrents CALLED ===\n")
        sys.stderr.flush()

        logger.info(f"【{self.plugin_name}】★★★ async_search_torrents 方法被调用 ★★★")

        # Delegate to synchronous implementation
        return self.search_torrents(site, keyword, mtype, page)

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
        # CRITICAL: Log IMMEDIATELY at method entry - before ANY code
        import sys
        sys.stderr.write(f"=== JACKETT search_torrents CALLED ===\n")
        sys.stderr.flush()

        results = []

        # First line of the method - log immediately
        logger.info(f"【{self.plugin_name}】★★★ search_torrents 方法被调用 ★★★")
        logger.info(f"【{self.plugin_name}】site={site}, keyword={keyword}")

        try:
            # Debug: Log method call with all parameters
            logger.debug(f"【{self.plugin_name}】search_torrents 被调用，site type={type(site)}, keyword={keyword}")

            # Validate inputs first (matching reference implementation pattern)
            if site is None:
                logger.debug(f"【{self.plugin_name}】站点参数为 None，返回空结果")
                return results

            if not isinstance(site, dict):
                logger.error(f"【{self.plugin_name}】站点参数类型错误：期望 dict，得到 {type(site)}")
                return results

            if not keyword:
                logger.debug(f"【{self.plugin_name}】关键词为空，返回空结果")
                return results

            # Filter non-English keywords (Jackett/Prowlarr work best with English)
            if not self._is_english_keyword(keyword):
                logger.info(f"【{self.plugin_name}】检测到非英文关键词，跳过搜索：{keyword}")
                return results
        except Exception as e:
            logger.error(f"【{self.plugin_name}】参数验证异常：{str(e)}\n{traceback.format_exc()}")
            return results

        try:
            # Get site name for logging
            site_name = site.get("name", "Unknown")
            logger.debug(f"【{self.plugin_name}】站点名称：{site_name}, plugin_name: {self.plugin_name}")

            # Check if this site belongs to our plugin (matching reference implementation)
            site_name_value = site.get("name", "")
            if not site_name_value:
                logger.debug(f"【{self.plugin_name}】站点名称为空，返回空结果")
                return results

            site_prefix = site_name_value.split("-")[0] if "-" in site_name_value else site_name_value
            logger.debug(f"【{self.plugin_name}】站点前缀：{site_prefix}, 是否匹配：{site_prefix == self.plugin_name}")

            if site_prefix != self.plugin_name:
                logger.debug(f"【{self.plugin_name}】站点不属于本插件，返回空结果")
                return results
        except Exception as e:
            logger.error(f"【{self.plugin_name}】站点名称处理异常：{str(e)}\n{traceback.format_exc()}")
            return results

        try:
            # Log that method was called
            logger.info(f"【{self.plugin_name}】开始搜索：站点={site_name}, 关键词={keyword}, 类型={mtype}, 页码={page}")

            # Extract indexer ID from domain (matching reference implementation)
            # Domain format: jackett_indexer.{indexer_id}
            domain = site.get("domain", "")
            if not domain:
                logger.warning(f"【{self.plugin_name}】站点缺少 domain 字段：{site_name}")
                return results

            # Extract indexer ID from domain (matching reference implementation)
            # domain 格式: "jackett_indexer.{indexer_id}"
            domain_url = StringUtils.get_url_domain(domain)
            if not domain_url:
                logger.warning(f"【{self.plugin_name}】无法解析domain：{domain}")
                return results

            indexer_id = domain_url.split(".")[-1]  # Take last part
            if not indexer_id:
                logger.warning(f"【{self.plugin_name}】从domain提取的索引器ID为空：{domain}")
                return results

            logger.info(f"【{self.plugin_name}】从domain提取索引器ID：{indexer_id}，准备构建搜索URL")

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
                return results

            # Additional safety check for xml_content type
            if not isinstance(xml_content, str):
                logger.error(f"【{self.plugin_name}】搜索返回了非字符串类型的结果：{type(xml_content)}")
                return results

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

            logger.info(f"【{self.plugin_name}】API请求：{url}")
            logger.debug(f"【{self.plugin_name}】搜索参数：{params}")

            response = RequestUtils(proxies=self._proxy).get_res(
                url=url,
                params=params,
                timeout=60
            )

            if not response:
                logger.error(f"【{self.plugin_name}】搜索API请求失败：无响应")
                return None

            # Check if response has status_code attribute
            if not hasattr(response, 'status_code'):
                logger.error(f"【{self.plugin_name}】响应对象格式异常：缺少status_code属性")
                return None

            if response.status_code != 200:
                logger.error(f"【{self.plugin_name}】搜索API请求失败：HTTP {response.status_code}")
                # Safely get response text
                response_text = getattr(response, 'text', '')
                if response_text:
                    logger.debug(f"【{self.plugin_name}】响应内容：{response_text[:500]}")
                return None

            # Safely get response text
            xml_content = getattr(response, 'text', None)
            if xml_content is None:
                logger.error(f"【{self.plugin_name}】响应对象没有text属性")
                return None

            return xml_content

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
            # Validate xml_content
            if not xml_content or not isinstance(xml_content, str):
                logger.error(f"【{self.plugin_name}】XML内容为空或类型错误")
                return results

            # Parse XML
            dom_tree = xml.dom.minidom.parseString(xml_content)
            root_node = dom_tree.documentElement

            # Safety check for root_node
            if not root_node:
                logger.error(f"【{self.plugin_name}】XML解析失败：无法获取根节点")
                return results

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
    def _is_english_keyword(keyword: str) -> bool:
        """
        Check if keyword is primarily English (allow English letters, numbers, common symbols).

        Args:
            keyword: Search keyword to check

        Returns:
            True if keyword is English or contains significant English content, False otherwise
        """
        if not keyword:
            return False

        # Remove common punctuation and spaces
        cleaned = re.sub(r'[.,!?;:()\[\]{}\s\-_]+', '', keyword)

        if not cleaned:
            return True  # Only punctuation, allow it

        # Count different character types
        ascii_count = sum(1 for c in cleaned if ord(c) < 128)
        total_count = len(cleaned)

        # If more than 50% are ASCII characters, consider it English
        if total_count == 0:
            return True

        ascii_ratio = ascii_count / total_count

        # Check for CJK (Chinese, Japanese, Korean) characters
        cjk_count = sum(1 for c in cleaned if '\u4e00' <= c <= '\u9fff' or  # Chinese
                       '\u3040' <= c <= '\u309f' or  # Hiragana
                       '\u30a0' <= c <= '\u30ff' or  # Katakana
                       '\uac00' <= c <= '\ud7af')    # Korean

        # If contains significant CJK characters, reject
        if cjk_count > 0 and cjk_count / total_count > 0.3:
            return False

        # Allow if majority is ASCII
        return ascii_ratio > 0.5

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
                                            'type': 'password',
                                            'append-inner-icon': 'mdi-eye-off'
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
                            'text': site.get("name", "Unknown")
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
                "description": "返回所有已注册的 Jackett 索引器"
            }
        ]
