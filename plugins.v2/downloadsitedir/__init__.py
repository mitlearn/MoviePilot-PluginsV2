# -*- coding: utf-8 -*-
"""
DownloadSiteDir Plugin for MoviePilot

根据下载来源站点自动设置种子保存目录。
支持为每个站点分别指定电影和剧集的下载路径，
未配置映射的站点将走系统默认的自动分类路径。

Version: 1.1.1
Author: Cassimolar
"""

from typing import List, Tuple, Dict, Any, Optional

from app.core.context import Context
from app.core.event import eventmanager, Event
from app.helper.downloader import DownloaderHelper
from app.helper.sites import SitesHelper
from app.log import logger
from app.plugins import _PluginBase
from app.schemas.types import EventType, MediaType, ChainEventType


# ==========================================
# EventManager Enum/Str 兼容性猴子补丁
# 解决 MoviePilot 核心事件分发中，使用字符串去匹配 Enum 键字典导致的无法监听 Bug
# ==========================================
class EnumCompatibleDict(dict):
    def _get_val_str(self, k):
        if hasattr(k, "value"):
            return str(k.value)
        return str(k)

    def _find_key(self, key):
        if super().__contains__(key):
            return key

        key_str = self._get_val_str(key)
        for k in self.keys():
            if self._get_val_str(k) == key_str:
                return k
        return key

    def __getitem__(self, key):
        return super().__getitem__(self._find_key(key))

    def __contains__(self, key):
        try:
            self.__getitem__(key)
            return True
        except KeyError:
            return False

    def get(self, key, default=None):
        try:
            return self.__getitem__(key)
        except KeyError:
            return default

    def pop(self, key, default=None):
        try:
            real_key = self._find_key(key)
            return super().pop(real_key)
        except KeyError:
            return default


try:
    orig_chain = getattr(eventmanager, "_EventManager__chain_subscribers", None)
    orig_broadcast = getattr(eventmanager, "_EventManager__broadcast_subscribers", None)

    # 不使用 isinstance，而是直接比对 class，以支持热重载时更新类定义
    if orig_chain is not None and type(orig_chain).__name__ != "EnumCompatibleDict":
        new_chain = EnumCompatibleDict()
        for k, v in orig_chain.items():
            new_chain[k] = v
        setattr(eventmanager, "_EventManager__chain_subscribers", new_chain)
        logger.info("[DownloadSiteDir] 成功对全局 EventManager 应用 Enum/Str 兼容性热补丁 (__chain_subscribers)！")
    elif orig_chain is not None and type(orig_chain) is not EnumCompatibleDict:
        # 如果是同名类但是属于不同的导入周期，也进行重新包装
        new_chain = EnumCompatibleDict()
        for k, v in orig_chain.items():
            new_chain[k] = v
        setattr(eventmanager, "_EventManager__chain_subscribers", new_chain)
        logger.info("[DownloadSiteDir] 热重载：成功更新全局 EventManager 的 Enum/Str 兼容性补丁 (__chain_subscribers)！")

    if orig_broadcast is not None and type(orig_broadcast).__name__ != "EnumCompatibleDict":
        new_broadcast = EnumCompatibleDict()
        for k, v in orig_broadcast.items():
            new_broadcast[k] = v
        setattr(eventmanager, "_EventManager__broadcast_subscribers", new_broadcast)
        logger.info("[DownloadSiteDir] 成功对全局 EventManager 应用 Enum/Str 兼容性热补丁 (__broadcast_subscribers)！")
    elif orig_broadcast is not None and type(orig_broadcast) is not EnumCompatibleDict:
        new_broadcast = EnumCompatibleDict()
        for k, v in orig_broadcast.items():
            new_broadcast[k] = v
        setattr(eventmanager, "_EventManager__broadcast_subscribers", new_broadcast)
        logger.info("[DownloadSiteDir] 热重载：成功更新全局 EventManager 的 Enum/Str 兼容性补丁 (__broadcast_subscribers)！")

except Exception as e:
    logger.error(f"[DownloadSiteDir] 应用 EventManager 补丁失败: {e}")


# ==========================================
# Qbittorrent 自动分类管理路径覆盖 Bug 猴子补丁
# 当使用自定义保存路径时，临时关闭 QB 的自动分类管理，防止指定的路径被分类目录覆盖
# ==========================================
import threading
_local_ctx = threading.local()
_patched_save_paths = set()

def apply_qb_patch():
    import sys
    patched_count = 0
    # 遍历 sys.modules 寻找所有可能导入的 Qbittorrent 类进行重写，防止多重导入时漏掉
    for mod_name, mod in list(sys.modules.items()):
        if mod and 'qbittorrent' in mod_name.lower():
            qb_class = getattr(mod, "Qbittorrent", None)
            if qb_class and not getattr(qb_class, "_patched_by_downloadsitedir", False):
                orig_add = getattr(qb_class, "add_torrent", None)
                if orig_add:
                    def make_patched_add(original_func):
                        def patched_add_torrent(self, content, is_paused=False, download_dir=None, tag=None, category=None, cookie=None, **kwargs):
                            # 通过线程上下文的 active 信号直接判断是否是由当前插件触发的改写
                            is_active = getattr(_local_ctx, "is_downloadsitedir_active", False)
                            if is_active:
                                logger.info(f"[DownloadSiteDir] 拦截到自定义保存目录下载任务，强制禁用 qBittorrent 自动分类管理（ATM）以防止路径被覆盖")
                                orig_category_setting = self._category
                                self._category = False
                                try:
                                    return original_func(self, content, is_paused, download_dir, tag, category, cookie, **kwargs)
                                finally:
                                    self._category = orig_category_setting
                                    _local_ctx.is_downloadsitedir_active = False

                            return original_func(self, content, is_paused, download_dir, tag, category, cookie, **kwargs)
                        return patched_add_torrent

                    qb_class.add_torrent = make_patched_add(orig_add)
                    setattr(qb_class, "_patched_by_downloadsitedir", True)
                    patched_count += 1
                    logger.info(f"[DownloadSiteDir] 成功对模块 {mod_name} 中的 Qbittorrent.add_torrent 应用 ATM 覆盖补丁！")

try:
    apply_qb_patch()
except Exception as e:
    logger.debug(f"[DownloadSiteDir] 尝试应用 Qbittorrent 补丁未生效 (可能未使用或未加载): {e}")


class DownloadSiteDir(_PluginBase):
    """
    下载站点目录映射插件

    监听下载添加事件，根据来源站点和媒体类型(电影/剧集)自动设置保存目录。
    支持 qBittorrent 和 Transmission。
    """

    # 插件元数据
    plugin_name = "下载站点目录映射"
    plugin_desc = "根据下载站点自动设置保存目录，支持电影/剧集分开配置"
    plugin_icon = "Linkease_A.png"
    plugin_version = "1.1.1"
    plugin_author = "Cassimolar"
    author_url = "https://github.com"
    plugin_config_prefix = "downloadsitedir_"
    plugin_order = 4
    auth_level = 1

    LOG_TAG = "[DownloadSiteDir] "

    # 运行时配置
    _enabled: bool = False
    _notify: bool = False
    _downloaders: list = None
    _selected_sites: list = []
    # 站点映射: {site_name: {"movie": "/path/movie", "tv": "/path/tv"}}
    _site_dir_map: Dict[str, Dict[str, str]] = {}

    def init_plugin(self, config: dict = None):
        """根据当前配置初始化插件"""
        config = config or {}
        self._enabled = bool(config.get("enabled"))
        self._notify = bool(config.get("notify"))
        self._downloaders = config.get("downloaders")
        self._selected_sites = config.get("selected_sites") or []

        # 从 config 中按站点名解析电影/剧集目录映射，并更新猴子补丁的排除目录集
        self._site_dir_map = {}
        _patched_save_paths.clear()
        for site in self._selected_sites:
            movie_dir = config.get(f"movie_dir__{site}", "").strip()
            tv_dir = config.get(f"tv_dir__{site}", "").strip()
            if movie_dir or tv_dir:
                self._site_dir_map[site] = {
                    "movie": movie_dir,
                    "tv": tv_dir
                }
                if movie_dir:
                    _patched_save_paths.add(movie_dir)
                if tv_dir:
                    _patched_save_paths.add(tv_dir)

        if self._enabled:
            if self._site_dir_map:
                logger.info(
                    f"{self.LOG_TAG}插件已启用，"
                    f"已加载 {len(self._site_dir_map)} 条站点映射"
                )
                for site, dirs in self._site_dir_map.items():
                    m = dirs.get('movie') or '(默认分类)'
                    t = dirs.get('tv') or '(默认分类)'
                    logger.debug(f"{self.LOG_TAG}  {site}: 电影={m}, 剧集={t}")
            else:
                logger.warning(f"{self.LOG_TAG}插件已启用但未配置任何映射规则")

    def _find_site_mapping(self, site_name: str) -> Optional[Dict[str, str]]:
        """
        根据站点名称查找映射规则，支持四级匹配：
        1. 精确匹配: "Jackett索引器-TheRARBG" == "Jackett索引器-TheRARBG"
        2. 配置键包含在站点名中: "BeyondHD" in "Jackett索引器-BeyondHD"
        3. 站点名包含在配置键中: "BeyondHD" in "Jackett索引器-BeyondHD"
        4. 前缀匹配(聚合索引器): "Jackett索引器-全部搜索" 和 "Jackett索引器-TheRARBG"
        共享前缀 "Jackett索引器"，视为匹配
        """
        if not site_name or not self._site_dir_map:
            return None

        # 1. 精确匹配
        if site_name in self._site_dir_map:
            return self._site_dir_map[site_name]

        # 2. 配置键在站点名中
        for key, mapping in self._site_dir_map.items():
            if key in site_name:
                return mapping

        # 3. 站点名在配置键中
        for key, mapping in self._site_dir_map.items():
            if site_name in key:
                return mapping

        # 4. 前缀匹配 — 处理聚合索引器场景
        #    配置: "Jackett索引器-全部搜索" → 前缀 "Jackett索引器"
        #    下载: "Jackett索引器-TheRARBG"  → 前缀 "Jackett索引器"
        #    前缀相同则匹配
        site_prefix = site_name.split("-")[0] if "-" in site_name else None
        if site_prefix:
            for key, mapping in self._site_dir_map.items():
                key_prefix = key.split("-")[0] if "-" in key else key
                if key_prefix == site_prefix:
                    logger.debug(
                        f"{self.LOG_TAG}前缀匹配: [{site_name}] 命中配置 [{key}] "
                        f"(共同前缀: {site_prefix})"
                    )
                    return mapping

        return None

    def get_state(self) -> bool:
        return self._enabled

    @staticmethod
    def get_command() -> List[Dict[str, Any]]:
        return []

    def get_api(self) -> List[Dict[str, Any]]:
        return []

    @eventmanager.register(ChainEventType.ResourceDownload)
    def on_resource_download(self, event: Event):
        """资源下载前拦截事件处理：根据站点+媒体类型设置保存目录"""
        if not self.get_state():
            return
        if not event or not event.event_data:
            return

        try:
            _local_ctx.is_downloadsitedir_active = False
            event_data = event.event_data
            if isinstance(event_data, dict):
                downloader = event_data.get("downloader")
                context: Context = event_data.get("context")
                options = event_data.get("options") or {}
            else:
                downloader = getattr(event_data, "downloader", None)
                context: Context = getattr(event_data, "context", None)
                options = getattr(event_data, "options", {}) or {}

            if not context:
                return

            # 获取种子和站点名称
            torrent_info = context.torrent_info if context else None
            site_name = torrent_info.site_name if torrent_info else None

            # 1. 尝试从 context 种子信息中获取下载器
            if not downloader:
                downloader = torrent_info.site_downloader if torrent_info else None

            # 2. 从系统配置中获取所有已启用的下载器
            active_downloaders = []
            try:
                from app.db.systemconfig_oper import SystemConfigOper
                from app.schemas.types import SystemConfigKey
                sys_downloaders = SystemConfigOper().get(SystemConfigKey.Downloaders) or []
                active_downloaders = [
                    d.get("name") for d in sys_downloaders
                    if d.get("enabled") and d.get("name")
                ]
            except Exception as e:
                logger.debug(f"{self.LOG_TAG}获取系统下载器配置失败: {e}")

            # 3. 如果 downloader 依然为 None，且系统只启用了一个下载器，直接使用它
            if not downloader and len(active_downloaders) == 1:
                downloader = active_downloaders[0]
                logger.info(f"{self.LOG_TAG}自动推导下载器为系统唯一启用的下载器: {downloader}")

            logger.info(
                f"{self.LOG_TAG}监听到资源下载事件！站点: {site_name}, 下载器: {downloader}"
            )

            # 4. 根据用户配置的监听下载器列表进行过滤
            if self._downloaders:
                if downloader:
                    if downloader not in self._downloaders:
                        logger.info(f"{self.LOG_TAG}下载器 {downloader} 不在监听列表中，跳过拦截")
                        return
                else:
                    # 如果下载器最终为 None，但系统所有启用的下载器都不在监听列表中，则跳过
                    if not any(d in self._downloaders for d in active_downloaders):
                        logger.info(f"{self.LOG_TAG}所有启用的下载器 {active_downloaders} 都不在监听列表中，跳过拦截")
                        return

            if not site_name:
                logger.info(f"{self.LOG_TAG}种子无站点信息，跳过拦截")
                return

            # 查找站点映射
            mapping = self._find_site_mapping(site_name)
            if not mapping:
                logger.info(
                    f"{self.LOG_TAG}站点 [{site_name}] 未配置映射，跳过拦截"
                )
                return

            # 判断媒体类型(电影/剧集)，选择对应目录
            media_info = context.media_info if context else None
            media_type = media_info.type if media_info else None

            if media_type == MediaType.MOVIE:
                target_dir = mapping.get("movie", "")
                type_label = "电影"
            else:
                # TV / 动漫 / 未知类型都走剧集目录
                target_dir = mapping.get("tv", "")
                type_label = "剧集"

            if not target_dir:
                logger.info(
                    f"{self.LOG_TAG}站点 [{site_name}] {type_label}目录未配置，跳过拦截"
                )
                return

            # 直接修改保存目录
            options["save_path"] = target_dir
            _local_ctx.is_downloadsitedir_active = True

            logger.info(
                f"{self.LOG_TAG}✅ [{site_name}] {type_label} -> {target_dir}"
            )

            if self._notify:
                title = media_info.title if media_info else "未知"
                self.post_message(
                    title="【下载站点目录映射】",
                    text=(f"媒体: {title}\n类型: {type_label}\n"
                          f"站点: {site_name}\n目录: {target_dir}"),
                )

        except Exception as e:
            logger.error(f"{self.LOG_TAG}处理下载拦截事件出错: {str(e)}")

    def get_form(self) -> Tuple[List[dict], Dict[str, Any]]:
        """返回插件配置页面"""

        # 获取所有可用站点作为选项
        site_options = []
        try:
            for s in SitesHelper().get_indexers():
                name = s.get("name", "")
                if name:
                    site_options.append({"title": name, "value": name})
        except Exception:
            pass

        # 为已选站点动态生成每站配置行 (站点名 + 电影目录 + 剧集目录)
        site_config_rows = []
        if self._selected_sites:
            # 表头
            site_config_rows.append({
                'component': 'VRow',
                'props': {'class': 'px-3 mt-2'},
                'content': [
                    {
                        'component': 'VCol',
                        'props': {'cols': 12, 'md': 4},
                        'content': [{'component': 'span',
                                     'props': {'class': 'text-subtitle-2 font-weight-bold'},
                                     'text': '站点'}]
                    },
                    {
                        'component': 'VCol',
                        'props': {'cols': 12, 'md': 4},
                        'content': [{'component': 'span',
                                     'props': {'class': 'text-subtitle-2 font-weight-bold'},
                                     'text': '电影目录'}]
                    },
                    {
                        'component': 'VCol',
                        'props': {'cols': 12, 'md': 4},
                        'content': [{'component': 'span',
                                     'props': {'class': 'text-subtitle-2 font-weight-bold'},
                                     'text': '剧集目录'}]
                    },
                ]
            })

            # 每个站点一行
            for site in self._selected_sites:
                site_config_rows.append({
                    'component': 'VRow',
                    'props': {'class': 'px-3'},
                    'content': [
                        # 站点名称
                        {
                            'component': 'VCol',
                            'props': {'cols': 12, 'md': 4,
                                      'class': 'd-flex align-center'},
                            'content': [{
                                'component': 'VChip',
                                'props': {'color': 'primary', 'variant': 'tonal',
                                          'label': True, 'size': 'small'},
                                'text': site
                            }]
                        },
                        # 电影目录
                        {
                            'component': 'VCol',
                            'props': {'cols': 12, 'md': 4},
                            'content': [{
                                'component': 'VTextField',
                                'props': {
                                    'model': f'movie_dir__{site}',
                                    'label': '电影目录',
                                    'placeholder': '留空走默认分类',
                                    'density': 'compact',
                                    'hide-details': True,
                                }
                            }]
                        },
                        # 剧集目录
                        {
                            'component': 'VCol',
                            'props': {'cols': 12, 'md': 4},
                            'content': [{
                                'component': 'VTextField',
                                'props': {
                                    'model': f'tv_dir__{site}',
                                    'label': '剧集目录',
                                    'placeholder': '留空走默认分类',
                                    'density': 'compact',
                                    'hide-details': True,
                                }
                            }]
                        },
                    ]
                })
        else:
            site_config_rows.append({
                'component': 'VRow',
                'content': [{
                    'component': 'VCol',
                    'props': {'cols': 12},
                    'content': [{
                        'component': 'VAlert',
                        'props': {
                            'type': 'warning',
                            'variant': 'tonal',
                            'text': '请先在上方选择需要配置目录的站点'
                        }
                    }]
                }]
            })

        # 组装完整表单
        form_content = [
            # 第一行：开关
            {
                'component': 'VRow',
                'content': [
                    {
                        'component': 'VCol',
                        'props': {'cols': 12, 'md': 6},
                        'content': [{
                            'component': 'VSwitch',
                            'props': {'model': 'enabled', 'label': '启用插件'}
                        }]
                    },
                    {
                        'component': 'VCol',
                        'props': {'cols': 12, 'md': 6},
                        'content': [{
                            'component': 'VSwitch',
                            'props': {'model': 'notify', 'label': '发送通知'}
                        }]
                    }
                ]
            },
            # 下载器选择
            {
                'component': 'VRow',
                'content': [{
                    'component': 'VCol',
                    'props': {'cols': 12},
                    'content': [{
                        'component': 'VSelect',
                        'props': {
                            'multiple': True,
                            'chips': True,
                            'clearable': True,
                            'model': 'downloaders',
                            'label': '监听下载器',
                            'items': [
                                {"title": c.name, "value": c.name}
                                for c in DownloaderHelper().get_configs().values()
                            ],
                        }
                    }]
                }]
            },
            # 站点选择
            {
                'component': 'VRow',
                'content': [{
                    'component': 'VCol',
                    'props': {'cols': 12},
                    'content': [{
                        'component': 'VSelect',
                        'props': {
                            'multiple': True,
                            'chips': True,
                            'clearable': True,
                            'model': 'selected_sites',
                            'label': '配置站点（选择后保存，即可为每个站点配置目录）',
                            'items': site_options,
                        }
                    }]
                }]
            },
            # 分隔线
            {
                'component': 'VRow',
                'content': [{
                    'component': 'VCol',
                    'props': {'cols': 12},
                    'content': [{'component': 'VDivider'}]
                }]
            },
        ]

        # 添加站点配置行
        form_content.extend(site_config_rows)

        # 说明
        form_content.append({
            'component': 'VRow',
            'props': {'class': 'mt-4'},
            'content': [{
                'component': 'VCol',
                'props': {'cols': 12},
                'content': [{
                    'component': 'VAlert',
                    'props': {
                        'type': 'info',
                        'variant': 'tonal',
                        'text': (
                            '使用说明：\n'
                            '1. 先选择需要配置的站点，保存后会出现每个站点的目录配置行\n'
                            '2. 为每个站点分别设置电影和剧集的保存目录\n'
                            '3. 留空的目录将不做干预，走系统默认的自动分类路径\n'
                            '4. 站点名支持模糊匹配，如配置"BeyondHD"可匹配"Jackett索引器-BeyondHD"'
                        )
                    }
                }]
            }]
        })

        return [{'component': 'VForm', 'content': form_content}], {
            "enabled": False,
            "notify": False,
        }

    def get_page(self) -> List[dict]:
        pass

    def stop_service(self):
        pass
