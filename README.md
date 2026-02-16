# MoviePilot Plugins Collection

<div align="center">

![Version](https://img.shields.io/badge/version-1.5.0-blue.svg)
![MoviePilot](https://img.shields.io/badge/MoviePilot-v2.x-green.svg)
![License](https://img.shields.io/badge/license-MIT-green.svg)

**MoviePilot 插件合集：索引器集成 & 观影列表同步**

[简介](#-简介) •
[插件列表](#-插件列表) •
[快速开始](#-快速开始) •
[文档](#-文档)

</div>

---

## 📖 简介

> [!IMPORTANT]
> 本项目由 AI Coding 而成。如遇问题，请在 Issues 中详细描述问题现象、错误日志及复现步骤。AI 能理解的问题就能修复，否则请自行动手并提交 PR，我们欢迎所有贡献！

本项目为 MoviePilot 提供三个实用插件，帮助您扩展站点搜索能力和自动化观影管理。

---

## 🔌 插件列表

### 索引器集成插件

#### Prowlarr 索引器

**[查看详细文档 →](plugins.v2/prowlarrindexer/README.md)**

集成 Prowlarr 的所有已配置索引器到 MoviePilot。

**核心功能**：
- ✅ 自动同步 Prowlarr 索引器
- ✅ 统一搜索接口（支持 IMDb ID）
- ✅ 站点分类和促销识别
- ✅ 智能过滤（仅索引私有和半公开站点）
- ✅ 定时同步、代理支持
- ✅ API 接口、远程命令、AI 智能体工具

---

#### Jackett 索引器

**[查看详细文档 →](plugins.v2/jackettindexer/README.md)**

集成 Jackett 的所有已配置索引器到 MoviePilot。

**核心功能**：
- ✅ 自动同步 Jackett 索引器
- ✅ 统一搜索接口（支持 IMDb ID）
- ✅ 站点分类和促销识别
- ✅ 智能过滤（仅索引私有和半公开站点）
- ✅ 定时同步、代理支持
- ✅ API 接口、远程命令、AI 智能体工具

---

### 观影列表同步插件

#### TraktSync

**[查看详细文档 →](plugins.v2/traktsync/README.md)**

同步 Trakt.tv 想看列表到 MoviePilot，自动添加订阅或搜索下载。

**核心功能**：
- ✅ 自动同步 Trakt Watchlist（电影 + 剧集）
- ✅ OAuth 2.0 认证与 Token 自动刷新
- ✅ 智能去重（检查媒体库和订阅列表）
- ✅ 可选搜索下载或仅添加订阅
- ✅ 定时任务、远程命令、系统通知
- ✅ 自动使用系统代理

---

## 🚀 快速开始

### 前置要求

- [x] MoviePilot v2.x
- [x] Prowlarr v1.0+ 或 Jackett v0.20+（索引器插件）
- [x] Trakt.tv 账号（TraktSync 插件）

### 安装方法

#### 方法一：通过插件市场安装（推荐）

1. MoviePilot → **设置 → 插件 → 插件市场**
2. 点击右上角齿轮 → 添加仓库：
   ```
   https://github.com/mitlearn/MoviePilot-PluginsV2
   ```
3. 更新后在列表中找到并安装所需插件

#### 方法二：手动安装

```bash
# 克隆仓库
git clone https://github.com/mitlearn/MoviePilot-PluginsV2.git

# 复制插件到 MoviePilot 插件目录
cp -r plugins.v2/prowlarrindexer /path/to/moviepilot/plugins/
cp -r plugins.v2/jackettindexer /path/to/moviepilot/plugins/
cp -r plugins.v2/traktsync /path/to/moviepilot/plugins/

# 重启 MoviePilot
```

---

## 📚 文档

### 插件文档

| 插件 | 完整文档 | 快速配置 |
|------|---------|---------|
| **Prowlarr 索引器** | [README](plugins.v2/prowlarrindexer/README.md) | 获取 API 密钥 → 填写配置 → 添加站点 |
| **Jackett 索引器** | [README](plugins.v2/jackettindexer/README.md) | 获取 API 密钥 → 填写配置 → 添加站点 |
| **TraktSync** | [README](plugins.v2/traktsync/README.md) | 创建应用 → 获取 Token → 填写配置 |

### 配置示例

**Prowlarr/Jackett 插件**：
1. 在 Prowlarr/Jackett 设置中获取 API 密钥
2. MoviePilot 插件配置：填写服务器地址和 API 密钥
3. ⚠️ **重要**：在站点管理中添加索引器（使用插件详情页的 domain）
4. 测试搜索

**TraktSync 插件**：
1. 访问 [Trakt OAuth Applications](https://trakt.tv/oauth/applications/new) 创建应用
2. 获取 Client ID、Client Secret 和 Refresh Token（[详细步骤](plugins.v2/traktsync/README.md#第二步获取-refresh-token)）
3. MoviePilot 插件配置：填写凭据
4. 测试同步

> [!TIP]
> 每个插件的 README 都包含详细的配置步骤、常见问题和故障排除指南。

---

## 🐛 报告问题

### 提交 Issue

遇到问题或有功能建议？欢迎提交 Issue！

**[🐛 报告 Bug](https://github.com/mitlearn/MoviePilot-PluginsV2/issues/new?template=bug_report.yml)** | **[✨ 功能建议](https://github.com/mitlearn/MoviePilot-PluginsV2/issues/new?template=feature_request.yml)**

### 提交前准备

**1. 查看文档**
- 先查看对应插件的 README 文档
- 检查常见问题（FAQ）章节
- 参考故障排除指南

**插件文档快速链接**：
- [Prowlarr 索引器](plugins.v2/prowlarrindexer/README.md) - 常见问题和故障排除
- [Jackett 索引器](plugins.v2/jackettindexer/README.md) - 常见问题和故障排除
- [TraktSync](plugins.v2/traktsync/README.md) - 常见问题和故障排除

**2. 收集日志**

收集完整的调试日志可以帮助快速定位问题：

| 组件 | 日志收集方法 |
|------|-------------|
| **MoviePilot** | 设置 → 系统 → 日志等级 → DEBUG<br>设置 → 系统 → 实时日志 → 搜索关键词 |
| **Prowlarr** | 设置 → 通用 → 日志 → Debug<br>设置 → 系统 → 日志 → 文件 → 下载 |
| **Jackett** | 勾选 Enhanced logging<br>View logs |

**3. 使用 Issue 模板**

我们提供了详细的 Issue 模板，填写时请：
- 选择正确的插件
- 提供版本信息
- 描述详细的复现步骤
- 粘贴完整的日志

---

## 📄 许可证

本项目采用 MIT 许可证。

---

## 🙏 致谢

- [ProwlarrExtend/JackettExtend](https://github.com/jtcymc/MoviePilot-PluginsV2) - ProwlarrIndexer 与 JackettIndexer 插件的参考实现
- [doubansync 插件](https://github.com/jxxghp/MoviePilot-Plugins) - TraktSync 插件的参考实现
- [MoviePilot](https://github.com/jxxghp/MoviePilot) - 优秀的媒体管理工具
- [Prowlarr](https://github.com/Prowlarr/Prowlarr) - 强大的索引器管理工具
- [Jackett](https://github.com/Jackett/Jackett) - 经典的索引器代理工具
- [Trakt.tv](https://trakt.tv) - 优秀的观影追踪平台

**Powered By** [Claude](https://claude.ai) - AI 编程助手

---

<div align="center">

**⭐ 如果这个项目对你有帮助，请给一个 Star！**

Made with ❤️ by Claude

</div>
