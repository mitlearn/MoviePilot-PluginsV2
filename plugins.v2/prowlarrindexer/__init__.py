# _*_ coding: utf-8 _*_
"""
MoviePilot 插件：ProwlarrIndexer v0.4
通过 Prowlarr API 搜索资源，将结果以 TorrentInfo 列表返回给 MoviePilot。
"""
import copy
import traceback
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional, Tuple
from urllib.parse import quote_plus, urlencode

import pytz
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
    Prowlarr 索引器插件 v0.4
    """

    # ==================== 插件元数据 ====================
    plugin_name = "ProwlarrIndexer"
    plugin_desc = "聚合索引：通过 Prowlarr 检索站点资源"
    plugin_icon = "Prowlarr.png"
    plugin_version = "0.4"
    plugin_author = "prowlarr"
    author_url = "https://github.com/prowlarr"
    plugin_config_prefix = "prowlarr_indexer_"
    plugin_order = 16
    auth_level = 1

    # 域名前缀，域名格式: prowlarr_indexer.{numeric_id}
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
        # 索引器列表（注册到 SitesHelper 的 dict 列表）
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
        同时用于 search_torrents 和 async_search_torrents（框架自动线程池包装）。
        """
        # --- 入口日志（在任何 guard 之前） ---
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
            # 站点归属检查：名称以 PluginName- 开头
            if site_name.split("-")[0] != self.plugin_name:
                return []

            # 从域名中提取 Prowlarr indexer 数字 ID
            domain = site.get("domain", "")
            indexer_id = domain.split(".")[-1] if domain else ""
            if not indexer_id:
                logger.warning(f"[{self.plugin_name}] 无法从域名提取 indexer ID: "
                               f"site={site_name}, domain={domain}")
                return []

            logger.info(f"[{self.plugin_name}] 开始检索 \"{site_name}\"，"
                        f"indexer_id={indexer_id}，关键词=\"{keyword}\"")

            # 构建 Prowlarr 搜索 API 请求
            headers = {
                "Content-Type": "application/json",
                "User-Agent": settings.USER_AGENT,
                "X-Api-Key": self._api_key,
                "Accept": "application/json",
            }
            categories = self._get_categories(mtype)
            params = [
                ("query", keyword),
                ("indexerIds", indexer_id),
                ("type", "search"),
                ("limit", 150),
                ("offset", (page or 0) * 150),
            ] + [("categories", c) for c in categories]
            query_string = urlencode(params, quote_via=quote_plus)
            api_url = f"{self._host}/api/v1/search?{query_string}"

            logger.info(f"[{self.plugin_name}] Prowlarr API: {api_url}")

            ret = RequestUtils(
                headers=headers, timeout=self._timeout
            ).get_res(api_url, proxies=settings.PROXY if self._proxy else None)

            if not ret:
                logger.warning(f"[{self.plugin_name}] Prowlarr 无响应: {site_name}")
                return []
            if ret.status_code != 200:
                logger.warning(f"[{self.plugin_name}] Prowlarr HTTP {ret.status_code}: {site_name}")
                return []

            try:
                data = ret.json()
            except Exception as e:
                logger.error(f"[{self.plugin_name}] JSON 解析失败: {e}")
                return []

            if not isinstance(data, list):
                logger.warning(f"[{self.plugin_name}] 返回非列表数据: type={type(data).__name__}")
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
                        page_url=entry.get("infoUrl") or entry.get("commentUrl")
                                 or entry.get("guid", ""),
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

        except Exception as e:
            logger.error(f"[{self.plugin_name}] search_torrents 异常: "
                         f"{e}\n{traceback.format_exc()}")
            return []

    # ==================== 索引器管理 ====================

    def _refresh_indexers(self):
        """获取 Prowlarr 索引器列表并注册到 SitesHelper"""
        if not self._api_key or not self._host:
            logger.warning(f"[{self.plugin_name}] 地址或 API Key 未配置")
            return

        headers = {
            "Content-Type": "application/json",
            "User-Agent": settings.USER_AGENT,
            "X-Api-Key": self._api_key,
            "Accept": "application/json",
        }
        url = f"{self._host}/api/v1/indexer"
        logger.info(f"[{self.plugin_name}] 获取索引器: {url}")

        try:
            ret = RequestUtils(
                headers=headers, timeout=self._timeout
            ).get_res(url, proxies=settings.PROXY if self._proxy else None)
        except Exception as e:
            logger.error(f"[{self.plugin_name}] 请求索引器异常: {e}")
            return

        if not ret:
            logger.warning(f"[{self.plugin_name}] 索引器请求无响应")
            return
        if ret.status_code != 200:
            logger.warning(f"[{self.plugin_name}] 索引器 HTTP {ret.status_code}")
            return

        try:
            data = ret.json()
        except Exception as e:
            logger.error(f"[{self.plugin_name}] 索引器 JSON 解析失败: {e}")
            return

        if not isinstance(data, list):
            logger.warning(f"[{self.plugin_name}] 索引器返回非列表")
            return

        self._indexers = []
        for v in data:
            indexer_id = v.get("id")
            indexer_name = v.get("name")
            if not indexer_id or not indexer_name:
                continue
            if not v.get("enable", True):
                continue

            # 域名使用数字 ID，搜索时直接从域名提取
            domain = f"{self._domain_prefix}.{indexer_id}"
            self._indexers.append({
                "id": f"{self.plugin_name}-{indexer_name}",
                "name": f"{self.plugin_name}-{indexer_name}",
                "domain": domain,
                "url": f"{self._host}/api/v1/indexer/{indexer_id}",
                "public": v.get("privacy", "public") == "public",
                "proxy": self._proxy,
                "language": v.get("language", ""),
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
            "Content-Type": "application/json",
            "User-Agent": settings.USER_AGENT,
            "X-Api-Key": self._api_key,
            "Accept": "application/json",
        }
        try:
            ret = RequestUtils(headers=headers, timeout=self._timeout).get_res(
                f"{self._host}/api/v1/indexer",
                proxies=settings.PROXY if self._proxy else None,
            )
        except Exception as e:
            return {"status": "error", "message": f"连接异常: {e}"}
        if not ret:
            return {"status": "error", "message": "无响应"}
        if ret.status_code == 401:
            return {"status": "error", "message": "API Key 无效 (401)"}
        if ret.status_code != 200:
            return {"status": "error", "message": f"HTTP {ret.status_code}"}
        try:
            data = ret.json()
            count = len(data) if isinstance(data, list) else 0
            return {"status": "ok", "message": f"连接成功，发现 {count} 个索引器"}
        except Exception as e:
            return {"status": "error", "message": f"JSON 解析失败: {e}"}

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

    def __update_config(self):
        self.update_config({
            "enabled": self._enabled,
            "host": self._host,
            "api_key": self._api_key,
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
            "summary": "测试 Prowlarr 连接",
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
                                "props": {"cols": 12, "md": 6},
                                "content": [{
                                    "component": "VTextField",
                                    "props": {
                                        "model": "host",
                                        "label": "Prowlarr 地址",
                                        "placeholder": "http://127.0.0.1:9696",
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
                                            "1. 填写 Prowlarr 地址和 API Key，开启「立即刷新索引」\n"
                                            "2. 在「查看数据」页面确认索引器已注册\n"
                                            "3. 到 MoviePilot「搜索设置」中勾选以 ProwlarrIndexer 开头的站点\n"
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
                                f"请到「搜索设置」中勾选以 ProwlarrIndexer 开头的站点。",
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
