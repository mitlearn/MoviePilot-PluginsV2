# Jackett 扩展索引器插件

## 📖 概述

集成 Jackett 聚合搜索服务，为 MoviePilot 提供多站点资源检索能力。通过 Jackett Torznab API 聚合多个 BT/PT 站点，实现统一搜索接口。

## ✨ 功能特性

- ✅ 自动同步 Jackett 配置的索引器列表
- ✅ 支持电影/电视分类过滤
- ✅ 支持 Torznab XML 格式解析
- ✅ 定时更新索引器状态
- ✅ 完善的错误处理和日志记录
- ✅ 支持密码保护的 Jackett 实例
- ✅ 支持代理配置
- ✅ 详情页面展示索引器列表

## 📋 使用前提

### 1. 部署 Jackett

需要先部署 Jackett 服务，可以使用 Docker 快速部署：

```bash
docker run -d \
  --name=jackett \
  -e PUID=1000 \
  -e PGID=1000 \
  -e TZ=Asia/Shanghai \
  -p 9117:9117 \
  -v /path/to/jackett/config:/config \
  -v /path/to/jackett/downloads:/downloads \
  --restart unless-stopped \
  lscr.io/linuxserver/jackett:latest
```

### 2. 配置 Jackett 索引器

1. 访问 Jackett Web 界面 (默认 `http://localhost:9117`)
2. 点击 `Add indexer`
3. 搜索并添加你想要的 BT/PT 站点
4. 配置站点的 Cookie、用户名/密码等认证信息
5. 点击 `Test` 验证配置
6. 保存索引器

### 3. 获取 API Key

1. 在 Jackett 管理界面右上角
2. 复制 API Key (黄色图标旁边)
3. 如果设置了管理密码，也需要记录

## 🚀 安装步骤

### 方法一：通过 Git 克隆

```bash
cd /path/to/moviepilot/plugins
git clone <repository-url> jackettextend
```

### 方法二：手动下载

1. 下载插件文件到 MoviePilot 插件目录
2. 确保目录结构为：
   ```
   plugins/
   └── jackettextend/
       ├── __init__.py
       ├── Jackett.png
       └── README.md
   ```

## ⚙️ 配置说明

### 基础配置

| 配置项 | 说明 | 必填 | 示例 |
|--------|------|------|------|
| **启用插件** | 开启/关闭插件功能 | 是 | `开启` |
| **Jackett 地址** | Jackett 服务地址 | 是 | `http://127.0.0.1:9117` |
| **API Key** | Jackett API 密钥 | 是 | `xxxxxxxxxxxxxxxx` |
| **管理密码** | Jackett Admin Password | 否 | `留空或填写密码` |
| **使用代理服务器** | 通过代理访问 Jackett | 否 | `关闭` |
| **立即运行一次** | 保存后立即同步索引器 | 否 | `开启` |
| **同步周期** | 索引器列表更新周期 | 否 | `0 0 */24 * *` |

### 配置示例

#### 本地部署（无密码）
```
Jackett 地址: http://localhost:9117
API Key: 1234567890abcdef1234567890abcdef
管理密码: (留空)
使用代理: 关闭
同步周期: 0 0 */24 * *
```

#### 本地部署（有密码）
```
Jackett 地址: http://localhost:9117
API Key: abcdef1234567890abcdef1234567890
管理密码: your_admin_password
使用代理: 关闭
同步周期: 0 */12 * * *
```

#### 远程部署
```
Jackett 地址: https://jackett.example.com
API Key: fedcba0987654321fedcba0987654321
管理密码: secure_password
使用代理: 开启
同步周期: 0 2 * * *
```

## 📝 使用流程

### 1. 配置插件

1. 在 MoviePilot 插件管理中找到 `Jackett 扩展索引器`
2. 填写 Jackett 地址和 API Key
3. 如果 Jackett 设置了管理密码，填写密码
4. 勾选 `立即运行一次`
5. 点击 `保存`

### 2. 查看索引器

1. 点击插件的 `查看数据` 按钮
2. 查看已同步的索引器列表
3. 记录需要添加的站点域名

### 3. 添加站点

1. 进入 MoviePilot `站点管理`
2. 点击 `新增站点`
3. 在 `站点地址` 中填入：`https://<站点域名>`
   - 例如：`https://jackett.extend.nyaa`
4. 点击 `保存`

### 4. 开始搜索

配置完成后，MoviePilot 的搜索功能会自动调用 Jackett 索引器进行搜索。

## 🔍 工作原理

### 架构流程

```
MoviePilot 搜索请求
    ↓
插件拦截 search_torrents 方法
    ↓
识别 Jackett 站点域名
    ↓
调用 Jackett Torznab API
    ↓
解析 XML 结果
    ↓
转换为 TorrentInfo 对象
    ↓
返回给 MoviePilot
```

### 技术实现

- **模块劫持**: 使用 `get_module()` 劫持系统的 `search_torrents` 方法
- **站点注册**: 通过 `SitesHelper().add_indexer()` 注册虚拟站点
- **API 调用**: 使用 Jackett Torznab 接口 `/api/v2.0/indexers/{id}/results/torznab/`
- **格式解析**: XML DOM 解析 Torznab 标准格式
- **分类映射**:
  - 电影: `cat=2000`
  - 电视: `cat=5000`

## 🆚 Jackett vs Prowlarr

| 特性 | Jackett | Prowlarr |
|------|---------|----------|
| **输出格式** | XML (Torznab) | JSON |
| **性能** | 较慢 | 较快 |
| **内存占用** | 较低 | 较高 |
| **站点支持** | 更多 | 较少但在增长 |
| **维护状态** | 活跃 | 活跃 |
| **集成方式** | Torznab API | 原生 API |
| **推荐场景** | 老站点、特殊站点 | 新部署、高性能需求 |

**选择建议**:
- 如果追求性能和现代化，使用 Prowlarr
- 如果需要更多站点支持，使用 Jackett
- 两者可以同时使用互补

## 🐛 常见问题

### Q1: 插件显示"未获取到任何索引器"

**可能原因**:
1. Jackett 地址或 API Key 错误
2. Jackett 未配置任何索引器
3. 管理密码错误
4. 网络连接问题

**解决方案**:
```bash
# 测试 Jackett 连通性
curl "http://localhost:9117/api/v2.0/indexers?configured=true&apikey=YOUR_API_KEY"

# 检查 MoviePilot 日志
docker logs moviepilot | grep "Jackett"
```

### Q2: 搜索无结果

**可能原因**:
1. 索引器未在 Jackett 中正确配置
2. 关键词不匹配
3. 索引器站点无资源
4. 索引器 Cookie 过期

**解决方案**:
1. 先在 Jackett 中测试索引器
2. 检查插件日志输出
3. 更新索引器 Cookie
4. 验证站点域名格式正确

### Q3: XML 解析错误

**可能原因**:
1. Jackett 返回非标准 XML
2. 网络传输损坏
3. 索引器返回错误

**解决方案**:
```python
# 检查 XML 响应
curl "http://localhost:9117/api/v2.0/indexers/nyaa/results/torznab/?apikey=KEY&t=search&q=test&cat=2000,5000"
```

### Q4: 管理密码认证失败

**症状**: 无法获取索引器列表，日志显示 401 错误

**解决方案**:
1. 确认 Jackett 管理界面能正常登录
2. 检查密码中是否有特殊字符
3. 尝试暂时移除 Jackett 管理密码
4. 重启 Jackett 服务

### Q5: 日志出现 "NoneType object has no attribute get"

这是正常现象，插件未搜索到结果时会触发后续模块继续搜索，可以忽略此错误。

## 📊 日志说明

### 正常日志

```
【Jackett 扩展索引器】索引器同步任务已启动，周期: 0 0 */24 * *
【Jackett 扩展索引器】登录成功，已获取 Cookie
【Jackett 扩展索引器】成功同步 18 个索引器
【Jackett 扩展索引器】新注册 18 个索引器到系统
【Jackett 扩展索引器】开始搜索 - 索引器: Jackett-Nyaa, 关键词: 咒术回战, 类型: 电视
【Jackett 扩展索引器】搜索完成 - 索引器: Jackett-Nyaa, 结果数: 25
```

### 错误日志

```
【Jackett 扩展索引器】配置验证失败，插件已禁用
【Jackett 扩展索引器】登录失败，将尝试无 Cookie 访问
【Jackett 扩展索引器】获取索引器列表失败: HTTP 401: Unauthorized
【Jackett 扩展索引器】解析 XML 失败: syntax error
【Jackett 扩展索引器】搜索请求异常: Connection timeout
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

如果 Jackett 需要通过代理访问：

1. 在 MoviePilot 中配置代理服务器
2. 开启插件的 `使用代理服务器` 选项
3. 保存配置

### Torznab 参数说明

Jackett Torznab API 支持的参数：

```
t=search           # 搜索类型
q=keyword          # 搜索关键词
cat=2000,5000      # 分类 (2000=电影, 5000=电视)
apikey=xxx         # API 密钥
limit=100          # 结果数量限制
offset=0           # 分页偏移
```

## 🧪 测试方法

### 1. 测试 Jackett 连通性

```bash
curl "http://localhost:9117/api/v2.0/indexers?configured=true&apikey=YOUR_API_KEY"
```

预期输出: JSON 数组包含索引器列表

### 2. 测试搜索功能

```bash
curl "http://localhost:9117/api/v2.0/indexers/all/results/torznab/?apikey=YOUR_API_KEY&t=search&q=test&cat=2000"
```

预期输出: XML 格式的搜索结果

### 3. 测试插件日志

```bash
# 查看插件日志
docker logs -f moviepilot | grep "Jackett 扩展索引器"

# 查看最近 100 行
docker logs --tail 100 moviepilot | grep "Jackett"
```

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

## 🔗 相关资源

- [Jackett 官方文档](https://github.com/Jackett/Jackett)
- [Torznab 规范](https://torznab.github.io/spec-1.3-draft/)
- [MoviePilot 项目](https://github.com/jxxghp/MoviePilot)

## 📄 许可证

本插件遵循 MIT 许可证。

## 🙏 致谢

- 基于 [jtcymc/MoviePilot-PluginsV2](https://github.com/jtcymc/MoviePilot-PluginsV2) 原始实现优化
- 感谢 [jxxghp/MoviePilot](https://github.com/jxxghp/MoviePilot) 项目
- 感谢 Jackett 团队提供优秀的聚合搜索服务

## 📞 支持

- 项目主页: [GitHub](https://github.com/jxxghp/MoviePilot-Plugins)
- 问题反馈: [Issues](https://github.com/jxxghp/MoviePilot-Plugins/issues)
- 讨论交流: [Discussions](https://github.com/jxxghp/MoviePilot-Plugins/discussions)

---

**版本**: 2.0
**更新时间**: 2026-02-05
**作者**: Claude Code
