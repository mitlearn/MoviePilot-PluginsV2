import datetime
import pytz
from typing import Optional, List, Dict, Tuple, Any
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger

from app.core.config import settings
from app.core.event import eventmanager, Event
from app.log import logger
from app.plugins import _PluginBase
from app.schemas.types import EventType, NotificationType, MediaType, SystemConfigKey
from app.utils.http import RequestUtils
from app.chain.subscribe import SubscribeChain
from app.chain.download import DownloadChain
from app.chain.search import SearchChain
from app.helper.mediaserver import MediaServerHelper
from app.core.metainfo import MetaInfo
from app.db.systemconfig_oper import SystemConfigOper
from app.db.subscribe_oper import SubscribeOper


class TraktSync(_PluginBase):
    # ── 元信息（类变量）──
    plugin_name = "Trakt想看"
    plugin_desc = "同步Trakt想看数据，自动添加订阅。"
    plugin_icon = "Trakt_A.png"
    plugin_version = "0.4.0"
    plugin_author = "Claude"
    author_url = "https://github.com/"
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
    _auth_code: str = ""
    _refresh_token: str = ""
    _access_token: str = ""
    _token_expires_at: Optional[datetime.datetime] = None
    _add_and_enable: bool = True  # 添加并启用订阅（开启则state=N，关闭则state=S）
    _sync_type: str = "all"  # 同步类型：all/movie/tv
    _last_sync_time: str = ""  # 上次同步时间
    _tabs: str = "sync_tab"  # 当前标签页
    _custom_lists: str = ""  # 自定义列表（格式：username/list_id，多个用逗号分隔）
    _use_proxy: bool = False  # 使用系统代理访问Trakt API

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
            self._auth_code = config.get("auth_code", "")
            self._refresh_token = config.get("refresh_token", "")
            self._access_token = config.get("access_token", "")
            self._add_and_enable = config.get("add_and_enable", True)
            self._sync_type = config.get("sync_type", "all")
            self._last_sync_time = config.get("last_sync_time", "")
            self._tabs = config.get("_tabs", "sync_tab")
            self._custom_lists = config.get("custom_lists", "")
            self._use_proxy = config.get("use_proxy", False)

            # 解析 token 过期时间
            token_expires_str = config.get("token_expires_at")
            if token_expires_str:
                try:
                    self._token_expires_at = datetime.datetime.fromisoformat(token_expires_str)
                except Exception as e:
                    logger.error(f"解析 token 过期时间失败: {str(e)}")
                    self._token_expires_at = None

            # 如果填写了client_id和client_secret，但没有refresh_token，生成授权链接
            if self._client_id and self._client_secret and not self._refresh_token:
                auth_url = f"https://trakt.tv/oauth/authorize?response_type=code&client_id={self._client_id}&redirect_uri=urn:ietf:wg:oauth:2.0:oob"
                logger.info("=" * 80)
                logger.info("请访问以下链接进行授权:")
                logger.info(auth_url)
                logger.info("授权后，将获得的授权码填入配置页面的【授权码】字段，然后保存配置")
                logger.info("=" * 80)

            # 如果填写了授权码，尝试获取token
            if self._auth_code and not self._refresh_token:
                logger.info("检测到授权码，正在获取Token...")
                if self.__get_token_from_code():
                    logger.info("Token获取成功！")
                    # 清空授权码
                    self._auth_code = ""
                    self.__update_config()
                else:
                    logger.error("Token获取失败，请检查授权码是否正确")

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
            "auth_code": self._auth_code,
            "refresh_token": self._refresh_token,
            "access_token": self._access_token,
            "add_and_enable": self._add_and_enable,
            "sync_type": self._sync_type,
            "last_sync_time": self._last_sync_time,
            "_tabs": self._tabs,
            "custom_lists": self._custom_lists,
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
                                        'label': '启用插件'
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
                                        'label': '发送通知'
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
                                        'label': '立即运行一次'
                                    }
                                }]
                            },
                        ]
                    },
                    {
                        'component': 'VTabs',
                        'props': {
                            'model': '_tabs',
                            'style': {
                                'margin-top': '8px',
                                'margin-bottom': '16px'
                            },
                            'stacked': True,
                            'fixed-tabs': True
                        },
                        'content': [
                            {
                                'component': 'VTab',
                                'props': {
                                    'value': 'sync_tab'
                                },
                                'text': '同步设置'
                            },
                            {
                                'component': 'VTab',
                                'props': {
                                    'value': 'trakt_tab'
                                },
                                'text': 'Trakt配置'
                            }
                        ]
                    },
                    {
                        'component': 'VWindow',
                        'props': {
                            'model': '_tabs'
                        },
                        'content': [
                            # 标签页1：同步设置
                            {
                                'component': 'VWindowItem',
                                'props': {
                                    'value': 'sync_tab'
                                },
                                'content': [
                                    {
                                        'component': 'VRow',
                                        'props': {
                                            'style': {
                                                'margin-top': '0px'
                                            }
                                        },
                                        'content': [
                                            {
                                                'component': 'VCol',
                                                'props': {'cols': 12, 'md': 6},
                                                'content': [{
                                                    'component': 'VCronField',
                                                    'props': {
                                                        'model': 'cron',
                                                        'label': '同步周期',
                                                        'placeholder': '如：0 8 * * *',
                                                        'hint': '5位cron表达式，留空则默认每天执行一次',
                                                        'persistent-hint': True
                                                    }
                                                }]
                                            },
                                            {
                                                'component': 'VCol',
                                                'props': {'cols': 12, 'md': 6},
                                                'content': [{
                                                    'component': 'VSelect',
                                                    'props': {
                                                        'model': 'sync_type',
                                                        'label': 'Watchlist同步类型',
                                                        'items': [
                                                            {'title': '全部', 'value': 'all'},
                                                            {'title': '仅电影', 'value': 'movie'},
                                                            {'title': '仅剧集', 'value': 'tv'}
                                                        ],
                                                        'hint': '仅对Watchlist生效，自定义列表全同步',
                                                        'persistent-hint': True
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
                                                    'component': 'VSwitch',
                                                    'props': {
                                                        'model': 'add_and_enable',
                                                        'label': '添加启用的订阅',
                                                        'hint': '开启后添加的订阅为激活状态(N)，MoviePilot会自动搜索下载；关闭后为暂停状态(S)，不会触发搜索',
                                                        'persistent-hint': True
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
                                                        'model': 'custom_lists',
                                                        'label': '自定义列表',
                                                        'placeholder': '如：username/list_id 或 https://trakt.tv/users/username/lists/list_id',
                                                        'hint': '支持Trakt自定义列表URL或username/list_id格式，多个用逗号分隔',
                                                        'persistent-hint': True
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
                                                        'type': 'info',
                                                        'variant': 'tonal',
                                                        'text': '同步设置说明：\n'
                                                               '• 同步周期：设置定时同步的执行周期，支持cron表达式\n'
                                                               '• Watchlist同步类型：选择同步电影、剧集或全部（仅对Watchlist生效）\n'
                                                               '• 添加启用的订阅：开启后添加的订阅为激活状态(N)会触发搜索，关闭后为暂停状态(S)\n'
                                                               '• 自定义列表：全同步电影和剧集，不受Watchlist同步类型限制，支持多个列表（逗号分隔）'
                                                    }
                                                }]
                                            }
                                        ]
                                    }
                                ]
                            },
                            # 标签页2：Trakt配置
                            {
                                'component': 'VWindowItem',
                                'props': {
                                    'value': 'trakt_tab'
                                },
                                'content': [
                                    {
                                        'component': 'VRow',
                                        'props': {
                                            'style': {
                                                'margin-top': '0px'
                                            }
                                        },
                                        'content': [
                                            {
                                                'component': 'VCol',
                                                'props': {'cols': 12, 'md': 4},
                                                'content': [{
                                                    'component': 'VSwitch',
                                                    'props': {
                                                        'model': 'use_proxy',
                                                        'label': '使用代理',
                                                        'hint': '开启后使用系统代理访问Trakt API',
                                                        'persistent-hint': True
                                                    }
                                                }]
                                            },
                                            {
                                                'component': 'VCol',
                                                'props': {'cols': 12, 'md': 8},
                                                'content': []
                                            }
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
                                                        'label': 'Client ID',
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
                                                        'label': 'Client Secret',
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
                                                'props': {'cols': 12, 'md': 6},
                                                'content': [{
                                                    'component': 'VTextField',
                                                    'props': {
                                                        'model': 'auth_code',
                                                        'label': '授权码（Authorization Code）',
                                                        'placeholder': '填写授权码后保存，将自动获取Token',
                                                        'hint': '填写授权码后将自动获取并保存Refresh Token',
                                                        'persistent-hint': True
                                                    }
                                                }]
                                            },
                                            {
                                                'component': 'VCol',
                                                'props': {'cols': 12, 'md': 6},
                                                'content': [{
                                                    'component': 'VTextField',
                                                    'props': {
                                                        'model': 'refresh_token',
                                                        'label': 'Refresh Token（可选）',
                                                        'placeholder': '自动获取，也可手动填写',
                                                        'hint': '通过授权码自动获取，或手动填写',
                                                        'persistent-hint': True
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
                                                        'text': 'Trakt配置说明：\n'
                                                               '1. 前往 https://trakt.tv/oauth/applications/new 创建应用\n'
                                                               '   • Redirect URI 必须填写：urn:ietf:wg:oauth:2.0:oob\n'
                                                               '2. 填写 Client ID 和 Client Secret 后保存，日志中会输出授权链接\n'
                                                               '3. 访问授权链接，授权后将获得授权码\n'
                                                               '4. 将授权码填入【授权码】字段并保存，插件将自动获取 Token\n'
                                                               '5. Token 有效期 90 天，过期前会自动刷新（每 72 小时检查一次）'
                                                    }
                                                }]
                                            }
                                        ]
                                    }
                                ]
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
            "sync_type": "all",
            "add_and_enable": True,
            "use_proxy": False,
            "client_id": "",
            "client_secret": "",
            "auth_code": "",
            "refresh_token": "",
            "custom_lists": "",
            "_tabs": "sync_tab"
        }

    def get_page(self) -> Optional[List[dict]]:
        """插件详情页面"""
        from app.utils.string import StringUtils

        # 查询同步详情
        historys = self.get_data('history') or []

        # 统计数据
        total_count = len(historys)
        movies_count = len([h for h in historys if h.get("type") == "电影"])
        tv_count = len([h for h in historys if h.get("type") == "电视剧"])

        # 获取上次同步时间
        last_sync_time = self._last_sync_time or "未同步"

        # Header 统计信息（参考 BrushFlow 样式）
        header_elements = [
            {
                'component': 'VRow',
                'props': {
                    'class': 'mb-3'
                },
                'content': [
                    # 上次同步时间
                    {
                        'component': 'VCol',
                        'props': {
                            'cols': 12,
                            'md': 3,
                            'sm': 6
                        },
                        'content': [
                            {
                                'component': 'VCard',
                                'props': {
                                    'variant': 'tonal',
                                },
                                'content': [
                                    {
                                        'component': 'VCardText',
                                        'props': {
                                            'class': 'd-flex align-center',
                                        },
                                        'content': [
                                            {
                                                'component': 'VAvatar',
                                                'props': {
                                                    'rounded': True,
                                                    'variant': 'text',
                                                    'class': 'me-3'
                                                },
                                                'content': [
                                                    {
                                                        'component': 'VIcon',
                                                        'props': {
                                                            'icon': 'mdi-clock-outline',
                                                            'size': '28'
                                                        }
                                                    }
                                                ]
                                            },
                                            {
                                                'component': 'div',
                                                'content': [
                                                    {
                                                        'component': 'span',
                                                        'props': {
                                                            'class': 'text-caption'
                                                        },
                                                        'text': '上次同步'
                                                    },
                                                    {
                                                        'component': 'div',
                                                        'props': {
                                                            'class': 'd-flex align-center flex-wrap'
                                                        },
                                                        'content': [
                                                            {
                                                                'component': 'span',
                                                                'props': {
                                                                    'class': 'text-h6'
                                                                },
                                                                'text': last_sync_time
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
                    },
                    # 同步总数
                    {
                        'component': 'VCol',
                        'props': {
                            'cols': 12,
                            'md': 3,
                            'sm': 6
                        },
                        'content': [
                            {
                                'component': 'VCard',
                                'props': {
                                    'variant': 'tonal',
                                },
                                'content': [
                                    {
                                        'component': 'VCardText',
                                        'props': {
                                            'class': 'd-flex align-center',
                                        },
                                        'content': [
                                            {
                                                'component': 'VAvatar',
                                                'props': {
                                                    'rounded': True,
                                                    'variant': 'text',
                                                    'class': 'me-3'
                                                },
                                                'content': [
                                                    {
                                                        'component': 'VIcon',
                                                        'props': {
                                                            'icon': 'mdi-format-list-bulleted',
                                                            'size': '28'
                                                        }
                                                    }
                                                ]
                                            },
                                            {
                                                'component': 'div',
                                                'content': [
                                                    {
                                                        'component': 'span',
                                                        'props': {
                                                            'class': 'text-caption'
                                                        },
                                                        'text': '同步总数'
                                                    },
                                                    {
                                                        'component': 'div',
                                                        'props': {
                                                            'class': 'd-flex align-center flex-wrap'
                                                        },
                                                        'content': [
                                                            {
                                                                'component': 'span',
                                                                'props': {
                                                                    'class': 'text-h6'
                                                                },
                                                                'text': str(total_count)
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
                    },
                    # 电影数量
                    {
                        'component': 'VCol',
                        'props': {
                            'cols': 12,
                            'md': 3,
                            'sm': 6
                        },
                        'content': [
                            {
                                'component': 'VCard',
                                'props': {
                                    'variant': 'tonal',
                                },
                                'content': [
                                    {
                                        'component': 'VCardText',
                                        'props': {
                                            'class': 'd-flex align-center',
                                        },
                                        'content': [
                                            {
                                                'component': 'VAvatar',
                                                'props': {
                                                    'rounded': True,
                                                    'variant': 'text',
                                                    'class': 'me-3'
                                                },
                                                'content': [
                                                    {
                                                        'component': 'VIcon',
                                                        'props': {
                                                            'icon': 'mdi-movie-outline',
                                                            'size': '28'
                                                        }
                                                    }
                                                ]
                                            },
                                            {
                                                'component': 'div',
                                                'content': [
                                                    {
                                                        'component': 'span',
                                                        'props': {
                                                            'class': 'text-caption'
                                                        },
                                                        'text': '电影数量'
                                                    },
                                                    {
                                                        'component': 'div',
                                                        'props': {
                                                            'class': 'd-flex align-center flex-wrap'
                                                        },
                                                        'content': [
                                                            {
                                                                'component': 'span',
                                                                'props': {
                                                                    'class': 'text-h6'
                                                                },
                                                                'text': str(movies_count)
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
                    },
                    # 剧集数量
                    {
                        'component': 'VCol',
                        'props': {
                            'cols': 12,
                            'md': 3,
                            'sm': 6
                        },
                        'content': [
                            {
                                'component': 'VCard',
                                'props': {
                                    'variant': 'tonal',
                                },
                                'content': [
                                    {
                                        'component': 'VCardText',
                                        'props': {
                                            'class': 'd-flex align-center',
                                        },
                                        'content': [
                                            {
                                                'component': 'VAvatar',
                                                'props': {
                                                    'rounded': True,
                                                    'variant': 'text',
                                                    'class': 'me-3'
                                                },
                                                'content': [
                                                    {
                                                        'component': 'VIcon',
                                                        'props': {
                                                            'icon': 'mdi-television-classic',
                                                            'size': '28'
                                                        }
                                                    }
                                                ]
                                            },
                                            {
                                                'component': 'div',
                                                'content': [
                                                    {
                                                        'component': 'span',
                                                        'props': {
                                                            'class': 'text-caption'
                                                        },
                                                        'text': '剧集数量'
                                                    },
                                                    {
                                                        'component': 'div',
                                                        'props': {
                                                            'class': 'd-flex align-center flex-wrap'
                                                        },
                                                        'content': [
                                                            {
                                                                'component': 'span',
                                                                'props': {
                                                                    'class': 'text-h6'
                                                                },
                                                                'text': str(tv_count)
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
                    }
                ]
            }
        ]

        # 如果没有历史记录
        if not historys:
            return header_elements + [
                {
                    'component': 'div',
                    'text': '暂无同步记录',
                    'props': {
                        'class': 'text-center mt-5',
                    }
                }
            ]

        # 数据按时间降序排序
        historys = sorted(historys, key=lambda x: x.get('time'), reverse=True)

        # 拼装页面
        contents = []
        for history in historys:
            title = history.get("title")
            poster = history.get("poster")
            mtype = history.get("type")
            source = history.get("source", "watchlist")
            time_str = history.get("time")
            tmdbid = history.get("tmdbid")
            action = "下载" if history.get("action") == "download" else "订阅" if history.get("action") == "subscribe" \
                else "添加" if history.get("action") == "add" else "存在" if history.get("action") == "exist" else history.get("action")

            # 根据source显示类型：watchlist显示媒体类型，自定义列表显示列表名称
            if source == "watchlist":
                display_type = mtype
            else:
                display_type = source
            contents.append(
                {
                    'component': 'VCard',
                    'content': [
                        {
                            "component": "VDialogCloseBtn",
                            "props": {
                                'innerClass': 'absolute top-0 right-0',
                            },
                            'events': {
                                'click': {
                                    'api': 'plugin/TraktSync/delete_history',
                                    'method': 'get',
                                    'params': {
                                        'tmdbid': tmdbid,
                                        'apikey': settings.API_TOKEN
                                    }
                                }
                            },
                        },
                        {
                            'component': 'div',
                            'props': {
                                'class': 'd-flex justify-space-start flex-nowrap flex-row',
                            },
                            'content': [
                                {
                                    'component': 'div',
                                    'content': [
                                        {
                                            'component': 'VImg',
                                            'props': {
                                                'src': poster,
                                                'height': 120,
                                                'width': 80,
                                                'aspect-ratio': '2/3',
                                                'class': 'object-cover shadow ring-gray-500',
                                                'cover': True
                                            }
                                        }
                                    ]
                                },
                                {
                                    'component': 'div',
                                    'content': [
                                        {
                                            'component': 'VCardTitle',
                                            'props': {
                                                'class': 'ps-1 pe-5 break-words whitespace-break-spaces'
                                            },
                                            'content': [
                                                {
                                                    'component': 'a',
                                                    'props': {
                                                        'href': f"https://www.themoviedb.org/{mtype.lower()}/{tmdbid}",
                                                        'target': '_blank'
                                                    },
                                                    'text': title
                                                }
                                            ]
                                        },
                                        {
                                            'component': 'VCardText',
                                            'props': {
                                                'class': 'pa-0 px-2'
                                            },
                                            'text': f'类型：{display_type}'
                                        },
                                        {
                                            'component': 'VCardText',
                                            'props': {
                                                'class': 'pa-0 px-2'
                                            },
                                            'text': f'时间：{time_str}'
                                        },
                                        {
                                            'component': 'VCardText',
                                            'props': {
                                                'class': 'pa-0 px-2'
                                            },
                                            'text': f'操作：{action}'
                                        }
                                    ]
                                }
                            ]
                        }
                    ]
                }
            )

        return header_elements + [
            {
                'component': 'div',
                'props': {
                    'class': 'grid gap-3 grid-info-card',
                },
                'content': contents
            }
        ]

    def get_service(self) -> List[Dict[str, Any]]:
        """注册常驻定时服务"""
        services = []

        # Token 自动刷新服务（每72小时检查一次，提前7天自动刷新）
        if self._enabled and self._refresh_token:
            services.append({
                "id": "TraktTokenRefresh",
                "name": "Trakt Token自动刷新",
                "trigger": "interval",
                "func": self.__refresh_access_token,
                "kwargs": {"hours": 72}
            })

        # 同步服务
        if self._enabled and self._cron:
            services.append({
                "id": "TraktSync",
                "name": "Trakt想看同步服务",
                "trigger": CronTrigger.from_crontab(self._cron),
                "func": self.sync,
                "kwargs": {}
            })
        elif self._enabled:
            # 无 cron 时，默认每天执行一次
            services.append({
                "id": "TraktSync",
                "name": "Trakt想看同步服务",
                "trigger": "interval",
                "func": self.sync,
                "kwargs": {"days": 1}
            })

        return services

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
            },
            {
                "cmd": "/trakt_custom_lists",
                "event": EventType.PluginAction,
                "desc": "同步Trakt自定义列表",
                "category": "订阅",
                "data": {
                    "action": "trakt_custom_lists"
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
            if action not in ["trakt_sync", "trakt_download", "trakt_custom_lists"]:
                return

            # 自定义列表同步
            if action == "trakt_custom_lists":
                logger.info(f"收到命令，开始执行Trakt自定义列表同步 ...")
                self.post_message(
                    channel=event_data.get("channel"),
                    title="开始同步Trakt自定义列表 ...",
                    userid=event_data.get("user")
                )
                self.sync_custom_lists()
                self.post_message(
                    channel=event.event_data.get("channel"),
                    title="同步Trakt自定义列表完成！",
                    userid=event.event_data.get("user")
                )
                return

            # Watchlist同步
            logger.info(f"收到命令，开始执行Trakt想看同步 ...")
            self.post_message(
                channel=event_data.get("channel"),
                title="开始同步Trakt想看 ...",
                userid=event_data.get("user")
            )

        # 执行同步
        self.sync()

        if event:
            self.post_message(
                channel=event.event_data.get("channel"),
                title="同步Trakt想看数据完成！",
                userid=event.event_data.get("user")
            )

    def get_api(self) -> List[Dict[str, Any]]:
        """注册API"""
        return [
            {
                "path": "/sync",
                "endpoint": self.api_sync,
                "methods": ["POST"],
                "summary": "触发Trakt想看同步"
            },
            {
                "path": "/sync_download",
                "endpoint": self.api_sync_download,
                "methods": ["POST"],
                "summary": "触发Trakt想看同步并下载"
            },
            {
                "path": "/sync_custom_lists",
                "endpoint": self.api_sync_custom_lists,
                "methods": ["POST"],
                "summary": "触发Trakt自定义列表同步"
            },
            {
                "path": "/delete_history",
                "endpoint": self.delete_history,
                "methods": ["GET"],
                "summary": "删除Trakt同步历史记录"
            }
        ]

    def __init_sync_stats(self) -> dict:
        """初始化同步统计数据"""
        return {
            "movies_added": 0,
            "shows_added": 0,
            "movies_exists": 0,
            "shows_exists": 0,
            "errors": 0
        }

    def __get_proxies(self) -> Optional[dict]:
        """
        获取代理配置
        :return: 代理配置字典，如果不使用代理则返回None
        """
        return settings.PROXY if self._use_proxy else None

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

    def sync(self):
        """
        同步Trakt想看列表
        """
        if not self._client_id or not self._client_secret or not self._refresh_token:
            logger.error("Trakt配置不完整，请检查Client ID、Client Secret和Refresh Token")
            return

        # 刷新 access token
        if not self.__refresh_access_token():
            logger.error("Trakt access token刷新失败，同步终止")
            return

        logger.info("开始同步Trakt想看列表...")

        # 读取历史记录
        history: List[dict] = self.get_data('history') or []

        # 统计数据
        stats = self.__init_sync_stats()

        # 同步电影（根据 sync_type 判断是否需要同步）
        if self._sync_type in ["all", "movie"]:
            movies = self.__get_watchlist_movies()
            if movies:
                logger.info(f"获取到 {len(movies)} 部Trakt想看电影")
                for item in movies:
                    try:
                        movie_data = item.get("movie", {})
                        result = self.__sync_movie(movie_data, history, source="watchlist")
                        if result:
                            if result.get("is_new"):
                                stats["movies_added"] += 1
                            else:
                                stats["movies_exists"] += 1
                            # 添加到历史记录
                            history.append(result.get("history"))
                    except Exception as e:
                        logger.error(f"同步电影失败: {str(e)}")
                        stats["errors"] += 1

        # 同步剧集（根据 sync_type 判断是否需要同步）
        if self._sync_type in ["all", "tv"]:
            shows = self.__get_watchlist_shows()
            if shows:
                logger.info(f"获取到 {len(shows)} 部Trakt想看剧集")
                for item in shows:
                    try:
                        show_data = item.get("show", {})
                        result = self.__sync_show(show_data, history, source="watchlist")
                        if result:
                            if result.get("is_new"):
                                stats["shows_added"] += 1
                            else:
                                stats["shows_exists"] += 1
                            # 添加到历史记录
                            history.append(result.get("history"))
                    except Exception as e:
                        logger.error(f"同步剧集失败: {str(e)}")
                        stats["errors"] += 1

        # 同步自定义列表
        if self._custom_lists:
            logger.info("开始同步Trakt自定义列表...")
            list_configs = self._custom_lists.split(",")

            for list_config in list_configs:
                list_config = list_config.strip()
                if not list_config:
                    continue

                # 解析列表配置
                username, list_id = self.__parse_list_config(list_config)
                if not username or not list_id:
                    logger.error(f"无效的列表配置: {list_config}")
                    stats["errors"] += 1
                    continue

                logger.info(f"同步自定义列表: {username}/{list_id}")

                # 获取列表内容
                items = self.__get_custom_list_items(username, list_id)
                if not items:
                    logger.warning(f"未获取到列表内容: {username}/{list_id}")
                    continue

                logger.info(f"获取到 {len(items)} 个列表项")

                # 列表名称作为来源
                list_source = f"{username}/{list_id}"

                # 处理列表项（自定义列表全同步，不受Watchlist同步类型限制）
                for item in items:
                    try:
                        item_type = item.get("type")

                        if item_type == "movie":
                            movie_data = item.get("movie", {})
                            result = self.__sync_movie(movie_data, history, source=list_source)
                            if result:
                                if result.get("is_new"):
                                    stats["movies_added"] += 1
                                else:
                                    stats["movies_exists"] += 1
                                history.append(result.get("history"))

                        elif item_type == "show":
                            show_data = item.get("show", {})
                            result = self.__sync_show(show_data, history, source=list_source)
                            if result:
                                if result.get("is_new"):
                                    stats["shows_added"] += 1
                                else:
                                    stats["shows_exists"] += 1
                                history.append(result.get("history"))

                        else:
                            logger.debug(f"跳过未知项目类型: {item_type}")

                    except Exception as e:
                        logger.error(f"同步列表项失败: {str(e)}")
                        stats["errors"] += 1

        # 更新上次同步时间
        self._last_sync_time = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        self.__update_config()

        # 保存历史记录
        self.save_data('history', history)

        # 发送通知
        if self._notify:
            self.__send_notification(stats)

        logger.info(f"Trakt想看同步完成: 新增电影 {stats['movies_added']} 部，"
                   f"新增剧集 {stats['shows_added']} 部，"
                   f"已存在电影 {stats['movies_exists']} 部，"
                   f"已存在剧集 {stats['shows_exists']} 部，"
                   f"错误 {stats['errors']} 个")

    def __get_token_from_code(self) -> bool:
        """
        使用授权码获取 access token 和 refresh token
        :return: 是否成功
        """
        if not self._auth_code or not self._client_id or not self._client_secret:
            logger.error("授权码、Client ID或Client Secret为空")
            return False

        try:
            # 发起 token 请求
            response = RequestUtils(
                headers={"Content-Type": "application/json"},
                proxies=self.__get_proxies()
            ).post_res(
                url=self._oauth_url,
                json={
                    "code": self._auth_code,
                    "client_id": self._client_id,
                    "client_secret": self._client_secret,
                    "redirect_uri": "urn:ietf:wg:oauth:2.0:oob",
                    "grant_type": "authorization_code"
                }
            )

            if not response or response.status_code != 200:
                logger.error(f"获取Token失败: {response.status_code if response else 'No response'}")
                if response:
                    logger.error(f"响应内容: {response.text}")
                return False

            token_data = response.json()
            self._access_token = token_data.get("access_token")
            self._refresh_token = token_data.get("refresh_token")
            expires_in = token_data.get("expires_in", 7776000)  # Trakt默认90天

            # 计算过期时间
            self._token_expires_at = datetime.datetime.now(tz=pytz.UTC) + datetime.timedelta(seconds=expires_in)

            logger.info(f"Token获取成功，有效期至 {self._token_expires_at.isoformat()}")
            return True

        except Exception as e:
            logger.error(f"获取Token异常: {str(e)}")
            return False

    def __refresh_access_token(self) -> bool:
        """
        刷新 Trakt access token
        :return: 是否成功
        """
        # 检查 token 是否需要刷新（提前7天刷新）
        if self._access_token and self._token_expires_at:
            now = datetime.datetime.now(tz=pytz.UTC)
            if self._token_expires_at > now + datetime.timedelta(days=7):
                logger.debug("Access token未过期，无需刷新")
                return True

        logger.info("正在刷新Trakt access token...")

        try:
            # 发起 token refresh 请求
            response = RequestUtils(
                headers={"Content-Type": "application/json"},
                proxies=self.__get_proxies()
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
                error_msg = f"Token刷新失败: {response.status_code if response else 'No response'}"
                logger.error(error_msg)
                if response:
                    logger.error(f"响应内容: {response.text}")

                # 发送通知
                if self._notify:
                    self.post_message(
                        mtype=NotificationType.SiteMessage,
                        title="Trakt Token刷新失败",
                        text=f"刷新失败，请检查配置\n错误：{error_msg}"
                    )
                return False

            token_data = response.json()
            self._access_token = token_data.get("access_token")
            new_refresh_token = token_data.get("refresh_token")
            expires_in = token_data.get("expires_in", 7776000)  # Trakt默认90天

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
            error_msg = f"Token刷新异常: {str(e)}"
            logger.error(error_msg)

            # 发送通知
            if self._notify:
                self.post_message(
                    mtype=NotificationType.SiteMessage,
                    title="Trakt Token刷新异常",
                    text=f"刷新过程中发生异常\n错误：{error_msg}"
                )
            return False

    def __make_trakt_api_call(self, url: str, desc: str) -> Optional[List[dict]]:
        """
        统一的Trakt API调用方法
        :param url: API URL
        :param desc: 描述（用于日志）
        :return: API响应数据
        """
        try:
            response = RequestUtils(
                headers={
                    "Content-Type": "application/json",
                    "trakt-api-version": self._api_version,
                    "trakt-api-key": self._client_id,
                    "Authorization": f"Bearer {self._access_token}"
                },
                proxies=self.__get_proxies()
            ).get_res(url=url)

            if not response or response.status_code != 200:
                logger.error(f"获取{desc}失败: {response.status_code if response else 'No response'}")
                return None

            return response.json()

        except Exception as e:
            logger.error(f"获取{desc}异常: {str(e)}")
            return None

    def __get_watchlist_movies(self) -> Optional[List[dict]]:
        """获取Trakt想看电影列表"""
        return self.__make_trakt_api_call(self._watchlist_movies_url, "想看电影")

    def __get_watchlist_shows(self) -> Optional[List[dict]]:
        """获取Trakt想看剧集列表"""
        return self.__make_trakt_api_call(self._watchlist_shows_url, "想看剧集")

    def __get_custom_list_items(self, username: str, list_id: str) -> Optional[List[dict]]:
        """
        获取Trakt自定义列表内容
        :param username: Trakt用户名
        :param list_id: 列表ID或slug
        :return: 列表项
        """
        url = f"{self._api_base}/users/{username}/lists/{list_id}/items"
        return self.__make_trakt_api_call(url, f"自定义列表 {username}/{list_id}")

    def __sync_media(self, media_data: dict, media_type: MediaType, history: List[dict] = None, source: str = "watchlist") -> Optional[dict]:
        """
        同步单个媒体（电影或剧集）
        :param media_data: 媒体数据
        :param media_type: 媒体类型（MediaType.MOVIE 或 MediaType.TV）
        :param history: 历史记录列表
        :param source: 来源标识（watchlist 或自定义列表名称）
        :return: 返回包含is_new和history的字典，或None
        """
        media_type_name = "电影" if media_type == MediaType.MOVIE else "剧集"
        title = media_data.get("title")
        year = media_data.get("year")
        ids = media_data.get("ids", {})
        tmdb_id = ids.get("tmdb")

        if not tmdb_id:
            logger.warning(f"{media_type_name} {title} ({year}) 缺少TMDB ID，跳过")
            return None

        # 检查是否已处理过
        if history and tmdb_id in [h.get("tmdbid") for h in history]:
            logger.info(f"{media_type_name} {title} ({year}) [TMDB: {tmdb_id}] 已处理过")
            return None

        logger.info(f"处理{media_type_name}: {title} ({year}) [TMDB: {tmdb_id}]")

        # 识别媒体信息
        meta = MetaInfo(title)
        meta.year = str(year) if year else None
        meta.type = media_type

        mediainfo = self.chain.recognize_media(meta=meta, tmdbid=tmdb_id)
        if not mediainfo:
            logger.error(f"无法识别{media_type_name}: {title} ({year})")
            return None

        # 检查是否已存在
        downloadchain = DownloadChain()
        exist_flag, no_exists = downloadchain.get_no_exists_info(meta=meta, mediainfo=mediainfo)

        if exist_flag:
            exist_msg = "媒体库中已存在" if media_type == MediaType.MOVIE else "媒体库中已完整"
            logger.info(f'{mediainfo.title_year} {exist_msg}')
            action = "exist"
            is_new = False
        elif self.__is_subscribed(tmdb_id, media_type):
            logger.info(f'{mediainfo.title_year} 已在订阅中')
            action = "subscribe"
            is_new = False
        else:
            # 添加订阅
            is_new = self.__add_subscribe(mediainfo, meta)
            # 根据add_and_enable设置action：开启时为"subscribe"(订阅)，关闭时为"add"(添加)
            if is_new:
                action = "subscribe" if self._add_and_enable else "add"
            else:
                action = "exist"

        # 存储历史记录
        history_item = {
            "action": action,
            "title": mediainfo.title_year,
            "type": mediainfo.type.value,
            "year": mediainfo.year,
            "poster": mediainfo.get_poster_image(),
            "overview": mediainfo.overview,
            "tmdbid": tmdb_id,
            "source": source,  # 来源：watchlist 或自定义列表名称
            "time": datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        }

        return {
            "is_new": is_new,
            "history": history_item
        }

    def __sync_movie(self, movie_data: dict, history: List[dict] = None, source: str = "watchlist") -> Optional[dict]:
        """同步单个电影（向后兼容方法）"""
        return self.__sync_media(movie_data, MediaType.MOVIE, history, source)

    def __sync_show(self, show_data: dict, history: List[dict] = None, source: str = "watchlist") -> Optional[dict]:
        """同步单个剧集（向后兼容方法）"""
        return self.__sync_media(show_data, MediaType.TV, history, source)

    def __is_subscribed(self, tmdb_id: int, mtype: MediaType) -> bool:
        """
        检查是否已订阅
        :param tmdb_id: TMDB ID
        :param mtype: 媒体类型
        :return: 是否已订阅
        """
        subscribeoper = SubscribeOper()
        subscribes = subscribeoper.list_by_tmdbid(tmdbid=tmdb_id)
        return len(subscribes) > 0 if subscribes else False

    def __add_subscribe(self, mediainfo, meta) -> bool:
        """
        添加订阅
        :return: 是否成功
        """
        try:
            # 根据"添加并启用订阅"开关决定订阅状态
            state = 'N' if self._add_and_enable else 'S'

            subscribe_id, message = SubscribeChain().add(
                title=mediainfo.title,
                year=mediainfo.year,
                mtype=mediainfo.type,
                tmdbid=mediainfo.tmdb_id,
                season=meta.begin_season if mediainfo.type == MediaType.TV else None,
                exist_ok=True,
                username="Trakt想看",
                state=state  # 设置订阅状态
            )
            if subscribe_id:
                status_text = "激活订阅" if self._add_and_enable else "暂停订阅"
                logger.info(f"添加订阅成功: {mediainfo.title_year} ({status_text})")
                return True
            else:
                logger.error(f"添加订阅失败: {mediainfo.title_year} - {message}")
                return False
        except Exception as e:
            logger.error(f"添加订阅异常: {mediainfo.title_year} - {str(e)}")
            return False

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

    def get_actions(self) -> List[Dict[str, Any]]:
        """
        注册工作流动作
        """
        return [
            {
                "id": "trakt_sync",
                "name": "同步Trakt想看",
                "func": self.action_sync,
                "kwargs": {}
            },
            {
                "id": "trakt_sync_download",
                "name": "同步并下载Trakt想看",
                "func": self.action_sync_download,
                "kwargs": {}
            },
            {
                "id": "trakt_sync_custom_lists",
                "name": "同步Trakt自定义列表",
                "func": self.action_sync_custom_lists,
                "kwargs": {}
            }
        ]

    def __api_wrapper(self, apikey: str, func_name: str, func_callable, *args, **kwargs):
        """
        API调用统一包装器
        :param apikey: API密钥
        :param func_name: 功能名称
        :param func_callable: 要调用的函数
        :param args: 函数参数
        :param kwargs: 函数关键字参数
        :return: Response对象
        """
        from app import schemas

        if apikey != settings.API_TOKEN:
            return schemas.Response(success=False, message="API密钥错误")

        try:
            logger.info(f"通过API触发{func_name}")
            func_callable(*args, **kwargs)
            return schemas.Response(success=True, message=f"{func_name}任务已启动")
        except Exception as e:
            logger.error(f"API {func_name}失败: {str(e)}")
            return schemas.Response(success=False, message=f"{func_name}失败: {str(e)}")

    def api_sync(self, apikey: str):
        """API端点：触发同步"""
        return self.__api_wrapper(apikey, "Trakt想看同步", self.sync)

    def api_sync_download(self, apikey: str):
        """API端点：触发同步并下载"""
        return self.__api_wrapper(apikey, "Trakt想看同步并下载", self.sync)

    def api_sync_custom_lists(self, apikey: str):
        """API端点：触发自定义列表同步"""
        return self.__api_wrapper(apikey, "Trakt自定义列表同步", self.sync_custom_lists)

    def __action_wrapper(self, action_content, func_name: str, func_callable, *args, **kwargs):
        """
        工作流动作统一包装器
        :param action_content: 动作内容
        :param func_name: 功能名称
        :param func_callable: 要调用的函数
        :param args: 函数参数
        :param kwargs: 函数关键字参数
        :return: (是否成功, 动作内容)
        """
        try:
            logger.info(f"工作流触发{func_name}")
            func_callable(*args, **kwargs)
            return True, action_content
        except Exception as e:
            logger.error(f"工作流{func_name}失败: {str(e)}")
            return False, action_content

    def action_sync(self, action_content):
        """工作流动作：同步Trakt想看"""
        return self.__action_wrapper(action_content, "Trakt想看同步", self.sync)

    def action_sync_download(self, action_content):
        """工作流动作：同步并下载Trakt想看"""
        return self.__action_wrapper(action_content, "Trakt想看同步并下载", self.sync)

    def action_sync_custom_lists(self, action_content):
        """工作流动作：同步Trakt自定义列表"""
        return self.__action_wrapper(action_content, "Trakt自定义列表同步", self.sync_custom_lists)

    def sync_custom_lists(self):
        """
        同步Trakt自定义列表
        """
        if not self._custom_lists:
            logger.warning("未配置自定义列表，跳过同步")
            return

        if not self._client_id or not self._client_secret or not self._refresh_token:
            logger.error("Trakt配置不完整，请检查Client ID、Client Secret和Refresh Token")
            return

        # 刷新 access token
        if not self.__refresh_access_token():
            logger.error("Trakt access token刷新失败，同步终止")
            return

        logger.info("开始同步Trakt自定义列表...")

        # 读取历史记录
        history: List[dict] = self.get_data('history') or []

        # 统计数据
        stats = self.__init_sync_stats()

        # 解析自定义列表配置
        list_configs = self._custom_lists.split(",")

        for list_config in list_configs:
            list_config = list_config.strip()
            if not list_config:
                continue

            # 解析列表配置
            username, list_id = self.__parse_list_config(list_config)
            if not username or not list_id:
                logger.error(f"无效的列表配置: {list_config}")
                stats["errors"] += 1
                continue

            logger.info(f"同步自定义列表: {username}/{list_id}")

            # 获取列表内容
            items = self.__get_custom_list_items(username, list_id)
            if not items:
                logger.warning(f"未获取到列表内容: {username}/{list_id}")
                continue

            logger.info(f"获取到 {len(items)} 个列表项")

            # 列表名称作为来源
            list_source = f"{username}/{list_id}"

            # 处理列表项（自定义列表全同步，不受Watchlist同步类型限制）
            for item in items:
                try:
                    item_type = item.get("type")

                    if item_type == "movie":
                        movie_data = item.get("movie", {})
                        result = self.__sync_movie(movie_data, history, source=list_source)
                        if result:
                            if result.get("is_new"):
                                stats["movies_added"] += 1
                            else:
                                stats["movies_exists"] += 1
                            history.append(result.get("history"))

                    elif item_type == "show":
                        show_data = item.get("show", {})
                        result = self.__sync_show(show_data, history, source=list_source)
                        if result:
                            if result.get("is_new"):
                                stats["shows_added"] += 1
                            else:
                                stats["shows_exists"] += 1
                            history.append(result.get("history"))

                    else:
                        logger.warning(f"未知的项目类型: {item_type}")

                except Exception as e:
                    logger.error(f"同步列表项失败: {str(e)}")
                    stats["errors"] += 1

        # 保存历史记录
        self.save_data('history', history)

        # 发送通知
        if self._notify:
            self.__send_notification(stats)

        logger.info(f"Trakt自定义列表同步完成: 新增电影 {stats['movies_added']} 部，"
                   f"新增剧集 {stats['shows_added']} 部，"
                   f"已存在电影 {stats['movies_exists']} 部，"
                   f"已存在剧集 {stats['shows_exists']} 部，"
                   f"错误 {stats['errors']} 个")

    def __parse_list_config(self, config: str) -> Tuple[Optional[str], Optional[str]]:
        """
        解析列表配置
        :param config: username/list_id 或 https://trakt.tv/users/username/lists/list_id
        :return: (username, list_id)
        """
        try:
            # 如果是URL格式
            if config.startswith("http"):
                # https://trakt.tv/users/username/lists/list_id
                parts = config.rstrip("/").split("/")
                if len(parts) >= 6 and "users" in parts and "lists" in parts:
                    users_index = parts.index("users")
                    lists_index = parts.index("lists")
                    username = parts[users_index + 1]
                    list_id = parts[lists_index + 1]
                    return username, list_id
            else:
                # username/list_id 格式
                parts = config.split("/")
                if len(parts) == 2:
                    return parts[0].strip(), parts[1].strip()

            return None, None

        except Exception as e:
            logger.error(f"解析列表配置失败: {config} - {str(e)}")
            return None, None

    def delete_history(self, tmdbid: str, apikey: str):
        """
        删除同步历史记录并同步删除订阅
        """
        from app import schemas

        if apikey != settings.API_TOKEN:
            return schemas.Response(success=False, message="API密钥错误")

        # 历史记录
        historys = self.get_data('history')
        if not historys:
            return schemas.Response(success=False, message="未找到历史记录")

        # 查找要删除的记录
        target_history = None
        for h in historys:
            if str(h.get("tmdbid")) == str(tmdbid):
                target_history = h
                break

        if not target_history:
            return schemas.Response(success=False, message="未找到指定记录")

        # 删除历史记录
        historys = [h for h in historys if str(h.get("tmdbid")) != str(tmdbid)]
        self.save_data('history', historys)

        # 删除对应的订阅
        try:
            subscribeoper = SubscribeOper()
            subscribes = subscribeoper.list_by_tmdbid(tmdbid=int(tmdbid))
            if subscribes:
                for subscribe in subscribes:
                    subscribeoper.delete(subscribe.id)
                    logger.info(f"已删除订阅: {target_history.get('title')} (TMDB: {tmdbid})")
        except Exception as e:
            logger.error(f"删除订阅失败: {str(e)}")
            return schemas.Response(success=True, message=f"历史记录已删除，但订阅删除失败: {str(e)}")

        return schemas.Response(success=True, message="历史记录和订阅已删除")
