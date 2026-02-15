# -*- coding: utf-8 -*-
"""
JackettIndexer Plugin for MoviePilot

This plugin integrates Jackett indexer search functionality into MoviePilot.
It allows searching across all indexers configured in Jackett through a unified interface.

Version: 0.1.0
Author: Claude
"""

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
    plugin_desc = "集成Jackett索引器搜索，支持Torznab协议多站点搜索。仅索引私有和半公开站点。"
    plugin_icon = "Jackett_A.png"
    plugin_version = "1.3.0"
    plugin_author = "Claude"
    author_url = "https://github.com"
    plugin_config_prefix = "jackettindexer_"
    plugin_order = 15
    auth_level = 2

    # Private attributes
    _enabled: bool = False
    _host: str = ""
    _api_key: str = ""
    _proxy: bool = False
    _cron: str = "0 0 */12 * *"  # Sync indexers every 12 hours
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
        logger.info(f"【{self.plugin_name}】开始初始化插件")
        logger.debug(f"【{self.plugin_name}】收到配置：{config}")

        # Stop existing services
        self.stop_service()

        # Load configuration
        if config:
            self._enabled = config.get("enabled", False)
            self._host = config.get("host", "").rstrip("/")
            self._api_key = config.get("api_key", "")
            self._proxy = config.get("proxy", False)
            self._cron = config.get("cron", "0 0 */12 * *")
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

        # Register indexers to site management (following official CustomIndexer pattern)
        # add_indexer will overwrite existing indexers with same domain
        for indexer in self._indexers:
            domain = indexer.get("domain", "")
            self._sites_helper.add_indexer(domain, indexer)
            logger.debug(f"【{self.plugin_name}】注册到站点管理：{indexer.get('name')} (domain: {domain})")

        logger.info(f"【{self.plugin_name}】插件初始化完成，共注册 {len(self._indexers)} 个索引器")

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
            filtered_count = 0
            xxx_filtered_count = 0
            for indexer_data in indexers:
                try:
                    indexer_dict, is_xxx_only = self._build_indexer_dict(indexer_data)

                    # 过滤掉公开站点，保留私有和半公开站点
                    if indexer_dict.get("public", False):
                        indexer_name = indexer_dict.get("name", "Unknown")
                        logger.info(f"【{self.plugin_name}】过滤公开站点：{indexer_name}")
                        filtered_count += 1
                        continue

                    # 过滤掉只有XXX分类的索引器
                    if is_xxx_only:
                        indexer_name = indexer_dict.get("name", "Unknown")
                        logger.debug(f"【{self.plugin_name}】过滤仅XXX分类站点：{indexer_name}")
                        xxx_filtered_count += 1
                        continue

                    self._indexers.append(indexer_dict)
                except Exception as e:
                    logger.error(f"【{self.plugin_name}】构建索引器失败：{str(e)}")
                    continue

            logger.info(f"【{self.plugin_name}】成功获取 {len(self._indexers)} 个索引器（私有+半公开），过滤掉 {filtered_count} 个公开站点，{xxx_filtered_count} 个XXX专属站点")
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

        需求一：只获取已配置的索引器（通过configured=true参数）

        Returns:
            List of indexer dictionaries from Jackett API
        """
        try:
            url = f"{self._host}/api/v2.0/indexers/all/results/torznab/api"
            params = {
                "apikey": self._api_key,
                "t": "indexers",
                "configured": "true"  # 需求一：只获取已配置（已认证）的索引器
            }

            # Build full URL for debug logging
            from urllib.parse import urlencode
            params_display = {k: ('***' if k == 'apikey' else v) for k, v in params.items()}
            query_string = urlencode(params_display)
            full_url = f"{url}?{query_string}"

            logger.debug(f"【{self.plugin_name}】正在获取索引器列表：{full_url}")

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

            logger.info(f"【{self.plugin_name}】获取到 {len(indexers)} 个已配置的索引器")

            # Debug log indexer types
            for idx in indexers[:3]:
                idx_type = idx.get("type", "未知")
                logger.debug(f"【{self.plugin_name}】索引器示例：id={idx.get('id')}, title={idx.get('title')}, type={idx_type}")

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

    def _get_indexer_categories(self, indexer_id: str) -> Tuple[Optional[Dict[str, List[Dict[str, Any]]]], bool]:
        """
        Get indexer categories from Jackett Torznab API and convert to MoviePilot format.

        Args:
            indexer_id: Jackett indexer identifier

        Returns:
            Tuple of (Category dictionary in MoviePilot format or None, is_xxx_only)
        """
        try:
            # Get indexer capabilities using Torznab API
            url = f"{self._host}/api/v2.0/indexers/{indexer_id}/results/torznab/api"
            params = {
                "apikey": self._api_key,
                "t": "caps"
            }

            response = RequestUtils(proxies=self._proxy).get_res(
                url=url,
                params=params,
                timeout=15
            )

            if not response or response.status_code != 200:
                logger.debug(f"【{self.plugin_name}】无法获取索引器 {indexer_id} 的分类信息")
                return None, False

            # Parse XML response
            try:
                dom_tree = xml.dom.minidom.parseString(response.text)
                root_node = dom_tree.documentElement
            except Exception as e:
                logger.debug(f"【{self.plugin_name}】解析索引器 {indexer_id} XML失败：{str(e)}")
                return None, False

            # Find all category elements
            categories = root_node.getElementsByTagName("category")
            if not categories:
                return None, False

            # Convert Jackett categories to MoviePilot format
            # Torznab categories: 2000=Movies, 5000=TV, 6000=XXX, etc.
            category_map = {
                "movie": [],
                "tv": []
            }

            # Track all top-level categories to detect XXX-only indexers
            top_level_categories = set()

            for cat in categories:
                cat_id = cat.getAttribute("id")
                cat_name = cat.getAttribute("name")

                if not cat_id:
                    continue

                try:
                    cat_num = int(cat_id)
                    top_level = (cat_num // 1000) * 1000
                    top_level_categories.add(top_level)

                    # Build category entry
                    cat_entry = {
                        "id": int(cat_id),
                        "cat": cat_name or f"Category {cat_id}",
                        "desc": cat_name or f"Category {cat_id}"
                    }

                    # Map to movie or tv based on top-level category
                    if top_level == 2000:  # Movies
                        if not any(c["id"] == cat_entry["id"] for c in category_map["movie"]):
                            category_map["movie"].append(cat_entry)
                    elif top_level == 5000:  # TV
                        if not any(c["id"] == cat_entry["id"] for c in category_map["tv"]):
                            category_map["tv"].append(cat_entry)
                    # Skip 6000 (XXX) and other categories

                except (ValueError, TypeError):
                    continue

            # Check if indexer is XXX-only (has 6000 but no other useful categories)
            # Only filter pure XXX sites, keep Music/Audio/etc sites
            has_xxx = 6000 in top_level_categories
            has_other_content = any(cat in top_level_categories for cat in [2000, 5000, 3000, 4000, 1000, 7000, 8000])

            is_xxx_only = has_xxx and not has_other_content

            if is_xxx_only:
                logger.debug(f"【{self.plugin_name}】索引器 {indexer_id} 仅包含XXX分类，顶层分类：{sorted(top_level_categories)}")
                return None, True

            # If indexer has no movie/tv categories, still allow it (might be Music, Audio, etc.)
            # Just don't add movie/tv category info
            if not category_map["movie"] and not category_map["tv"]:
                logger.debug(f"【{self.plugin_name}】索引器 {indexer_id} 无电影/电视分类（可能是音乐/其他类型站点），顶层分类：{sorted(top_level_categories)}")
                # Return None for category but False for is_xxx_only (allow the indexer)
                return None, False

            # Remove empty categories
            result = {}
            if category_map["movie"]:
                result["movie"] = category_map["movie"]
            if category_map["tv"]:
                result["tv"] = category_map["tv"]

            if result:
                logger.debug(f"【{self.plugin_name}】索引器 {indexer_id} 分类：movie={len(result.get('movie', []))}, tv={len(result.get('tv', []))}")

            return (result if result else None), False

        except Exception as e:
            logger.debug(f"【{self.plugin_name}】获取索引器 {indexer_id} 分类信息异常：{str(e)}")
            return None, False

    def _build_indexer_dict(self, indexer: Dict[str, Any]) -> Tuple[Dict[str, Any], bool]:
        """
        Build MoviePilot indexer dictionary from Jackett indexer data.

        Args:
            indexer: Jackett indexer dictionary

        Returns:
            Tuple of (MoviePilot compatible indexer dictionary, is_xxx_only)
        """
        indexer_id = indexer.get("id", "")
        indexer_title = indexer.get("title", f"Indexer-{indexer_id}")
        indexer_type = indexer.get("type", "")

        # Build domain identifier (matching JackettExtend reference implementation)
        # Replace author part with indexer_id: "jackett_indexer.claude" -> "jackett_indexer.{indexer_id}"
        domain = self.JACKETT_DOMAIN.replace(self.plugin_author.lower(), str(indexer_id))

        # Detect if indexer is public or private based on type
        # Jackett types: "public", "semi-public", "private", or empty string
        # 只过滤公开站点，保留私有和半公开站点
        # 注意：Jackett 很多索引器的 type 为空字符串，默认视为私有
        is_public = indexer_type.lower() == "public" if indexer_type else False

        # Log type detection and domain generation
        type_display = indexer_type if indexer_type else "(空)"
        privacy_display = "公开" if is_public else "私有"
        logger.debug(f"【{self.plugin_name}】索引器 {indexer_title} 类型：{type_display} -> {privacy_display}")
        logger.debug(f"【{self.plugin_name}】生成domain：{domain}，indexer_id={indexer_id} (类型：{type(indexer_id)})")

        # Get category information from indexer and check if XXX-only
        category, is_xxx_only = self._get_indexer_categories(indexer_id)

        # Build indexer dictionary (matching JackettExtend reference implementation exactly)
        indexer_dict = {
            "id": f"{self.plugin_name}-{indexer_title}",
            "name": f"{self.plugin_name}-{indexer_title}",
            "url": f"{self._host.rstrip('/')}/api/v2.0/indexers/{indexer_id}/results/torznab/",
            "domain": domain,
            "public": is_public,
            "proxy": False,
        }

        # Add category if available
        if category:
            indexer_dict["category"] = category

        return indexer_dict, is_xxx_only

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

        # Register search methods
        result = {
            "search_torrents": self.search_torrents,
            "async_search_torrents": self.async_search_torrents,
        }
        logger.debug(f"【{self.plugin_name}】get_module 被调用，注册 search_torrents 和 async_search_torrents 方法")
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
        logger.debug(f"【{self.plugin_name}】async_search_torrents 被调用")

        # Delegate to synchronous implementation
        return self.search_torrents(site, keyword, mtype, page)

    def test_connection(self, site: Dict[str, Any]) -> Tuple[bool, str]:
        """
        Test Jackett indexer connectivity.

        This method replaces the default site connectivity test for Jackett indexers.
        Instead of testing the fake domain, it tests the actual Jackett server.

        Args:
            site: Site/indexer information dictionary

        Returns:
            Tuple of (success: bool, message: str)
        """
        site_name = site.get("name", "Unknown") if site else "Unknown"
        logger.debug(f"【{self.plugin_name}】开始测试站点连通性：{site_name}")

        try:
            # Validate site belongs to this plugin
            if site is None or not isinstance(site, dict):
                return False, "站点参数无效"

            site_name_value = site.get("name", "")
            if not site_name_value:
                return False, "站点名称为空"

            site_prefix = site_name_value.split("-")[0] if "-" in site_name_value else site_name_value
            if site_prefix != self.plugin_name:
                logger.debug(f"【{self.plugin_name}】站点不属于本插件，跳过测试：{site_name}")
                # 返回 None 让系统使用默认测试方法
                return None, None

            # Extract indexer ID from domain
            domain = site.get("domain", "")
            if not domain:
                return False, "缺少 domain 字段"

            domain_clean = domain.replace("http://", "").replace("https://", "").rstrip("/")
            indexer_id = domain_clean.split(".")[-1]

            if not indexer_id:
                return False, "无法从 domain 提取索引器 ID"

            logger.debug(f"【{self.plugin_name}】测试索引器 {indexer_id} 的连通性")

            # Test Jackett API connectivity by getting indexer capabilities
            url = f"{self._host}/api/v2.0/indexers/{indexer_id}/results/torznab/api"
            params = {
                "apikey": self._api_key,
                "t": "caps"
            }

            response = RequestUtils(proxies=self._proxy).get_res(
                url=url,
                params=params,
                timeout=10
            )

            if not response:
                logger.warning(f"【{self.plugin_name}】站点 {site_name} 连通性测试失败：无响应")
                return False, f"Jackett 服务器无响应"

            if response.status_code != 200:
                logger.warning(f"【{self.plugin_name}】站点 {site_name} 连通性测试失败：HTTP {response.status_code}")
                return False, f"Jackett 返回错误：HTTP {response.status_code}"

            # Check if response is valid XML
            try:
                dom_tree = xml.dom.minidom.parseString(response.text)
                root_node = dom_tree.documentElement

                # Check for error response
                if root_node.tagName == "error":
                    error_code = root_node.getAttribute("code")
                    error_desc = root_node.getAttribute("description")
                    logger.warning(f"【{self.plugin_name}】站点 {site_name} 连通性测试失败：{error_desc}")
                    return False, f"Jackett 错误：{error_desc}"

            except Exception as e:
                logger.warning(f"【{self.plugin_name}】站点 {site_name} 连通性测试失败：XML解析错误")
                return False, f"Jackett 响应格式错误"

            logger.debug(f"【{self.plugin_name}】站点 {site_name} 连通性测试成功")
            return True, f"Jackett 索引器连接正常"

        except Exception as e:
            logger.error(f"【{self.plugin_name}】站点 {site_name} 连通性测试异常：{str(e)}\n{traceback.format_exc()}")
            return False, f"测试异常：{str(e)}"

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
        # Initialize results first to ensure it always exists
        results = []

        # Safe extraction of site name
        try:
            site_name = site.get("name", "Unknown") if site and isinstance(site, dict) else "Unknown"
        except Exception:
            site_name = "Unknown"

        logger.info(f"【{self.plugin_name}】开始检索站点：{site_name}，关键词：{keyword}")

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

            # Check if keyword is IMDb ID (IMDb IDs are always valid)
            is_imdb = self._is_imdb_id(keyword)

            # Filter non-English keywords (Jackett/Prowlarr work best with English)
            # Skip filter for IMDb IDs
            if not is_imdb and not self._is_english_keyword(keyword):
                logger.debug(f"【{self.plugin_name}】检测到非英文关键词，跳过搜索：{keyword}")
                return results
            else:
                if is_imdb:
                    logger.debug(f"【{self.plugin_name}】关键词检查通过（IMDb ID）：{keyword}")
                else:
                    logger.debug(f"【{self.plugin_name}】关键词检查通过：{keyword}")

            # Get site name for logging
            site_name = site.get("name", "Unknown")
            logger.debug(f"【{self.plugin_name}】站点名称：{site_name}")

            # Check if this site belongs to our plugin (matching reference implementation)
            site_name_value = site.get("name", "")
            if not site_name_value:
                logger.warning(f"【{self.plugin_name}】站点名称为空，返回空结果")
                return results

            site_prefix = site_name_value.split("-")[0] if "-" in site_name_value else site_name_value

            if site_prefix != self.plugin_name:
                return results

            logger.debug(f"【{self.plugin_name}】站点匹配成功，准备搜索")
        except Exception as e:
            logger.error(f"【{self.plugin_name}】站点验证异常：{str(e)}\n{traceback.format_exc()}")
            return results

        try:
            # Extract indexer ID from domain (matching reference implementation)
            # Domain format: jackett_indexer.{indexer_id}
            domain = site.get("domain", "")
            if not domain:
                logger.warning(f"【{self.plugin_name}】站点缺少 domain 字段：{site_name}")
                return results

            # Extract indexer ID from domain (matching reference implementation)
            # domain 原始格式: "jackett_indexer.{indexer_id}"
            # 但MoviePilot存储时会转换为URL格式: "http://jackett_indexer.{indexer_id}/"
            # 需要先剥离URL格式，再提取ID
            logger.debug(f"【{self.plugin_name}】准备从domain提取indexer_id，domain={domain}")

            # 剥离URL格式：移除协议前缀和尾部斜杠
            domain_clean = domain.replace("http://", "").replace("https://", "").rstrip("/")
            logger.debug(f"【{self.plugin_name}】清理后的domain：{domain_clean}")

            # 从清理后的domain提取ID（最后一个点后面的部分）
            indexer_id = domain_clean.split(".")[-1]
            logger.debug(f"【{self.plugin_name}】提取结果：indexer_id={indexer_id}")

            if not indexer_id:
                logger.warning(f"【{self.plugin_name}】从domain提取的索引器ID为空：{domain}")
                return results

            logger.debug(f"【{self.plugin_name}】从domain提取索引器ID：{indexer_id}")

            # Build search parameters
            search_params = self._build_search_params(
                keyword=keyword,
                mtype=mtype,
                page=page
            )

            logger.debug(f"【{self.plugin_name}】开始搜索站点：{site_name}，关键词：{keyword}，索引器ID：{indexer_id}")

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
            logger.debug(f"【{self.plugin_name}】开始解析XML内容，长度：{len(xml_content)}")
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
            keyword: Search keyword or IMDb ID
            mtype: Media type for category filtering
            page: Page number

        Returns:
            Dictionary of search parameters
        """
        # Determine categories based on media type
        categories = self._get_categories(mtype)

        # Check if keyword is an IMDb ID (format: tt1234567)
        is_imdb_id = self._is_imdb_id(keyword)

        # Build parameters
        params = {
            "apikey": self._api_key,
            "limit": 100,
            "offset": page * 100 if page else 0,
        }

        # Use IMDb ID search if detected
        if is_imdb_id:
            # For IMDb ID search, use t=movie or t=tvsearch
            if mtype == MediaType.TV:
                params["t"] = "tvsearch"
            else:
                # Default to movie search for IMDb IDs
                params["t"] = "movie"
            params["imdbid"] = keyword
            logger.debug(f"【{self.plugin_name}】检测到IMDb ID搜索：{keyword}，使用 {params['t']} 模式")
        else:
            # Regular keyword search
            params["t"] = "search"
            params["q"] = keyword

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

            # Build query string for debug logging
            from urllib.parse import urlencode
            query_string = urlencode(params)
            full_url = f"{url}?{query_string}"

            logger.debug(f"【{self.plugin_name}】正在搜索 Jackett 索引器 [{indexer_id}]: {full_url}")
            logger.debug(f"【{self.plugin_name}】搜索参数：{params}")

            response = RequestUtils(proxies=self._proxy).get_res(
                url=url,
                params=params,
                timeout=60
            )

            # Check if response is None or False
            if response is None:
                logger.error(f"【{self.plugin_name}】搜索API请求失败：response 为 None")
                return None

            if not response:
                logger.error(f"【{self.plugin_name}】搜索API请求失败：response 为 {type(response)}")
                return None

            # Check if response has required attributes
            if not hasattr(response, 'status_code') or not hasattr(response, 'text'):
                logger.error(f"【{self.plugin_name}】响应对象格式异常：response type={type(response)}, "
                           f"has status_code={hasattr(response, 'status_code')}, "
                           f"has text={hasattr(response, 'text')}")
                return None

            # Check HTTP status code
            if response.status_code != 200:
                logger.error(f"【{self.plugin_name}】搜索API请求失败：HTTP {response.status_code}")
                # Safely get response text
                try:
                    response_text = response.text if hasattr(response, 'text') else ''
                    if response_text:
                        logger.debug(f"【{self.plugin_name}】响应内容：{response_text[:500]}")
                except Exception as e:
                    logger.debug(f"【{self.plugin_name}】无法读取响应文本：{str(e)}")
                return None

            # Get response text
            try:
                xml_content = response.text
                if xml_content is None or xml_content == '':
                    logger.warning(f"【{self.plugin_name}】响应内容为空")
                    return None

                # Check if response is an error
                error_message = self._parse_jackett_error(xml_content)
                if error_message:
                    logger.warning(f"【{self.plugin_name}】索引器 [{indexer_id}] 搜索失败：{error_message}")
                    return None

                logger.debug(f"【{self.plugin_name}】成功获取响应，长度：{len(xml_content)}")
                return xml_content
            except Exception as e:
                logger.error(f"【{self.plugin_name}】读取响应text属性失败：{str(e)}")
                return None

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
            logger.debug(f"【{self.plugin_name}】找到 {len(items)} 个item元素")

            for idx, item in enumerate(items):
                try:
                    torrent_info = self._parse_torznab_item(item, site_name)
                    if torrent_info:
                        results.append(torrent_info)
                        logger.debug(f"【{self.plugin_name}】成功解析item #{idx}: {torrent_info.title[:50]}")
                    else:
                        logger.debug(f"【{self.plugin_name}】item #{idx} 解析结果为 None")
                except Exception as e:
                    logger.warning(f"【{self.plugin_name}】解析item #{idx} 失败：{str(e)}")
                    continue

            logger.debug(f"【{self.plugin_name}】XML解析完成，从 {len(items)} 个item中解析出 {len(results)} 个有效结果")

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
            # Validate item is not None
            if item is None:
                logger.warning(f"【{self.plugin_name}】XML item 为 None，跳过")
                return None

            # Extract basic fields
            title = DomUtils.tag_value(item, "title", default="")
            if not title:
                logger.debug(f"【{self.plugin_name}】跳过无标题的item")
                return None

            # Get download link
            enclosure = ""
            try:
                enclosure_node = item.getElementsByTagName("enclosure")
                if enclosure_node and len(enclosure_node) > 0:
                    enclosure = enclosure_node[0].getAttribute("url")
            except Exception as e:
                logger.debug(f"【{self.plugin_name}】获取enclosure失败：{str(e)}")

            if not enclosure:
                try:
                    enclosure = DomUtils.tag_value(item, "link", default="")
                except Exception as e:
                    logger.debug(f"【{self.plugin_name}】获取link失败：{str(e)}")

            # Try to get magnet link from torznab attributes
            try:
                magnet_url = self._get_torznab_attr(item, "magneturl")
                if magnet_url:
                    enclosure = magnet_url
            except Exception as e:
                logger.debug(f"【{self.plugin_name}】获取magneturl失败：{str(e)}")

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

    def _parse_jackett_error(self, xml_content: str) -> Optional[str]:
        """
        Parse Jackett error XML response and extract friendly error message.

        Args:
            xml_content: XML response string

        Returns:
            Error message string if this is an error response, None otherwise
        """
        try:
            # Quick check if this looks like an error response
            if not xml_content or '<error' not in xml_content:
                return None

            # Parse XML
            dom_tree = xml.dom.minidom.parseString(xml_content)
            root_node = dom_tree.documentElement

            # Check if root node is an error element
            if root_node.tagName != "error":
                return None

            # Extract error information
            error_code = root_node.getAttribute("code")
            error_desc = root_node.getAttribute("description")

            if not error_desc:
                return f"错误代码 {error_code}" if error_code else "未知错误"

            # Extract meaningful error message from stack trace
            # Common patterns:
            # 1. "Exception (indexer-name): actual error message"
            # 2. SSL connection errors
            # 3. Timeout errors
            # 4. Indexer unavailable

            error_lines = error_desc.split('\n')
            first_line = error_lines[0].strip() if error_lines else error_desc

            # Try to extract the root cause
            if "Exception" in first_line and ":" in first_line:
                # Extract message after the exception type
                parts = first_line.split(":", 2)
                if len(parts) >= 2:
                    # Get the actual error message
                    message = parts[-1].strip()

                    # Simplify common error patterns
                    if "SSL connection could not be established" in error_desc or "unexpected EOF" in error_desc:
                        return f"SSL连接失败（{message}）"
                    elif "timeout" in message.lower():
                        return f"请求超时（{message}）"
                    elif "unavailable" in message.lower():
                        return f"索引器不可用（{message}）"
                    else:
                        return message
                else:
                    return first_line
            else:
                # Return first line as-is if no exception pattern found
                return first_line[:200]  # Limit length

        except Exception as e:
            logger.debug(f"【{self.plugin_name}】解析错误响应失败：{str(e)}")
            return None

    @staticmethod
    def _is_imdb_id(keyword: str) -> bool:
        """
        Check if keyword is an IMDb ID (format: tt followed by digits).

        Args:
            keyword: Search keyword to check

        Returns:
            True if keyword is an IMDb ID, False otherwise
        """
        if not keyword:
            return False

        # IMDb ID format: tt followed by at least 7 digits (e.g., tt0133093, tt8289930)
        return bool(re.match(r'^tt\d{7,}$', keyword.strip()))

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
                                            'placeholder': '0 0 */12 * *',
                                            'hint': 'Cron表达式，默认每12小时同步一次索引器',
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
                                            'type': 'warning',
                                            'variant': 'tonal',
                                            'text': '❓ 遇到问题？查看常见问题解答：https://github.com/mitlearn/MoviePilot-PluginsV2#-常见问题'
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
            "cron": "0 0 */12 * *",
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
