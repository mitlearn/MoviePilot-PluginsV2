# TraktSync 插件使用说明

## 插件简介

TraktSync 是为 MoviePilot 开发的 Trakt.tv 想看列表同步插件。它可以自动从 Trakt.tv 同步你的想看电影和剧集，并自动添加到 MoviePilot 订阅列表。

### 主要功能

- ✅ 同步 Trakt Watchlist 电影和剧集
- ✅ 同步 Trakt 自定义列表（Custom Lists）
- ✅ OAuth自动授权（可选，配置域名后免手动操作）
- ✅ 远程命令提交授权码（Token失效时快速更新）
- ✅ 自动识别 TMDB 媒体信息
- ✅ 自动去重（检查媒体库和订阅列表）
- ✅ 支持定时自动同步（Cron）
- ✅ 支持远程命令和工作流触发
- ✅ 详情页展示同步历史记录
- ✅ 订阅状态控制（激活/暂停）
- ✅ 系统通知支持
- ✅ 可选使用系统代理

---

## 安装方式

### 方式一：从插件市场安装（推荐）

1. 进入 MoviePilot 管理界面
2. 导航到 **插件** → **插件市场**
3. 搜索 "TraktSync" 或 "Trakt想看"
4. 点击 **安装**

### 方式二：手动安装

1. 将 `traktsync` 目录复制到 MoviePilot 插件目录：
   ```bash
   cp -r traktsync /path/to/MoviePilot/app/plugins/
   ```

2. 重启 MoviePilot：
   ```bash
   # Docker 环境
   docker restart moviepilot

   # 源码环境
   # 如果开启了插件热重载，会自动加载
   ```

3. 在插件页面应该能看到 "Trakt想看" 插件

---

## 配置步骤

### 第一步：创建 Trakt 应用

1. 访问 [Trakt OAuth Applications](https://trakt.tv/oauth/applications/new)
2. 登录你的 Trakt 账号
3. 填写应用信息：
   - **Name**: `MoviePilot TraktSync`（或任意名称）
   - **Description**: `MoviePilot Trakt想看同步插件`
   - **Redirect URI**:
     - **自动授权模式**（推荐）：`http(s)://your-domain.com/api/v1/plugin/traktsync/auth`
       - 需要填写你的MoviePilot访问域名
       - 例如：`https://moviepilot.example.com/api/v1/plugin/traktsync/auth`
     - **手动授权模式**：`urn:ietf:wg:oauth:2.0:oob`
       - 用于内网环境或无域名时
   - **Permissions**: 勾选需要的权限（至少勾选读取 Watchlist）
4. 点击 **CREATE APP**
5. 保存以下信息：
   - **Client ID**
   - **Client Secret**

> [!TIP]
> 如果你的MoviePilot有公网域名，强烈推荐使用自动授权模式，授权过程更加便捷！

### 第二步：获取 Refresh Token

#### 方法一：自动授权（最简单，推荐）

**前提条件**：
- 已在插件配置中填写 **MoviePilot访问域名**
- 域名可从外网访问
- Trakt应用的Redirect URI使用了域名格式

**步骤**：

1. 在插件配置中填写以下信息：
   - **Client ID** 和 **Client Secret**（第一步获取）
   - **MoviePilot访问域名**（如：`https://moviepilot.example.com`）

2. **保存配置**后，查看 MoviePilot 日志（设置 → 系统 → 实时日志）

3. 日志中会输出授权链接，类似：
   ```log
   ================================================================================
   请访问以下链接进行授权（配置了域名，将自动完成授权）:
   https://trakt.tv/oauth/authorize?response_type=code&client_id=YOUR_CLIENT_ID&redirect_uri=https://moviepilot.example.com/api/v1/plugin/traktsync/auth
   授权后会自动跳转完成，无需手动操作
   ================================================================================
   ```

4. 复制链接在浏览器中访问，登录并授权

5. 授权成功后会自动完成，显示成功页面

6. 插件会收到授权并自动保存Token，无需任何手动操作

> [!TIP]
> 这是最简单便捷的方法，一键完成授权，无需复制粘贴任何代码！

#### 方法二：手动授权（传统方式）

**适用场景**：
- 未配置MoviePilot访问域名
- 内网环境，无法从外网访问

**步骤**：

1. 在插件配置中填写 **Client ID** 和 **Client Secret**

2. **保存配置**后，查看 MoviePilot 日志

3. 日志中会输出授权链接：
   ```log
   ================================================================================
   请访问以下链接进行授权:
   https://trakt.tv/oauth/authorize?response_type=code&client_id=YOUR_CLIENT_ID&redirect_uri=urn:ietf:wg:oauth:2.0:oob
   授权后，将获得的授权码填入配置页面的【授权码】字段，或使用 /trakt_code 命令提交
   ================================================================================
   ```

4. 复制链接在浏览器中访问，登录并授权

5. 授权后会显示一个 **Authorization Code**（类似：`abc123def456...`）

6. 提交授权码（任选一种方式）：
   - **方式A**：复制授权码，填入插件配置页面的 **【授权码】** 字段，保存
   - **方式B**：使用远程命令 `/trakt_code 授权码`（推荐，更快捷）

7. 日志中会显示 `Token获取成功！`，授权完成

#### 方法二：使用浏览器手动获取

1. 将以下 URL 中的 `YOUR_CLIENT_ID` 替换为你的 Client ID，然后在浏览器中访问：
   ```
   https://trakt.tv/oauth/authorize?response_type=code&client_id=YOUR_CLIENT_ID&redirect_uri=urn:ietf:wg:oauth:2.0:oob
   ```

2. 授权后会显示一个 **Authorization Code**（类似：`abc123def456...`），复制这个代码

3. 使用以下 cURL 命令获取 Refresh Token（替换其中的值）：
   ```bash
   curl -X POST "https://api.trakt.tv/oauth/token" \
     -H "Content-Type: application/json" \
     -d '{
       "code": "YOUR_AUTHORIZATION_CODE",
       "client_id": "YOUR_CLIENT_ID",
       "client_secret": "YOUR_CLIENT_SECRET",
       "redirect_uri": "urn:ietf:wg:oauth:2.0:oob",
       "grant_type": "authorization_code"
     }'
   ```

4. 响应中的 `refresh_token` 字段就是你需要的 Refresh Token

#### 方法三：使用 Python 脚本获取

创建文件 `get_trakt_token.py`:

```python
import requests

CLIENT_ID = "你的Client ID"
CLIENT_SECRET = "你的Client Secret"

# Step 1: 获取授权链接
auth_url = f"https://trakt.tv/oauth/authorize?response_type=code&client_id={CLIENT_ID}&redirect_uri=urn:ietf:wg:oauth:2.0:oob"
print(f"请访问以下链接并授权:\n{auth_url}\n")

# Step 2: 输入授权码
auth_code = input("请输入授权码: ").strip()

# Step 3: 获取 Token
response = requests.post(
    "https://api.trakt.tv/oauth/token",
    json={
        "code": auth_code,
        "client_id": CLIENT_ID,
        "client_secret": CLIENT_SECRET,
        "redirect_uri": "urn:ietf:wg:oauth:2.0:oob",
        "grant_type": "authorization_code"
    }
)

if response.status_code == 200:
    data = response.json()
    print("\n获取成功！")
    print(f"Access Token: {data['access_token']}")
    print(f"Refresh Token: {data['refresh_token']}")
    print(f"\n请将 Refresh Token 填入插件配置")
else:
    print(f"获取失败: {response.status_code}")
    print(response.text)
```

运行脚本：
```bash
python get_trakt_token.py
```

### 第三步：配置插件

1. 进入 MoviePilot 管理界面
2. 导航到 **插件** → **已安装插件**
3. 找到 **Trakt想看** 插件，点击 **设置**
4. 填写以下配置：

#### 基础设置

| 配置项 | 说明 | 必填 |
|--------|------|------|
| **启用插件** | 是否启用插件 | 是 |
| **发送通知** | 同步完成后是否发送通知 | 否 |
| **立即运行一次** | 保存配置后立即执行一次同步 | 否 |

#### 同步设置

| 配置项 | 说明 | 必填 |
|--------|------|------|
| **同步周期** | Cron 表达式，留空则默认每天 8:00 执行 | 否 |
| **Watchlist同步类型** | 选择同步类型：全部、仅电影、仅剧集（整剧+单季）、仅整剧、仅单季（⚠️ 仅对 Watchlist 生效） | 否 |
| **添加启用的订阅** | 开启后添加的订阅为激活状态(N)，MoviePilot会自动搜索下载；关闭后为暂停状态(S)，不会触发搜索 | 否 |
| **自定义列表** | Trakt自定义列表，格式：username/list_id 或 URL，多个用逗号分隔（⚠️ 全同步，不受Watchlist同步类型限制） | 否 |

#### Trakt 配置

| 配置项 | 说明 | 必填 |
|--------|------|------|
| **使用代理** | 是否使用系统代理访问 Trakt API | 否 |
| **Client ID** | 第一步获取的 Client ID | 是 |
| **Client Secret** | 第一步获取的 Client Secret | 是 |
| **授权码** | 授权后获取的 Authorization Code，填写后自动获取 Token（手动授权方式） | 否 |
| **Refresh Token** | 通过授权码自动获取，或手动填写 | 是 |
| **MoviePilot访问域名** | 填写后可实现自动授权，免去手动填写授权码的步骤（如：`https://moviepilot.example.com`） | 否 |

5. 点击 **保存**

### 第四步：测试同步

勾选 **立即运行一次** 并保存，或使用远程命令 `/trakt_sync` 测试同步。

---

## 配置项详解

### 执行周期（Cron）

支持标准的 5 位 Cron 表达式：

| 表达式 | 说明 |
|--------|------|
| `0 8 * * *` | 每天早上 8:00 执行（默认） |
| `0 */6 * * *` | 每 6 小时执行一次 |
| `0 0 * * 0` | 每周日凌晨执行 |
| `*/30 * * * *` | 每 30 分钟执行一次 |

留空则默认每天执行一次。

---

## 远程命令

插件注册了三个远程命令，可以通过聊天工具（Telegram、微信等）或 MoviePilot 命令行触发：

### `/trakt_sync`

**功能**: 立即同步 Trakt 想看列表（Watchlist）

**行为**:
- 同步 Watchlist 电影和剧集
- 如果配置了自定义列表，也会一起同步
- 根据"添加启用的订阅"配置决定订阅状态

**示例**:
```
/trakt_sync
```

### `/trakt_code <授权码>`

**功能**: 提交Trakt授权码以更新Token

**行为**:
- 接收授权码并自动获取Token
- 更新并保存Access Token和Refresh Token
- 发送授权结果通知

**使用场景**:
- Token失效时快速更新授权
- 手动授权模式（未配置域名）
- 收到Token失效通知后重新授权

**示例**:
```
/trakt_code abc123def456ghi789
```

**使用流程**:
1. Token失效时会收到通知，包含授权链接
2. 访问链接并授权，获取授权码
3. 使用 `/trakt_code 授权码` 提交
4. 系统自动完成Token更新

> [!TIP]
> 相比在配置页面填写授权码，使用命令方式更快捷，无需打开网页！

---

## 工作流支持

插件支持作为工作流动作使用，可以在特定条件下触发同步：

### 工作流动作

| 动作名称 | 功能 | 说明 |
|---------|------|------|
| **同步Trakt想看** | 同步 Watchlist 和自定义列表 | 根据"添加启用的订阅"配置决定订阅状态 |
| **同步Trakt自定义列表** | 仅同步自定义列表 | 根据"添加启用的订阅"配置决定订阅状态 |

### 使用示例

在 MoviePilot 工作流编辑器中：

1. 创建新工作流或编辑现有工作流
2. 添加触发条件（如：定时触发、事件触发等）
3. 添加动作 → 选择 **TraktSync** 插件
4. 选择需要的动作类型
5. 保存并启用工作流

### API 端点

插件还提供了 HTTP API 端点，可以通过 POST 请求触发：

```bash
# 同步 Watchlist（根据配置决定订阅状态）
curl -X POST "http://your-moviepilot/api/v1/plugin/TraktSync/sync" \
  -H "Content-Type: application/json" \
  -d '{"apikey": "your_api_key"}'

# 同步自定义列表（根据配置决定订阅状态）
curl -X POST "http://your-moviepilot/api/v1/plugin/TraktSync/sync_custom_lists" \
  -H "Content-Type: application/json" \
  -d '{"apikey": "your_api_key"}'
```

详细的 API 文档请参考 [API_Document.md](API_Document.md)。

---

## 自定义列表功能

### 配置格式

自定义列表支持两种配置格式：

#### 格式一：username/list_id

```
username/my-favorite-movies
```

#### 格式二：完整 URL

```
https://trakt.tv/users/username/lists/my-favorite-movies
```

#### 多个列表

使用逗号分隔多个列表：

```
username/list1,username/list2,https://trakt.tv/users/username/lists/list3
```

### 如何获取列表信息

1. 访问你的 Trakt.tv 个人主页
2. 进入 **Lists** 标签页
3. 选择要同步的列表
4. 查看 URL，格式为：`https://trakt.tv/users/{username}/lists/{list_id}`
5. 复制 URL 或提取 `username/list_id` 填入插件配置

### 同步行为

- 自定义列表会与 Watchlist 一起同步（使用 `/trakt_sync` 或定时任务时）
- 可以单独同步自定义列表（使用工作流动作"同步Trakt自定义列表"或 API 端点）
- **⚠️ 重要**：自定义列表是全同步（电影+剧集），不受"Watchlist同步类型"配置限制
- 自定义列表的项目在详情页会显示列表名称，而不是"电影"或"电视剧"

### 使用场景

- **分类管理**: 创建不同主题的列表（如：科幻电影、经典剧集）
- **共享列表**: 同步其他用户公开的列表
- **推荐收藏**: 从网上找到的 Trakt 推荐列表
- **临时关注**: 某些特定主题的临时列表

---

## 同步逻辑说明

### 同步流程

```
1. 同步 Watchlist（受"Watchlist同步类型"配置限制）
   ├─ 同步电影（如果Watchlist同步类型=全部/仅电影）
   ├─ 同步整剧（如果Watchlist同步类型=全部/仅剧集/仅整剧）
   └─ 同步单季（如果Watchlist同步类型=全部/仅剧集/仅单季）
2. 同步自定义列表（如果配置）
   ├─ 解析列表配置（支持 username/list_id 或 URL）
   ├─ 获取列表内容
   ├─ 全同步电影和剧集（⚠️ 不受"Watchlist同步类型"限制）
   └─ 记录来源为列表名称
3. 保存同步历史
4. 发送通知（如果启用）
```

### 去重机制

插件会自动检查以下情况，避免重复：

1. **媒体库已存在**: 通过 TMDB ID 检查媒体服务器（Plex/Emby/Jellyfin）
2. **已在订阅列表**: 检查 MoviePilot 订阅数据库（包含激活、暂停等所有状态）
3. **已在同步历史**: 检查本次同步是否已处理过该 TMDB ID

满足以上任一条件，将跳过该媒体。

> [!NOTE]
> 对于单季剧集，订阅检测会精确到具体季号，不同季可以独立订阅。

### 订阅状态说明

- **添加启用的订阅=开启**: 新添加的订阅状态为 N（激活），MoviePilot 会自动搜索下载
- **添加启用的订阅=关闭**: 新添加的订阅状态为 S（暂停），不会触发自动搜索

> [!IMPORTANT]
> 此开关**仅影响本次新添加的订阅**，不会修改已有订阅的状态。若某媒体已有订阅（包括暂停状态），插件会跳过，不做任何修改。

### 通知内容

同步完成后，如果启用了通知，会发送包含以下信息的通知：

- 新增电影数量
- 新增剧集数量
- 已存在数量
- 错误数量

---

## ❓ 常见问题

<details>
<summary><b>Q: Token 过期怎么办？</b></summary>

**A**: 插件会自动刷新 Access Token。Token失效时会收到通知。

**方式一：自动授权（推荐，如果配置了域名）**
1. 收到Token失效通知
2. 点击通知中的授权链接
3. 授权后自动完成，无需任何操作

**方式二：使用命令更新（快捷）**
1. 收到Token失效通知，包含授权链接
2. 访问链接并授权，复制授权码
3. 使用命令：`/trakt_code 授权码`

**方式三：配置页面更新（传统）**
1. 访问授权链接获取授权码
2. 在插件配置页面填入授权码
3. 保存配置自动更新Token
</details>

<details>
<summary><b>Q: 自动授权和手动授权有什么区别？</b></summary>

**A**: 两种授权方式的区别在于是否需要手动复制粘贴授权码。

| 授权方式 | 需要域名 | 操作步骤 | 推荐度 |
|---------|---------|---------|--------|
| **自动授权** | 是 | 点击链接 → 授权 → 完成 | ⭐⭐⭐⭐⭐ |
| **手动授权** | 否 | 点击链接 → 授权 → 复制码 → 提交 | ⭐⭐⭐ |

**自动授权优势**:
- 一键完成，无需复制粘贴
- Token失效时重新授权更快捷
- 更好的用户体验

**手动授权适用**:
- 内网环境，无公网域名
- 不想暴露MoviePilot地址
- 临时测试使用
</details>

<details>
<summary><b>Q: 如何配置自动授权？</b></summary>

**A**: 配置自动授权需要3个步骤：

1. **配置MoviePilot访问域名**
   - 在插件Trakt配置中填写：`https://moviepilot.example.com`
   - 必须是可从外网访问的域名

2. **配置Trakt应用Redirect URI**
   - 访问 [Trakt应用设置](https://trakt.tv/oauth/applications)
   - Redirect URI填写：`https://moviepilot.example.com/api/v1/plugin/traktsync/auth`
   - 保存应用设置

3. **完成授权**
   - 保存插件配置，查看日志中的授权链接
   - 访问链接授权，自动完成

**注意事项**:
- 域名必须与Trakt应用配置完全一致
- 支持HTTP和HTTPS
- 内网IP地址不能使用自动授权
</details>

<details>
<summary><b>Q: 同步失败，日志显示 401 错误</b></summary>

**A**: 检查以下几点：
1. Refresh Token 是否正确
2. Client ID 和 Client Secret 是否匹配
3. Trakt 应用权限是否足够
4. 尝试重新获取 Refresh Token
</details>

<details>
<summary><b>Q: 同步了但没有添加订阅</b></summary>

**A**: 可能原因：
1. 媒体库已存在该媒体
2. 已在订阅列表中（包括暂停状态的订阅）
3. TMDB ID 缺失
4. 媒体识别失败

**排查步骤**:
1. 将 MoviePilot 日志等级调整为 **DEBUG**
2. 重新触发同步，搜索关键词 "处理电影" 或 "处理单季"
3. 查看是否有 "已存在" 或 "已在订阅中，跳过" 的提示
4. 确认 Trakt Watchlist 中的媒体有正确的 TMDB ID

> [!NOTE]
> 若某媒体在订阅列表中处于暂停（S）状态，插件会将其视为"已订阅"而跳过，不会修改其状态。如需重新激活，请在 MoviePilot 订阅管理页面手动操作。
</details>

<details>
<summary><b>Q: 想要手动控制哪些媒体同步</b></summary>

**A**: 插件会同步 Trakt Watchlist 中的所有媒体。如果想控制，请在 Trakt.tv 上管理你的 Watchlist（添加/移除想看的媒体）。
</details>

<details>
<summary><b>Q: 自定义列表是什么？如何使用？</b></summary>

**A**: 自定义列表是 Trakt.tv 上用户创建的个人列表，可以按主题分类管理媒体。

**使用步骤**:
1. 在 Trakt.tv 上创建或找到想要同步的列表
2. 获取列表的 username/list_id 或完整 URL
3. 填入插件配置的"自定义列表"字段
4. 多个列表用逗号分隔

**示例**:
```
myusername/sci-fi-movies,myusername/classic-tv
```

或使用完整 URL：
```
https://trakt.tv/users/myusername/lists/sci-fi-movies
```
</details>

<details>
<summary><b>Q: 自定义列表何时同步？</b></summary>

**A**: 自定义列表的同步时机：

1. **定时任务**: 会与 Watchlist 一起自动同步
2. **`/trakt_sync` 命令**: 会同时同步 Watchlist 和自定义列表
3. **工作流动作"同步Trakt自定义列表"或 API 端点**: 仅同步自定义列表，不同步 Watchlist
4. **工作流动作**: 根据选择的动作类型决定

**⚠️ 重要**：自定义列表始终全同步（电影+剧集），不受"Watchlist同步类型"配置影响。
</details>

<details>
<summary><b>Q: "Watchlist同步类型"配置对自定义列表生效吗？</b></summary>

**A**: 不生效。"Watchlist同步类型"配置仅对 Watchlist 生效。

**说明**：
- **Watchlist**：受"Watchlist同步类型"控制，可以选择：
  - **全部**：同步电影、整剧、单季
  - **仅电影**：只同步电影
  - **仅剧集**：同步整剧和单季
  - **仅整剧**：只同步完整剧集（不含单季）
  - **仅单季**：只同步单独添加的季度
- **自定义列表**：始终全同步，会同步列表中的所有电影和剧集，不受"Watchlist同步类型"限制

**使用场景**：
- 如果你只想订阅电影，但有一个包含剧集的自定义列表，该列表中的剧集仍然会被同步
- 建议根据需求创建专门的电影列表或剧集列表
</details>

<details>
<summary><b>Q: 如何在详情页区分 Watchlist 和自定义列表？</b></summary>

**A**: 在插件详情页的同步历史中：
- Watchlist 的项目类型显示为"电影"或"电视剧"
- 自定义列表的项目类型显示为列表名称（如 "myusername/sci-fi-movies"）
</details>

<details>
<summary><b>Q: 支持同步已看记录吗？</b></summary>

**A**: 当前版本仅支持同步 Watchlist 和自定义列表，不支持同步观看记录。
</details>

<details>
<summary><b>Q: 如何使用代理访问 Trakt？</b></summary>

**A**: 插件提供了代理开关，可以选择是否使用系统代理。

**配置步骤**:
1. 进入 MoviePilot **设置 → 系统 → 网络**，配置代理服务器地址
2. 在插件 **Trakt配置** 标签页，开启"使用代理"开关
3. 保存后插件会使用系统代理访问 Trakt API

**注意**:
- 默认关闭代理（直连访问）
- 如果 Trakt 被墙或访问速度慢，建议开启代理
- 系统代理未配置时，开启开关无效
</details>

<details>
<summary><b>Q: 同步频率建议</b></summary>

**A**: 建议设置为每天同步一次（如 `0 8 * * *`）。过于频繁可能触发 Trakt API 限流。

**Trakt API 限制**:
- 开发版应用：1000 次/天
- 生产版应用：根据审核结果调整

如果经常触发限流，可以降低同步频率。
</details>

---

## 🛠️ 故障排除

### 重置插件

如果插件出现问题：

1. 在插件配置中禁用插件
2. 保存配置
3. 重新启用插件并重新配置
4. 启用"立即运行一次"重新同步

### 获取调试日志

**MoviePilot 日志**:
1. 进入 **设置 → 系统 → 日志等级**，选择 **DEBUG**
2. 保存并重启 MoviePilot
3. 复现问题后，进入 **设置 → 系统 → 实时日志**
4. 点击右上角 **新标签页打开**，搜索（Ctrl+F）关键词
5. 复制与问题相关的日志（包括前后上下文）

---

## 日志说明

插件运行时会输出详细日志，位置：`/config/logs/moviepilot.log`

### 关键日志示例

```log
[INFO] 开始同步Trakt想看列表...
[INFO] 正在刷新Trakt access token...
[INFO] Access token刷新成功，有效期至 2024-02-20T08:00:00+00:00
[INFO] 获取到 15 部Trakt想看电影
[INFO] 获取到 8 部Trakt想看剧集
[INFO] 添加订阅成功: The Dark Knight (2008) (激活)
[INFO] Trakt想看同步完成: 新增电影 10 部，新增剧集 3 部，已存在电影 5 部，已存在剧集 5 部，错误 0 个
```

> [!TIP]
> 每个条目的处理细节（已存在、已在订阅中、TMDB ID 等）记录在 **DEBUG** 级别。如需查看完整处理过程，请在 MoviePilot 中将日志等级调整为 DEBUG。

### 错误排查

| 日志关键词 | 等级 | 可能原因 | 解决方案 |
|-----------|------|---------|---------|
| `Token刷新失败` | ERROR | Refresh Token 无效或过期 | 重新获取 Refresh Token |
| `无法识别` | WARN | TMDB 数据库无该媒体 | 检查 TMDB ID 是否正确 |
| `添加订阅失败` | ERROR | 订阅链路异常 | 查看完整 DEBUG 日志 |
| `429` | ERROR | API 请求过于频繁 | 降低同步频率 |
| `缺少TMDB ID` | DEBUG | Trakt 数据不完整 | 在 Trakt.tv 上检查该媒体信息 |

---

## 技术细节

### 依赖的 MoviePilot 组件

- **SubscribeChain**: 订阅管理
- **DownloadChain**: 下载管理
- **SearchChain**: 资源搜索
- **MediaServerHelper**: 媒体服务器查询
- **RequestUtils**: HTTP 请求（自动使用系统代理）
- **EventManager**: 事件系统
- **SystemConfigOper**: 配置管理

### API 调用流程

#### Watchlist 同步流程
```
1. __refresh_access_token() → 刷新 Token
2. __get_watchlist_movies() → 获取电影列表
3. __get_watchlist_shows() → 获取剧集列表
4. recognize_media() → 识别媒体信息（每个项目）
5. __add_subscribe() → 添加订阅
```

#### 自定义列表同步流程
```
1. __refresh_access_token() → 刷新 Token
2. __parse_list_config() → 解析列表配置
3. __get_custom_list_items() → 获取列表内容
4. 根据项目类型（movie/show）调用相应同步方法
5. 处理逻辑同 Watchlist
```

---

## 开发与贡献

### 代码结构

```
traktsync/
├── __init__.py          # 插件主文件
├── API_Document.md      # API 文档
└── README.md            # 使用说明（本文件）
```

### 主要类和方法

| 方法 | 功能 |
|------|------|
| `init_plugin(config)` | 初始化插件配置 |
| `sync()` | 核心同步逻辑（Watchlist + 自定义列表） |
| `sync_custom_lists()` | 仅同步自定义列表 |
| `__refresh_access_token()` | 刷新 Access Token |
| `__make_trakt_api_call()` | 统一的 Trakt API 调用方法 |
| `__get_watchlist_movies()` | 获取电影 Watchlist |
| `__get_watchlist_shows()` | 获取剧集 Watchlist |
| `__get_custom_list_items()` | 获取自定义列表内容 |
| `__sync_media()` | 同步单个媒体（统一方法） |
| `__sync_movie()` | 同步单个电影（兼容方法） |
| `__sync_show()` | 同步单个剧集（兼容方法） |
| `__add_subscribe()` | 添加订阅 |
| `__parse_list_config()` | 解析列表配置（URL 或 username/list_id） |

---

## 🐛 问题反馈

### 遇到问题？

在提交 Issue 之前，请先尝试以下步骤：

1. **查看常见问题** - 检查上面的 [常见问题](#-常见问题) 章节
2. **查看故障排除** - 参考 [故障排除](#-故障排除) 部分
3. **查看 API 文档** - [Trakt API 文档](API_Document.md) 了解接口详情
4. **收集调试日志** - 按照 [获取调试日志](#获取调试日志) 步骤收集完整日志

### 提交 Issue

如果问题仍未解决，欢迎提交 Issue。我们提供了详细的模板帮助您快速报告问题：

**[🐛 提交 Bug 报告](https://github.com/mitlearn/MoviePilot-PluginsV2/issues/new?template=bug_report.yml)** | **[✨ 功能建议](https://github.com/mitlearn/MoviePilot-PluginsV2/issues/new?template=feature_request.yml)**

**提交时请：**
- 选择插件：**TraktSync**
- 提供版本信息（MoviePilot、插件）
- 描述详细的复现步骤
- 粘贴完整的 MoviePilot DEBUG 日志
- 附上配置截图（⚠️ 隐藏 Client Secret 和所有 Token）

> [!TIP]
> Issue 模板会引导您填写所有必要信息，这能帮助我们更快地定位和解决问题！

---

## 📖 更新日志

### v0.5.0 (2026-02-17) - 最新

- 🐛 **修复** `add_and_enable=True` 时订阅仍为暂停状态的问题：改用 `SubscribeOper().exists()` 进行订阅检测，该方法与 `SubscribeChain` 内部使用相同查找逻辑，不受订阅 state 影响
- 🐛 **修复** 单季订阅检测不精确：`__sync_season()` 现在按具体季号检测，避免已订阅 S1 导致 S2 被错误跳过
- 🧹 **清理** 移除从未使用的 `force_enable` 参数（存在于 5 个方法中但从未以 `True` 调用）
- 📝 **优化** 日志等级：逐条处理详情（已存在/已订阅/TMDB缺失）调整为 DEBUG；媒体识别失败降为 WARNING；保留关键操作为 INFO

---

### v0.5.0 (2026-02-16)

- ✅ **删除远程命令**：移除 `/trakt_custom_lists` 命令（功能已合并到 `/trakt_sync`）
- ✅ **新增远程命令**：`/trakt_code` 快速提交授权码更新Token
- ✅ **新增API端点**：`/auth` 接收Trakt OAuth授权回调
- ✅ **自动授权支持**：配置域名后实现一键授权，无需手动操作
- ✅ **Token失效通知优化**：提示用户使用 `/trakt_code` 命令或访问授权链接
- ✅ **配置项新增**：MoviePilot访问域名配置
- ✅ **授权流程优化**：支持自动授权和手动授权两种方式

### v0.4.0 (2024-02-16)

- ✅ 新增工作流动作：同步Trakt自定义列表
- ✅ 支持同步 Trakt 自定义列表（Custom Lists）
- ✅ 自定义列表与 Watchlist 统一同步
- ✅ 详情页区分显示来源（Watchlist 或列表名称）
- ✅ 新增 API 端点：同步自定义列表
- ✅ 代码优化：合并重复方法，减少约200行代码
- ✅ 新增代理开关：可选择是否使用系统代理

### v0.3.0 (2024-02-15)

- ✅ 新增详情页：展示同步历史记录
- ✅ 新增订阅状态控制：支持激活/暂停状态
- ✅ 订阅状态控制
- ✅ 操作类型优化：区分下载、添加、已存在

### v0.2.0 (2024-02-15)

- ✅ 新增详情页展示同步历史
- ✅ 增强订阅状态管理
- ✅ 支持删除历史记录

### v0.1.0 (2024-02-15)

- ✅ 初始版本发布
- ✅ 支持同步 Trakt Watchlist 电影和剧集
- ✅ 支持定时任务和远程命令
- ✅ 支持订阅状态控制
- ✅ 支持系统通知
- ✅ 支持 OAuth Token 自动刷新

---

<div align="center">

[返回主页](../../README.md) • [查看 API 文档](API_Document.md)

**享受自动化的影视追踪体验！**

</div>
