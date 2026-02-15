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

from typing import Type
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger

from app.core.context import MediaInfo, TorrentInfo
from app.core.event import eventmanager, Event
from app.core.metainfo import MetaInfo
from app.helper.sites import SitesHelper
from app.log import logger
from app.plugins import _PluginBase
from app.schemas.types import MediaType, EventType
from app.utils.http import RequestUtils
from app.utils.string import StringUtils

from .agenttool import SearchTorrentsTool, ListIndexersTool


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
    plugin_version = "1.5.0"
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
                    indexer_dict, is_xxx_only = self._build_indexer_dict(indexer_data)

                    # 过滤掉公开站点，保留私有和半公开站点
                    if indexer_dict.get("public", False):
                        logger.info(f"【{self.plugin_name}】过滤公开站点：{indexer_dict.get('name', 'Unknown')}")
                        filtered_count += 1
                        continue

                    # 过滤掉只有XXX分类的索引器
                    if is_xxx_only:
                        logger.debug(f"【{self.plugin_name}】过滤仅XXX分类站点：{indexer_dict.get('name', 'Unknown')}")
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
                privacy = idx.get("privacy", "private")
                privacy_str = {"public": "公开", "private": "私有", "semiPrivate": "半私有"}.get(privacy, f"未知({privacy})")
                logger.debug(f"【{self.plugin_name}】索引器示例：id={idx.get('id')}, name={idx.get('name')}, 类型={privacy_str}")

            return enabled_indexers

        except Exception as e:
            logger.error(f"【{self.plugin_name}】获取索引器列表异常：{str(e)}\n{traceback.format_exc()}")
            return []

    def _get_indexer_categories(self, indexer_name: int) -> Tuple[Optional[Dict[str, List[Dict[str, Any]]]], bool]:
        """
        Get indexer categories from Prowlarr API and convert to MoviePilot format.

        Args:
            indexer_name: Prowlarr indexer ID

        Returns:
            Tuple of (Category dictionary in MoviePilot format or None, is_xxx_only)
        """
        try:
            # Get indexer capabilities from Prowlarr API
            url = f"{self._host}/api/v1/indexer/{indexer_name}"
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
                logger.debug(f"【{self.plugin_name}】无法获取索引器 {indexer_name} 的分类信息")
                return None, False

            try:
                indexer_detail = response.json()
            except Exception as e:
                logger.debug(f"【{self.plugin_name}】解析索引器 {indexer_name} 详细信息失败：{str(e)}")
                return None, False

            # Get capabilities -> categories
            capabilities = indexer_detail.get("capabilities", {})
            if not capabilities:
                return None, False

            categories = capabilities.get("categories", [])
            if not categories:
                return None, False

            # Convert Prowlarr categories to MoviePilot format
            # Torznab categories: 2000=Movies, 5000=TV, 6000=XXX, etc.
            category_map = {
                "movie": [],
                "tv": []
            }

            # Track all top-level categories to detect XXX-only indexers
            top_level_categories = set()

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
                    top_level_categories.add(top_level)

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

            # Check if indexer is XXX-only (has 6000 but no other useful categories)
            # Only filter pure XXX sites, keep Music/Audio/etc sites
            has_xxx = 6000 in top_level_categories
            has_other_content = any(cat in top_level_categories for cat in [2000, 5000, 3000, 4000, 1000, 7000, 8000])

            is_xxx_only = has_xxx and not has_other_content

            if is_xxx_only:
                logger.debug(f"【{self.plugin_name}】索引器 {indexer_name} 仅包含XXX分类，顶层分类：{sorted(top_level_categories)}")
                return None, True

            # If indexer has no movie/tv categories, still allow it (might be Music, Audio, etc.)
            # Just don't add movie/tv category info
            if not category_map["movie"] and not category_map["tv"]:
                logger.debug(f"【{self.plugin_name}】索引器 {indexer_name} 无电影/电视分类（可能是音乐/其他类型站点），顶层分类：{sorted(top_level_categories)}")
                # Return None for category but False for is_xxx_only (allow the indexer)
                return None, False

            # Remove empty categories
            result = {}
            if category_map["movie"]:
                result["movie"] = category_map["movie"]
            if category_map["tv"]:
                result["tv"] = category_map["tv"]

            if result:
                logger.debug(f"【{self.plugin_name}】索引器 {indexer_name} 分类：movie={len(result.get('movie', []))}, tv={len(result.get('tv', []))}")

            return (result if result else None), False

        except Exception as e:
            logger.debug(f"【{self.plugin_name}】获取索引器 {indexer_name} 分类信息异常：{str(e)}")
            return None, False

    def _build_indexer_dict(self, indexer: Dict[str, Any]) -> Tuple[Dict[str, Any], bool]:
        """
        Build MoviePilot indexer dictionary from Prowlarr indexer data.

        Args:
            indexer: Prowlarr indexer dictionary

        Returns:
            Tuple of (MoviePilot compatible indexer dictionary, is_xxx_only)
        """
        indexer_name = indexer.get("id")
        indexer_title = indexer.get("name", str(indexer_name))

        # Build domain identifier (matching ProwlarrExtend reference implementation)
        # Replace author part with indexer_name: "prowlarr_indexer.claude" -> "prowlarr_indexer.{indexer_name}"
        domain = self.PROWLARR_DOMAIN.replace(self.plugin_author.lower(), str(indexer_name))

        # Detect if indexer is public or private
        # Prowlarr privacy: "public" = 公开, "private" = 私有, "semiPrivate" = 半私有
        # 只过滤公开站点，保留私有和半公开站点
        privacy = indexer.get("privacy", "private")
        is_public = (privacy == "public")  # "public"=公开

        # Log privacy detection and domain generation
        privacy_str = {"public": "公开", "private": "私有", "semiPrivate": "半私有"}.get(privacy, f"未知({privacy})")
        logger.debug(f"【{self.plugin_name}】索引器 {indexer_title} 隐私级别：{privacy_str} (privacy={privacy})")
        logger.debug(f"【{self.plugin_name}】生成domain：{domain}，indexer_name={indexer_name} (类型：{type(indexer_name).__name__})")

        # Get category information from indexer and check if XXX-only
        category, is_xxx_only = self._get_indexer_categories(indexer_name)

        # Build indexer dictionary (matching ProwlarrExtend reference implementation)
        indexer_dict = {
            "id": f"{self.plugin_name}-{indexer_title}",
            "name": f"{self.plugin_name}-{indexer_title}",
            "url": f"{self._host.rstrip('/')}/api/v1/indexer/{indexer_name}",
            "domain": domain,
            "public": is_public,
            "privacy": privacy,  # 存储原始隐私类型
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
        # Initialize results
        results = []

        # Validate inputs first
        if site is None or not isinstance(site, dict):
            logger.debug(f"【{self.plugin_name}】站点参数无效")
            return results

        if not keyword:
            logger.debug(f"【{self.plugin_name}】关键词为空")
            return results

        # Extract site name
        site_name = site.get("name", "")
        if not site_name:
            logger.warning(f"【{self.plugin_name}】站点名称为空")
            return results

        # Check if this site belongs to our plugin
        site_prefix = site_name.split("-")[0] if "-" in site_name else site_name
        if site_prefix != self.plugin_name:
            return results

        logger.info(f"【{self.plugin_name}】开始检索站点：{site_name}，关键词：{keyword}")

        try:
            # Check if keyword is IMDb ID (IMDb IDs are always valid)
            is_imdb = self._is_imdb_id(keyword)

            # Filter non-English keywords (Jackett/Prowlarr work best with English)
            if not is_imdb and not self._is_english_keyword(keyword):
                logger.debug(f"【{self.plugin_name}】检测到非英文关键词，跳过搜索：{keyword}")
                return results


            # Extract indexer ID from domain (matching reference implementation)
            # Domain format: prowlarr_indexer.{indexer_name}
            domain = site.get("domain", "")
            if not domain:
                logger.warning(f"【{self.plugin_name}】站点缺少 domain 字段：{site_name}")
                return results

            # Extract indexer ID from domain (matching reference implementation)
            # domain 原始格式: "prowlarr_indexer.{indexer_name}"
            # 但MoviePilot存储时会转换为URL格式: "http://prowlarr_indexer.{indexer_name}/"
            # 需要先剥离URL格式，再提取ID
            logger.debug(f"【{self.plugin_name}】准备从domain提取indexer_name，domain={domain}")

            # 剥离URL格式：移除协议前缀和尾部斜杠
            domain_clean = domain.replace("http://", "").replace("https://", "").rstrip("/")
            logger.debug(f"【{self.plugin_name}】清理后的domain：{domain_clean}")

            # 从清理后的domain提取ID（最后一个点后面的部分）
            indexer_name_str = domain_clean.split(".")[-1]
            logger.debug(f"【{self.plugin_name}】提取结果：indexer_name_str={indexer_name_str}")

            if not indexer_name_str or not indexer_name_str.isdigit():
                logger.warning(f"【{self.plugin_name}】从domain提取的索引器ID无效：{domain} -> '{indexer_name_str}'")
                return results

            indexer_name = int(indexer_name_str)
            logger.debug(f"【{self.plugin_name}】从domain提取索引器ID：{indexer_name}")

            # Build search parameters
            search_params = self._build_search_params(
                keyword=keyword,
                indexer_name=indexer_name,
                mtype=mtype,
                page=page
            )

            logger.debug(f"【{self.plugin_name}】开始搜索站点：{site_name}，关键词：{keyword}，索引器ID：{indexer_name}")

            # Execute search API call
            api_results = self._search_prowlarr_api(search_params, indexer_name)

            # Validate API results
            if not isinstance(api_results, list):
                logger.error(f"【{self.plugin_name}】API返回了非列表类型的结果：{type(api_results)}")
                return results

            # Parse results to TorrentInfo
            logger.debug(f"【{self.plugin_name}】索引器 [{indexer_name}] 开始解析 {len(api_results)} 条API结果")
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
        indexer_name: int,
        mtype: Optional[MediaType] = None,
        page: int = 0
    ) -> Dict[str, Any]:
        """
        Build Prowlarr API search parameters.

        Args:
            keyword: Search keyword or IMDb ID
            indexer_name: Prowlarr indexer ID
            mtype: Media type for category filtering
            page: Page number

        Returns:
            Dictionary of search parameters
        """
        # Determine categories based on media type
        categories = self._get_categories(mtype)

        # Check if keyword is an IMDb ID (format: tt1234567)
        is_imdb_id = self._is_imdb_id(keyword)

        # Build parameter list (supports multiple category parameters)
        params = [
            ("indexerIds", indexer_name),
            ("type", "search"),
            ("limit", 100),
            ("offset", page * 100 if page else 0),
        ]

        # Use IMDb ID search if detected
        if is_imdb_id:
            # Extract numeric part from IMDb ID (tt1234567 -> 1234567)
            imdb_numeric = keyword[2:] if keyword.startswith("tt") else keyword
            params.append(("imdbId", imdb_numeric))
            logger.debug(f"【{self.plugin_name}】检测到IMDb ID搜索：{keyword}，使用 imdbId={imdb_numeric}")
        else:
            # Regular keyword search
            params.append(("query", keyword))

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

    def _search_prowlarr_api(self, params: List[Tuple[str, Any]], indexer_name: int = None) -> List[Dict[str, Any]]:
        """
        Execute Prowlarr API search request.

        Args:
            params: List of (key, value) tuples for query parameters
            indexer_name: Prowlarr indexer ID (for error logging)

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

            logger.debug(f"【{self.plugin_name}】正在搜索 Prowlarr API: {url}")
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
                indexer_info = f"索引器 [{indexer_name}] " if indexer_name else ""
                logger.error(f"【{self.plugin_name}】{indexer_info}搜索API请求失败：HTTP {response.status_code}")
                # Try to parse error message from response
                try:
                    error_data = response.json() if hasattr(response, 'json') else None
                    if error_data and isinstance(error_data, dict):
                        error_message = self._parse_prowlarr_error(error_data)
                        if error_message:
                            logger.warning(f"【{self.plugin_name}】{indexer_info}搜索失败：{error_message}")
                except:
                    pass
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

            # Check if response is an error object (dict with message field)
            if isinstance(data, dict):
                indexer_info = f"索引器 [{indexer_name}] " if indexer_name else ""
                error_message = self._parse_prowlarr_error(data)
                if error_message:
                    logger.warning(f"【{self.plugin_name}】{indexer_info}搜索失败：{error_message}")
                    return []
                # If not an error but still a dict, it's unexpected
                logger.error(f"【{self.plugin_name}】{indexer_info}API返回格式错误：期望列表，得到字典")
                return []

            if not isinstance(data, list):
                logger.error(f"【{self.plugin_name}】API返回格式错误：期望列表，得到 {type(data)}")
                return []

            indexer_info = f"索引器 [{indexer_name}] " if indexer_name else ""
            logger.debug(f"【{self.plugin_name}】{indexer_info}成功获取 {len(data)} 条搜索结果")
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

            # Parse indexer flags (Prowlarr returns a string array)
            # Prowlarr indexerFlags 常见字符串值：
            # "g_freeleech" / "freeleech" = 免费下载
            # "g_halfleech" / "halfleech" = 半价下载
            # "g_doubleupload" / "doubleupload" = 双倍上传
            # "g_internal" / "internal" = 内部发布
            indexer_flags = item.get("indexerFlags", [])
            download_volume_factor = 1.0
            upload_volume_factor = 1.0

            if isinstance(indexer_flags, list) and indexer_flags:
                # Convert all flags to lowercase for case-insensitive comparison
                flags_lower = [str(flag).lower() for flag in indexer_flags]

                # Check for freeleech variants
                freeleech_flags = ["g_freeleech", "freeleech", "g_personalfreeleech", "personalfreeleech"]
                halfleech_flags = ["g_halfleech", "halfleech"]
                doubleupload_flags = ["g_doubleupload", "doubleupload"]

                # Freeleech (完全免费)
                if any(flag in flags_lower for flag in freeleech_flags):
                    download_volume_factor = 0.0
                # Halfleech (半价)
                elif any(flag in flags_lower for flag in halfleech_flags):
                    download_volume_factor = 0.5

                # DoubleUpload (双倍上传)
                if any(flag in flags_lower for flag in doubleupload_flags):
                    upload_volume_factor = 2.0

                # 记录所有标志用于调试
                if flags_lower:
                    logger.debug(f"【{self.plugin_name}】种子标志：{title[:50]}... -> flags={flags_lower}")
            elif isinstance(indexer_flags, int):
                # 兼容旧版数字格式（位运算）
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

    def _parse_prowlarr_error(self, error_data: Dict[str, Any]) -> Optional[str]:
        """
        Parse Prowlarr error JSON response and extract error message.

        Args:
            error_data: Error response dictionary

        Returns:
            Error message string if this is an error response, None otherwise
        """
        try:
            # Check if this is an error response (has 'message' field)
            if not isinstance(error_data, dict):
                return None

            message = error_data.get("message", "")

            # If no message field, this is not an error response
            if not message:
                return None

            # Return the message directly without translation
            return message.strip()

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
                                            'border': 'start',
                                            'title': '配置步骤',
                                            'text': '① 填写Prowlarr服务器地址和API密钥 → ② 保存并启用「立即运行一次」同步索引器 → ③ 在「站点管理」中添加站点（使用插件详情页的domain作为站点地址）'
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
                                            'border': 'start',
                                            'title': '获取API密钥',
                                            'text': '在Prowlarr中打开「设置 → 通用 → 安全 → API密钥」即可查看和复制。'
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
                                            'type': 'success',
                                            'variant': 'tonal',
                                            'border': 'start',
                                            'text': '📖 使用说明：https://github.com/mitlearn/MoviePilot-PluginsV2#-快速开始\n❓ 常见问题：https://github.com/mitlearn/MoviePilot-PluginsV2#-常见问题'
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

        # Build headers
        headers = [
            {'title': '索引器名称', 'key': 'name', 'sortable': True},
            {'title': '站点domain', 'key': 'domain', 'sortable': True},
            {'title': '隐私类型', 'key': 'privacy', 'sortable': True}
        ]

        # Build table items
        items = []
        if self._indexers:
            for site in self._indexers:
                # 根据隐私类型显示对应文字
                privacy = site.get("privacy", "private")
                if privacy == "public":
                    privacy_text = "公开"
                elif privacy == "semiPrivate":
                    privacy_text = "半私有"
                else:  # private 或其他
                    privacy_text = "私有"

                items.append({
                    'name': site.get("name", "Unknown"),
                    'domain': site.get("domain", "N/A"),
                    'privacy': privacy_text
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
                        'props': {'cols': 12},
                        'content': [
                            {
                                'component': 'VCard',
                                'props': {
                                    'class': 'pa-0'
                                },
                                'content': [
                                    {
                                        'component': 'VCardText',
                                        'content': [
                                            {
                                                'component': 'VDataTableVirtual',
                                                'props': {
                                                    'class': 'text-sm',
                                                    'headers': headers,
                                                    'items': items,
                                                    'height': '30rem',
                                                    'density': 'compact',
                                                    'fixed-header': True,
                                                    'hide-no-data': True,
                                                    'hover': True
                                                }
                                            }
                                        ]
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

    def api_search(self, keyword: str, indexer_id: int = None, mtype: str = None, page: int = 0) -> List[Dict[str, Any]]:
        """
        API搜索端点：搜索种子资源

        Args:
            keyword: 搜索关键词（必填）
            indexer_id: Prowlarr索引器ID（可选，不填则搜索所有索引器）
            mtype: 媒体类型，movie或tv（可选）
            page: 页码，默认0

        Returns:
            种子信息列表，每个种子包含：title, size, seeders, peers, page_url, enclosure等字段
        """
        if not self._enabled:
            return []

        if not keyword:
            return []

        # 转换媒体类型字符串为MediaType枚举
        media_type = None
        if mtype:
            if mtype.lower() == "movie":
                media_type = MediaType.MOVIE
            elif mtype.lower() == "tv":
                media_type = MediaType.TV

        results = []

        # 如果指定了索引器ID，只搜索该索引器
        if indexer_id:
            # 查找对应的索引器
            target_indexer = None
            for indexer in self._indexers:
                domain = indexer.get("domain", "")
                # 从domain中提取索引器ID
                domain_clean = domain.replace("http://", "").replace("https://", "").rstrip("/")
                idx_id_str = domain_clean.split(".")[-1]
                if idx_id_str.isdigit() and int(idx_id_str) == indexer_id:
                    target_indexer = indexer
                    break

            if target_indexer:
                torrents = self.search_torrents(target_indexer, keyword, media_type, page)
                results.extend(torrents)
        else:
            # 搜索所有索引器
            for indexer in self._indexers:
                try:
                    torrents = self.search_torrents(indexer, keyword, media_type, page)
                    results.extend(torrents)
                except Exception as e:
                    logger.error(f"【{self.plugin_name}】搜索索引器 {indexer.get('name')} 失败：{str(e)}")
                    continue

        # 转换TorrentInfo对象为字典
        return [
            {
                "title": t.title,
                "description": t.description,
                "enclosure": t.enclosure,
                "page_url": t.page_url,
                "size": t.size,
                "seeders": t.seeders,
                "peers": t.peers,
                "pubdate": t.pubdate,
                "imdbid": t.imdbid,
                "downloadvolumefactor": t.downloadvolumefactor,
                "uploadvolumefactor": t.uploadvolumefactor,
                "site_name": t.site_name,
                "grabs": t.grabs,
            }
            for t in results
        ]

    def get_api(self) -> List[Dict[str, Any]]:
        """
        Get plugin API endpoints.

        Returns:
            List of API endpoint definitions
        """
        # 提供 API 端点返回索引器列表和搜索功能
        return [
            {
                "path": "/indexers",
                "endpoint": self.get_indexers,
                "methods": ["GET"],
                "summary": "获取索引器列表",
                "description": "返回所有已注册的 Prowlarr 索引器"
            },
            {
                "path": "/search",
                "endpoint": self.api_search,
                "methods": ["GET"],
                "summary": "搜索种子资源",
                "description": "通过Prowlarr搜索种子资源。参数：keyword(必填), indexer_id(可选), mtype(可选: movie/tv), page(可选，默认0)"
            }
        ]

    def get_command(self) -> List[Dict[str, Any]]:
        """
        注册插件远程命令

        Returns:
            命令列表
        """
        return [
            {
                "cmd": "/prowlarr_search",
                "event": EventType.PluginAction,
                "desc": "Prowlarr搜索",
                "category": "索引器",
                "data": {
                    "action": "prowlarr_search"
                }
            },
            {
                "cmd": "/prowlarr_sites",
                "event": EventType.PluginAction,
                "desc": "Prowlarr站点列表",
                "category": "索引器",
                "data": {
                    "action": "prowlarr_sites"
                }
            }
        ]

    @eventmanager.register(EventType.PluginAction)
    def command_action(self, event: Event):
        """
        远程命令响应

        支持的命令：
        1. /prowlarr_search 关键词 [分类] [索引器ID]
        2. /prowlarr_sites - 列出所有索引站点

        示例：
        /prowlarr_search The Matrix
        /prowlarr_search The Matrix movie
        /prowlarr_search The Matrix movie 12
        /prowlarr_search tt0133093
        /prowlarr_sites
        """
        if not self._enabled:
            return

        event_data = event.event_data
        if not event_data:
            return

        action = event_data.get("action")
        if not action:
            return

        # 获取用户信息
        channel = event_data.get("channel")
        source = event_data.get("source")
        user = event_data.get("user")

        # 处理站点列表命令
        if action == "prowlarr_sites":
            self._handle_sites_command(channel, source, user)
            return

        # 处理搜索命令
        if action != "prowlarr_search":
            return

        # 获取命令文本
        args = event_data.get("args", "")
        if not args:
            self.post_message(
                channel=channel,
                title="❌ Prowlarr搜索失败",
                text="请提供搜索关键词\n\n"
                     "用法：/prowlarr_search 关键词 [分类] [索引器ID]\n"
                     "分类：movie 或 tv\n"
                     "示例：/prowlarr_search The Matrix movie 12",
                userid=user
            )
            return

        # 解析参数
        parts = args.strip().split()
        if len(parts) < 1:
            self.post_message(
                channel=channel,
                title="❌ Prowlarr搜索失败",
                text="请提供搜索关键词",
                userid=user
            )
            return

        keyword = parts[0]
        mtype = None
        indexer_id = None

        # 解析可选参数
        if len(parts) > 1:
            if parts[1].lower() in ["movie", "tv"]:
                mtype = parts[1].lower()
                if len(parts) > 2 and parts[2].isdigit():
                    indexer_id = int(parts[2])
            elif parts[1].isdigit():
                indexer_id = int(parts[1])

        # 转换媒体类型
        media_type = None
        if mtype:
            media_type = MediaType.MOVIE if mtype == "movie" else MediaType.TV

        # 发送搜索开始提示
        search_info = f"关键词：{keyword}"
        if mtype:
            search_info += f"\n分类：{mtype}"
        if indexer_id:
            search_info += f"\n索引器ID：{indexer_id}"

        self.post_message(
            channel=channel,
            title="🔍 Prowlarr搜索中...",
            text=search_info,
            userid=user
        )

        try:
            # 执行搜索
            results = self.api_search(keyword=keyword, indexer_id=indexer_id, mtype=mtype, page=0)

            if not results:
                self.post_message(
                    channel=channel,
                    title="📭 未找到结果",
                    text=f"关键词：{keyword}\n未搜索到任何种子",
                    userid=user
                )
                return

            # 格式化结果（限制显示前10条）
            max_display = 10
            result_text = f"找到 {len(results)} 条结果，显示前 {min(len(results), max_display)} 条：\n\n"

            for idx, torrent in enumerate(results[:max_display], 1):
                # 格式化大小
                size_gb = torrent['size'] / (1024**3) if torrent['size'] > 0 else 0

                # 促销标志
                promo = []
                if torrent['downloadvolumefactor'] == 0.0:
                    promo.append("🆓")
                elif torrent['downloadvolumefactor'] == 0.5:
                    promo.append("50%")
                if torrent['uploadvolumefactor'] == 2.0:
                    promo.append("2xUp")
                promo_str = " ".join(promo) if promo else ""

                result_text += (
                    f"{idx}. {torrent['title']}\n"
                    f"   大小: {size_gb:.2f}GB | "
                    f"做种: {torrent['seeders']} | "
                    f"下载: {torrent['peers']}\n"
                    f"   站点: {torrent['site_name']}"
                )

                # 显示完成数
                if torrent.get('grabs'):
                    result_text += f" | 完成: {torrent['grabs']}"

                result_text += "\n"

                if promo_str:
                    result_text += f"   促销: {promo_str}\n"

                result_text += "\n"

            self.post_message(
                channel=channel,
                title="✅ Prowlarr搜索完成",
                text=result_text.strip(),
                userid=user
            )

        except Exception as e:
            logger.error(f"【{self.plugin_name}】远程搜索失败：{str(e)}\n{traceback.format_exc()}")
            self.post_message(
                channel=channel,
                title="❌ Prowlarr搜索失败",
                text=f"搜索过程中发生错误：{str(e)}",
                userid=user
            )

    def _handle_sites_command(self, channel, source, user):
        """
        处理站点列表命令

        Args:
            channel: 消息渠道
            source: 消息来源
            user: 用户ID
        """
        try:
            if not self._indexers:
                self.post_message(
                    channel=channel,
                    title="📋 Prowlarr站点列表",
                    text="当前没有已注册的索引器\n请先配置并启用插件",
                    userid=user
                )
                return

            # 统计信息
            total = len(self._indexers)
            private_count = sum(1 for idx in self._indexers if idx.get("privacy") == "private")
            semi_private_count = sum(1 for idx in self._indexers if idx.get("privacy") == "semiPrivate")

            # 构建站点列表
            sites_text = f"共 {total} 个索引器（私有:{private_count} | 半私有:{semi_private_count}）\n\n"

            for idx, indexer in enumerate(self._indexers, 1):
                # 隐私类型标识
                privacy = indexer.get("privacy", "private")
                if privacy == "private":
                    privacy_icon = "🔒"
                elif privacy == "semiPrivate":
                    privacy_icon = "🔓"
                else:
                    privacy_icon = "🌐"

                # 站点名称（去掉插件前缀）
                site_name = indexer.get("name", "Unknown")
                if site_name.startswith(f"{self.plugin_name}-"):
                    site_name = site_name[len(f"{self.plugin_name}-"):]

                sites_text += f"{idx}. {privacy_icon} {site_name}\n"

            self.post_message(
                channel=channel,
                title="📋 Prowlarr站点列表",
                text=sites_text.strip(),
                userid=user
            )

        except Exception as e:
            logger.error(f"【{self.plugin_name}】获取站点列表失败：{str(e)}\n{traceback.format_exc()}")
            self.post_message(
                channel=channel,
                title="❌ 获取站点列表失败",
                text=f"发生错误：{str(e)}",
                userid=user
            )

    def get_agent_tools(self) -> List[Type]:
        """
        获取插件智能体工具
        返回工具类列表，每个工具类必须继承自 MoviePilotTool
        """
        return [SearchTorrentsTool, ListIndexersTool]
