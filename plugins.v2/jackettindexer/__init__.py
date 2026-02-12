# _*_ coding: utf-8 _*_
"""
MoviePilot 插件：JackettIndexer
通过 Jackett Torznab API 搜索资源，将结果以 TorrentInfo 列表返回给 MoviePilot。
"""
import copy
import time
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
from app.utils.http import RequestUtils
from app.utils.string import StringUtils


class JackettIndexer(_PluginBase):
    """
    Jackett 索引器插件
    通过 get_module() 劫持 search_torrents 方法，将 Jackett Torznab 搜索结果注入 MoviePilot 搜索链。
    """

    # ==================== 插件元数据 ====================
    plugin_name = "JackettIndexer"
    plugin_desc = "聚合索引：通过 Jackett 检索站点资源"
    plugin_icon = "Jackett_A.png"
    plugin_version = "0.1"
    plugin_author = "prowlarr"
    author_url = "https://github.com/prowlarr"
    plugin_config_prefix = "jackett_indexer_"
    plugin_order = 15
    auth_level = 1

    # 域名标识前缀
    _domain_prefix = "jackett_indexer"

    # ==================== 生命周期 ====================

    def __init__(self):
        super().__init__()
        self._scheduler: Optional[BackgroundScheduler] = None
        self._enabled: bool = False
        self._host: str = ""
        self._api_key: str = ""
        self._password: str = ""
        self._proxy: bool = False
        self._onlyonce: bool = False
        self._cron: str = "0 0 */24 * *"
        self._timeout: int = 30
        self._max_retries: int = 3
        self._indexers: list = []
        self._sites_helper: Optional[SitesHelper] = None

    def init_plugin(self, config: dict = None):
        self._sites_helper = SitesHelper()
        self._indexers = []

        if config:
            self._enabled = config.get("enabled", False)
            self._host = self._normalize_host(config.get("host", ""))
            self._api_key = config.get("api_key", "")
            self._password = config.get("password", "")
            self._proxy = config.get("proxy", False)
            self._onlyonce = config.get("onlyonce", False)
            self._cron = config.get("cron") or "0 0 */24 * *"
            self._timeout = int(config.get("timeout", 30))
            self._max_retries = int(config.get("max_retries", 3))

        self.stop_service()

        if not self._enabled:
            return

        self._scheduler = BackgroundScheduler(timezone=settings.TZ)
        if self._cron:
            logger.info(f"[{self.plugin_name}] 索引更新服务启动，周期：{self._cron}")
            self._scheduler.add_job(self._refresh_indexers, CronTrigger.from_crontab(self._cron))

        if self._onlyonce:
            logger.info(f"[{self.plugin_name}] 立即获取索引器列表")
            self._scheduler.add_job(
                self._refresh_indexers, "date",
                run_date=datetime.now(tz=pytz.timezone(settings.TZ)) + timedelta(seconds=3),
            )
            self._onlyonce = False
            self._save_config()

        if self._scheduler.get_jobs():
            self._scheduler.print_jobs()
            self._scheduler.start()

        if not self._indexers:
            self._refresh_indexers()

        self._register_indexers()

    def get_state(self) -> bool:
        return self._enabled

    def stop_service(self):
        try:
            if self._scheduler:
                self._scheduler.remove_all_jobs()
                if self._scheduler.running:
                    self._scheduler.shutdown()
                self._scheduler = None
        except Exception as e:
            logger.error(f"[{self.plugin_name}] 停止服务出错: {e}")

    # ==================== 模块劫持 ====================

    def get_module(self) -> Dict[str, Any]:
        return {"search_torrents": self.search_torrents}

    # ==================== 搜索逻辑 ====================

    def search_torrents(
        self,
        site: dict,
        keyword: str = None,
        mtype: Optional[MediaType] = None,
        cat: Optional[str] = None,
        page: Optional[int] = 0,
    ) -> List[TorrentInfo]:
        """
        MoviePilot 搜索链回调。仅处理本插件注册的站点。
        """
        if not site or not keyword:
            return []
        site_name = site.get("name", "")
        if not site_name.startswith(self.plugin_name):
            return []

        logger.debug(f"[{self.plugin_name}] 搜索 -> 站点: {site_name}, "
                     f"关键词: {keyword}, 类型: {mtype}, 页码: {page}")

        indexer_id = self._extract_indexer_id(site)
        if not indexer_id:
            logger.warning(f"[{self.plugin_name}] 无法提取 indexer ID: {site_name}")
            return []

        categories = self._get_categories(mtype)
        params = {
            "apikey": self._api_key,
            "t": "search",
            "q": keyword,
            "cat": ",".join(map(str, categories)),
        }
        query_string = urlencode(params, doseq=True, quote_via=quote_plus)
        api_url = f"{self._host}/api/v2.0/indexers/{indexer_id}/results/torznab/?{query_string}"

        logger.debug(f"[{self.plugin_name}] Torznab 请求 URL: {api_url}")

        results = self._parse_torznab_xml(api_url, site_name=site_name)
        logger.info(f"[{self.plugin_name}] {site_name} 返回 {len(results)} 条资源")
        return results

    # ==================== Torznab XML 解析 ====================

    def _parse_torznab_xml(self, url: str, site_name: str = "") -> List[TorrentInfo]:
        if not url:
            return []

        response = self._request_with_retry(url)
        if not response or not response.text:
            return []

        # 检查是否返回了 Torznab 错误
        text = response.text.strip()
        if "<error " in text:
            try:
                dom = xml.dom.minidom.parseString(text)
                error_node = dom.getElementsByTagName("error")
                if error_node:
                    code = error_node[0].getAttribute("code")
                    desc = error_node[0].getAttribute("description")
                    logger.error(f"[{self.plugin_name}] Torznab 错误 {code}: {desc}")
            except Exception:
                logger.error(f"[{self.plugin_name}] Torznab 返回错误响应")
            return []

        torrents: List[TorrentInfo] = []
        try:
            dom_tree = xml.dom.minidom.parseString(text)
            root_node = dom_tree.documentElement
            items = root_node.getElementsByTagName("item")
        except Exception as e:
            logger.error(f"[{self.plugin_name}] Torznab XML 解析失败: {e}")
            return []

        for item in items:
            try:
                title = self._tag_value(item, "title")
                if not title:
                    continue

                # 优先从 enclosure url 获取下载链接
                enclosure = self._tag_attr(item, "enclosure", "url")
                if not enclosure:
                    enclosure = self._tag_value(item, "link")
                if not enclosure:
                    continue

                description = self._tag_value(item, "description") or ""

                # 从 enclosure length 或 torznab:attr 获取大小
                size = self._safe_int(self._tag_attr(item, "enclosure", "length"), 0)

                page_url = self._tag_value(item, "comments") or self._tag_value(item, "guid") or ""
                pubdate = self._tag_value(item, "pubDate") or ""
                if pubdate:
                    pubdate = StringUtils.unify_datetime_str(pubdate)

                seeders = 0
                peers = 0
                grabs = 0
                imdbid = ""
                magneturl = ""
                downloadvolumefactor = None
                uploadvolumefactor = None

                for attr in item.getElementsByTagName("torznab:attr"):
                    name = attr.getAttribute("name")
                    value = attr.getAttribute("value")
                    if name == "seeders":
                        seeders = self._safe_int(value, 0)
                    elif name == "peers":
                        peers = self._safe_int(value, 0)
                    elif name == "leechers":
                        # peers 可能在某些 indexer 里是 leechers
                        if not peers:
                            peers = self._safe_int(value, 0)
                    elif name == "grabs":
                        grabs = self._safe_int(value, 0)
                    elif name == "size":
                        if not size:
                            size = self._safe_int(value, 0)
                    elif name == "imdbid":
                        imdbid = value or ""
                    elif name == "magneturl":
                        magneturl = value or ""
                    elif name == "downloadvolumefactor":
                        downloadvolumefactor = self._safe_float(value)
                    elif name == "uploadvolumefactor":
                        uploadvolumefactor = self._safe_float(value)

                # 如果 enclosure 是 magnet 链接，也记录一下
                if not magneturl and enclosure and enclosure.startswith("magnet:"):
                    magneturl = enclosure

                torrents.append(TorrentInfo(
                    site_name=site_name,
                    title=title,
                    description=description,
                    enclosure=enclosure,
                    page_url=page_url,
                    size=size,
                    seeders=seeders,
                    peers=peers,
                    grabs=grabs,
                    pubdate=pubdate,
                    imdbid=imdbid,
                    downloadvolumefactor=downloadvolumefactor,
                    uploadvolumefactor=uploadvolumefactor,
                ))
            except Exception as e:
                logger.debug(f"[{self.plugin_name}] 解析 item 出错: {e}")
                continue

        return torrents

    # ==================== 索引器管理 ====================

    def _refresh_indexers(self):
        if not self._api_key or not self._host:
            logger.warning(f"[{self.plugin_name}] 地址或 API Key 未配置")
            return

        headers = self._build_headers()
        cookie = self._jackett_login(headers)

        url = f"{self._host}/api/v2.0/indexers?configured=true"
        logger.debug(f"[{self.plugin_name}] 索引器列表请求: {url}")

        try:
            ret = RequestUtils(
                headers=headers, cookies=cookie, timeout=self._timeout,
            ).get_res(url, proxies=settings.PROXY if self._proxy else None)
        except Exception as e:
            logger.error(f"[{self.plugin_name}] 索引器请求异常: {e}")
            return

        if not ret:
            logger.warning(f"[{self.plugin_name}] 索引器请求无响应")
            return

        try:
            raw_indexers = ret.json()
        except Exception:
            logger.error(f"[{self.plugin_name}] 索引器响应 JSON 解析失败")
            return

        if not raw_indexers:
            return

        self._indexers = []
        for v in raw_indexers:
            indexer_id = v.get("id")
            indexer_name = v.get("name")
            if not indexer_id or not indexer_name:
                continue
            self._indexers.append({
                "id": f"{self.plugin_name}-{indexer_name}",
                "name": f"{self.plugin_name}-{indexer_name}",
                "domain": f"{self._domain_prefix}.{indexer_id}",
                "url": f"{self._host}/api/v2.0/indexers/{indexer_id}/results/torznab/",
                "public": True,
                "proxy": self._proxy,
                "torrents": {"list": {}, "fields": {}},
            })

        logger.info(f"[{self.plugin_name}] 获取到 {len(self._indexers)} 个索引器")
        self._register_indexers()

    def _register_indexers(self):
        if not self._sites_helper:
            return
        for indexer in self._indexers:
            domain = indexer.get("domain", "")
            if not domain:
                continue
            self._sites_helper.add_indexer(domain, copy.deepcopy(indexer))
            logger.debug(f"[{self.plugin_name}] 注册索引器: {indexer.get('name')} -> {domain}")

    def _jackett_login(self, headers: dict) -> Optional[dict]:
        if not self._password:
            return None
        session = requests.session()
        try:
            RequestUtils(headers=headers, session=session).post_res(
                url=f"{self._host}/UI/Dashboard",
                data={"password": self._password},
                params={"password": self._password},
                proxies=settings.PROXY if self._proxy else None,
            )
            if session.cookies:
                return session.cookies.get_dict()
        except Exception as e:
            logger.warning(f"[{self.plugin_name}] Jackett 登录异常: {e}")
        return None

    # ==================== HTTP 工具 ====================

    def _build_headers(self) -> dict:
        return {
            "Content-Type": "application/x-www-form-urlencoded; charset=UTF-8",
            "User-Agent": settings.USER_AGENT,
            "X-Api-Key": self._api_key,
            "Accept": "application/json, text/javascript, */*; q=0.01",
        }

    def _request_with_retry(self, url: str, headers: Optional[dict] = None) -> Optional[requests.Response]:
        proxies = settings.PROXY if self._proxy else None
        last_error = None

        for attempt in range(1, self._max_retries + 1):
            try:
                logger.debug(f"[{self.plugin_name}] HTTP GET (第{attempt}次): {url}")
                ret = RequestUtils(headers=headers, timeout=self._timeout).get_res(url, proxies=proxies)
                if ret is not None:
                    logger.debug(f"[{self.plugin_name}] 状态码: {ret.status_code}")
                    if ret.status_code == 200:
                        return ret
                    logger.warning(f"[{self.plugin_name}] HTTP {ret.status_code} (第{attempt}次)")
                else:
                    logger.warning(f"[{self.plugin_name}] 无响应 (第{attempt}次)")
            except Exception as e:
                last_error = e
                logger.warning(f"[{self.plugin_name}] 请求异常 (第{attempt}次): {e}")

            if attempt < self._max_retries:
                wait = 2 ** attempt
                logger.debug(f"[{self.plugin_name}] {wait}秒后重试...")
                time.sleep(wait)

        logger.error(f"[{self.plugin_name}] 请求失败，已重试 {self._max_retries} 次: {url}"
                     + (f" 最后错误: {last_error}" if last_error else ""))
        return None

    # ==================== 辅助方法 ====================

    @staticmethod
    def _normalize_host(host: str) -> str:
        if not host:
            return ""
        host = host.strip()
        if not host.startswith("http"):
            host = "http://" + host
        return host.rstrip("/")

    @staticmethod
    def _get_categories(mtype: Optional[MediaType] = None) -> list:
        if not mtype:
            return [2000, 5000]
        if mtype == MediaType.MOVIE:
            return [2000]
        if mtype == MediaType.TV:
            return [5000]
        return [2000, 5000]

    def _extract_indexer_id(self, site: dict) -> str:
        """域名格式: jackett_indexer.<indexer_id>"""
        domain = site.get("domain", "")
        if not domain:
            return ""
        parts = domain.split(".")
        return parts[-1] if len(parts) >= 2 else ""

    @staticmethod
    def _tag_value(node, tag: str) -> str:
        elements = node.getElementsByTagName(tag)
        if elements and elements[0].childNodes:
            return elements[0].childNodes[0].data.strip()
        return ""

    @staticmethod
    def _tag_attr(node, tag: str, attr: str) -> str:
        elements = node.getElementsByTagName(tag)
        if elements:
            return elements[0].getAttribute(attr) or ""
        return ""

    @staticmethod
    def _safe_int(value, default: int = 0) -> int:
        try:
            return int(value)
        except (ValueError, TypeError):
            return default

    @staticmethod
    def _safe_float(value, default: float = None) -> Optional[float]:
        try:
            return float(value)
        except (ValueError, TypeError):
            return default

    def _save_config(self):
        self.update_config({
            "enabled": self._enabled,
            "host": self._host,
            "api_key": self._api_key,
            "password": self._password,
            "proxy": self._proxy,
            "onlyonce": self._onlyonce,
            "cron": self._cron,
            "timeout": self._timeout,
            "max_retries": self._max_retries,
        })

    # ==================== 插件接口 ====================

    @staticmethod
    def get_command() -> List[Dict[str, Any]]:
        return []

    def get_api(self) -> List[Dict[str, Any]]:
        return []

    def get_form(self) -> Tuple[List[dict], Dict[str, Any]]:
        return [
            {
                "component": "VForm",
                "content": [
                    {
                        "component": "VRow",
                        "content": [
                            {
                                "component": "VCol",
                                "props": {"cols": 12, "md": 4},
                                "content": [{
                                    "component": "VSwitch",
                                    "props": {"model": "enabled", "label": "启用插件"},
                                }],
                            },
                            {
                                "component": "VCol",
                                "props": {"cols": 12, "md": 4},
                                "content": [{
                                    "component": "VSwitch",
                                    "props": {"model": "proxy", "label": "使用代理"},
                                }],
                            },
                            {
                                "component": "VCol",
                                "props": {"cols": 12, "md": 4},
                                "content": [{
                                    "component": "VSwitch",
                                    "props": {
                                        "model": "onlyonce",
                                        "label": "立即刷新索引",
                                        "hint": "打开后立即获取索引器列表",
                                    },
                                }],
                            },
                        ],
                    },
                    {
                        "component": "VRow",
                        "content": [
                            {
                                "component": "VCol",
                                "props": {"cols": 12, "md": 4},
                                "content": [{
                                    "component": "VTextField",
                                    "props": {
                                        "model": "host",
                                        "label": "Jackett 地址",
                                        "placeholder": "http://127.0.0.1:9117",
                                        "hint": "Jackett 访问地址，需先在 Jackett 中添加 indexer",
                                    },
                                }],
                            },
                            {
                                "component": "VCol",
                                "props": {"cols": 12, "md": 4},
                                "content": [{
                                    "component": "VTextField",
                                    "props": {
                                        "model": "api_key",
                                        "label": "API Key",
                                        "hint": "Jackett 管理界面右上角复制",
                                    },
                                }],
                            },
                            {
                                "component": "VCol",
                                "props": {"cols": 12, "md": 4},
                                "content": [{
                                    "component": "VTextField",
                                    "props": {
                                        "model": "password",
                                        "label": "管理密码",
                                        "type": "password",
                                        "hint": "Jackett Admin Password，未设置可留空",
                                    },
                                }],
                            },
                        ],
                    },
                    {
                        "component": "VRow",
                        "content": [
                            {
                                "component": "VCol",
                                "props": {"cols": 12, "md": 4},
                                "content": [{
                                    "component": "VTextField",
                                    "props": {
                                        "model": "cron",
                                        "label": "索引更新周期",
                                        "placeholder": "0 0 */24 * *",
                                        "hint": "Cron 表达式，默认每24小时",
                                    },
                                }],
                            },
                            {
                                "component": "VCol",
                                "props": {"cols": 12, "md": 4},
                                "content": [{
                                    "component": "VTextField",
                                    "props": {
                                        "model": "timeout",
                                        "label": "超时(秒)",
                                        "type": "number",
                                        "placeholder": "30",
                                    },
                                }],
                            },
                            {
                                "component": "VCol",
                                "props": {"cols": 12, "md": 4},
                                "content": [{
                                    "component": "VTextField",
                                    "props": {
                                        "model": "max_retries",
                                        "label": "重试次数",
                                        "type": "number",
                                        "placeholder": "3",
                                    },
                                }],
                            },
                        ],
                    },
                    {
                        "component": "VRow",
                        "content": [{
                            "component": "VCol",
                            "props": {"cols": 12},
                            "content": [{
                                "component": "VAlert",
                                "props": {
                                    "type": "info",
                                    "variant": "tonal",
                                    "text": "使用说明：\n"
                                            "1. 填写 Jackett 地址、API Key 和管理密码，开启「立即刷新索引」\n"
                                            "2. 在「查看数据」页面复制站点 domain\n"
                                            "3. 到站点管理新增站点（格式: https://<domain>）\n"
                                            "4. 在搜索设置中勾选新增的站点即可使用",
                                },
                            }],
                        }],
                    },
                ],
            }
        ], {
            "enabled": False,
            "host": "",
            "api_key": "",
            "password": "",
            "proxy": False,
            "onlyonce": False,
            "cron": "0 0 */24 * *",
            "timeout": 30,
            "max_retries": 3,
        }

    def get_page(self) -> List[dict]:
        if not self._indexers:
            self._refresh_indexers()
        if not self._indexers:
            return [{
                "component": "VRow",
                "content": [{
                    "component": "VCol",
                    "props": {"cols": 12},
                    "content": [{
                        "component": "VAlert",
                        "props": {
                            "type": "warning",
                            "variant": "tonal",
                            "text": "未获取到任何索引器，请检查配置后点击「立即刷新索引」",
                        },
                    }],
                }],
            }]

        rows = []
        for site in self._indexers:
            rows.append({
                "component": "tr",
                "content": [
                    {"component": "td", "text": site.get("name", "")},
                    {"component": "td", "text": f"https://{site.get('domain', '')}"},
                    {"component": "td", "text": "是" if site.get("public") else "否"},
                ],
            })

        return [{
            "component": "VRow",
            "content": [{
                "component": "VCol",
                "props": {"cols": 12},
                "content": [{
                    "component": "VTable",
                    "props": {"hover": True},
                    "content": [
                        {
                            "component": "thead",
                            "content": [{
                                "component": "tr",
                                "content": [
                                    {"component": "th", "props": {"class": "text-start ps-4"}, "text": "索引器名称"},
                                    {"component": "th", "props": {"class": "text-start ps-4"}, "text": "站点 Domain"},
                                    {"component": "th", "props": {"class": "text-start ps-4"}, "text": "公开"},
                                ],
                            }],
                        },
                        {"component": "tbody", "content": rows},
                    ],
                }],
            }],
        }]
