import datetime
import pytz
from typing import Optional, List, Dict, Tuple, Any
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger

from app.core.config import settings
from app.core.event import eventmanager, Event
from app.log import logger
from app.plugins import _PluginBase
from app.schemas.types import EventType, NotificationType, MediaType
from app.utils.http import RequestUtils
from app.chain.subscribe import SubscribeChain
from app.chain.download import DownloadChain
from app.chain.search import SearchChain
from app.helper.mediaserver import MediaServerHelper
from app.core.metainfo import MetaInfo
from app.db.systemconfig_oper import SystemConfigOper
from app.db.subscribe_oper import SubscribeOper
from app.schemas import SystemConfigKey


class TraktSync(_PluginBase):
    # ── 元信息（类变量）──
    plugin_name = "Trakt想看"
    plugin_desc = "同步Trakt想看数据，自动添加订阅。"
    plugin_icon = "Trakt_A.png"
    plugin_version = "0.1.0"
    plugin_author = "MoviePilot"
    author_url = "https://github.com/jxxghp/MoviePilot"
    plugin_config_prefix = "traktsync_"
    plugin_order = 20
    auth_level = 2

    # ── Trakt API 配置 ──
    _api_base = "https://api.trakt.tv"
    _oauth_url = f"{_api_base}/oauth/token"
    _watchlist_movies_url = f"{_api_base}/sync/watchlist/movies"
    _watchlist_shows_url = f"{_api_base}/sync/watchlist/shows"
    _api_version = "2"

    # ── 私有属性 ──
    _scheduler: Optional[BackgroundScheduler] = None
    _mediaserver_helper: Optional[MediaServerHelper] = None

    # ── 配置属性 ──
    _enabled: bool = False
    _onlyonce: bool = False
    _cron: str = ""
    _notify: bool = True
    _client_id: str = ""
    _client_secret: str = ""
    _refresh_token: str = ""
    _access_token: str = ""
    _token_expires_at: Optional[datetime.datetime] = None
    _auto_download: bool = False

    def init_plugin(self, config: dict = None):
        """初始化插件配置"""
        # 停止旧的调度任务
        self.stop_service()

        # 初始化 MediaServer Helper
        if not self._mediaserver_helper:
            self._mediaserver_helper = MediaServerHelper()

        # 读取配置
        if config:
            self._enabled = config.get("enabled", False)
            self._cron = config.get("cron", "")
            self._notify = config.get("notify", True)
            self._onlyonce = config.get("onlyonce", False)
            self._client_id = config.get("client_id", "")
            self._client_secret = config.get("client_secret", "")
            self._refresh_token = config.get("refresh_token", "")
            self._access_token = config.get("access_token", "")
            self._auto_download = config.get("auto_download", False)

            # 解析 token 过期时间
            token_expires_str = config.get("token_expires_at")
            if token_expires_str:
                try:
                    self._token_expires_at = datetime.datetime.fromisoformat(token_expires_str)
                except Exception as e:
                    logger.error(f"解析 token 过期时间失败: {str(e)}")
                    self._token_expires_at = None

        # 立即运行一次
        if self._enabled or self._onlyonce:
            if self._onlyonce:
                logger.info("Trakt想看服务启动，立即运行一次")
                self._scheduler = BackgroundScheduler(timezone=settings.TZ)
                self._scheduler.add_job(
                    func=self.sync,
                    trigger='date',
                    run_date=datetime.datetime.now(tz=pytz.timezone(settings.TZ))
                             + datetime.timedelta(seconds=3)
                )
                if self._scheduler.get_jobs():
                    self._scheduler.print_jobs()
                    self._scheduler.start()

            # 一次性开关用完即关
            if self._onlyonce:
                self._onlyonce = False
                self.__update_config()

    def get_state(self) -> bool:
        """获取插件状态"""
        return self._enabled

    def __update_config(self):
        """持久化配置"""
        config = {
            "enabled": self._enabled,
            "notify": self._notify,
            "onlyonce": self._onlyonce,
            "cron": self._cron,
            "client_id": self._client_id,
            "client_secret": self._client_secret,
            "refresh_token": self._refresh_token,
            "access_token": self._access_token,
            "auto_download": self._auto_download,
        }
        if self._token_expires_at:
            config["token_expires_at"] = self._token_expires_at.isoformat()
        self.update_config(config)

    def get_form(self) -> Tuple[List[dict], Dict[str, Any]]:
        """返回配置页面"""
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
                                        'model': 'notify',
                                        'label': '发送通知',
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
                                'props': {'cols': 12, 'md': 4},
                                'content': [{
                                    'component': 'VSwitch',
                                    'props': {
                                        'model': 'auto_download',
                                        'label': '搜索下载',
                                        'hint': '同步后自动搜索并下载资源',
                                        'persistent-hint': True
                                    }
                                }]
                            },
                            {
                                'component': 'VCol',
                                'props': {'cols': 12, 'md': 8},
                                'content': [{
                                    'component': 'VTextField',
                                    'props': {
                                        'model': 'cron',
                                        'label': '执行周期',
                                        'placeholder': '5位cron表达式，留空则默认每天执行一次'
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
                                        'model': 'client_id',
                                        'label': 'Trakt Client ID',
                                        'placeholder': '请输入Trakt应用的Client ID'
                                    }
                                }]
                            },
                            {
                                'component': 'VCol',
                                'props': {'cols': 12, 'md': 6},
                                'content': [{
                                    'component': 'VTextField',
                                    'props': {
                                        'model': 'client_secret',
                                        'label': 'Trakt Client Secret',
                                        'placeholder': '请输入Trakt应用的Client Secret'
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
                                    'component': 'VTextField',
                                    'props': {
                                        'model': 'refresh_token',
                                        'label': 'Refresh Token',
                                        'placeholder': '请输入Trakt的Refresh Token'
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
                                        'type': 'info',
                                        'variant': 'tonal',
                                        'text': '1. 前往 https://trakt.tv/oauth/applications/new 创建应用（Redirect URI填：urn:ietf:wg:oauth:2.0:oob）\n'
                                               '2. 获取 Client ID 和 Client Secret\n'
                                               '3. 参考使用说明获取 Refresh Token\n'
                                               '4. 搜索下载开启后，会自动搜索资源并下载，未下载完成的会自动添加订阅'
                                    }
                                }]
                            }
                        ]
                    }
                ]
            }
        ], {
            "enabled": False,
            "notify": True,
            "onlyonce": False,
            "cron": "0 8 * * *",
            "client_id": "",
            "client_secret": "",
            "refresh_token": "",
            "auto_download": False
        }

    def get_page(self) -> Optional[List[dict]]:
        """插件详情页面"""
        return None

    def get_service(self) -> List[Dict[str, Any]]:
        """注册常驻定时服务"""
        if self._enabled and self._cron:
            return [{
                "id": "TraktSync",
                "name": "Trakt想看同步服务",
                "trigger": CronTrigger.from_crontab(self._cron),
                "func": self.sync,
                "kwargs": {}
            }]
        elif self._enabled:
            # 无 cron 时，默认每天执行一次
            return [{
                "id": "TraktSync",
                "name": "Trakt想看同步服务",
                "trigger": "interval",
                "func": self.sync,
                "kwargs": {"days": 1}
            }]
        return []

    @staticmethod
    def get_command() -> List[Dict[str, Any]]:
        """注册远程命令"""
        return [
            {
                "cmd": "/trakt_sync",
                "event": EventType.PluginAction,
                "desc": "同步Trakt想看",
                "category": "订阅",
                "data": {
                    "action": "trakt_sync"
                }
            },
            {
                "cmd": "/trakt_download",
                "event": EventType.PluginAction,
                "desc": "同步并下载Trakt想看",
                "category": "订阅",
                "data": {
                    "action": "trakt_download"
                }
            }
        ]

    @eventmanager.register(EventType.PluginAction)
    def remote_sync(self, event: Event):
        """远程命令事件处理"""
        if event:
            event_data = event.event_data
            if not event_data:
                return

            action = event_data.get("action")
            if action not in ["trakt_sync", "trakt_download"]:
                return

            logger.info(f"收到命令，开始执行Trakt想看同步 ...")
            self.post_message(
                channel=event_data.get("channel"),
                title="开始同步Trakt想看 ...",
                userid=event_data.get("user")
            )

        # 执行同步（如果是 trakt_download 则强制开启自动下载）
        auto_download = event.event_data.get("action") == "trakt_download" if event else False
        self.sync(force_download=auto_download)

        if event:
            self.post_message(
                channel=event.event_data.get("channel"),
                title="同步Trakt想看数据完成！",
                userid=event.event_data.get("user")
            )

    def get_api(self) -> List[Dict[str, Any]]:
        """注册API"""
        return []

    def stop_service(self):
        """停止服务"""
        try:
            if self._scheduler:
                self._scheduler.remove_all_jobs()
                if self._scheduler.running:
                    self._scheduler.shutdown()
                self._scheduler = None
        except Exception as e:
            logger.error(f"退出插件失败：{str(e)}")

    # ────────────────────────────────────────────────────────────────
    # 核心同步逻辑
    # ────────────────────────────────────────────────────────────────

    def sync(self, force_download: bool = False):
        """
        同步Trakt想看列表
        :param force_download: 是否强制开启搜索下载（用于远程命令）
        """
        if not self._client_id or not self._client_secret or not self._refresh_token:
            logger.error("Trakt配置不完整，请检查Client ID、Client Secret和Refresh Token")
            return

        # 刷新 access token
        if not self.__refresh_access_token():
            logger.error("Trakt access token刷新失败，同步终止")
            return

        logger.info("开始同步Trakt想看列表...")

        # 统计数据
        stats = {
            "movies_added": 0,
            "shows_added": 0,
            "movies_exists": 0,
            "shows_exists": 0,
            "errors": 0
        }

        # 是否启用搜索下载
        enable_download = force_download or self._auto_download

        # 同步电影
        movies = self.__get_watchlist_movies()
        if movies:
            logger.info(f"获取到 {len(movies)} 部Trakt想看电影")
            for item in movies:
                try:
                    movie_data = item.get("movie", {})
                    if self.__sync_movie(movie_data, enable_download):
                        stats["movies_added"] += 1
                    else:
                        stats["movies_exists"] += 1
                except Exception as e:
                    logger.error(f"同步电影失败: {str(e)}")
                    stats["errors"] += 1

        # 同步剧集
        shows = self.__get_watchlist_shows()
        if shows:
            logger.info(f"获取到 {len(shows)} 部Trakt想看剧集")
            for item in shows:
                try:
                    show_data = item.get("show", {})
                    if self.__sync_show(show_data, enable_download):
                        stats["shows_added"] += 1
                    else:
                        stats["shows_exists"] += 1
                except Exception as e:
                    logger.error(f"同步剧集失败: {str(e)}")
                    stats["errors"] += 1

        # 发送通知
        if self._notify:
            self.__send_notification(stats)

        logger.info(f"Trakt想看同步完成: 新增电影 {stats['movies_added']} 部，"
                   f"新增剧集 {stats['shows_added']} 部，"
                   f"已存在电影 {stats['movies_exists']} 部，"
                   f"已存在剧集 {stats['shows_exists']} 部，"
                   f"错误 {stats['errors']} 个")

    def __refresh_access_token(self) -> bool:
        """
        刷新 Trakt access token
        :return: 是否成功
        """
        # 检查 token 是否需要刷新（提前1小时刷新）
        if self._access_token and self._token_expires_at:
            now = datetime.datetime.now(tz=pytz.UTC)
            if self._token_expires_at > now + datetime.timedelta(hours=1):
                logger.debug("Access token未过期，无需刷新")
                return True

        logger.info("正在刷新Trakt access token...")

        try:
            # 发起 token refresh 请求
            response = RequestUtils(
                headers={"Content-Type": "application/json"},
                proxies=settings.PROXY  # 使用系统代理
            ).post_res(
                url=self._oauth_url,
                json={
                    "refresh_token": self._refresh_token,
                    "client_id": self._client_id,
                    "client_secret": self._client_secret,
                    "redirect_uri": "urn:ietf:wg:oauth:2.0:oob",
                    "grant_type": "refresh_token"
                }
            )

            if not response or response.status_code != 200:
                logger.error(f"Token刷新失败: {response.status_code if response else 'No response'}")
                if response:
                    logger.error(f"响应内容: {response.text}")
                return False

            token_data = response.json()
            self._access_token = token_data.get("access_token")
            new_refresh_token = token_data.get("refresh_token")
            expires_in = token_data.get("expires_in", 86400)  # 默认24小时

            # 更新 refresh token（如果返回了新的）
            if new_refresh_token:
                self._refresh_token = new_refresh_token

            # 计算过期时间
            self._token_expires_at = datetime.datetime.now(tz=pytz.UTC) + datetime.timedelta(seconds=expires_in)

            # 持久化配置
            self.__update_config()

            logger.info(f"Access token刷新成功，有效期至 {self._token_expires_at.isoformat()}")
            return True

        except Exception as e:
            logger.error(f"Token刷新异常: {str(e)}")
            return False

    def __get_watchlist_movies(self) -> Optional[List[dict]]:
        """
        获取Trakt想看电影列表
        :return: 电影列表
        """
        try:
            response = RequestUtils(
                headers={
                    "Content-Type": "application/json",
                    "trakt-api-version": self._api_version,
                    "trakt-api-key": self._client_id,
                    "Authorization": f"Bearer {self._access_token}"
                },
                proxies=settings.PROXY  # 使用系统代理
            ).get_res(url=self._watchlist_movies_url)

            if not response or response.status_code != 200:
                logger.error(f"获取想看电影失败: {response.status_code if response else 'No response'}")
                return None

            return response.json()

        except Exception as e:
            logger.error(f"获取想看电影异常: {str(e)}")
            return None

    def __get_watchlist_shows(self) -> Optional[List[dict]]:
        """
        获取Trakt想看剧集列表
        :return: 剧集列表
        """
        try:
            response = RequestUtils(
                headers={
                    "Content-Type": "application/json",
                    "trakt-api-version": self._api_version,
                    "trakt-api-key": self._client_id,
                    "Authorization": f"Bearer {self._access_token}"
                },
                proxies=settings.PROXY  # 使用系统代理
            ).get_res(url=self._watchlist_shows_url)

            if not response or response.status_code != 200:
                logger.error(f"获取想看剧集失败: {response.status_code if response else 'No response'}")
                return None

            return response.json()

        except Exception as e:
            logger.error(f"获取想看剧集异常: {str(e)}")
            return None

    def __sync_movie(self, movie_data: dict, enable_download: bool = False) -> bool:
        """
        同步单个电影
        :param movie_data: 电影数据
        :param enable_download: 是否启用搜索下载
        :return: 是否为新增（True=新增，False=已存在）
        """
        title = movie_data.get("title")
        year = movie_data.get("year")
        ids = movie_data.get("ids", {})
        tmdb_id = ids.get("tmdb")
        imdb_id = ids.get("imdb")

        if not tmdb_id:
            logger.warning(f"电影 {title} ({year}) 缺少TMDB ID，跳过")
            return False

        logger.info(f"处理电影: {title} ({year}) [TMDB: {tmdb_id}]")

        # 识别媒体信息
        meta = MetaInfo(title)
        meta.year = str(year) if year else None
        meta.type = MediaType.MOVIE

        mediainfo = self.chain.recognize_media(meta=meta, tmdbid=tmdb_id)
        if not mediainfo:
            logger.error(f"无法识别电影: {title} ({year})")
            return False

        # 检查是否已存在
        downloadchain = DownloadChain()
        exist_flag, _ = downloadchain.get_no_exists_info(meta=meta, mediainfo=mediainfo)

        if exist_flag:
            logger.info(f'{mediainfo.title_year} 媒体库中已存在')
            return False

        # 检查是否已订阅
        if self.__is_subscribed(tmdb_id, MediaType.MOVIE):
            logger.info(f'{mediainfo.title_year} 已在订阅中')
            return False

        # 如果启用搜索下载
        if enable_download:
            return self.__search_and_download_movie(mediainfo, meta)
        else:
            # 添加订阅
            return self.__add_subscribe(mediainfo, meta)

    def __sync_show(self, show_data: dict, enable_download: bool = False) -> bool:
        """
        同步单个剧集
        :param show_data: 剧集数据
        :param enable_download: 是否启用搜索下载
        :return: 是否为新增（True=新增，False=已存在）
        """
        title = show_data.get("title")
        year = show_data.get("year")
        ids = show_data.get("ids", {})
        tmdb_id = ids.get("tmdb")

        if not tmdb_id:
            logger.warning(f"剧集 {title} ({year}) 缺少TMDB ID，跳过")
            return False

        logger.info(f"处理剧集: {title} ({year}) [TMDB: {tmdb_id}]")

        # 识别媒体信息
        meta = MetaInfo(title)
        meta.year = str(year) if year else None
        meta.type = MediaType.TV

        mediainfo = self.chain.recognize_media(meta=meta, tmdbid=tmdb_id)
        if not mediainfo:
            logger.error(f"无法识别剧集: {title} ({year})")
            return False

        # 检查是否已订阅
        if self.__is_subscribed(tmdb_id, MediaType.TV):
            logger.info(f'{mediainfo.title_year} 已在订阅中')
            return False

        # 如果启用搜索下载
        if enable_download:
            return self.__search_and_download_show(mediainfo, meta)
        else:
            # 添加订阅
            return self.__add_subscribe(mediainfo, meta)

    def __is_subscribed(self, tmdb_id: int, mtype: MediaType) -> bool:
        """
        检查是否已订阅
        :param tmdb_id: TMDB ID
        :param mtype: 媒体类型
        :return: 是否已订阅
        """
        subscribeoper = SubscribeOper()
        subscribes = subscribeoper.list(tmdbid=tmdb_id)
        return len(subscribes) > 0 if subscribes else False

    def __add_subscribe(self, mediainfo, meta) -> bool:
        """
        添加订阅
        :return: 是否成功
        """
        try:
            subscribe_id, message = SubscribeChain().add(
                title=mediainfo.title,
                year=mediainfo.year,
                mtype=mediainfo.type,
                tmdbid=mediainfo.tmdb_id,
                season=meta.begin_season if mediainfo.type == MediaType.TV else None,
                exist_ok=True,
                username="Trakt想看"
            )
            if subscribe_id:
                logger.info(f"添加订阅成功: {mediainfo.title_year}")
                return True
            else:
                logger.error(f"添加订阅失败: {mediainfo.title_year} - {message}")
                return False
        except Exception as e:
            logger.error(f"添加订阅异常: {mediainfo.title_year} - {str(e)}")
            return False

    def __search_and_download_movie(self, mediainfo, meta) -> bool:
        """
        搜索并下载电影
        :return: 是否为新增
        """
        downloadchain = DownloadChain()
        searchchain = SearchChain()
        systemconfig = SystemConfigOper()

        # 检查媒体库是否已存在
        exist_flag, no_exists = downloadchain.get_no_exists_info(meta=meta, mediainfo=mediainfo)
        if exist_flag:
            logger.info(f'{mediainfo.title_year} 媒体库中已存在')
            return False

        # 搜索资源
        logger.info(f"开始搜索资源: {mediainfo.title_year}")
        filter_results = searchchain.process(
            mediainfo=mediainfo,
            no_exists=no_exists,
            sites=systemconfig.get(SystemConfigKey.RssSites),
            rule_groups=systemconfig.get(SystemConfigKey.SubscribeFilterRuleGroups)
        )

        if not filter_results:
            logger.warning(f"未找到资源: {mediainfo.title_year}，添加订阅")
            return self.__add_subscribe(mediainfo, meta)

        # 下载
        download_id = downloadchain.download_single(
            context=filter_results[0],
            username="Trakt想看"
        )

        if download_id:
            logger.info(f"下载任务已添加: {mediainfo.title_year}")
            return True
        else:
            logger.warning(f"下载失败: {mediainfo.title_year}，添加订阅")
            return self.__add_subscribe(mediainfo, meta)

    def __search_and_download_show(self, mediainfo, meta) -> bool:
        """
        搜索并下载剧集
        :return: 是否为新增
        """
        downloadchain = DownloadChain()
        searchchain = SearchChain()
        systemconfig = SystemConfigOper()
        subscribeoper = SubscribeOper()

        # 检查缺失剧集
        exist_flag, no_exists = downloadchain.get_no_exists_info(meta=meta, mediainfo=mediainfo)

        if exist_flag:
            logger.info(f'{mediainfo.title_year} 媒体库中已完整')
            return False

        # 搜索资源
        logger.info(f"开始搜索资源: {mediainfo.title_year}")
        filter_results = searchchain.process(
            mediainfo=mediainfo,
            no_exists=no_exists,
            sites=systemconfig.get(SystemConfigKey.RssSites),
            rule_groups=systemconfig.get(SystemConfigKey.SubscribeFilterRuleGroups)
        )

        if not filter_results:
            logger.warning(f"未找到资源: {mediainfo.title_year}，添加订阅")
            return self.__add_subscribe(mediainfo, meta)

        # 批量下载
        downloaded_list, lefts = downloadchain.batch_download(
            contexts=filter_results,
            no_exists=no_exists,
            username="Trakt想看"
        )

        if downloaded_list:
            logger.info(f"已下载部分剧集: {mediainfo.title_year}")

        # 如果还有未下载的剧集，添加订阅
        if lefts:
            logger.info(f"还有未下载的剧集，添加订阅: {mediainfo.title_year}")
            sub_id, message = self.__add_subscribe(mediainfo, meta)
            if sub_id:
                # 更新订阅状态
                subscribe = subscribeoper.get(sub_id)
                if subscribe:
                    SubscribeChain().finish_subscribe_or_not(
                        subscribe=subscribe,
                        meta=meta,
                        mediainfo=mediainfo,
                        downloads=downloaded_list,
                        lefts=lefts
                    )
            return True

        return len(downloaded_list) > 0

    def __send_notification(self, stats: dict):
        """
        发送通知
        :param stats: 统计数据
        """
        total_added = stats["movies_added"] + stats["shows_added"]
        if total_added == 0 and stats["errors"] == 0:
            return

        text_parts = []
        if stats["movies_added"] > 0:
            text_parts.append(f"新增电影：{stats['movies_added']} 部")
        if stats["shows_added"] > 0:
            text_parts.append(f"新增剧集：{stats['shows_added']} 部")
        if stats["movies_exists"] > 0 or stats["shows_exists"] > 0:
            text_parts.append(f"已存在：{stats['movies_exists'] + stats['shows_exists']} 部")
        if stats["errors"] > 0:
            text_parts.append(f"错误：{stats['errors']} 个")

        text = "\n".join(text_parts)

        self.post_message(
            mtype=NotificationType.Subscribe,
            title="Trakt想看同步完成",
            text=text
        )
