# -*- coding: utf-8 -*-
"""
ProwlarrIndexer Plugin for MoviePilot

This plugin integrates Prowlarr indexer search functionality into MoviePilot.
It allows searching across all indexers configured in Prowlarr through a unified interface.

Version: 0.1.0
Author: Claude
"""

import re
import traceback
from typing import List, Dict, Optional, Any, Tuple
from datetime import datetime, timedelta
from urllib.parse import urlencode
import unicodedata

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger

from app.core.context import MediaInfo, TorrentInfo
from app.core.metainfo import MetaInfo
from app.helper.sites import SitesHelper
from app.log import logger
from app.plugins import _PluginBase
from app.schemas.types import MediaType
from app.utils.http import RequestUtils
from app.utils.string import StringUtils


class ProwlarrIndexer(_PluginBase):
    """
    Prowlarr Indexer Plugin

    Provides torrent search functionality through Prowlarr API.
    Registers all configured Prowlarr indexers as MoviePilot sites.
    """

    # Plugin metadata
    plugin_name = "Prowlarr索引器"
    plugin_desc = "集成Prowlarr索引器搜索，支持多站点统一搜索。仅索引私有和半公开站点。"
    plugin_icon = "Prowlarr.png"
    plugin_version = "1.1.0"
    plugin_author = "Claude"
    author_url = "https://github.com"
    plugin_config_prefix = "prowlarrindexer_"
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
    PROWLARR_DOMAIN = "prowlarr_indexer.claude"

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
            filtered_count = 0
            xxx_filtered_count = 0
            for indexer_data in indexers:
                try:
                    indexer_dict = self._build_indexer_dict(indexer_data)

                    # 过滤掉公开站点，保留私有和半公开站点
                    if indexer_dict.get("public", False):
                        indexer_name = indexer_dict.get("name", "Unknown")
                        logger.info(f"【{self.plugin_name}】过滤公开站点：{indexer_name}")
                        filtered_count += 1
                        continue

                    # 需求三：过滤掉只有XXX分类的索引器
                    if self._is_xxx_only_indexer(indexer_data):
                        indexer_name = indexer_dict.get("name", "Unknown")
                        logger.info(f"【{self.plugin_name}】过滤仅XXX分类站点：{indexer_name}")
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
                    logger.info(f"【{self.plugin_name}】成功添加到站点管理：{indexer.get('name')} (domain: {domain})")
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

        需求一：只获取已启用且已认证的索引器

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

            # 需求一：只获取已启用的索引器（表示已在Prowlarr中认证配置）
            enabled_indexers = [idx for idx in indexers if idx.get("enable", False)]
            logger.info(f"【{self.plugin_name}】获取到 {len(enabled_indexers)} 个已启用的索引器（总计 {len(indexers)} 个）")

            # Debug log first few indexers
            for idx in enabled_indexers[:3]:
                privacy = idx.get("privacy", 1)
                privacy_str = {0: "公开", 1: "私有", 2: "半私有"}.get(privacy, "未知")
                logger.debug(f"【{self.plugin_name}】索引器示例：id={idx.get('id')}, name={idx.get('name')}, 类型={privacy_str}")

            return enabled_indexers

        except Exception as e:
            logger.error(f"【{self.plugin_name}】获取索引器列表异常：{str(e)}\n{traceback.format_exc()}")
            return []

    def _get_indexer_categories(self, indexer_id: int) -> Optional[Dict[str, List[Dict[str, Any]]]]:
        """
        Get indexer categories from Prowlarr API and convert to MoviePilot format.

        Args:
            indexer_id: Prowlarr indexer ID

        Returns:
            Category dictionary in MoviePilot format or None
        """
        try:
            # Get indexer capabilities from Prowlarr API
            url = f"{self._host}/api/v1/indexer/{indexer_id}"
            headers = {
                "X-Api-Key": self._api_key,
                "Content-Type": "application/json",
                "Accept": "application/json"
            }

            response = RequestUtils(
                headers=headers,
                proxies=self._proxy
            ).get_res(url, timeout=15)

            if not response or response.status_code != 200:
                logger.debug(f"【{self.plugin_name}】无法获取索引器 {indexer_id} 的分类信息")
                return None

            try:
                indexer_detail = response.json()
            except Exception as e:
                logger.debug(f"【{self.plugin_name}】解析索引器 {indexer_id} 详细信息失败：{str(e)}")
                return None

            # Get capabilities -> categories
            capabilities = indexer_detail.get("capabilities", {})
            if not capabilities:
                return None

            categories = capabilities.get("categories", [])
            if not categories:
                return None

            # Convert Prowlarr categories to MoviePilot format
            # Torznab categories: 2000=Movies, 5000=TV, 6000=XXX, etc.
            category_map = {
                "movie": [],
                "tv": []
            }

            for cat in categories:
                if not isinstance(cat, dict):
                    continue

                cat_id = cat.get("id")
                cat_name = cat.get("name", "")

                if not cat_id:
                    continue

                try:
                    cat_num = int(cat_id)
                    top_level = (cat_num // 1000) * 1000

                    # Build category entry
                    cat_entry = {
                        "id": cat_id,
                        "cat": cat_name,
                        "desc": cat_name
                    }

                    # Map to movie or tv based on top-level category
                    if top_level == 2000:  # Movies
                        category_map["movie"].append(cat_entry)
                    elif top_level == 5000:  # TV
                        category_map["tv"].append(cat_entry)
                    # Skip 6000 (XXX) and other categories

                except (ValueError, TypeError):
                    continue

            # Return None if no movie/tv categories found
            if not category_map["movie"] and not category_map["tv"]:
                return None

            # Remove empty categories
            result = {}
            if category_map["movie"]:
                result["movie"] = category_map["movie"]
            if category_map["tv"]:
                result["tv"] = category_map["tv"]

            if result:
                logger.debug(f"【{self.plugin_name}】索引器 {indexer_id} 分类：movie={len(result.get('movie', []))}, tv={len(result.get('tv', []))}")

            return result if result else None

        except Exception as e:
            logger.debug(f"【{self.plugin_name}】获取索引器 {indexer_id} 分类信息异常：{str(e)}")
            return None

    def _is_xxx_only_indexer(self, indexer_data: Dict[str, Any]) -> bool:
        """
        Check if indexer only supports XXX (adult) categories.

        Args:
            indexer_data: Prowlarr indexer data dictionary

        Returns:
            True if indexer only has XXX categories (6000 series), False otherwise
        """
        try:
            indexer_id = indexer_data.get("id")
            if not indexer_id:
                return False

            # Get indexer capabilities from Prowlarr API
            url = f"{self._host}/api/v1/indexer/{indexer_id}"
            headers = {
                "X-Api-Key": self._api_key,
                "Content-Type": "application/json",
                "Accept": "application/json"
            }

            response = RequestUtils(
                headers=headers,
                proxies=self._proxy
            ).get_res(url, timeout=15)

            if not response or response.status_code != 200:
                logger.debug(f"【{self.plugin_name}】无法获取索引器 {indexer_id} 的详细信息")
                return False

            try:
                indexer_detail = response.json()
            except Exception as e:
                logger.debug(f"【{self.plugin_name}】解析索引器 {indexer_id} 详细信息失败：{str(e)}")
                return False

            # Get capabilities -> categories
            capabilities = indexer_detail.get("capabilities", {})
            if not capabilities:
                logger.debug(f"【{self.plugin_name}】索引器 {indexer_id} 无capabilities信息")
                return False

            categories = capabilities.get("categories", [])
            if not categories:
                logger.debug(f"【{self.plugin_name}】索引器 {indexer_id} 无分类信息")
                return False

            # Extract all top-level category IDs
            category_ids = set()
            for cat in categories:
                if isinstance(cat, dict):
                    cat_id = cat.get("id")
                    if cat_id:
                        try:
                            cat_num = int(cat_id)
                            # Get top-level category (first digit determines main category)
                            # 2000 = Movies, 5000 = TV, 6000 = XXX, etc.
                            top_level = (cat_num // 1000) * 1000
                            category_ids.add(top_level)
                        except (ValueError, TypeError):
                            continue

            if not category_ids:
                return False

            # Check if ONLY 6000 (XXX) category exists
            is_xxx_only = category_ids == {6000}

            if is_xxx_only:
                indexer_name = indexer_data.get("name", "Unknown")
                logger.debug(f"【{self.plugin_name}】索引器 {indexer_name} 仅包含XXX分类：{category_ids}")

            return is_xxx_only

        except Exception as e:
            logger.debug(f"【{self.plugin_name}】检查索引器XXX分类失败：{str(e)}")
            return False

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

        # Build domain identifier (matching ProwlarrExtend reference implementation)
        # Replace author part with indexer_id: "prowlarr_indexer.claude" -> "prowlarr_indexer.{indexer_id}"
        domain = self.PROWLARR_DOMAIN.replace(self.plugin_author.lower(), str(indexer_id))

        # Detect if indexer is public or private
        # Prowlarr privacy: 0 = public, 1 = private, 2 = semi-private
        # 只过滤公开站点，保留私有和半公开站点
        privacy = indexer.get("privacy", 1)
        is_public = privacy == 0  # 0=公开

        # Log privacy detection and domain generation
        privacy_str = {0: "公开", 1: "私有", 2: "半私有"}.get(privacy, "未知")
        logger.debug(f"【{self.plugin_name}】索引器 {indexer_name} 隐私级别：{privacy_str} (privacy={privacy})")
        logger.debug(f"【{self.plugin_name}】生成domain：{domain}，indexer_id={indexer_id} (类型：{type(indexer_id)})")

        # Get category information from indexer
        category = self._get_indexer_categories(indexer_id)

        # Build indexer dictionary (matching ProwlarrExtend reference implementation)
        indexer_dict = {
            "id": f"{self.plugin_name}-{indexer_name}",
            "name": f"{self.plugin_name}-{indexer_name}",
            "url": f"{self._host.rstrip('/')}/api/v1/indexer/{indexer_id}",
            "domain": domain,
            "public": is_public,
            "proxy": False,
        }

        # Add category if available
        if category:
            indexer_dict["category"] = category

        return indexer_dict

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

        Note: 站点连通性测试无法通过 get_module 劫持，因为 MoviePilot 使用
        SiteChain.test() 方法进行测试。test_connection 方法仅用于内部调用。

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
        Test Prowlarr indexer connectivity.

        This method replaces the default site connectivity test for Prowlarr indexers.
        Instead of testing the fake domain, it tests the actual Prowlarr server.

        Args:
            site: Site/indexer information dictionary

        Returns:
            Tuple of (success: bool, message: str)
        """
        site_name = site.get("name", "Unknown") if site else "Unknown"
        logger.info(f"【{self.plugin_name}】开始测试站点连通性：{site_name}")

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
            indexer_id_str = domain_clean.split(".")[-1]

            if not indexer_id_str or not indexer_id_str.isdigit():
                return False, "无法从 domain 提取索引器 ID"

            indexer_id = int(indexer_id_str)
            logger.debug(f"【{self.plugin_name}】测试索引器 {indexer_id} 的连通性")

            # Test Prowlarr API connectivity by getting indexer details
            url = f"{self._host}/api/v1/indexer/{indexer_id}"
            headers = {
                "X-Api-Key": self._api_key,
                "Content-Type": "application/json",
                "Accept": "application/json"
            }

            response = RequestUtils(
                headers=headers,
                proxies=self._proxy
            ).get_res(url, timeout=10)

            if not response:
                logger.warning(f"【{self.plugin_name}】站点 {site_name} 连通性测试失败：无响应")
                return False, f"Prowlarr 服务器无响应"

            if response.status_code == 404:
                logger.warning(f"【{self.plugin_name}】站点 {site_name} 连通性测试失败：索引器不存在")
                return False, f"索引器不存在（可能已被删除）"

            if response.status_code != 200:
                logger.warning(f"【{self.plugin_name}】站点 {site_name} 连通性测试失败：HTTP {response.status_code}")
                return False, f"Prowlarr 返回错误：HTTP {response.status_code}"

            # Parse JSON response
            try:
                indexer_data = response.json()
                if not isinstance(indexer_data, dict):
                    return False, "Prowlarr 响应格式错误"

                # Check if indexer is enabled
                is_enabled = indexer_data.get("enable", False)
                if not is_enabled:
                    logger.warning(f"【{self.plugin_name}】站点 {site_name} 已被禁用")
                    return False, "索引器已在 Prowlarr 中被禁用"

            except Exception as e:
                logger.warning(f"【{self.plugin_name}】站点 {site_name} 连通性测试失败：JSON解析错误")
                return False, f"Prowlarr 响应格式错误"

            logger.info(f"【{self.plugin_name}】站点 {site_name} 连通性测试成功")
            return True, f"Prowlarr 索引器连接正常"

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

        # 搜索发起日志（INFO级别）
        site_name = site.get("name", "Unknown") if site else "Unknown"
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

            # Filter non-English keywords (Jackett/Prowlarr work best with English)
            if not self._is_english_keyword(keyword):
                logger.info(f"【{self.plugin_name}】检测到非英文关键词，跳过搜索：{keyword}")
                return results
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
            logger.debug(f"【{self.plugin_name}】站点前缀：'{site_prefix}', 插件名称：'{self.plugin_name}', 匹配：{site_prefix == self.plugin_name}")

            if site_prefix != self.plugin_name:
                logger.debug(f"【{self.plugin_name}】站点不属于本插件（站点：{site_prefix}，插件：{self.plugin_name}），跳过")
                return results

            logger.debug(f"【{self.plugin_name}】站点匹配成功，准备搜索")
        except Exception as e:
            logger.error(f"【{self.plugin_name}】参数验证异常：{str(e)}\n{traceback.format_exc()}")
            return results

        try:
            # Extract indexer ID from domain (matching reference implementation)
            # Domain format: prowlarr_indexer.{indexer_id}
            domain = site.get("domain", "")
            if not domain:
                logger.warning(f"【{self.plugin_name}】站点缺少 domain 字段：{site_name}")
                return results

            # Extract indexer ID from domain (matching reference implementation)
            # domain 原始格式: "prowlarr_indexer.{indexer_id}"
            # 但MoviePilot存储时会转换为URL格式: "http://prowlarr_indexer.{indexer_id}/"
            # 需要先剥离URL格式，再提取ID
            logger.debug(f"【{self.plugin_name}】准备从domain提取indexer_id，domain={domain}")

            # 剥离URL格式：移除协议前缀和尾部斜杠
            domain_clean = domain.replace("http://", "").replace("https://", "").rstrip("/")
            logger.debug(f"【{self.plugin_name}】清理后的domain：{domain_clean}")

            # 从清理后的domain提取ID（最后一个点后面的部分）
            indexer_id_str = domain_clean.split(".")[-1]
            logger.debug(f"【{self.plugin_name}】提取结果：indexer_id_str={indexer_id_str}")

            if not indexer_id_str or not indexer_id_str.isdigit():
                logger.warning(f"【{self.plugin_name}】从domain提取的索引器ID无效：{domain} -> '{indexer_id_str}'")
                return results

            indexer_id = int(indexer_id_str)
            logger.debug(f"【{self.plugin_name}】从domain提取索引器ID：{indexer_id}")

            # Build search parameters
            search_params = self._build_search_params(
                keyword=keyword,
                indexer_id=indexer_id,
                mtype=mtype,
                page=page
            )

            # Execute search API call
            api_results = self._search_prowlarr_api(search_params)

            # Validate API results
            if not isinstance(api_results, list):
                logger.error(f"【{self.plugin_name}】API返回了非列表类型的结果：{type(api_results)}")
                return results

            # Parse results to TorrentInfo
            logger.debug(f"【{self.plugin_name}】开始解析 {len(api_results)} 条API结果")
            for idx, item in enumerate(api_results):
                try:
                    if item is None:
                        logger.warning(f"【{self.plugin_name}】跳过空项目 #{idx}")
                        continue

                    torrent_info = self._parse_torrent_info(item, site_name)
                    if torrent_info:
                        results.append(torrent_info)
                        logger.debug(f"【{self.plugin_name}】成功解析项目 #{idx}: {torrent_info.title[:50]}")
                    else:
                        logger.debug(f"【{self.plugin_name}】项目 #{idx} 解析结果为 None")
                except Exception as e:
                    logger.error(f"【{self.plugin_name}】解析种子信息失败 #{idx}：{str(e)}\n{traceback.format_exc()}")
                    continue

            logger.info(f"【{self.plugin_name}】搜索完成：{site_name} 从 {len(api_results)} 条原始结果中解析出 {len(results)} 个有效结果")

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

            logger.info(f"【{self.plugin_name}】API请求：{url}")
            logger.debug(f"【{self.plugin_name}】搜索参数：{params}")

            response = RequestUtils(
                headers=headers,
                proxies=self._proxy
            ).get_res(url, timeout=60)

            # Check if response is None or False
            if response is None:
                logger.error(f"【{self.plugin_name}】搜索API请求失败：response 为 None")
                return []

            if not response:
                logger.error(f"【{self.plugin_name}】搜索API请求失败：response 为 {type(response)}")
                return []

            # Check if response has required attributes
            if not hasattr(response, 'status_code'):
                logger.error(f"【{self.plugin_name}】响应对象格式异常：response type={type(response)}, "
                           f"has status_code={hasattr(response, 'status_code')}")
                return []

            # Check HTTP status code
            if response.status_code != 200:
                logger.error(f"【{self.plugin_name}】搜索API请求失败：HTTP {response.status_code}")
                # Safely get response text
                try:
                    response_text = response.text if hasattr(response, 'text') else ''
                    if response_text:
                        logger.debug(f"【{self.plugin_name}】响应内容：{response_text}")
                except Exception as e:
                    logger.debug(f"【{self.plugin_name}】无法读取响应文本：{str(e)}")
                return []

            # Parse JSON response
            try:
                if not hasattr(response, 'json'):
                    logger.error(f"【{self.plugin_name}】响应对象没有json方法")
                    return []

                data = response.json()
                if data is None:
                    logger.warning(f"【{self.plugin_name}】JSON解析结果为 None")
                    return []

                logger.debug(f"【{self.plugin_name}】成功解析JSON，类型：{type(data)}")
            except Exception as e:
                logger.error(f"【{self.plugin_name}】解析搜索结果JSON失败：{str(e)}")
                try:
                    response_text = response.text if hasattr(response, 'text') else ''
                    logger.debug(f"【{self.plugin_name}】原始响应：{response_text[:500]}")
                except:
                    pass
                return []

            if not isinstance(data, list):
                logger.error(f"【{self.plugin_name}】API返回格式错误：期望列表，得到 {type(data)}")
                return []

            logger.debug(f"【{self.plugin_name}】成功获取 {len(data)} 条搜索结果")
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
            # Validate item is not None
            if item is None:
                logger.warning(f"【{self.plugin_name}】item 为 None，跳过")
                return None

            # Validate item is a dictionary
            if not isinstance(item, dict):
                logger.error(f"【{self.plugin_name}】种子信息格式错误：期望字典，得到 {type(item)}")
                return None

            # Extract required fields with safe get
            title = item.get("title", "") if item else ""
            if not title:
                logger.debug(f"【{self.plugin_name}】跳过无标题的结果")
                return None

            # Get download URL (prefer direct download over magnet)
            download_url = item.get("downloadUrl", "") if item else ""
            magnet_url = item.get("magnetUrl", "") if item else ""
            enclosure = download_url or magnet_url
            if not enclosure:
                logger.debug(f"【{self.plugin_name}】跳过无下载链接的结果：{title}")
                return None

            # Parse indexer flags (Prowlarr returns a list/array)
            # Prowlarr indexerFlags常见值：
            # 1 = G_Freeleech (免费)
            # 4 = G_Halfleech (半价)
            # 8 = G_DoubleUpload (双倍上传)
            # 32 = G_PersonalFreeleech (个人免费)
            indexer_flags = item.get("indexerFlags", [])
            download_volume_factor = 1.0
            upload_volume_factor = 1.0

            if isinstance(indexer_flags, list):
                # Freeleech (完全免费)
                if 1 in indexer_flags or 32 in indexer_flags:
                    download_volume_factor = 0.0
                # Halfleech (半价)
                elif 4 in indexer_flags:
                    download_volume_factor = 0.5

                # DoubleUpload (双倍上传)
                if 8 in indexer_flags:
                    upload_volume_factor = 2.0
            elif isinstance(indexer_flags, int):
                # 兼容整数格式（位运算）
                if indexer_flags & 1 or indexer_flags & 32:  # Freeleech
                    download_volume_factor = 0.0
                elif indexer_flags & 4:  # Halfleech
                    download_volume_factor = 0.5

                if indexer_flags & 8:  # DoubleUpload
                    upload_volume_factor = 2.0

            # 记录促销信息（仅在有促销时）
            if download_volume_factor < 1.0 or upload_volume_factor > 1.0:
                promo_info = []
                if download_volume_factor == 0.0:
                    promo_info.append("免费")
                elif download_volume_factor == 0.5:
                    promo_info.append("半价")
                if upload_volume_factor == 2.0:
                    promo_info.append("2X上传")
                logger.debug(f"【{self.plugin_name}】种子促销：{title[:50]}... -> {', '.join(promo_info)}")

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
                downloadvolumefactor=download_volume_factor,
                uploadvolumefactor=upload_volume_factor,
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
                "description": "返回所有已注册的 Prowlarr 索引器"
            }
        ]
