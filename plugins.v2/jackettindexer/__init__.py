# -*- coding: utf-8 -*-
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


class JackettIndexer(_PluginBase):
    # 插件名称 - 必须是英文，用于站点名称匹配
    plugin_name = "JackettIndexer"
    # 插件描述
    plugin_desc = "扩展MoviePilot搜索功能，支持通过Jackett聚合多个索引站点进行资源检索"
    # 插件图标
    plugin_icon = "Jackett_A.png"
    # 插件版本
    plugin_version = "2.3"
    # 插件作者
    plugin_author = "claude"
    # 作者主页
    author_url = "https://github.com/anthropics"
    # 插件配置项ID前缀
    plugin_config_prefix = "jackett_indexer_"
    # 加载顺序
    plugin_order = 15
    # 可使用的用户级别
    auth_level = 1

    # 私有属性
    _scheduler = None
    _cron = None
    _enabled = False
    _proxy = False
    _host = ""
    _api_key = ""
    _password = ""
    _onlyonce = False
    _indexers = []
    sites_helper = None

    # 域名标识 - 两段格式
    jackett_domain = "jackett.indexer"

    def init_plugin(self, config: dict = None):
        """
        初始化插件
        """
        self.sites_helper = SitesHelper()
        # 读取配置
        if config:
            self._host = config.get("host")
            if self._host:
                if not self._host.startswith('http'):
                    self._host = "http://" + self._host
                if self._host.endswith('/'):
                    self._host = self._host.rstrip('/')
            self._api_key = config.get("api_key")
            self._password = config.get("password")
            self._enabled = config.get("enabled")
            self._proxy = config.get("proxy")
            self._onlyonce = config.get("onlyonce")
            self._cron = config.get("cron") or "0 0 */24 * *"

        # 停止现有任务
        self.stop_service()

        # 启动定时任务 & 立即运行一次
        self._scheduler = BackgroundScheduler(timezone=settings.TZ)
        if self._cron:
            logger.info(f"【{self.plugin_name}】索引更新服务启动，周期：{self._cron}")
            self._scheduler.add_job(self.get_status, CronTrigger.from_crontab(self._cron))

        if self._onlyonce:
            logger.info(f"【{self.plugin_name}】开始获取索引器状态")
            self._scheduler.add_job(self.get_status, 'date',
                                    run_date=datetime.now(tz=pytz.timezone(settings.TZ)) + timedelta(seconds=3))
            # 关闭一次性开关
            self._onlyonce = False
            self.__update_config()

        if self._cron or self._onlyonce:
            # 启动服务
            self._scheduler.print_jobs()
            self._scheduler.start()

        # 获取索引器并注册
        if not self._indexers:
            self.get_status()

        for indexer in self._indexers:
            domain = indexer.get("domain", "")
            site_info = self.sites_helper.get_indexer(domain)
            if not site_info:
                new_indexer = copy.deepcopy(indexer)
                self.sites_helper.add_indexer(domain, new_indexer)

    def get_status(self):
        """
        检查连通性
        """
        if not self._api_key or not self._host:
            return False
        self._indexers = self.get_indexers()
        return True if isinstance(self._indexers, list) and len(self._indexers) > 0 else False

    def get_state(self) -> bool:
        return self._enabled

    def stop_service(self):
        """
        退出插件
        """
        try:
            if self._scheduler:
                self._scheduler.remove_all_jobs()
                if self._scheduler.running:
                    self._scheduler.shutdown()
                self._scheduler = None
        except Exception as e:
            logger.error(f"【{self.plugin_name}】停止插件错误: {str(e)}")

    def __update_config(self):
        """
        更新插件配置
        """
        self.update_config({
            "enabled": self._enabled,
            "onlyonce": False,
            "cron": self._cron,
            "host": self._host,
            "api_key": self._api_key,
            "password": self._password,
            "proxy": self._proxy,
        })

    def get_module(self) -> Dict[str, Any]:
        """
        获取插件模块声明
        """
        return {
            "search_torrents": self.search_torrents,
        }

    def get_api(self) -> List[Dict[str, Any]]:
        pass

    def get_indexers(self):
        """
        获取配置的 Jackett Indexer 信息
        """
        headers = {
            "Content-Type": "application/x-www-form-urlencoded; charset=UTF-8",
            "User-Agent": settings.USER_AGENT,
            "X-Api-Key": self._api_key,
            "Accept": "application/json, text/javascript, */*; q=0.01"
        }

        cookie = None
        session = requests.session()

        try:
            # Jackett 密码认证
            if self._password:
                login_url = f"{self._host}/UI/Dashboard"
                login_data = {"password": self._password}
                login_params = {"password": self._password}
                login_res = RequestUtils(headers=headers, session=session).post_res(
                    url=login_url,
                    data=login_data,
                    params=login_params,
                    proxies=settings.PROXY if self._proxy else None
                )
                if login_res and session.cookies:
                    cookie = session.cookies.get_dict()
                else:
                    logger.warning(f"【{self.plugin_name}】Jackett 登录失败")

            indexer_query_url = f"{self._host}/api/v2.0/indexers?configured=true"
            ret = RequestUtils(headers=headers, cookies=cookie).get_res(
                indexer_query_url,
                proxies=settings.PROXY if self._proxy else None
            )

            if not ret or not ret.json():
                logger.warning(f"【{self.plugin_name}】未获取到任何 indexer 配置")
                return []

            raw_indexers = ret.json()
            indexers = []
            for v in raw_indexers:
                indexer_id = v.get("id")
                indexer_name = v.get("name")
                if not indexer_id or not indexer_name:
                    continue

                indexers.append({
                    "id": f'{self.plugin_name}-{indexer_name}',
                    "name": f'{self.plugin_name}-{indexer_name}',
                    "url": f'{self._host}/api/v2.0/indexers/{indexer_id}/results/torznab/',
                    "domain": f'{self.jackett_domain}.{indexer_id}',
                    "public": True,
                    "proxy": self._proxy,
                })

            logger.info(f"【{self.plugin_name}】获取到 {len(indexers)} 个索引器")
            return indexers

        except Exception as e:
            logger.error(f"【{self.plugin_name}】获取 Jackett indexers 失败：{str(e)}")
            return []

    def search_torrents(self, site: dict, keyword: str, mtype: Optional[MediaType] = None,
                        page: Optional[int] = 0) -> List[TorrentInfo]:
        """
        使用 Jackett Torznab API 检索种子
        """
        results = []
        if not site or not keyword:
            return results

        # 检查是否是本插件注册的站点
        if site.get("name", "").split("-")[0] != self.plugin_name:
            return results

        domain = StringUtils.get_url_domain(site.get("domain", ""))
        if not domain:
            logger.warning(f"【{self.plugin_name}】站点域名无法解析")
            return results

        indexer_name = domain.split(".")[-1]
        categories = self.get_cat(mtype)

        try:
            logger.info(f"【{self.plugin_name}】开始检索 Indexer：{site.get('name')}，关键词：{keyword}")

            params = {
                "apikey": self._api_key,
                "t": "search",
                "q": keyword,
                "cat": ",".join(map(str, categories))
            }
            query_string = urlencode(params, quote_via=quote_plus)
            api_url = f"{self._host}/api/v2.0/indexers/{indexer_name}/results/torznab/?{query_string}"

            result_array = self.__parse_torznab_xml(api_url, site.get("name"))

            if result_array:
                logger.info(f"【{self.plugin_name}】{site.get('name')} 返回 {len(result_array)} 条结果")
                results.extend(result_array)
            else:
                logger.info(f"【{self.plugin_name}】{site.get('name')} 未检索到数据")

        except Exception as e:
            logger.error(f"【{self.plugin_name}】检索出错：{str(e)}")

        return results

    @staticmethod
    def get_cat(mtype: Optional[MediaType] = None):
        if not mtype:
            return [2000, 5000]
        elif mtype == MediaType.MOVIE:
            return [2000]
        elif mtype == MediaType.TV:
            return [5000]
        else:
            return [2000, 5000]

    def __parse_torznab_xml(self, url, site_name) -> List[TorrentInfo]:
        """
        解析 torznab XML 响应
        """
        if not url:
            return []
        try:
            ret = RequestUtils(timeout=60).get_res(url,
                                                   proxies=settings.PROXY if self._proxy else None)
        except Exception as e:
            logger.error(str(e))
            return []
        if not ret or not ret.text:
            return []

        xmls = ret.text
        torrents = []
        try:
            dom_tree = xml.dom.minidom.parseString(xmls)
            root_node = dom_tree.documentElement
            items = root_node.getElementsByTagName("item")
            for item in items:
                try:
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

                    seeders = 0
                    peers = 0
                    imdbid = ""

                    torznab_attrs = item.getElementsByTagName("torznab:attr")
                    for torznab_attr in torznab_attrs:
                        name = torznab_attr.getAttribute('name')
                        value = torznab_attr.getAttribute('value')
                        if name == "seeders":
                            seeders = int(value) if value else 0
                        if name == "peers":
                            peers = int(value) if value else 0
                        if name == "imdbid":
                            imdbid = value

                    tmp_dict = TorrentInfo(
                        title=title,
                        enclosure=enclosure,
                        description=description,
                        size=size,
                        seeders=seeders,
                        peers=peers,
                        site_name=site_name,
                        page_url=page_url,
                        pubdate=pubdate,
                        imdbid=imdbid
                    )
                    torrents.append(tmp_dict)
                except Exception as e:
                    logger.error(str(e))
                    continue
        except Exception as e:
            logger.error(f"解析错误：{traceback.format_exc()}")

        return torrents

    def get_form(self) -> Tuple[List[dict], Dict[str, Any]]:
        """
        拼装插件配置页面
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
                                        'label': '使用代理服务器',
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
                                        'hint': 'Jackett访问地址和端口'
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
                                        'label': 'Api Key',
                                        'placeholder': '',
                                        'hint': 'Jackett管理界面右上角复制API Key'
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
                                        'label': '密码',
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
                                        'label': '更新周期',
                                        'placeholder': '0 0 */24 * *',
                                        'hint': '索引列表更新周期，5位cron表达式'
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
                                                '1. 填写Jackett地址和API Key；'
                                                '2. 启用插件并点击"立即运行一次"；'
                                                '3. 前往 设置->搜索->索引站点 勾选 JackettIndexer 开头的索引器；'
                                                '4. 搜索时将自动调用Jackett'
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
                                        'text': '注意：无需在"站点管理"中添加站点！索引器会自动注册到搜索系统。'
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
            "onlyonce": False
        }

    def _ensure_sites_loaded(self) -> bool:
        """
        确保索引器已加载
        """
        if isinstance(self._indexers, list) and len(self._indexers) > 0:
            return True
        self.get_status()
        return isinstance(self._indexers, list) and len(self._indexers) > 0

    def get_page(self) -> List[dict]:
        """
        拼装插件详情页面
        """
        if not self._ensure_sites_loaded():
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

        items = []
        for site in self._indexers:
            items.append({
                'component': 'tr',
                'content': [
                    {'component': 'td', 'text': site.get("name")},
                    {'component': 'td', 'text': site.get("domain")},
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
                                        {'component': 'th', 'props': {'class': 'text-start ps-4'}, 'text': '域名标识'},
                                    ]
                                }]
                            },
                            {
                                'component': 'tbody',
                                'content': items
                            }
                        ]
                    }]
                }]
            }
        ]
