# -*- coding: utf-8 -*-
"""
Jackett 扩展索引器插件

集成 Jackett 聚合搜索服务，为 MoviePilot 提供多站点资源检索能力。

功能特性:
- 自动同步 Jackett 配置的索引器列表
- 支持电影/电视分类过滤
- 支持 Torznab XML 格式解析
- 定时更新索引器状态
- 完善的错误处理机制
- 支持密码保护和代理配置

作者: Claude Code (基于 jtcymc 原始实现优化)
版本: 2.0
"""

import copy
import traceback
import xml.dom.minidom
from typing import List, Dict, Any, Tuple, Optional
from datetime import datetime, timedelta
from urllib.parse import urlencode, quote_plus

import pytz
import requests
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger

from app.helper.sites import SitesHelper
from app.core.context import TorrentInfo
from app.log import logger
from app.plugins import _PluginBase
from app.core.config import settings
from app.schemas import MediaType
from app.utils.dom import DomUtils
from app.utils.http import RequestUtils
from app.utils.string import StringUtils


class JackettExtend(_PluginBase):
    # ========== 插件元数据 ==========
    plugin_name = "Jackett 扩展索引器"
    plugin_desc = "集成 Jackett 聚合搜索服务，支持多站点资源检索"
    plugin_icon = "Jackett.png"
    plugin_version = "2.0"
    plugin_author = "Claude Code"
    author_url = "https://github.com/jxxghp/MoviePilot-Plugins"
    plugin_config_prefix = "jackett_extend_"
    plugin_order = 15
    auth_level = 1

    # ========== 私有属性 ==========
    _scheduler: Optional[BackgroundScheduler] = None
    _sites_helper: Optional[SitesHelper] = None

    # 配置参数
    _enabled = False
    _host = ""
    _api_key = ""
    _password = ""
    _proxy = False
    _cron = "0 0 */24 * *"
    _onlyonce = False

    # 索引器数据
    _indexers: List[Dict[str, Any]] = []
    _indexers_cache_time: Optional[datetime] = None

    # 标识域名，避免重复注册
    JACKETT_DOMAIN_PREFIX = "jackett.extend"

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
            self._password = config.get("password", "").strip()
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

        # 如果插件未启用，停止后直接返回
        if not self._enabled:
            return

        # 启动定时任务
        self._setup_scheduler()

        # 初始加载索引器
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
            logger.error(f"【{self.plugin_name}】Jackett 地址未配置")
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
                id="jackett_sync_indexers",
                name="Jackett 索引器同步"
            )

        # 立即运行一次
        if self._onlyonce:
            logger.info(f"【{self.plugin_name}】立即执行索引器同步")
            run_time = datetime.now(tz=pytz.timezone(settings.TZ)) + timedelta(seconds=3)
            self._scheduler.add_job(
                func=self._sync_indexers,
                trigger='date',
                run_date=run_time,
                id="jackett_sync_once",
                name="Jackett 索引器立即同步"
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

    # ========== Jackett API 交互 ==========

    def _sync_indexers(self) -> bool:
        """
        从 Jackett 同步索引器列表

        Returns:
            bool: 是否同步成功
        """
        if not self._api_key or not self._host:
            logger.warning(f"【{self.plugin_name}】API Key 或主机地址未配置")
            return False

        try:
            indexers = self._fetch_indexers_from_jackett()

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

    def _fetch_indexers_from_jackett(self) -> List[Dict[str, Any]]:
        """
        从 Jackett API 获取索引器列表

        需要先通过密码登录获取 Cookie，然后才能访问 API

        Returns:
            List[Dict]: 索引器列表

        Raises:
            Exception: API 请求失败时抛出异常
        """
        headers = {
            "Content-Type": "application/x-www-form-urlencoded; charset=UTF-8",
            "User-Agent": settings.USER_AGENT,
            "X-Api-Key": self._api_key,
            "Accept": "application/json"
        }

        cookie = None
        session = requests.session()

        try:
            # 第一步：密码登录获取 Cookie (如果配置了密码)
            if self._password:
                login_url = f"{self._host}/UI/Dashboard"
                login_data = {"password": self._password}
                login_params = {"password": self._password}

                logger.debug(f"【{self.plugin_name}】尝试登录 Jackett: {login_url}")

                login_response = RequestUtils(
                    headers=headers,
                    session=session,
                    timeout=30
                ).post_res(
                    url=login_url,
                    data=login_data,
                    params=login_params,
                    proxies=settings.PROXY if self._proxy else None
                )

                if login_response and session.cookies:
                    cookie = session.cookies.get_dict()
                    logger.debug(f"【{self.plugin_name}】登录成功，已获取 Cookie")
                else:
                    logger.warning(f"【{self.plugin_name}】登录失败，将尝试无 Cookie 访问")

            # 第二步：获取索引器列表
            api_url = f"{self._host}/api/v2.0/indexers?configured=true"

            logger.debug(f"【{self.plugin_name}】请求 Jackett API: {api_url}")

            response = RequestUtils(
                headers=headers,
                cookies=cookie,
                timeout=30
            ).get_res(
                api_url,
                proxies=settings.PROXY if self._proxy else None
            )

            if not response:
                raise Exception("请求无响应")

            if response.status_code != 200:
                raise Exception(f"HTTP {response.status_code}: {response.text[:200]}")

            data = response.json()

            if not data or not isinstance(data, list):
                raise Exception("响应数据格式异常，应为索引器数组")

            if not data:
                logger.info(f"【{self.plugin_name}】Jackett 未配置任何索引器")
                return []

            # 转换为插件内部格式
            indexers = []
            for item in data:
                indexer_id = item.get("id")
                indexer_name = item.get("name")

                if not indexer_id or not indexer_name:
                    logger.warning(f"【{self.plugin_name}】跳过无效索引器: {item}")
                    continue

                indexers.append({
                    "id": f"{self.plugin_name}-{indexer_name}",
                    "name": f"{self.plugin_name}-{indexer_name}",
                    "url": f"{self._host}/api/v2.0/indexers/{indexer_id}/results/torznab/",
                    "domain": f"{self.JACKETT_DOMAIN_PREFIX}.{indexer_id}",
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

            results = self._search_from_jackett(
                indexer_id=indexer_id,
                keyword=keyword,
                mtype=mtype
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

    def _search_from_jackett(
        self,
        indexer_id: str,
        keyword: str,
        mtype: Optional[MediaType] = None
    ) -> List[TorrentInfo]:
        """
        从 Jackett 搜索资源

        Args:
            indexer_id: 索引器 ID
            keyword: 搜索关键词
            mtype: 媒体类型

        Returns:
            List[TorrentInfo]: 搜索结果
        """
        # 构建搜索参数
        categories = self._get_categories(mtype)

        params = {
            "apikey": self._api_key,
            "t": "search",
            "q": keyword,
            "cat": ",".join(map(str, categories))
        }

        query_string = urlencode(params, quote_via=quote_plus)
        api_url = f"{self._host}/api/v2.0/indexers/{indexer_id}/results/torznab/?{query_string}"

        logger.debug(f"【{self.plugin_name}】搜索 API: {api_url}")

        try:
            # 解析 Torznab XML
            results = self._parse_torznab_xml(api_url)

            logger.debug(f"【{self.plugin_name}】解析到 {len(results)} 个结果")
            return results

        except Exception as e:
            logger.error(f"【{self.plugin_name}】搜索请求异常: {str(e)}")
            logger.debug(traceback.format_exc())
            return []

    def _parse_torznab_xml(self, url: str) -> List[TorrentInfo]:
        """
        解析 Torznab XML 格式的搜索结果

        Args:
            url: XML 数据的 URL

        Returns:
            List[TorrentInfo]: 解析后的种子信息列表
        """
        if not url:
            return []

        try:
            response = RequestUtils(timeout=60).get_res(
                url,
                proxies=settings.PROXY if self._proxy else None
            )

            if not response or not response.text:
                logger.warning(f"【{self.plugin_name}】XML 响应为空")
                return []

            xml_content = response.text
            torrents = []

            # 解析 XML
            dom_tree = xml.dom.minidom.parseString(xml_content)
            root_node = dom_tree.documentElement
            items = root_node.getElementsByTagName("item")

            for item in items:
                try:
                    # 提取基础字段
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

                    # 提取 Torznab 属性
                    seeders = 0
                    peers = 0
                    imdbid = ""

                    torznab_attrs = item.getElementsByTagName("torznab:attr")
                    for torznab_attr in torznab_attrs:
                        name = torznab_attr.getAttribute('name')
                        value = torznab_attr.getAttribute('value')

                        if name == "seeders":
                            seeders = int(value) if value else 0
                        elif name == "peers":
                            peers = int(value) if value else 0
                        elif name == "imdbid":
                            imdbid = value

                    # 构建 TorrentInfo 对象
                    torrent = TorrentInfo(
                        title=title,
                        enclosure=enclosure,
                        description=description,
                        size=size,
                        seeders=seeders,
                        peers=peers,
                        pubdate=pubdate,
                        page_url=page_url,
                        imdbid=imdbid,
                    )
                    torrents.append(torrent)

                except Exception as e:
                    logger.warning(f"【{self.plugin_name}】解析种子项失败: {str(e)}")
                    continue

            return torrents

        except Exception as e:
            logger.error(f"【{self.plugin_name}】解析 XML 失败: {str(e)}")
            return []

    @staticmethod
    def _get_categories(mtype: Optional[MediaType] = None) -> List[int]:
        """
        根据媒体类型获取 Jackett 分类

        Args:
            mtype: 媒体类型

        Returns:
            List[int]: Torznab 分类代码
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
            "password": self._password,
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
                                        'hint': '开启后将集成 Jackett 搜索'
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
                                        'hint': '通过 MoviePilot 配置的代理访问 Jackett'
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
                                        'label': 'Jackett 地址',
                                        'placeholder': 'http://127.0.0.1:9117',
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
                                        'hint': '在 Jackett 管理界面右上角复制'
                                    }
                                }]
                            }
                        ]
                    },
                    # 第三行：密码和定时任务
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
                                        'placeholder': '如未设置可留空',
                                        'type': 'password',
                                        'hint': 'Jackett Admin Password，用于获取索引器列表'
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
                                        'label': '同步周期',
                                        'placeholder': '0 0 */24 * *',
                                        'hint': 'Cron 表达式，默认每 24 小时同步一次'
                                    }
                                }]
                            }
                        ]
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
                                        '1. 在 Jackett 中配置好索引器\n'
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
                                        '- 建议先在 Jackett 中验证索引器可用性'
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
            "password": "",
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
