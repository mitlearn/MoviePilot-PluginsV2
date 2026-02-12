# _*_ coding: utf-8 _*_
"""
MoviePilot 插件：JackettIndexer v0.4
通过 Jackett Torznab API 搜索资源，将结果以 TorrentInfo 列表返回给 MoviePilot。
"""
import copy
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
    Jackett 索引器插件 v0.4
    """

    # ==================== 插件元数据 ====================
    plugin_name = "JackettIndexer"
    plugin_desc = "聚合索引：通过 Jackett 检索站点资源"
    plugin_icon = "Jackett_A.png"
    plugin_version = "0.4"
    plugin_author = "prowlarr"
    author_url = "https://github.com/prowlarr"
    plugin_config_prefix = "jackett_indexer_"
    plugin_order = 15
    auth_level = 1

    # 域名前缀，域名格式: jackett_indexer.{indexer_id}
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

        self.stop_service()

        if not self._enabled:
            return

        self._scheduler = BackgroundScheduler(timezone=settings.TZ)
        if self._cron:
            self._scheduler.add_job(self._refresh_indexers, CronTrigger.from_crontab(self._cron))

        if self._onlyonce:
            logger.info(f"[{self.plugin_name}] 立即获取索引器列表")
            self._scheduler.add_job(
                self._refresh_indexers, "date",
                run_date=datetime.now(tz=pytz.timezone(settings.TZ)) + timedelta(seconds=3),
            )
            self._onlyonce = False
            self.__update_config()

        if self._scheduler.get_jobs():
            self._scheduler.print_jobs()
            self._scheduler.start()

        # 同步刷新索引器并注册
        if not self._indexers:
            self._refresh_indexers()

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
        return {
            "search_torrents": self.search_torrents,
            "async_search_torrents": self.search_torrents,
        }

    # ==================== 搜索逻辑 ====================

    def search_torrents(
        self,
        site: dict = None,
        keyword: str = None,
        mtype: Optional[MediaType] = None,
        page: Optional[int] = 0,
    ) -> List[TorrentInfo]:
        """
        MoviePilot 搜索链回调。仅处理本插件注册的站点。
        """
        # --- 入口日志 ---
        try:
            _site_name = site.get("name", "") if isinstance(site, dict) else str(site)
        except Exception:
            _site_name = "(unknown)"
        logger.debug(f"[{self.plugin_name}] search_torrents 调用: "
                     f"site_name={_site_name}, keyword={keyword}, mtype={mtype}")

        try:
            if not site or not keyword:
                return []

            site_name = site.get("name", "") if isinstance(site, dict) else ""
            if site_name.split("-")[0] != self.plugin_name:
                return []

            # 从域名提取 Jackett indexer ID
            domain = site.get("domain", "")
            indexer_id = domain.split(".")[-1] if domain else ""
            if not indexer_id:
                logger.warning(f"[{self.plugin_name}] 无法从域名提取 indexer ID: "
                               f"site={site_name}, domain={domain}")
                return []

            categories = self._get_categories(mtype)
            params = {
                "apikey": self._api_key,
                "t": "search",
                "q": keyword,
                "cat": ",".join(map(str, categories)),
            }
            query_string = urlencode(params, doseq=True, quote_via=quote_plus)
            api_url = (f"{self._host}/api/v2.0/indexers/{indexer_id}"
                       f"/results/torznab/?{query_string}")

            logger.info(f"[{self.plugin_name}] 开始检索 \"{site_name}\"，"
                        f"indexer_id={indexer_id}，关键词=\"{keyword}\"")
            logger.info(f"[{self.plugin_name}] Torznab API: {api_url}")

            results = self._parse_torznab_xml(api_url, site_name=site_name)
            logger.info(f"[{self.plugin_name}] {site_name} 返回 {len(results)} 条资源")
            return results

        except Exception as e:
            logger.error(f"[{self.plugin_name}] search_torrents 异常: "
                         f"{e}\n{traceback.format_exc()}")
            return []

    # ==================== Torznab XML 解析 ====================

    def _parse_torznab_xml(self, url: str, site_name: str = "") -> List[TorrentInfo]:
        if not url:
            return []

        try:
            ret = RequestUtils(timeout=self._timeout).get_res(
                url, proxies=settings.PROXY if self._proxy else None
            )
        except Exception as e:
            logger.error(f"[{self.plugin_name}] Torznab 请求异常: {e}")
            return []

        if not ret or not ret.text:
            logger.warning(f"[{self.plugin_name}] Torznab 无响应: {url}")
            return []

        text = ret.text.strip()
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
            logger.error(f"[{self.plugin_name}] XML 解析失败: {e}")
            return []

        for item in items:
            try:
                title = self._tag_value(item, "title")
                if not title:
                    continue

                enclosure = self._tag_attr(item, "enclosure", "url")
                if not enclosure:
                    enclosure = self._tag_value(item, "link")
                if not enclosure:
                    continue

                description = self._tag_value(item, "description") or ""
                size = self._safe_int(self._tag_attr(item, "enclosure", "length"), 0)
                page_url = (self._tag_value(item, "comments")
                            or self._tag_value(item, "guid") or "")
                pubdate = self._tag_value(item, "pubDate") or ""
                if pubdate:
                    pubdate = StringUtils.unify_datetime_str(pubdate)

                seeders = 0
                peers = 0
                grabs = 0
                imdbid = ""
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
                        if not peers:
                            peers = self._safe_int(value, 0)
                    elif name == "grabs":
                        grabs = self._safe_int(value, 0)
                    elif name == "size":
                        if not size:
                            size = self._safe_int(value, 0)
                    elif name == "imdbid":
                        imdbid = value or ""
                    elif name == "downloadvolumefactor":
                        downloadvolumefactor = self._safe_float(value)
                    elif name == "uploadvolumefactor":
                        uploadvolumefactor = self._safe_float(value)

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
        """
        获取 Jackett 索引器列表（参考 jtcymc/JackettExtend 实现）：
        1. 登录 Jackett 获取 session cookies
        2. 使用 cookies 请求 REST API 获取索引器列表
        """
        if not self._api_key or not self._host:
            logger.warning(f"[{self.plugin_name}] 地址或 API Key 未配置")
            return

        headers = {
            "Content-Type": "application/x-www-form-urlencoded; charset=UTF-8",
            "User-Agent": settings.USER_AGENT,
            "X-Api-Key": self._api_key,
            "Accept": "application/json, text/javascript, */*; q=0.01",
        }

        # Step 1: 登录获取 session cookies
        cookie = None
        session = requests.session()
        try:
            login_url = f"{self._host}/UI/Dashboard"
            login_res = RequestUtils(headers=headers, session=session).post_res(
                url=login_url,
                data={"password": self._password or ""},
                params={"password": self._password or ""},
                proxies=settings.PROXY if self._proxy else None,
            )
            if login_res and session.cookies:
                cookie = session.cookies.get_dict()
                logger.info(f"[{self.plugin_name}] Jackett 登录成功，获取到 cookie")
            else:
                logger.warning(f"[{self.plugin_name}] Jackett 登录未返回 cookie")
        except Exception as e:
            logger.warning(f"[{self.plugin_name}] Jackett 登录异常（忽略）: {e}")

        # Step 2: 使用 cookies 请求索引器列表（不在 URL 中带 apikey，参考 jtcymc 实现）
        indexer_url = f"{self._host}/api/v2.0/indexers?configured=true"
        logger.info(f"[{self.plugin_name}] 索引器列表请求: {indexer_url}")

        try:
            ret = RequestUtils(
                headers=headers, cookies=cookie, timeout=self._timeout,
            ).get_res(indexer_url, proxies=settings.PROXY if self._proxy else None)
        except Exception as e:
            logger.error(f"[{self.plugin_name}] 索引器请求异常: {e}")
            return

        if not ret:
            logger.warning(f"[{self.plugin_name}] 索引器请求无响应")
            return

        logger.debug(f"[{self.plugin_name}] 响应状态码: {ret.status_code}, "
                     f"Content-Type: {ret.headers.get('Content-Type', 'unknown')}")

        if ret.status_code != 200:
            logger.warning(f"[{self.plugin_name}] 索引器 HTTP {ret.status_code}")
            # 尝试打印响应体前200字符帮助调试
            body = ret.text[:200] if ret.text else "(empty)"
            logger.debug(f"[{self.plugin_name}] 响应内容: {body}")
            return

        # 解析 JSON
        try:
            raw_indexers = ret.json()
        except Exception:
            # 尝试 utf-8-sig（BOM 处理）
            try:
                import json
                raw_indexers = json.loads(ret.content.decode("utf-8-sig"))
            except Exception:
                body = ret.text[:500] if ret.text else "(empty)"
                logger.error(f"[{self.plugin_name}] JSON 解析失败，响应前500字符: {body}")
                return

        if not isinstance(raw_indexers, list):
            logger.warning(f"[{self.plugin_name}] 返回非列表: type={type(raw_indexers).__name__}")
            return

        self._indexers = []
        for v in raw_indexers:
            indexer_id = v.get("id")
            indexer_name = v.get("name")
            if not indexer_id or not indexer_name:
                continue

            # 域名使用 Jackett indexer ID（字符串，如 "beyondhd"）
            domain = f"{self._domain_prefix}.{indexer_id}"
            self._indexers.append({
                "id": f"{self.plugin_name}-{indexer_name}",
                "name": f"{self.plugin_name}-{indexer_name}",
                "domain": domain,
                "url": f"{self._host}/api/v2.0/indexers/{indexer_id}/results/torznab/",
                "public": True,
                "proxy": self._proxy,
            })

        logger.info(f"[{self.plugin_name}] 获取到 {len(self._indexers)} 个索引器:")
        for idx in self._indexers:
            logger.info(f"[{self.plugin_name}]   - {idx['name']} (domain={idx['domain']})")

        # 注册到 SitesHelper
        self._register_indexers()

    def _register_indexers(self):
        if not self._sites_helper:
            return
        for indexer in self._indexers:
            domain = indexer.get("domain", "")
            if not domain:
                continue
            existing = self._sites_helper.get_indexer(domain)
            if not existing:
                self._sites_helper.add_indexer(domain, copy.deepcopy(indexer))
                logger.info(f"[{self.plugin_name}] 注册: {indexer.get('name')} -> {domain}")
            else:
                logger.debug(f"[{self.plugin_name}] 已存在: {domain}")

    # ==================== 测试连接 ====================

    def _test_connection(self) -> dict:
        if not self._host or not self._api_key:
            return {"status": "error", "message": "地址或 API Key 未配置"}

        headers = {
            "Content-Type": "application/x-www-form-urlencoded; charset=UTF-8",
            "User-Agent": settings.USER_AGENT,
            "X-Api-Key": self._api_key,
            "Accept": "application/json, text/javascript, */*; q=0.01",
        }

        # 登录
        cookie = None
        session = requests.session()
        try:
            login_res = RequestUtils(headers=headers, session=session).post_res(
                url=f"{self._host}/UI/Dashboard",
                data={"password": self._password or ""},
                params={"password": self._password or ""},
                proxies=settings.PROXY if self._proxy else None,
            )
            if login_res and session.cookies:
                cookie = session.cookies.get_dict()
        except Exception:
            pass

        url = f"{self._host}/api/v2.0/indexers?configured=true"
        try:
            ret = RequestUtils(
                headers=headers, cookies=cookie, timeout=self._timeout,
            ).get_res(url, proxies=settings.PROXY if self._proxy else None)
        except Exception as e:
            return {"status": "error", "message": f"连接异常: {e}"}

        if not ret:
            return {"status": "error", "message": "无响应"}
        if ret.status_code != 200:
            return {"status": "error", "message": f"HTTP {ret.status_code}"}

        try:
            data = ret.json()
            count = len(data) if isinstance(data, list) else 0
            return {"status": "ok", "message": f"连接成功，发现 {count} 个索引器"}
        except Exception:
            try:
                import json
                data = json.loads(ret.content.decode("utf-8-sig"))
                count = len(data) if isinstance(data, list) else 0
                return {"status": "ok", "message": f"连接成功(BOM)，发现 {count} 个索引器"}
            except Exception as e:
                body = ret.text[:200] if ret.text else "(empty)"
                return {"status": "error",
                        "message": f"JSON 解析失败: {e}, 响应: {body}"}

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

    def __update_config(self):
        self.update_config({
            "enabled": self._enabled,
            "host": self._host,
            "api_key": self._api_key,
            "password": self._password,
            "proxy": self._proxy,
            "onlyonce": self._onlyonce,
            "cron": self._cron,
            "timeout": self._timeout,
        })

    # ==================== 插件接口 ====================

    @staticmethod
    def get_command() -> List[Dict[str, Any]]:
        return []

    def get_api(self) -> List[Dict[str, Any]]:
        return [{
            "path": "/test",
            "endpoint": self._test_connection,
            "methods": ["GET"],
            "summary": "测试 Jackett 连接",
        }]

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
                                "props": {"cols": 12, "md": 6},
                                "content": [{
                                    "component": "VTextField",
                                    "props": {
                                        "model": "cron",
                                        "label": "索引更新周期",
                                        "placeholder": "0 0 */24 * *",
                                    },
                                }],
                            },
                            {
                                "component": "VCol",
                                "props": {"cols": 12, "md": 6},
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
                                            "1. 填写 Jackett 地址、API Key 和管理密码，"
                                            "开启「立即刷新索引」\n"
                                            "2. 在「查看数据」页面确认索引器已注册\n"
                                            "3. 到 MoviePilot「搜索设置」中勾选以 "
                                            "JackettIndexer 开头的站点\n"
                                            "4. 若更新插件后域名变更，需重新在搜索设置中勾选",
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
                    {"component": "td", "text": site.get("id", "")},
                    {"component": "td", "text": site.get("name", "")},
                    {"component": "td", "text": site.get("domain", "")},
                    {"component": "td", "text": "是" if site.get("public") else "否"},
                ],
            })

        return [{
            "component": "VRow",
            "content": [{
                "component": "VCol",
                "props": {"cols": 12},
                "content": [{
                    "component": "VAlert",
                    "props": {
                        "type": "success",
                        "variant": "tonal",
                        "text": f"已注册 {len(self._indexers)} 个索引器。"
                                f"请到「搜索设置」中勾选以 JackettIndexer 开头的站点。",
                    },
                }],
            }],
        }, {
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
                                    {"component": "th", "props": {"class": "text-start ps-4"},
                                     "text": "站点 ID"},
                                    {"component": "th", "props": {"class": "text-start ps-4"},
                                     "text": "索引器名称"},
                                    {"component": "th", "props": {"class": "text-start ps-4"},
                                     "text": "域名"},
                                    {"component": "th", "props": {"class": "text-start ps-4"},
                                     "text": "公开"},
                                ],
                            }],
                        },
                        {"component": "tbody", "content": rows},
                    ],
                }],
            }],
        }]
