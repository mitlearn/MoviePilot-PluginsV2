# _*_ coding: utf-8 _*_
"""
MoviePilot 插件：ProwlarrIndexer
通过 Prowlarr API 搜索资源，将结果以 TorrentInfo 列表返回给 MoviePilot。
"""
import copy
import time
import traceback
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


class ProwlarrIndexer(_PluginBase):
    """
    Prowlarr 索引器插件
    通过 get_module() 劫持 search_torrents 方法，将 Prowlarr 搜索结果注入 MoviePilot 搜索链。
    """

    # ==================== 插件元数据 ====================
    plugin_name = "ProwlarrIndexer"
    plugin_desc = "聚合索引：通过 Prowlarr 检索站点资源"
    plugin_icon = "Prowlarr.png"
    plugin_version = "0.1"
    plugin_author = "prowlarr"
    author_url = "https://github.com/prowlarr"
    plugin_config_prefix = "prowlarr_indexer_"
    plugin_order = 16
    auth_level = 1

    # 域名标识前缀
    _domain_prefix = "prowlarr_indexer"

    # ==================== 生命周期 ====================

    def __init__(self):
        super().__init__()
        self._scheduler: Optional[BackgroundScheduler] = None
        self._enabled: bool = False
        self._host: str = ""
        self._api_key: str = ""
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

        headers = self._build_headers()
        categories = self._get_categories(mtype)

        # Prowlarr 要求 categories 参数重复传递，而非逗号分隔
        params = [
            ("query", keyword),
            ("indexerIds", indexer_id),
            ("type", "search"),
            ("limit", 150),
            ("offset", (page or 0) * 150),
        ] + [("categories", c) for c in categories]

        query_string = urlencode(params, quote_via=quote_plus)
        api_url = f"{self._host}/api/v1/search?{query_string}"
        logger.debug(f"[{self.plugin_name}] 请求 URL: {api_url}")

        response = self._request_with_retry(api_url, headers=headers)
        if not response:
            return []

        try:
            data = response.json()
        except Exception as e:
            logger.error(f"[{self.plugin_name}] JSON 解析失败: {e}")
            return []

        if not isinstance(data, list):
            logger.warning(f"[{self.plugin_name}] 返回非列表数据")
            return []

        results = []
        for entry in data:
            if not entry or not isinstance(entry, dict):
                continue
            try:
                title = entry.get("title")
                enclosure = entry.get("downloadUrl") or entry.get("magnetUrl")
                if not title or not enclosure:
                    continue
                torrent = TorrentInfo(
                    site_name=site_name,
                    title=title,
                    description=entry.get("sortTitle") or "",
                    enclosure=enclosure,
                    page_url=entry.get("infoUrl") or entry.get("commentUrl") or entry.get("guid", ""),
                    size=entry.get("size", 0),
                    seeders=entry.get("seeders", 0),
                    peers=entry.get("leechers") or entry.get("peers", 0),
                    grabs=entry.get("grabs", 0),
                    pubdate=entry.get("publishDate", ""),
                    imdbid=self._extract_imdb(entry),
                    downloadvolumefactor=self._parse_download_factor(entry),
                    uploadvolumefactor=self._parse_upload_factor(entry),
                )
                results.append(torrent)
            except Exception as e:
                logger.debug(f"[{self.plugin_name}] 解析条目出错: {e}")

        logger.info(f"[{self.plugin_name}] {site_name} 返回 {len(results)} 条资源")
        return results

    # ==================== 索引器管理 ====================

    def _refresh_indexers(self):
        if not self._api_key or not self._host:
            logger.warning(f"[{self.plugin_name}] 地址或 API Key 未配置")
            return

        headers = self._build_headers()
        # 使用 /api/v1/indexer 获取已配置的索引器列表
        url = f"{self._host}/api/v1/indexer"
        logger.debug(f"[{self.plugin_name}] 索引器列表请求: {url}")

        response = self._request_with_retry(url, headers=headers)
        if not response:
            return

        try:
            data = response.json()
        except Exception as e:
            logger.error(f"[{self.plugin_name}] 索引器响应解析失败: {e}")
            return

        if not isinstance(data, list):
            logger.warning(f"[{self.plugin_name}] 返回数据格式不正确")
            return

        self._indexers = []
        for v in data:
            indexer_id = v.get("id")
            indexer_name = v.get("name")
            if not indexer_id or not indexer_name:
                continue
            # 仅添加已启用且支持搜索的索引器
            if not v.get("enable", True):
                continue
            if not v.get("supportsSearch", True):
                continue

            self._indexers.append({
                "id": f"{self.plugin_name}-{indexer_name}",
                "name": f"{self.plugin_name}-{indexer_name}",
                "domain": f"{self._domain_prefix}.{indexer_id}",
                "url": f"{self._host}/api/v1/indexer/{indexer_id}",
                "public": v.get("privacy", "public") == "public",
                "proxy": self._proxy,
                "language": v.get("language", ""),
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

    # ==================== HTTP 工具 ====================

    def _build_headers(self) -> dict:
        return {
            "Content-Type": "application/json",
            "User-Agent": settings.USER_AGENT,
            "X-Api-Key": self._api_key,
            "Accept": "application/json",
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
                    if ret.status_code == 401:
                        logger.error(f"[{self.plugin_name}] API Key 无效或未授权")
                        return None
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
        """域名格式: prowlarr_indexer.<indexer_id>"""
        domain = site.get("domain", "")
        if not domain:
            return ""
        parts = domain.split(".")
        return parts[-1] if len(parts) >= 2 else ""

    @staticmethod
    def _extract_imdb(entry: dict) -> str:
        imdb_id = entry.get("imdbId")
        if imdb_id and isinstance(imdb_id, int) and imdb_id > 0:
            return f"tt{imdb_id:07d}"
        return ""

    @staticmethod
    def _parse_download_factor(entry: dict) -> Optional[float]:
        flags = entry.get("indexerFlags") or []
        if isinstance(flags, list):
            for flag in flags:
                s = str(flag).lower()
                if "freeleech" in s:
                    return 0.0
                if "halfleech" in s:
                    return 0.5
        return None

    @staticmethod
    def _parse_upload_factor(entry: dict) -> Optional[float]:
        flags = entry.get("indexerFlags") or []
        if isinstance(flags, list):
            for flag in flags:
                if "doubleupload" in str(flag).lower():
                    return 2.0
        return None

    def _save_config(self):
        self.update_config({
            "enabled": self._enabled,
            "host": self._host,
            "api_key": self._api_key,
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
                                "props": {"cols": 12, "md": 6},
                                "content": [{
                                    "component": "VTextField",
                                    "props": {
                                        "model": "host",
                                        "label": "Prowlarr 地址",
                                        "placeholder": "http://127.0.0.1:9696",
                                        "hint": "Prowlarr 访问地址",
                                    },
                                }],
                            },
                            {
                                "component": "VCol",
                                "props": {"cols": 12, "md": 6},
                                "content": [{
                                    "component": "VTextField",
                                    "props": {
                                        "model": "api_key",
                                        "label": "API Key",
                                        "hint": "Settings -> General -> Security -> API Key",
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
                                            "1. 填写 Prowlarr 地址和 API Key，开启「立即刷新索引」\n"
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
