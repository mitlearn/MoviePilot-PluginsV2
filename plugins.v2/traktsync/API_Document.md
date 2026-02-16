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

## 更新历史

| 版本 | 日期 | 说明 |
|------|------|------|
| 1.0 | 2024-02-15 | 初始版本 |
