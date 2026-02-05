# -*- coding: utf-8 -*-
"""
Prowlarr 扩展索引器插件

集成 Prowlarr 聚合搜索服务，为 MoviePilot 提供多站点资源检索能力。

功能特性:
- 自动同步 Prowlarr 配置的索引器列表
- 支持电影/电视分类过滤
- 定时更新索引器状态
- 完善的错误处理和重试机制
- 支持代理配置

作者: Claude Code (基于 jtcymc 原始实现优化)
版本: 2.0
"""

import copy
import traceback
from typing import List, Dict, Any, Tuple, Optional
from datetime import datetime, timedelta
from urllib.parse import urlencode, quote_plus

import pytz
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger

from app.helper.sites import SitesHelper
from app.core.context import TorrentInfo
from app.plugins import _PluginBase
from app.core.config import settings
from app.schemas import MediaType
from app.utils.http import RequestUtils
from app.log import logger
from app.utils.string import StringUtils


class ProwlarrExtend(_PluginBase):
    # ========== 插件元数据 ==========
    plugin_name = "Prowlarr 扩展索引器"
    plugin_desc = "集成 Prowlarr 聚合搜索服务，支持多站点资源检索"
    plugin_icon = "Prowlarr.png"
    plugin_version = "2.0"
    plugin_author = "Claude Code"
    author_url = "https://github.com/jxxghp/MoviePilot-Plugins"
    plugin_config_prefix = "prowlarr_extend_"
    plugin_order = 16
    auth_level = 1

    # ========== 私有属性 ==========
    _scheduler: Optional[BackgroundScheduler] = None
    _sites_helper: Optional[SitesHelper] = None

    # 配置参数
    _enabled = False
    _host = ""
    _api_key = ""
    _proxy = False
    _cron = "0 0 */24 * *"
    _onlyonce = False

    # 索引器数据
    _indexers: List[Dict[str, Any]] = []
    _indexers_cache_time: Optional[datetime] = None

    # 标识域名，避免重复注册
    PROWLARR_DOMAIN_PREFIX = "prowlarr.extend"

    # ========== 核心方法 ==========

    def init_plugin(self, config: dict = None):
        """
        初始化插件

        Args:
            config: 插件配置字典
        """
        self._sites_helper = SitesHelper()

        # 读取配置
        if config:
            self._enabled = config.get("enabled", False)
            self._host = self._normalize_host(config.get("host", ""))
            self._api_key = config.get("api_key", "").strip()
            self._proxy = config.get("proxy", False)
            self._cron = config.get("cron") or "0 0 */24 * *"
            self._onlyonce = config.get("onlyonce", False)

        # 配置验证
        if self._enabled and not self._validate_config():
            logger.error(f"【{self.plugin_name}】配置验证失败，插件已禁用")
            self._enabled = False
            return

        # 停止现有任务
        self.stop_service()

        # 启动定时任务（仅在启用时）
        if self._enabled:
            self._setup_scheduler()

        # 初始加载索引器并注册到系统（无论是否启用都执行，用于站点管理）
        if not self._indexers:
            self._sync_indexers()

        # 遍历并注册所有索引器到系统
        for indexer in self._indexers:
            domain = indexer.get("domain", "")
            if not domain:
                continue
            # 检查是否已注册
            site_info = self._sites_helper.get_indexer(domain)
            if not site_info:
                # 注册新索引器
                new_indexer = copy.deepcopy(indexer)
                self._sites_helper.add_indexer(domain, new_indexer)
                logger.debug(f"【{self.plugin_name}】已注册索引器: {indexer.get('name')}")

    def _validate_config(self) -> bool:
        """
        验证配置完整性

        Returns:
            bool: 配置是否有效
        """
        if not self._host:
            logger.error(f"【{self.plugin_name}】Prowlarr 地址未配置")
            return False

        if not self._api_key:
            logger.error(f"【{self.plugin_name}】API Key 未配置")
            return False

        return True

    def _normalize_host(self, host: str) -> str:
        """
        规范化主机地址

        Args:
            host: 原始地址

        Returns:
            str: 规范化后的地址
        """
        if not host:
            return ""

        host = host.strip()

        # 添加协议前缀
        if not host.startswith(('http://', 'https://')):
            host = 'http://' + host

        # 移除尾部斜杠
        return host.rstrip('/')

    def _setup_scheduler(self):
        """设置定时任务调度器"""
        self._scheduler = BackgroundScheduler(timezone=settings.TZ)

        # 定时同步任务
        if self._cron:
            logger.info(f"【{self.plugin_name}】索引器同步任务已启动，周期: {self._cron}")
            self._scheduler.add_job(
                func=self._sync_indexers,
                trigger=CronTrigger.from_crontab(self._cron),
                id="prowlarr_sync_indexers",
                name="Prowlarr 索引器同步"
            )

        # 立即运行一次
        if self._onlyonce:
            logger.info(f"【{self.plugin_name}】立即执行索引器同步")
            run_time = datetime.now(tz=pytz.timezone(settings.TZ)) + timedelta(seconds=3)
            self._scheduler.add_job(
                func=self._sync_indexers,
                trigger='date',
                run_date=run_time,
                id="prowlarr_sync_once",
                name="Prowlarr 索引器立即同步"
            )
            # 关闭一次性开关
            self._onlyonce = False
            self._update_config()

        # 启动调度器
        if self._scheduler.get_jobs():
            self._scheduler.print_jobs()
            self._scheduler.start()

    def get_state(self) -> bool:
        """
        获取插件状态

        Returns:
            bool: 插件是否启用
        """
        return self._enabled

    def stop_service(self):
        """停止插件服务"""
        try:
            if self._scheduler:
                self._scheduler.remove_all_jobs()
                if self._scheduler.running:
                    self._scheduler.shutdown()
                self._scheduler = None
                logger.info(f"【{self.plugin_name}】定时任务已停止")
        except Exception as e:
            logger.error(f"【{self.plugin_name}】停止服务时出错: {str(e)}")

    # ========== Prowlarr API 交互 ==========

    def _sync_indexers(self) -> bool:
        """
        从 Prowlarr 同步索引器列表

        Returns:
            bool: 是否同步成功
        """
        if not self._api_key or not self._host:
            logger.warning(f"【{self.plugin_name}】API Key 或主机地址未配置")
            return False

        try:
            indexers = self._fetch_indexers_from_prowlarr()

            if not indexers:
                logger.warning(f"【{self.plugin_name}】未获取到任何索引器")
                return False

            self._indexers = indexers
            self._indexers_cache_time = datetime.now()

            logger.info(f"【{self.plugin_name}】成功同步 {len(indexers)} 个索引器")

            # 注册到系统
            self._register_indexers()

            return True

        except Exception as e:
            logger.error(f"【{self.plugin_name}】同步索引器失败: {str(e)}")
            logger.debug(traceback.format_exc())
            return False

    def _fetch_indexers_from_prowlarr(self) -> List[Dict[str, Any]]:
        """
        从 Prowlarr API 获取索引器列表

        Returns:
            List[Dict]: 索引器列表

        Raises:
            Exception: API 请求失败时抛出异常
        """
        headers = {
            "Content-Type": "application/json",
            "User-Agent": settings.USER_AGENT,
            "X-Api-Key": self._api_key,
            "Accept": "application/json"
        }

        api_url = f"{self._host}/api/v1/indexerstats"

        logger.debug(f"【{self.plugin_name}】请求 Prowlarr API: {api_url}")

        try:
            response = RequestUtils(
                headers=headers,
                timeout=30,
                proxies=settings.PROXY if self._proxy else None
            ).get_res(api_url)

            if not response:
                raise Exception("请求无响应")

            if response.status_code != 200:
                raise Exception(f"HTTP {response.status_code}: {response.text[:200]}")

            data = response.json()

            if not data or "indexers" not in data:
                raise Exception("响应数据格式异常，缺少 indexers 字段")

            raw_indexers = data.get("indexers", [])

            if not raw_indexers:
                logger.info(f"【{self.plugin_name}】Prowlarr 未配置任何索引器")
                return []

            # 转换为插件内部格式
            indexers = []
            for item in raw_indexers:
                indexer_id = item.get("indexerId")
                indexer_name = item.get("indexerName")

                if not indexer_id or not indexer_name:
                    logger.warning(f"【{self.plugin_name}】跳过无效索引器: {item}")
                    continue

                indexers.append({
                    "id": f"{self.plugin_name}-{indexer_name}",
                    "name": f"{self.plugin_name}-{indexer_name}",
                    "url": f"{self._host}/api/v1/indexer/{indexer_id}",
                    "domain": f"{self.PROWLARR_DOMAIN_PREFIX}.{indexer_id}",
                    "public": True,
                    "proxy": self._proxy,
                })

            logger.debug(f"【{self.plugin_name}】解析索引器: {len(indexers)} 个")
            return indexers

        except Exception as e:
            logger.error(f"【{self.plugin_name}】获取索引器列表失败: {str(e)}")
            raise

    def _register_indexers(self):
        """将索引器注册到 MoviePilot 系统"""
        if not self._indexers:
            logger.debug(f"【{self.plugin_name}】无索引器需要注册")
            return

        registered_count = 0
        for indexer in self._indexers:
            domain = indexer.get("domain", "")
            if not domain:
                continue

            # 检查是否已注册
            if self._sites_helper.get_indexer(domain):
                logger.debug(f"【{self.plugin_name}】索引器已存在，跳过: {domain}")
                continue

            # 注册新索引器
            new_indexer = copy.deepcopy(indexer)
            self._sites_helper.add_indexer(domain, new_indexer)
            registered_count += 1
            logger.debug(f"【{self.plugin_name}】已注册索引器: {indexer.get('name')}")

        if registered_count > 0:
            logger.info(f"【{self.plugin_name}】新注册 {registered_count} 个索引器到系统")

    # ========== 搜索功能 ==========

    def search_torrents(
        self,
        site: dict,
        keyword: str,
        mtype: Optional[MediaType] = None,
        page: Optional[int] = 0
    ) -> List[TorrentInfo]:
        """
        搜索种子资源

        Args:
            site: 站点信息
            keyword: 搜索关键词
            mtype: 媒体类型 (电影/电视)
            page: 页码

        Returns:
            List[TorrentInfo]: 搜索结果列表
        """
        results = []

        # 参数验证
        if not site or not keyword:
            logger.warning(f"【{self.plugin_name}】搜索参数不完整")
            return results

        # 检查站点是否属于本插件
        site_name = site.get("name", "")
        if not site_name.startswith(self.plugin_name):
            logger.debug(f"【{self.plugin_name}】站点不属于本插件: {site_name}")
            return results

        # 提取索引器 ID
        domain = StringUtils.get_url_domain(site.get("domain", ""))
        if not domain:
            logger.warning(f"【{self.plugin_name}】无法解析站点域名: {site}")
            return results

        indexer_id = domain.split(".")[-1]
        if not indexer_id:
            logger.warning(f"【{self.plugin_name}】无法提取索引器 ID: {domain}")
            return results

        # 执行搜索
        try:
            logger.info(
                f"【{self.plugin_name}】开始搜索 - "
                f"索引器: {site_name}, 关键词: {keyword}, 类型: {mtype}, 页码: {page}"
            )

            results = self._search_from_prowlarr(
                indexer_id=indexer_id,
                keyword=keyword,
                mtype=mtype,
                page=page
            )

            logger.info(
                f"【{self.plugin_name}】搜索完成 - "
                f"索引器: {site_name}, 结果数: {len(results)}"
            )

        except Exception as e:
            logger.error(
                f"【{self.plugin_name}】搜索出错 - "
                f"索引器: {site_name}, 错误: {str(e)}"
            )
            logger.debug(traceback.format_exc())

        return results

    def _search_from_prowlarr(
        self,
        indexer_id: str,
        keyword: str,
        mtype: Optional[MediaType] = None,
        page: int = 0
    ) -> List[TorrentInfo]:
        """
        从 Prowlarr 搜索资源

        Args:
            indexer_id: 索引器 ID
            keyword: 搜索关键词
            mtype: 媒体类型
            page: 页码

        Returns:
            List[TorrentInfo]: 搜索结果
        """
        headers = {
            "Content-Type": "application/json",
            "User-Agent": settings.USER_AGENT,
            "X-Api-Key": self._api_key,
            "Accept": "application/json"
        }

        # 构建搜索参数
        categories = self._get_categories(mtype)
        limit = 150
        offset = page * limit if page else 0

        params = [
            ("query", keyword),
            ("indexerIds", indexer_id),
            ("type", "search"),
            ("limit", limit),
            ("offset", offset),
        ]

        # 添加分类参数
        for cat in categories:
            params.append(("categories", cat))

        query_string = urlencode(params, quote_via=quote_plus)
        api_url = f"{self._host}/api/v1/search?{query_string}"

        logger.debug(f"【{self.plugin_name}】搜索 API: {api_url}")

        try:
            response = RequestUtils(
                headers=headers,
                timeout=60,
                proxies=settings.PROXY if self._proxy else None
            ).get_res(api_url)

            if not response:
                logger.warning(f"【{self.plugin_name}】搜索请求无响应")
                return []

            if response.status_code != 200:
                logger.error(
                    f"【{self.plugin_name}】搜索请求失败: "
                    f"HTTP {response.status_code}"
                )
                return []

            data = response.json()

            if not isinstance(data, list):
                logger.warning(f"【{self.plugin_name}】搜索结果格式异常")
                return []

            # 解析结果
            results = []
            for entry in data:
                try:
                    torrent = TorrentInfo(
                        title=entry.get("title"),
                        enclosure=entry.get("downloadUrl") or entry.get("magnetUrl"),
                        description=entry.get("sortTitle"),
                        size=entry.get("size"),
                        seeders=entry.get("seeders"),
                        peers=entry.get("leechers"),
                        pubdate=entry.get("publishDate"),
                        page_url=entry.get("infoUrl") or entry.get("guid"),
                        imdbid=entry.get("imdbId"),
                    )
                    results.append(torrent)
                except Exception as e:
                    logger.warning(f"【{self.plugin_name}】解析种子失败: {str(e)}")
                    continue

            logger.debug(f"【{self.plugin_name}】解析到 {len(results)} 个结果")
            return results

        except Exception as e:
            logger.error(f"【{self.plugin_name}】搜索请求异常: {str(e)}")
            logger.debug(traceback.format_exc())
            return []

    @staticmethod
    def _get_categories(mtype: Optional[MediaType] = None) -> List[int]:
        """
        根据媒体类型获取 Prowlarr 分类

        Args:
            mtype: 媒体类型

        Returns:
            List[int]: Newznab/Torznab 分类代码
        """
        if mtype == MediaType.MOVIE:
            return [2000]  # Movies
        elif mtype == MediaType.TV:
            return [5000]  # TV
        else:
            return [2000, 5000]  # All

    # ========== 插件配置 ==========

    def _update_config(self):
        """更新插件配置"""
        self.update_config({
            "enabled": self._enabled,
            "host": self._host,
            "api_key": self._api_key,
            "proxy": self._proxy,
            "cron": self._cron,
            "onlyonce": False,
        })

    def get_form(self) -> Tuple[List[dict], Dict[str, Any]]:
        """
        构建插件配置表单

        Returns:
            Tuple[List[dict], Dict[str, Any]]: 表单配置和默认值
        """
        return [
            {
                'component': 'VForm',
                'content': [
                    # 第一行：基础开关
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
                                        'hint': '开启后将集成 Prowlarr 搜索'
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
                                        'label': '使用代理服务器',
                                        'hint': '通过 MoviePilot 配置的代理访问 Prowlarr'
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
                                        'label': '立即运行一次',
                                        'hint': '保存后立即同步索引器列表'
                                    }
                                }]
                            }
                        ]
                    },
                    # 第二行：服务配置
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
                                        'label': 'Prowlarr 地址',
                                        'placeholder': 'http://127.0.0.1:9696',
                                        'hint': '完整地址，支持 HTTP/HTTPS'
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
                                        'placeholder': 'xxxxxxxxxxxxxxxxxxxxxxxx',
                                        'hint': 'Settings → General → Security → API Key'
                                    }
                                }]
                            }
                        ]
                    },
                    # 第三行：定时任务
                    {
                        'component': 'VRow',
                        'content': [{
                            'component': 'VCol',
                            'props': {'cols': 12, 'md': 6},
                            'content': [{
                                'component': 'VTextField',
                                'props': {
                                    'model': 'cron',
                                    'label': '同步周期',
                                    'placeholder': '0 0 */24 * *',
                                    'hint': 'Cron 表达式，默认每 24 小时同步一次'
                                }
                            }]
                        }]
                    },
                    # 使用说明
                    {
                        'component': 'VRow',
                        'content': [{
                            'component': 'VCol',
                            'props': {'cols': 12},
                            'content': [{
                                'component': 'VAlert',
                                'props': {
                                    'type': 'info',
                                    'variant': 'tonal',
                                    'text': (
                                        '📌 使用步骤：\n'
                                        '1. 在 Prowlarr 中配置好索引器\n'
                                        '2. 填写上方配置并保存\n'
                                        '3. 点击"查看数据"查看同步的索引器\n'
                                        '4. 复制站点域名到 MoviePilot 站点管理中添加'
                                    )
                                }
                            }]
                        }]
                    },
                    {
                        'component': 'VRow',
                        'content': [{
                            'component': 'VCol',
                            'props': {'cols': 12},
                            'content': [{
                                'component': 'VAlert',
                                'props': {
                                    'type': 'warning',
                                    'variant': 'tonal',
                                    'text': (
                                        '⚠️ 注意：\n'
                                        '- 此插件通过模块劫持方式实现搜索\n'
                                        '- 无法进行站点连通性测试\n'
                                        '- 建议先在 Prowlarr 中验证索引器可用性'
                                    )
                                }
                            }]
                        }]
                    }
                ]
            }
        ], {
            "enabled": False,
            "host": "",
            "api_key": "",
            "proxy": False,
            "cron": "0 0 */24 * *",
            "onlyonce": False
        }

    def get_page(self) -> List[dict]:
        """
        构建插件详情页面

        Returns:
            List[dict]: 页面配置
        """
        if not self._ensure_indexers_loaded():
            return [{
                'component': 'VAlert',
                'props': {
                    'type': 'warning',
                    'variant': 'tonal',
                    'text': '暂无索引器数据，请检查配置或点击"立即运行一次"'
                }
            }]

        # 构建表格行
        table_rows = []
        for indexer in self._indexers:
            table_rows.append({
                'component': 'tr',
                'content': [
                    {'component': 'td', 'text': indexer.get("name")},
                    {'component': 'td', 'text': f"https://{indexer.get('domain')}"},
                    {'component': 'td', 'text': '是' if indexer.get('public') else '否'}
                ]
            })

        return [
            {
                'component': 'VRow',
                'content': [{
                    'component': 'VCol',
                    'props': {'cols': 12},
                    'content': [{
                        'component': 'VAlert',
                        'props': {
                            'type': 'success',
                            'variant': 'tonal',
                            'text': f'已同步 {len(self._indexers)} 个索引器'
                        }
                    }]
                }]
            },
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
                                        {
                                            'component': 'th',
                                            'props': {'class': 'text-start ps-4'},
                                            'text': '索引器名称'
                                        },
                                        {
                                            'component': 'th',
                                            'props': {'class': 'text-start ps-4'},
                                            'text': '站点域名'
                                        },
                                        {
                                            'component': 'th',
                                            'props': {'class': 'text-start ps-4'},
                                            'text': '是否公开'
                                        }
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

    def _ensure_indexers_loaded(self) -> bool:
        """
        确保索引器列表已加载

        Returns:
            bool: 是否成功加载
        """
        if self._indexers and len(self._indexers) > 0:
            return True

        # 尝试重新同步
        return self._sync_indexers()

    # ========== 模块劫持 ==========

    def get_module(self) -> Dict[str, Any]:
        """
        获取模块劫持映射

        劫持系统的 search_torrents 方法，实现搜索功能

        Returns:
            Dict[str, Any]: 方法映射
        """
        return {
            "search_torrents": self.search_torrents,
        }

    def get_api(self) -> List[Dict[str, Any]]:
        """
        获取插件 API

        Returns:
            List[Dict[str, Any]]: API 端点列表
        """
        return []

    @staticmethod
    def get_command() -> List[Dict[str, Any]]:
        """
        获取插件命令

        Returns:
            List[Dict[str, Any]]: 命令列表
        """
        return []
