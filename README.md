# MoviePilot Prowlarr / Jackett 索引器插件

MoviePilot V2 搜索插件，通过 Prowlarr 或 Jackett 将外部索引器资源注入 MoviePilot 搜索链。

## 插件列表

| 插件 | 说明 |
|------|------|
| **ProwlarrIndexer** | 通过 Prowlarr JSON API 搜索资源 |
| **JackettIndexer** | 通过 Jackett Torznab XML API 搜索资源 |

## 工作原理

1. 插件启动时从 Prowlarr / Jackett 获取已配置的索引器列表
2. 将每个索引器注册为 MoviePilot 的"虚拟站点"（通过 `SitesHelper.add_indexer`）
3. 通过 `get_module()` 劫持 `search_torrents` 和 `async_search_torrents` 方法
4. 当 MoviePilot 搜索链调用搜索时，插件拦截属于自己注册的站点，向 Prowlarr / Jackett API 发起请求
5. 将搜索结果映射为 `TorrentInfo` 返回给 MoviePilot

## 安装方式

将本仓库添加为 MoviePilot 的第三方插件源：

```
https://github.com/<your-repo>/prowalarr/
```

或手动将 `plugins.v2/prowlarrindexer` 和 `plugins.v2/jackettindexer` 目录复制到 MoviePilot 插件目录。

## 使用说明

### ProwlarrIndexer

1. 在插件设置中填写 Prowlarr 地址（如 `http://127.0.0.1:9696`）和 API Key
2. 开启「立即刷新索引」获取索引器列表
3. 在插件「查看数据」页面复制站点 domain
4. 到 MoviePilot 站点管理新增站点，地址格式：`https://<domain>`
5. 在搜索设置中勾选新增的站点

### JackettIndexer

1. 在插件设置中填写 Jackett 地址（如 `http://127.0.0.1:9117`）、API Key 和管理密码（可选）
2. 开启「立即刷新索引」获取索引器列表
3. 在插件「查看数据」页面复制站点 domain
4. 到 MoviePilot 站点管理新增站点，地址格式：`https://<domain>`
5. 在搜索设置中勾选新增的站点

## 配置项

| 配置 | 说明 | 默认值 |
|------|------|--------|
| host | Prowlarr / Jackett 访问地址 | - |
| api_key | API Key | - |
| password | Jackett 管理密码（仅 Jackett） | 空 |
| proxy | 是否使用代理 | 否 |
| cron | 索引器刷新周期（Cron 表达式） | `0 0 */24 * *` |
| timeout | 请求超时（秒） | 30 |
| max_retries | 请求重试次数 | 3 |

## 更新日志

### v0.2

- **JackettIndexer**: 修复索引器列表请求认证失败（`apikey` 需作为查询参数传递）
- **两个插件**: 修复搜索返回 0 结果（MoviePilot 实际调用 `async_search_torrents`，插件需劫持此方法）
- **两个插件**: 站点域名使用索引器名称（如 `prowlarr_indexer.beyondhd`）替代数字 ID，可读性更好

### v0.1

- 初始版本
- ProwlarrIndexer: 支持 Prowlarr JSON API 搜索，索引器自动发现与注册
- JackettIndexer: 支持 Jackett Torznab XML 搜索，索引器自动发现与注册
