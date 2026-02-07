# MoviePilot Prowlarr/Jackett 索引器插件

为 [MoviePilot](https://github.com/jxxghp/MoviePilot) V2 版本开发的搜索扩展插件，支持通过 Prowlarr 或 Jackett 聚合多个索引站点进行资源检索。

## 功能特性

- **Prowlarr 集成**：通过 Prowlarr API 搜索所有配置的索引器
- **Jackett 集成**：通过 Jackett Torznab API 搜索所有配置的索引器
- **自动同步**：定期从 Prowlarr/Jackett 同步索引器列表
- **无缝集成**：自动注册到 MoviePilot 站点系统，支持原生搜索流程
- **媒体类型过滤**：根据电影/电视剧类型自动筛选分类

## 插件列表

| 插件 | 说明 |
|------|------|
| ProwlarrIndexer | Prowlarr 索引器集成 |
| JackettIndexer | Jackett 索引器集成 |

## 安装方法

### 方法一：添加第三方插件仓库

1. 在 MoviePilot 设置中添加插件仓库地址
2. 在插件市场中搜索并安装 `Prowlarr索引器` 或 `Jackett索引器`

### 方法二：手动安装

1. 将 `plugins.v2/prowlarrindexer` 或 `plugins.v2/jackettindexer` 目录复制到 MoviePilot 的插件目录
2. 将 `icons/` 目录中的图标复制到 MoviePilot 的图标目录
3. 重启 MoviePilot

## 配置说明

### Prowlarr 索引器配置

| 配置项 | 说明 | 必填 |
|--------|------|------|
| Prowlarr地址 | Prowlarr 服务访问地址，如 `http://192.168.1.100:9696` | 是 |
| API Key | 在 Prowlarr → Settings → General → Security 中获取 | 是 |
| 使用代理 | 是否通过 MoviePilot 配置的代理访问 | 否 |
| 索引器同步周期 | 定期同步索引器列表的 cron 表达式，默认每24小时同步一次 | 否 |

### Jackett 索引器配置

| 配置项 | 说明 | 必填 |
|--------|------|------|
| Jackett地址 | Jackett 服务访问地址，如 `http://192.168.1.100:9117` | 是 |
| API Key | 在 Jackett 管理界面右上角复制 | 是 |
| 管理密码 | Jackett 管理密码（如已设置） | 否 |
| 使用代理 | 是否通过 MoviePilot 配置的代理访问 | 否 |
| 索引器同步周期 | 定期同步索引器列表的 cron 表达式，默认每24小时同步一次 | 否 |

## 使用流程

### 前置条件

1. 已部署并配置好 Prowlarr 或 Jackett 服务
2. 在 Prowlarr/Jackett 中添加并测试好索引器
3. MoviePilot V2 版本

### 使用步骤

1. **安装插件**：在插件市场安装对应的索引器插件
2. **配置插件**：填写服务地址和 API Key
3. **启用插件**：打开"启用插件"开关
4. **同步索引器**：点击"立即同步一次"按钮
5. **启用索引站点**：
   - 前往 **设置 → 搜索 → 索引站点**
   - 在列表中找到插件注册的索引器（以 `Prowlarr-` 或 `Jackett-` 开头）
   - 勾选需要启用的索引器
6. **开始搜索**：在 MoviePilot 中搜索资源时会自动调用已启用的索引器

> **重要提示**：无需在"站点管理"中手动添加站点！插件会自动将索引器注册到搜索系统。

## API 说明

### Prowlarr API

- **获取索引器列表**：`GET /api/v1/indexerstats`
- **搜索资源**：`GET /api/v1/search`
  - 参数：`query`, `indexerIds`, `type`, `categories`, `limit`, `offset`
- **认证方式**：`X-Api-Key` 请求头

### Jackett API (Torznab)

- **获取索引器列表**：`GET /api/v2.0/indexers?configured=true`
- **搜索资源**：`GET /api/v2.0/indexers/{id}/results/torznab/`
  - 参数：`apikey`, `t=search`, `q`, `cat`
- **认证方式**：`apikey` 查询参数 + 可选的管理密码

## 分类映射

| MoviePilot 类型 | Prowlarr/Jackett 分类 |
|-----------------|----------------------|
| 电影 (MOVIE) | 2000 |
| 电视剧 (TV) | 5000 |
| 未指定 | 2000, 5000 |

## 常见问题

### Q: 添加站点时报错"该站点不支持"？

**这是正常的！** 插件使用虚拟域名注册索引器，不支持通过"站点管理"手动添加。

正确的使用方式是：
1. 启用插件并同步索引器
2. 前往 **设置 → 搜索 → 索引站点** 勾选需要的索引器
3. 搜索时会自动调用

### Q: 为什么搜索没有结果？

1. 检查 Prowlarr/Jackett 服务是否正常运行
2. 确认 API Key 是否正确
3. 确认索引器在 Prowlarr/Jackett 中是否正常工作
4. 确认已在 **设置 → 搜索 → 索引站点** 中勾选了对应的索引器
5. 查看 MoviePilot 日志获取详细错误信息

### Q: 索引器列表为空？

1. 点击插件配置中的"立即同步一次"
2. 查看插件的"查看数据"页面确认是否获取到索引器
3. 检查 Prowlarr/Jackett 中是否已配置索引器

### Q: Prowlarr 和 Jackett 应该选择哪个？

- **Prowlarr**：推荐新用户使用，配置更简单，API 更现代
- **Jackett**：历史悠久，索引器支持更多，社区活跃

两者可以同时使用，但建议只选择其一以避免重复结果。

## 目录结构

```
output/
├── package.v2.json          # 插件注册配置
├── plugins.v2/
│   ├── prowlarrindexer/
│   │   └── __init__.py      # Prowlarr 索引器插件
│   └── jackettindexer/
│       └── __init__.py      # Jackett 索引器插件
├── icons/
│   ├── Prowlarr.png         # Prowlarr 图标
│   └── Jackett_A.png        # Jackett 图标
└── README.md                # 本文档
```

## 开发说明

### 插件架构

插件基于 MoviePilot V2 插件框架开发，核心实现：

1. **继承 `_PluginBase`**：实现插件生命周期方法
2. **实现 `get_module()`**：注册 `search_torrents` 方法钩子
3. **使用 `SitesHelper`**：将索引器注册到 MoviePilot 站点系统
4. **返回 `TorrentInfo`**：搜索结果标准化为 MoviePilot 可识别的格式

### 关键方法

| 方法 | 说明 |
|------|------|
| `init_plugin()` | 初始化插件，加载配置，启动定时任务 |
| `get_module()` | 注册搜索钩子 |
| `search_torrents()` | 执行搜索并返回结果 |
| `get_form()` | 配置表单 UI |
| `get_page()` | 数据展示页面 |

## 致谢

- [MoviePilot](https://github.com/jxxghp/MoviePilot) - 优秀的媒体自动化工具
- [jtcymc](https://github.com/jtcymc/MoviePilot-PluginsV2) - 原始实现参考
- [Prowlarr](https://github.com/Prowlarr/Prowlarr) - 统一的索引器管理
- [Jackett](https://github.com/Jackett/Jackett) - 经典的索引器代理

## 许可证

MIT License
