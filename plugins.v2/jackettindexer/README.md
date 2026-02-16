# Jackett 索引器插件

集成 Jackett 的所有已配置索引器到 MoviePilot，实现统一搜索管理。

## ✨ 功能特性

### 核心功能

- ✅ **自动同步索引器** - 自动从 Jackett 同步已启用的索引器
- ✅ **统一搜索接口** - 通过 MoviePilot 统一搜索所有索引器
- ✅ **IMDb ID 搜索** - 支持 IMDb ID 精确搜索（v1.2.0+）
- ✅ **站点分类支持** - 自动识别并添加电影/电视分类（v1.1.0+）
- ✅ **促销识别** - 自动识别免费、半价、双倍上传等促销
- ✅ **定时同步** - 支持 Cron 表达式定时同步索引器列表
- ✅ **代理支持** - 支持使用系统代理访问服务
- ✅ **API接口** - 提供HTTP API支持外部调用搜索功能（v1.5.0+）
- ✅ **远程命令** - 支持通过消息渠道远程搜索（v1.5.0+）
- ✅ **AI智能体工具** - 支持通过AI智能体自然语言搜索（v1.5.0+）

### 智能过滤

- **站点类型过滤**: 只索引私有和半公开站点，自动过滤公开站点
- **XXX内容过滤**: 自动屏蔽仅包含成人内容的索引器（配合官方要求）
- **英文关键词优化**: 自动过滤非英文搜索关键词（Jackett 对中文支持有限）

### 分类支持

> [!NOTE]
> 插件会自动从 Jackett 获取每个索引器支持的分类，并按 MoviePilot 标准格式转换。

**Torznab 分类映射**:
- `2000` 系列 → 电影分类
- `5000` 系列 → 电视分类

---

## 🚀 快速开始

### 前置要求

- [x] MoviePilot v2.x
- [x] Jackett v0.20+
- [x] Jackett 中已配置并启用至少一个索引器

### 安装插件

#### 方法一：通过插件市场安装（推荐）

1. 在 MoviePilot 中打开 **设置 → 插件 → 插件市场**
2. 点击右上角齿轮图标，添加仓库地址：
   ```
   https://github.com/mitlearn/MoviePilot-PluginsV2
   ```
3. 点击更新按钮，在插件列表中找到 **Jackett索引器** 并安装

#### 方法二：手动安装

1. 下载插件文件：
   ```bash
   git clone https://github.com/mitlearn/MoviePilot-PluginsV2.git
   cd MoviePilot-PluginsV2
   ```

2. 复制到 MoviePilot 插件目录：
   ```bash
   cp -r plugins.v2/jackettindexer /path/to/moviepilot/plugins/
   ```

3. 重启 MoviePilot

---

## ⚙️ 配置说明

### 第一步：获取 Jackett API 密钥

1. 登录 Jackett Web 界面
2. 在页面右上角可以直接看到 **API Key** 输入框
3. 点击旁边的 **复制** 按钮复制 API 密钥

> [!TIP]
> Jackett 的 API 密钥就在首页顶部，非常容易找到！

### 第二步：配置插件

1. 在 MoviePilot 中打开 **设置 → 插件 → Jackett索引器**
2. 填写配置信息：

| 配置项 | 说明 | 示例 | 必填 |
|--------|------|------|:----:|
| **启用插件** | 开启插件功能 | ✅ | ✅ |
| **服务器地址** | Jackett 服务器地址（必须包含 http:// 或 https://） | `http://192.168.1.100:9117` | ✅ |
| **API密钥** | 在 Jackett 首页获取的 API 密钥 | `abcdef123456...` | ✅ |
| **同步周期** | Cron 表达式，设置定时同步频率 | `0 0 */12 * *` (每12小时) | ❌ |
| **使用代理** | 访问 Jackett 时是否使用系统代理 | ❌ | ❌ |
| **立即运行一次** | 保存后立即同步索引器列表 | ✅ | ❌ |

3. 点击 **保存**

> [!TIP]
> **服务器地址示例**:
> - 本地部署：`http://localhost:9117`
> - 局域网：`http://192.168.1.100:9117`
> - Docker 内网：`http://jackett:9117`
> - 公网：`https://jackett.example.com`

### 第三步：添加站点到站点管理

> [!IMPORTANT]
> **必须执行此步骤**，否则插件无法参与搜索！

1. 打开 **设置 → 插件 → Jackett索引器**，查看插件详情页
2. 在索引器列表中，找到每个站点的 **domain**（如 `jackett_indexer.mteamtp`）
3. 打开 **设置 → 站点管理 → 添加站点**
4. 将 domain 填入 **站点地址** 字段
5. 其他字段可以留空或随意填写（插件会忽略这些字段）
6. 点击 **保存**
7. 重复以上步骤，为每个索引器添加站点

**示例**：

| 插件详情页 | 站点管理 |
|-----------|---------|
| 索引器名称：`Jackett索引器-M-Team - TP`<br>站点domain：`jackett_indexer.mteamtp` | 站点地址：`jackett_indexer.mteamtp`<br>站点名称：`Jackett索引器-M-Team - TP`（可选）<br>Cookie/UA：留空 |

> [!TIP]
> **批量添加技巧**：
> - 插件详情页的表格可以直接复制 domain
> - 或者编写脚本通过 MoviePilot API 自动添加

### 第四步：测试搜索

1. 在 MoviePilot 搜索框输入英文关键词（如 `The Matrix`）
2. 查看搜索结果中是否包含 Jackett 索引器的资源
3. 检查日志：
   ```log
   【Jackett索引器】开始检索站点：Jackett索引器-M-Team - TP
   【Jackett索引器】搜索完成：从 125 条原始结果中解析出 120 个有效结果
   ```

---

## 📝 配置详解

### 同步周期

| 表达式 | 说明 |
|--------|------|
| `0 0 */12 * *` | 每12小时同步一次（推荐） |
| `0 2 * * *` | 每天凌晨2点同步一次 |
| `0 2 */3 * *` | 每3天凌晨2点同步一次 |
| `0 2 1 * *` | 每月1日凌晨2点同步一次 |

> [!TIP]
> 索引器变化不频繁，建议设置较长的同步周期（如每天或每3天），避免不必要的 API 请求。

### 代理设置

- 当 MoviePilot 需要通过代理才能访问 Jackett 时启用
- 使用 MoviePilot 系统设置中配置的代理服务器
- 如果 Jackett 在本地网络，通常不需要代理

**配置代理**:
1. 进入 MoviePilot **设置 → 系统 → 网络**
2. 配置代理服务器地址
3. 在插件配置中勾选 **使用代理**

### 立即运行一次

- 启用后会在保存配置时立即同步索引器
- 同步完成后会自动关闭该选项
- 用于快速验证配置是否正确

---

## ❓ 常见问题

<details>
<summary><b>Q: 为什么站点管理中的"测试连接"显示失败？</b></summary>

> [!NOTE]
> 这是已知限制。插件使用虚拟域名（如 `jackett_indexer.mteamtp`）注册站点，MoviePilot 的站点测试会尝试 DNS 解析这些域名，因此可能失败。

**错误示例**:
```
请求失败: Failed to resolve 'jackett_indexer.mteamtp'
```

**解决方案**:
- **忽略该错误** - 不影响搜索功能
- 站点连通性通过 Jackett 本身的测试功能验证
- 在 Jackett 管理界面中查看索引器状态
- 实际搜索测试：如果能搜索到结果，说明站点工作正常
</details>

<details>
<summary><b>Q: 提示"未搜索到数据"但实际有搜索结果？</b></summary>

**问题现象**:
```
【WARNING】Jackett索引器-FileList 未搜索到数据，耗时 0 秒
【INFO】站点搜索完成，有效资源数：89
```

**原因**: MoviePilot 在统计搜索结果时可能未正确识别部分插件返回的数据。

**解决方案**:
- 如果搜索结果页面能看到资源，**忽略该警告**
- 查看日志中"站点搜索完成"的资源数，确认是否真的有结果
- 如果确实搜索不到结果：
  - 检查搜索关键词是否为英文
  - 检查 Jackett 中对应索引器是否已启用且正常工作
  - 在 Jackett 中直接搜索测试
</details>

<details>
<summary><b>Q: 为什么搜索中文关键词没有结果？</b></summary>

**A**: Jackett 对中文关键词支持有限，插件会自动过滤非英文关键词。

**解决方案**:
- 使用英文关键词搜索（如 `The Matrix` 而不是 `黑客帝国`）
- MoviePilot 的识别功能会自动将中文标题转换为英文后搜索
</details>

<details>
<summary><b>Q: 如何知道哪些索引器被过滤了？</b></summary>

**A**: 查看 MoviePilot 日志，搜索关键词 "过滤"：

```bash
grep "过滤" logs/moviepilot.log
```

日志示例：
```
【Jackett索引器】过滤公开站点：RARBG
【Jackett索引器】过滤仅XXX分类站点：AdultSite
```
</details>

<details>
<summary><b>Q: 可以同时使用 Prowlarr 和 Jackett 插件吗？</b></summary>

**A**: 可以！两个插件完全独立，可以同时启用。每个插件会注册自己的索引器，不会冲突。
</details>

<details>
<summary><b>Q: 为什么有些索引器没有显示分类信息？</b></summary>

**A**: 可能的原因：
- 索引器没有配置 Torznab 分类
- API 请求超时（默认 15 秒）
- 索引器仅支持成人内容分类，已被过滤

查看日志可以看到详细原因。
</details>

<details>
<summary><b>Q: 插件会影响搜索速度吗？</b></summary>

**A**:
- **初次同步**: 每个索引器约 0.5-1 秒（需要获取分类信息）
- **搜索**: 与直接使用 Jackett API 速度相同
- **分类信息**: 仅在注册时获取一次，后续搜索不受影响
</details>

---

## 🛠️ 故障排除

### 常见错误

| 错误信息 | 解决方法 |
|---------|---------|
| `配置错误：缺少服务器地址或API密钥` | 检查服务器地址和 API 密钥是否正确填写 |
| `配置错误：服务器地址必须以 http:// 或 https:// 开头` | 在服务器地址前添加 `http://` 或 `https://` |
| `API请求失败：无响应` | 检查网络连接、服务器地址、防火墙设置 |
| `API请求失败：HTTP 401` | API 密钥错误，重新获取并填写 |
| `未获取到索引器列表` | 在 Jackett 中配置并启用索引器 |

### 重置插件

如果插件出现问题：

1. 在插件配置中禁用插件
2. 保存配置
3. 重新启用插件并重新配置
4. 启用"立即运行一次"重新同步

### 查看日志

插件会在 MoviePilot 日志中记录运行信息：

```log
【Jackett索引器】成功获取 12 个索引器（私有+半公开），过滤掉 2 个公开站点，1 个XXX专属站点
【Jackett索引器】开始检索站点：Jackett索引器-M-Team - TP，关键词：The Matrix
【Jackett索引器】搜索完成：Jackett索引器-M-Team - TP 从 125 条原始结果中解析出 120 个有效结果
```

### 获取调试日志

**MoviePilot 日志**:
1. 进入 **设置 → 系统 → 日志等级**，选择 **DEBUG**
2. 保存并重启 MoviePilot
3. 复现问题后，进入 **设置 → 系统 → 实时日志**
4. 点击右上角 **新标签页打开**，搜索（Ctrl+F）关键词
5. 复制与问题相关的日志（包括前后上下文）

**Jackett 日志**:
1. 勾选 **Enhanced logging** 并保存
2. 点击 **View logs** 查看日志

---

## 📖 API 文档

Jackett 和 Prowlarr 使用 Torznab 协议进行通信。详细的 API 文档请查看：

**[Prowlarr/Jackett API 文档](../prowlarrindexer/API%20Documents.md)**

包含：
- Torznab 协议说明
- API 端点详解
- 请求和响应格式
- 分类映射规则
- 错误码说明

---

## 🐛 问题反馈

### 遇到问题？

在提交 Issue 之前，请先尝试以下步骤：

1. **查看常见问题** - 检查上面的 [常见问题](#-常见问题) 章节
2. **查看故障排除** - 参考 [故障排除](#-故障排除) 部分
3. **收集调试日志** - 按照 [获取调试日志](#获取调试日志) 步骤收集完整日志

### 提交 Issue

如果问题仍未解决，欢迎提交 Issue。我们提供了详细的模板帮助您快速报告问题：

**[🐛 提交 Bug 报告](https://github.com/mitlearn/MoviePilot-PluginsV2/issues/new?template=bug_report.yml)** | **[✨ 功能建议](https://github.com/mitlearn/MoviePilot-PluginsV2/issues/new?template=feature_request.yml)**

**提交时请：**
- 选择插件：**Jackett索引器**
- 提供版本信息（MoviePilot、Jackett、插件）
- 描述详细的复现步骤
- 粘贴完整的日志（MoviePilot DEBUG + Jackett Enhanced）
- 附上配置截图（隐藏敏感信息）

> [!TIP]
> Issue 模板会引导您填写所有必要信息，这能帮助我们更快地定位和解决问题！

---

<div align="center">

[返回主页](../../README.md) • [查看 API 文档](../prowlarrindexer/API%20Documents.md)

</div>
