# Trakt API 文档

## 概述

Trakt API 是一个 RESTful API，用于访问 Trakt.tv 的影视追踪功能。本文档描述了 TraktSync 插件使用的核心 API 端点。

## API 基础信息

- **Base URL**: `https://api.trakt.tv`
- **API 版本**: `2`
- **协议**: HTTPS
- **数据格式**: JSON
- **认证方式**: OAuth 2.0

## 认证流程

### 1. 创建应用

访问 [Trakt Applications](https://trakt.tv/oauth/applications/new) 创建新应用：

- **Name**: 应用名称（如：MoviePilot TraktSync）
- **Description**: 应用描述
- **Redirect URI**: `urn:ietf:wg:oauth:2.0:oob`（用于获取授权码的特殊URI）
- **Permissions**: 勾选所需权限

创建后获得：
- **Client ID**: 应用标识
- **Client Secret**: 应用密钥

### 2. 获取授权码（手动操作）

访问以下 URL 获取授权码：

```
https://trakt.tv/oauth/authorize?response_type=code&client_id={CLIENT_ID}&redirect_uri=urn:ietf:wg:oauth:2.0:oob
```

用户登录并授权后，会显示授权码（Authorization Code）。

### 3. 获取 Access Token 和 Refresh Token

**请求**:

```http
POST https://api.trakt.tv/oauth/token
Content-Type: application/json

{
  "code": "授权码",
  "client_id": "你的Client ID",
  "client_secret": "你的Client Secret",
  "redirect_uri": "urn:ietf:wg:oauth:2.0:oob",
  "grant_type": "authorization_code"
}
```

**cURL 示例**:

```bash
curl -X POST "https://api.trakt.tv/oauth/token" \
  -H "Content-Type: application/json" \
  -d '{
    "code": "YOUR_AUTH_CODE",
    "client_id": "YOUR_CLIENT_ID",
    "client_secret": "YOUR_CLIENT_SECRET",
    "redirect_uri": "urn:ietf:wg:oauth:2.0:oob",
    "grant_type": "authorization_code"
  }'
```

**响应**:

```json
{
  "access_token": "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9...",
  "token_type": "Bearer",
  "expires_in": 7776000,
  "refresh_token": "def50200abcd1234...",
  "scope": "public",
  "created_at": 1706169600
}
```

**字段说明**:
- `access_token`: 访问令牌（用于 API 请求）
- `token_type`: 令牌类型（固定为 "Bearer"）
- `expires_in`: 过期时间（秒，通常为 7776000 秒 = 90 天）
- `refresh_token`: 刷新令牌（用于获取新的 access token）
- `scope`: 权限范围
- `created_at`: 创建时间（Unix 时间戳）

### 4. 刷新 Access Token

Access Token 过期后（或即将过期时），使用 Refresh Token 获取新的 Access Token。

**请求**:

```http
POST https://api.trakt.tv/oauth/token
Content-Type: application/json

{
  "refresh_token": "你的Refresh Token",
  "client_id": "你的Client ID",
  "client_secret": "你的Client Secret",
  "redirect_uri": "urn:ietf:wg:oauth:2.0:oob",
  "grant_type": "refresh_token"
}
```

**cURL 示例**:

```bash
curl -X POST "https://api.trakt.tv/oauth/token" \
  -H "Content-Type: application/json" \
  -d '{
    "refresh_token": "YOUR_REFRESH_TOKEN",
    "client_id": "YOUR_CLIENT_ID",
    "client_secret": "YOUR_CLIENT_SECRET",
    "redirect_uri": "urn:ietf:wg:oauth:2.0:oob",
    "grant_type": "refresh_token"
  }'
```

**响应**:

```json
{
  "access_token": "新的access_token",
  "token_type": "Bearer",
  "expires_in": 7776000,
  "refresh_token": "新的refresh_token",
  "scope": "public",
  "created_at": 1706256000
}
```

**注意**:
- 每次刷新后都会返回新的 `refresh_token`，需要保存
- 建议在 Token 过期前 1 小时刷新

---

## Watchlist API

### 获取想看电影列表

**端点**: `GET /sync/watchlist/movies`

**请求头**:

```http
Content-Type: application/json
trakt-api-version: 2
trakt-api-key: {CLIENT_ID}
Authorization: Bearer {ACCESS_TOKEN}
```

**cURL 示例**:

```bash
curl -X GET "https://api.trakt.tv/sync/watchlist/movies" \
  -H "Content-Type: application/json" \
  -H "trakt-api-version: 2" \
  -H "trakt-api-key: YOUR_CLIENT_ID" \
  -H "Authorization: Bearer YOUR_ACCESS_TOKEN"
```

**响应**:

```json
[
  {
    "rank": 1,
    "id": 12345,
    "listed_at": "2024-01-15T10:30:00.000Z",
    "notes": null,
    "type": "movie",
    "movie": {
      "title": "The Dark Knight",
      "year": 2008,
      "ids": {
        "trakt": 120,
        "slug": "the-dark-knight-2008",
        "imdb": "tt0468569",
        "tmdb": 155
      }
    }
  },
  {
    "rank": 2,
    "id": 67890,
    "listed_at": "2024-02-10T14:20:00.000Z",
    "notes": null,
    "type": "movie",
    "movie": {
      "title": "Inception",
      "year": 2010,
      "ids": {
        "trakt": 16662,
        "slug": "inception-2010",
        "imdb": "tt1375666",
        "tmdb": 27205
      }
    }
  }
]
```

**字段说明**:
- `rank`: 在列表中的排序
- `id`: Watchlist 条目 ID
- `listed_at`: 添加到 Watchlist 的时间（ISO 8601 格式）
- `type`: 类型（固定为 "movie"）
- `movie.title`: 电影标题
- `movie.year`: 上映年份
- `movie.ids.trakt`: Trakt ID
- `movie.ids.slug`: URL slug
- `movie.ids.imdb`: IMDb ID（格式：ttXXXXXXX）
- `movie.ids.tmdb`: TMDB ID（整数）

---

### 获取想看剧集列表

**端点**: `GET /sync/watchlist/shows`

**请求头**:

```http
Content-Type: application/json
trakt-api-version: 2
trakt-api-key: {CLIENT_ID}
Authorization: Bearer {ACCESS_TOKEN}
```

**cURL 示例**:

```bash
curl -X GET "https://api.trakt.tv/sync/watchlist/shows" \
  -H "Content-Type: application/json" \
  -H "trakt-api-version: 2" \
  -H "trakt-api-key: YOUR_CLIENT_ID" \
  -H "Authorization: Bearer YOUR_ACCESS_TOKEN"
```

**响应**:

```json
[
  {
    "rank": 1,
    "id": 23456,
    "listed_at": "2024-01-20T09:15:00.000Z",
    "notes": null,
    "type": "show",
    "show": {
      "title": "Breaking Bad",
      "year": 2008,
      "ids": {
        "trakt": 1388,
        "slug": "breaking-bad",
        "tvdb": 81189,
        "imdb": "tt0903747",
        "tmdb": 1396
      }
    }
  },
  {
    "rank": 2,
    "id": 34567,
    "listed_at": "2024-02-05T16:45:00.000Z",
    "notes": null,
    "type": "show",
    "show": {
      "title": "The Wire",
      "year": 2002,
      "ids": {
        "trakt": 1393,
        "slug": "the-wire",
        "tvdb": 79126,
        "imdb": "tt0306414",
        "tmdb": 1438
      }
    }
  }
]
```

**字段说明**:
- `rank`: 在列表中的排序
- `id`: Watchlist 条目 ID
- `listed_at`: 添加到 Watchlist 的时间
- `type`: 类型（固定为 "show"）
- `show.title`: 剧集标题
- `show.year`: 首播年份
- `show.ids.trakt`: Trakt ID
- `show.ids.slug`: URL slug
- `show.ids.tvdb`: TVDB ID
- `show.ids.imdb`: IMDb ID
- `show.ids.tmdb`: TMDB ID（整数）

---

## 错误处理

### 常见错误码

| 状态码 | 说明 | 处理方式 |
|--------|------|----------|
| 200 | 成功 | - |
| 400 | 请求参数错误 | 检查请求格式和参数 |
| 401 | 未授权（Token 无效或过期） | 刷新 Access Token |
| 403 | 禁止访问 | 检查权限范围 |
| 404 | 资源不存在 | 检查 API 端点 |
| 420 | 账户限制 | 联系 Trakt 支持 |
| 422 | 参数验证失败 | 检查参数格式 |
| 429 | 请求过于频繁（Rate Limit） | 降低请求频率，等待后重试 |
| 500-504 | 服务器错误 | 稍后重试 |

### 错误响应示例

```json
{
  "error": "invalid_grant",
  "error_description": "The provided authorization grant is invalid, expired, revoked, or does not match the redirection URI used in the authorization request."
}
```

### Rate Limiting

Trakt API 有请求频率限制：
- **开发版应用**: 1000 次/天
- **生产版应用**: 根据审核结果调整

**Rate Limit 响应头**:
```http
X-RateLimit-Limit: 1000
X-RateLimit-Remaining: 995
X-RateLimit-Reset: 1706256000
```

**建议**:
- 检查 `X-RateLimit-Remaining` 头
- 收到 429 错误时，等待 `X-RateLimit-Reset` 指定的时间后重试
- 使用合理的请求间隔（建议 1-2 秒）

---

## 字段映射

TraktSync 插件将 Trakt API 数据映射到 MoviePilot 所需格式：

| Trakt 字段 | MoviePilot 字段 | 说明 |
|------------|-----------------|------|
| `movie.title` / `show.title` | `title` | 标题 |
| `movie.year` / `show.year` | `year` | 年份 |
| `movie.ids.tmdb` / `show.ids.tmdb` | `tmdb_id` | TMDB ID（主要标识符） |
| `movie.ids.imdb` / `show.ids.imdb` | `imdb_id` | IMDb ID（备用） |
| `type` | `media_type` | 媒体类型（movie/tv） |

---

## 参考资源

- [Trakt API 官方文档](https://trakt.docs.apiary.io)
- [Trakt OAuth 应用管理](https://trakt.tv/oauth/applications)
- [OAuth 2.0 规范](https://oauth.net/2/)
- [PyTrakt 库](https://github.com/moogar0880/PyTrakt)

---

## 自定义列表 API

### 获取自定义列表内容

**端点**: `GET /users/{username}/lists/{list_id}/items`

**请求头**:

```http
Content-Type: application/json
trakt-api-version: 2
trakt-api-key: {CLIENT_ID}
Authorization: Bearer {ACCESS_TOKEN}
```

**cURL 示例**:

```bash
curl -X GET "https://api.trakt.tv/users/justin/lists/star-wars/items" \
  -H "Content-Type: application/json" \
  -H "trakt-api-version: 2" \
  -H "trakt-api-key: YOUR_CLIENT_ID" \
  -H "Authorization: Bearer YOUR_ACCESS_TOKEN"
```

**响应**:

```json
[
  {
    "rank": 1,
    "id": 12345,
    "listed_at": "2024-01-15T10:30:00.000Z",
    "type": "movie",
    "movie": {
      "title": "Star Wars",
      "year": 1977,
      "ids": {
        "trakt": 466,
        "slug": "star-wars-1977",
        "imdb": "tt0076759",
        "tmdb": 11
      }
    }
  },
  {
    "rank": 2,
    "id": 67890,
    "listed_at": "2024-02-10T14:20:00.000Z",
    "type": "show",
    "show": {
      "title": "The Mandalorian",
      "year": 2019,
      "ids": {
        "trakt": 139211,
        "slug": "the-mandalorian",
        "tvdb": 361753,
        "imdb": "tt8111088",
        "tmdb": 82856
      }
    }
  }
]
```

**字段说明**:
- `type`: 类型（"movie" 或 "show"）
- `movie`/`show`: 电影或剧集的详细信息
- 其他字段同 Watchlist API

---

## 插件 API 端点

TraktSync 插件提供以下 API 端点用于触发同步和管理历史记录。

### 触发同步

**端点**: `POST /api/v1/plugin/TraktSync/sync`

**请求参数**:

| 参数名 | 类型 | 必填 | 说明 |
|--------|------|------|------|
| apikey | string | 是 | MoviePilot API Token |

**cURL 示例**:

```bash
curl -X POST "http://localhost:3000/api/v1/plugin/TraktSync/sync?apikey=YOUR_API_TOKEN"
```

**成功响应**:

```json
{
  "success": true,
  "message": "同步任务已启动"
}
```

**说明**:
- 触发Trakt想看列表同步
- 仅添加订阅，不搜索下载
- 异步执行，立即返回

---

### 触发同步并下载

**端点**: `POST /api/v1/plugin/TraktSync/sync_download`

**请求参数**:

| 参数名 | 类型 | 必填 | 说明 |
|--------|------|------|------|
| apikey | string | 是 | MoviePilot API Token |

**cURL 示例**:

```bash
curl -X POST "http://localhost:3000/api/v1/plugin/TraktSync/sync_download?apikey=YOUR_API_TOKEN"
```

**成功响应**:

```json
{
  "success": true,
  "message": "同步下载任务已启动"
}
```

**说明**:
- 触发Trakt想看列表同步
- 优先搜索下载，失败时添加订阅
- 异步执行，立即返回

---

### 触发自定义列表同步

**端点**: `POST /api/v1/plugin/TraktSync/sync_custom_lists`

**请求参数**:

| 参数名 | 类型 | 必填 | 说明 |
|--------|------|------|------|
| apikey | string | 是 | MoviePilot API Token |

**cURL 示例**:

```bash
curl -X POST "http://localhost:3000/api/v1/plugin/TraktSync/sync_custom_lists?apikey=YOUR_API_TOKEN"
```

**成功响应**:

```json
{
  "success": true,
  "message": "自定义列表同步任务已启动"
}
```

**说明**:
- 触发配置的Trakt自定义列表同步
- 同步配置中所有列表的电影和剧集
- 异步执行，立即返回

---

### 删除历史记录

**端点**: `GET /api/v1/plugin/TraktSync/delete_history`

**请求参数**:

| 参数名 | 类型 | 必填 | 说明 |
|--------|------|------|------|
| tmdbid | string | 是 | TMDB ID |
| apikey | string | 是 | MoviePilot API Token |

**cURL 示例**:

```bash
curl -X GET "http://localhost:3000/api/v1/plugin/TraktSync/delete_history?tmdbid=155&apikey=YOUR_API_TOKEN"
```

**成功响应**:

```json
{
  "success": true,
  "message": "删除成功"
}
```

**错误响应**:

```json
{
  "success": false,
  "message": "API密钥错误"
}
```

或

```json
{
  "success": false,
  "message": "未找到历史记录"
}
```

**说明**:
- 此端点用于从插件详情页删除单条同步历史记录
- 需要提供有效的 MoviePilot API Token
- 删除操作不可逆

---

## 插件远程命令

TraktSync 插件支持以下远程命令，可通过 MoviePilot 的消息通知渠道（如 Telegram、WeChat、Slack）触发。

### 同步 Trakt 想看

**命令**: `/trakt_sync`

**分类**: 订阅

**描述**: 同步 Trakt 想看列表，仅添加订阅（不搜索下载）

**执行流程**:
1. 获取 Trakt 想看电影和剧集列表
2. 检查媒体库是否已存在
3. 检查是否已订阅
4. 未存在且未订阅的内容添加订阅
5. 记录同步历史

**使用场景**:
- 手动触发同步
- 快速添加订阅，不消耗下载资源

---

### 同步并下载 Trakt 想看

**命令**: `/trakt_download`

**分类**: 订阅

**描述**: 同步 Trakt 想看列表，优先搜索下载，失败时添加订阅

**执行流程**:
1. 获取 Trakt 想看电影和剧集列表
2. 检查媒体库是否已存在
3. 检查是否已订阅
4. 未存在的内容：
   - 搜索资源
   - 找到资源 → 立即下载
   - 未找到资源或下载失败 → 添加订阅
5. 记录同步历史

**使用场景**:
- 希望立即获取资源
- 资源丰富的站点环境
- 需要快速完成观看需求

**注意**:
- 强制启用搜索下载功能，无论插件配置中是否开启
- 会消耗站点流量和下载器资源
- 剧集可能部分下载成功，剩余部分自动添加订阅

---

### 同步 Trakt 自定义列表

**命令**: `/trakt_custom_lists`

**分类**: 订阅

**描述**: 同步配置的 Trakt 自定义列表

**执行流程**:
1. 读取插件配置中的自定义列表
2. 逐个获取列表内容
3. 处理列表中的电影和剧集
4. 添加订阅或下载
5. 记录同步历史

**使用场景**:
- 同步策划的主题列表（如"漫威电影宇宙"、"必看经典"等）
- 同步他人分享的列表
- 批量添加订阅

**注意**:
- 需要在插件配置中预先设置自定义列表
- 支持多个列表，用逗号分隔

---

## 工作流动作（Workflow Actions）

TraktSync 插件注册了以下工作流动作，可在 MoviePilot 工作流编排中使用。

### 同步Trakt想看

**动作ID**: `trakt_sync`

**动作名称**: 同步Trakt想看

**功能**: 同步Trakt想看列表，仅添加订阅

**参数**: 无

**返回**:
- `成功`: `True, ActionContent`
- `失败`: `False, ActionContent`

**使用场景**:
- 定时工作流中自动同步
- 与其他动作组合使用
- 条件触发同步

---

### 同步并下载Trakt想看

**动作ID**: `trakt_sync_download`

**动作名称**: 同步并下载Trakt想看

**功能**: 同步Trakt想看列表，优先搜索下载

**参数**: 无

**返回**:
- `成功`: `True, ActionContent`
- `失败`: `False, ActionContent`

**使用场景**:
- 立即获取资源的工作流
- 资源监控触发后的下载动作
- 与通知、过滤等动作组合

---

### 同步Trakt自定义列表

**动作ID**: `trakt_sync_custom_lists`

**动作名称**: 同步Trakt自定义列表

**功能**: 同步配置的Trakt自定义列表

**参数**: 无

**返回**:
- `成功`: `True, ActionContent`
- `失败`: `False, ActionContent`

**使用场景**:
- 定期同步主题列表
- 批量处理自定义收藏
- 与条件触发器结合

**配置要求**:
- 插件配置中需要预先设置自定义列表
- 列表格式：`username/list_id` 或完整URL
- 多个列表用逗号分隔

**示例配置**:
```
justin/star-wars, https://trakt.tv/users/jasonbourne/lists/action-movies
```

---

## 集成示例

### Python 脚本调用

```python
import requests

# MoviePilot配置
base_url = "http://localhost:3000"
api_token = "YOUR_API_TOKEN"

# 触发同步
response = requests.post(
    f"{base_url}/api/v1/plugin/TraktSync/sync",
    params={"apikey": api_token}
)
print(response.json())

# 触发同步并下载
response = requests.post(
    f"{base_url}/api/v1/plugin/TraktSync/sync_download",
    params={"apikey": api_token}
)
print(response.json())

# 触发自定义列表同步
response = requests.post(
    f"{base_url}/api/v1/plugin/TraktSync/sync_custom_lists",
    params={"apikey": api_token}
)
print(response.json())
```

### Bash脚本调用

```bash
#!/bin/bash

BASE_URL="http://localhost:3000"
API_TOKEN="YOUR_API_TOKEN"

# 触发同步
curl -X POST "${BASE_URL}/api/v1/plugin/TraktSync/sync?apikey=${API_TOKEN}"

# 触发同步并下载
curl -X POST "${BASE_URL}/api/v1/plugin/TraktSync/sync_download?apikey=${API_TOKEN}"

# 触发自定义列表同步
curl -X POST "${BASE_URL}/api/v1/plugin/TraktSync/sync_custom_lists?apikey=${API_TOKEN}"
```

### 工作流配置示例

```yaml
# 示例1：每天凌晨2点同步Trakt想看
workflow:
  name: "每日Trakt同步"
  trigger:
    type: "cron"
    cron: "0 2 * * *"
  actions:
    - plugin: "TraktSync"
      action: "trakt_sync"

# 示例2：每周日晚上8点同步自定义列表
workflow:
  name: "每周Trakt列表同步"
  trigger:
    type: "cron"
    cron: "0 20 * * 0"
  actions:
    - plugin: "TraktSync"
      action: "trakt_sync_custom_lists"
```

---

## 更新历史

| 版本 | 日期 | 说明 |
|------|------|------|
| 1.0 | 2024-02-15 | 初始版本 |
| 1.1 | 2026-02-15 | 新增插件API端点文档；新增远程命令说明 |
| 1.2 | 2026-02-15 | 新增同步API端点；新增工作流动作注册；新增集成示例 |
| 1.3 | 2026-02-15 | 新增Trakt自定义列表API；新增自定义列表同步功能；新增工作流动作和远程命令 |
