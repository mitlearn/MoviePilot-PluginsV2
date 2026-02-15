# Prowlarr/Jackett Indexer Plugins for MoviePilot

<div align="center">

![Version](https://img.shields.io/badge/version-1.1.0-blue.svg)
![MoviePilot](https://img.shields.io/badge/MoviePilot-v1.x%2B-green.svg)
![Python](https://img.shields.io/badge/python-3.10%2B-blue.svg)
![License](https://img.shields.io/badge/license-MIT-green.svg)

**为 MoviePilot 提供 Prowlarr 和 Jackett 索引器集成**

[功能特性](#-功能特性) •
[快速开始](#-快速开始) •
[配置说明](#-配置说明) •
[常见问题](#-常见问题) •
[API 文档](API%20Documents.md)

</div>

---

## 📖 简介

> [!IMPORTANT]
> 如你所见，本项目由 AI Coding 而成，如有问题请详细提起 Issues。若 AI 能修就能，不能则请忍住。

本项目提供两个 MoviePilot 插件，用于集成 Prowlarr 和 Jackett 索引器服务：

- **Prowlarr索引器**: 集成 Prowlarr 的所有已配置索引器
- **Jackett索引器**: 集成 Jackett 的所有已配置索引器

通过这些插件，您可以在 MoviePilot 中统一管理和搜索来自 Prowlarr/Jackett 的所有索引站点，无需手动逐个添加站点。

## ✨ 功能特性

### 核心功能

- ✅ **自动同步索引器** - 自动从 Prowlarr/Jackett 同步已启用的索引器
- ✅ **统一搜索接口** - 通过 MoviePilot 统一搜索所有索引器
- ✅ **站点分类支持** - 自动识别并添加电影/电视分类（v1.1.0+）
- ✅ **促销识别** - 自动识别免费、半价、双倍上传等促销
- ✅ **定时同步** - 支持 Cron 表达式定时同步索引器列表
- ✅ **代理支持** - 支持使用系统代理访问服务

### 智能过滤

- **站点类型过滤**: 只索引私有和半公开站点，自动过滤公开站点
- **XXX内容过滤**: 自动屏蔽仅包含成人内容的索引器
- **英文关键词优化**: 自动过滤非英文搜索关键词（Prowlarr/Jackett 对中文支持有限）

### 分类支持 (v1.1.0)

> [!NOTE]
> 插件会自动从 Prowlarr/Jackett 获取每个索引器支持的分类，并按 MoviePilot 标准格式转换。

**Torznab 分类映射**:
- `2000` 系列 → 电影分类
- `5000` 系列 → 电视分类
- `6000` 系列 → 自动过滤（成人内容）

## 🚀 快速开始

### 前置要求

- [x] MoviePilot v1.x 或更高版本
- [x] Prowlarr v1.0+ 或 Jackett v0.20+（至少其中之一）
- [x] Python 3.10+

### 安装方法

#### 方法一：通过插件市场安装（推荐）

1. 在 MoviePilot 中打开 **设置 → 插件 → 插件市场**
2. 点击右上角齿轮图标，添加本仓库地址：
   ```
   https://github.com/YOUR_USERNAME/prowalarr.git
   ```
3. 点击更新按钮，在插件列表中找到并安装插件

#### 方法二：手动安装

1. 克隆本仓库：
   ```bash
   git clone https://github.com/YOUR_USERNAME/prowalarr.git
   ```

2. 复制插件文件到 MoviePilot 插件目录：
   ```bash
   # Prowlarr 插件
   cp -r plugins.v2/prowlarrindexer /path/to/moviepilot/plugins/

   # Jackett 插件
   cp -r plugins.v2/jackettindexer /path/to/moviepilot/plugins/
   ```

3. 重启 MoviePilot

### 首次配置

#### Prowlarr索引器

1. 在 MoviePilot 中打开 **设置 → 插件 → Prowlarr索引器**
2. 填写配置信息：

| 配置项 | 说明 | 示例 |
|--------|------|------|
| 启用插件 | 开启插件功能 | ✅ |
| 服务器地址 | Prowlarr 服务器地址（必须包含 http:// 或 https://） | `http://192.168.1.100:9696` |
| API密钥 | 在 Prowlarr 设置→通用→安全→API密钥 中获取 | `1234567890abcdef` |
| 同步周期 | Cron 表达式，设置定时同步频率 | `0 0 */6 * *` (每6小时) |
| 使用代理 | 访问 Prowlarr 时是否使用系统代理 | ❌ |
| 立即运行一次 | 保存后立即同步索引器列表 | ✅ |

3. 点击 **保存**，插件会立即同步索引器

#### Jackett索引器

配置项与 Prowlarr 插件相同，只需将服务器地址改为 Jackett 地址（默认端口 9117）。

### 验证安装

查看插件详情页面：
- 插件运行状态应该显示"运行中"
- 已注册的索引器数量应该大于 0
- 索引器列表中能看到站点信息

## 📝 配置说明

### 同步周期

| 表达式 | 说明 |
|--------|------|
| `0 0 */6 * *` | 每6小时同步一次（推荐） |
| `0 0 */12 * *` | 每12小时同步一次 |
| `0 2 * * *` | 每天凌晨2点同步 |

> [!TIP]
> 建议设置较长的同步周期（如6-12小时），避免频繁请求 API。

### 代理设置

- 当 MoviePilot 需要通过代理才能访问 Prowlarr/Jackett 时启用
- 使用 MoviePilot 系统设置中配置的代理服务器
- 如果 Prowlarr/Jackett 在本地网络，通常不需要代理

### 立即运行一次

- 启用后会在保存配置时立即同步索引器
- 同步完成后会自动关闭该选项
- 用于快速验证配置是否正确

## ❓ 常见问题

<details>
<summary><b>Q: 为什么站点管理中的"测试连接"显示失败？</b></summary>

> [!WARNING]
> 这是已知限制。插件使用的是伪域名，MoviePilot 的站点测试会尝试访问这个域名，因此会失败。

**解决方案**:
- 站点连通性通过 Prowlarr/Jackett 本身的测试功能验证
- 在 Prowlarr/Jackett 管理界面中查看索引器状态
- 如果搜索功能正常，说明站点工作正常
</details>

<details>
<summary><b>Q: 为什么搜索中文关键词没有结果？</b></summary>

**A**: Prowlarr/Jackett 对中文关键词支持有限，插件会自动过滤非英文关键词。

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
【Prowlarr索引器】过滤公开站点：RARBG
【Prowlarr索引器】过滤仅XXX分类站点：AdultSite
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
- **搜索**: 与直接使用 Prowlarr/Jackett API 速度相同
- **分类信息**: 仅在注册时获取一次，后续搜索不受影响
</details>

## 🛠️ 故障排除

### 常见错误

| 错误信息 | 解决方法 |
|---------|---------|
| `配置错误：缺少服务器地址或API密钥` | 检查服务器地址和 API 密钥是否正确填写 |
| `配置错误：服务器地址必须以 http:// 或 https:// 开头` | 在服务器地址前添加 `http://` 或 `https://` |
| `API请求失败：无响应` | 检查网络连接、服务器地址、防火墙设置 |
| `API请求失败：HTTP 401` | API 密钥错误，重新获取并填写 |
| `未获取到索引器列表` | 在 Prowlarr/Jackett 中配置并启用索引器 |

### 重置插件

如果插件出现问题：

1. 在插件配置中禁用插件
2. 保存配置
3. 重新启用插件并重新配置
4. 启用"立即运行一次"重新同步

### 查看日志

插件会在 MoviePilot 日志中记录运行信息：

```log
【Prowlarr索引器】成功获取 15 个索引器（私有+半公开），过滤掉 3 个公开站点，2 个XXX专属站点
【Prowlarr索引器】开始检索站点：Prowlarr索引器-M-Team，关键词：The Matrix
【Prowlarr索引器】搜索完成：Prowlarr索引器-M-Team 从 125 条原始结果中解析出 120 个有效结果
```

## 🤝 贡献

欢迎提交 Issue 和 Pull Request！

### 报告问题

提交 Issue 时请包含：
- MoviePilot 版本
- Prowlarr/Jackett 版本
- 插件版本
- 详细的错误信息和日志
- 复现步骤

### 提交代码

1. Fork 本仓库
2. 创建特性分支
3. 提交更改
4. 创建 Pull Request

## 📄 许可证

本项目采用 MIT 许可证。

## 🙏 致谢

- [MoviePilot](https://github.com/jxxghp/MoviePilot) - 优秀的媒体管理工具
- [Prowlarr](https://github.com/Prowlarr/Prowlarr) - 索引器管理工具
- [Jackett](https://github.com/Jackett/Jackett) - 索引器代理工具
- [ProwlarrExtend/JackettExtend](https://github.com/jtcymc/MoviePilot-PluginsV2) - 本项目起源

---

<div align="center">

**⭐ 如果这个项目对你有帮助，请给一个 Star！**

Made with ❤️ by Claude

**版本**: v1.1.0 | **更新日期**: 2026-02-14

</div>
