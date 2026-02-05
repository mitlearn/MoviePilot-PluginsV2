# Prowlarr 扩展索引器插件

## 📖 概述

集成 Prowlarr 聚合搜索服务，为 MoviePilot 提供多站点资源检索能力。通过 Prowlarr API 聚合多个 BT/PT 站点，实现统一搜索接口。

## ✨ 功能特性

- ✅ 自动同步 Prowlarr 配置的索引器列表
- ✅ 支持电影/电视分类过滤
- ✅ 定时更新索引器状态
- ✅ 完善的错误处理和日志记录
- ✅ 支持代理配置
- ✅ 支持分页搜索
- ✅ 详情页面展示索引器列表

## 📋 使用前提

### 1. 部署 Prowlarr

需要先部署 Prowlarr 服务，可以使用 Docker 快速部署：

```bash
docker run -d \
  --name=prowlarr \
  -e PUID=1000 \
  -e PGID=1000 \
  -e TZ=Asia/Shanghai \
  -p 9696:9696 \
  -v /path/to/prowlarr/config:/config \
  --restart unless-stopped \
  lscr.io/linuxserver/prowlarr:latest
```

### 2. 配置 Prowlarr 索引器

1. 访问 Prowlarr Web 界面 (默认 `http://localhost:9696`)
2. 进入 `Indexers` → `Add Indexer`
3. 搜索并添加你想要的 BT/PT 站点
4. 配置站点的 Cookie、API Key 等认证信息
5. 测试索引器连通性

### 3. 获取 API Key

1. 进入 `Settings` → `General` → `Security`
2. 找到 `API Key` 字段
3. 复制 API Key 备用

## 🚀 安装步骤

### 方法一：通过 Git 克隆

```bash
cd /path/to/moviepilot/plugins
git clone <repository-url> prowlarrextend
```

### 方法二：手动下载

1. 下载插件文件到 MoviePilot 插件目录
2. 确保目录结构为：
   ```
   plugins/
   └── prowlarrextend/
       ├── __init__.py
       ├── Prowlarr.png
       └── README.md
   ```

## ⚙️ 配置说明

### 基础配置

| 配置项 | 说明 | 必填 | 示例 |
|--------|------|------|------|
| **启用插件** | 开启/关闭插件功能 | 是 | `开启` |
| **Prowlarr 地址** | Prowlarr 服务地址 | 是 | `http://127.0.0.1:9696` |
| **API Key** | Prowlarr API 密钥 | 是 | `xxxxxxxxxxxxxxxx` |
| **使用代理服务器** | 通过代理访问 Prowlarr | 否 | `关闭` |
| **立即运行一次** | 保存后立即同步索引器 | 否 | `开启` |
| **同步周期** | 索引器列表更新周期 | 否 | `0 0 */24 * *` |

### 配置示例

#### 本地部署
```
Prowlarr 地址: http://localhost:9696
API Key: 1234567890abcdef1234567890abcdef
使用代理: 关闭
同步周期: 0 0 */24 * *
```

#### 远程部署
```
Prowlarr 地址: https://prowlarr.example.com
API Key: abcdef1234567890abcdef1234567890
使用代理: 开启
同步周期: 0 */12 * * *
```

## 📝 使用流程

### 1. 配置插件

1. 在 MoviePilot 插件管理中找到 `Prowlarr 扩展索引器`
2. 填写 Prowlarr 地址和 API Key
3. 勾选 `立即运行一次`
4. 点击 `保存`

### 2. 查看索引器

1. 点击插件的 `查看数据` 按钮
2. 查看已同步的索引器列表
3. 记录需要添加的站点域名

### 3. 添加站点

1. 进入 MoviePilot `站点管理`
2. 点击 `新增站点`
3. 在 `站点地址` 中填入：`https://<站点域名>`
   - 例如：`https://prowlarr.extend.123`
4. 点击 `保存`

### 4. 开始搜索

配置完成后，MoviePilot 的搜索功能会自动调用 Prowlarr 索引器进行搜索。

## 🔍 工作原理

### 架构流程

```
MoviePilot 搜索请求
    ↓
插件拦截 search_torrents 方法
    ↓
识别 Prowlarr 站点域名
    ↓
调用 Prowlarr API
    ↓
解析 JSON 结果
    ↓
转换为 TorrentInfo 对象
    ↓
返回给 MoviePilot
```

### 技术实现

- **模块劫持**: 使用 `get_module()` 劫持系统的 `search_torrents` 方法
- **站点注册**: 通过 `SitesHelper().add_indexer()` 注册虚拟站点
- **API 调用**: 使用 Prowlarr `/api/v1/search` 接口
- **分类映射**:
  - 电影: `categories=2000`
  - 电视: `categories=5000`

## 🐛 常见问题

### Q1: 插件显示"未获取到任何索引器"

**可能原因**:
1. Prowlarr 地址或 API Key 错误
2. Prowlarr 未配置任何索引器
3. 网络连接问题

**解决方案**:
```bash
# 测试 Prowlarr 连通性
curl -H "X-Api-Key: YOUR_API_KEY" http://localhost:9696/api/v1/indexerstats

# 检查 MoviePilot 日志
docker logs moviepilot | grep "Prowlarr"
```

### Q2: 搜索无结果

**可能原因**:
1. 索引器未在 Prowlarr 中正确配置
2. 关键词不匹配
3. 索引器站点无资源

**解决方案**:
1. 先在 Prowlarr 中测试搜索
2. 检查插件日志输出
3. 验证站点域名格式正确

### Q3: 日志出现 "NoneType object has no attribute get"

这是正常现象，插件未搜索到结果时会触发后续模块继续搜索，可以忽略此错误。

### Q4: 如何更新索引器列表？

1. 方法一：等待定时任务自动更新 (默认 24 小时)
2. 方法二：开启 `立即运行一次` 并保存配置
3. 方法三：重启 MoviePilot 服务

## 📊 日志说明

### 正常日志

```
【Prowlarr 扩展索引器】索引器同步任务已启动，周期: 0 0 */24 * *
【Prowlarr 扩展索引器】成功同步 15 个索引器
【Prowlarr 扩展索引器】新注册 15 个索引器到系统
【Prowlarr 扩展索引器】开始搜索 - 索引器: Prowlarr-RSSing, 关键词: 肖申克的救赎, 类型: 电影
【Prowlarr 扩展索引器】搜索完成 - 索引器: Prowlarr-RSSing, 结果数: 12
```

### 错误日志

```
【Prowlarr 扩展索引器】配置验证失败，插件已禁用
【Prowlarr 扩展索引器】获取索引器列表失败: HTTP 401: Unauthorized
【Prowlarr 扩展索引器】搜索请求无响应
```

## 🔧 高级配置

### 自定义同步周期

Cron 表达式示例：

```
# 每 6 小时同步一次
0 */6 * * *

# 每天凌晨 2 点同步
0 2 * * *

# 每周一凌晨 3 点同步
0 3 * * 1

# 每月 1 号凌晨 4 点同步
0 4 1 * *
```

### 代理配置

如果 Prowlarr 需要通过代理访问：

1. 在 MoviePilot 中配置代理服务器
2. 开启插件的 `使用代理服务器` 选项
3. 保存配置

## 🤝 贡献指南

欢迎提交 Issue 和 Pull Request！

### 开发环境

```bash
# 克隆仓库
git clone <repository-url>

# 安装依赖
pip install -r requirements.txt

# 运行测试
python -m pytest tests/
```

### 代码规范

- 遵循 PEP 8 编码规范
- 添加详细的中文注释
- 编写单元测试
- 更新文档

## 📄 许可证

本插件遵循 MIT 许可证。

## 🙏 致谢

- 基于 [jtcymc/MoviePilot-PluginsV2](https://github.com/jtcymc/MoviePilot-PluginsV2) 原始实现优化
- 感谢 [jxxghp/MoviePilot](https://github.com/jxxghp/MoviePilot) 项目
- 感谢 Prowlarr 团队提供优秀的聚合搜索服务

## 📞 支持

- 项目主页: [GitHub](https://github.com/jxxghp/MoviePilot-Plugins)
- 问题反馈: [Issues](https://github.com/jxxghp/MoviePilot-Plugins/issues)
- 讨论交流: [Discussions](https://github.com/jxxghp/MoviePilot-Plugins/discussions)

---

**版本**: 2.0
**更新时间**: 2026-02-05
**作者**: Claude Code
