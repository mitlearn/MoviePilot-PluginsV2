# MoviePilot Indexer Plugins

MoviePilot 插件，集成 Prowlarr 和 Jackett 索引器搜索功能。

> [!IMPORTANT]  
> 如你所见，本项目由Vibe Coding而成，如有问题请详细提起Issues。若AI能修就能，不能则请忍住。

## 插件列表

### 1. ProwlarrIndexer - Prowlarr索引器

通过 Prowlarr API 集成多个索引器搜索功能。

**主要特性：**
- ✅ 自动同步 Prowlarr 中已启用的索引器
- ✅ 站点认证：仅使用已在 Prowlarr 中启用和认证的索引器
- ✅ 私有站点过滤：自动过滤公开站点，仅索引私有站点
- ✅ 支持电影和电视剧分类搜索
- ✅ 支持分页和结果过滤
- ✅ 完整的元数据映射（做种、下载数、大小等）
- ✅ 定时自动同步索引器列表
- ✅ 代理支持
- ✅ 完善的错误处理和日志记录

### 2. JackettIndexer - Jackett索引器

通过 Jackett Torznab API 集成多个索引器搜索功能。

**主要特性：**
- ✅ 自动同步 Jackett 中已配置的索引器
- ✅ 站点认证：仅使用已在 Jackett 中配置和认证的索引器
- ✅ 私有站点过滤：自动过滤公开站点，仅索引私有站点
- ✅ 支持 Torznab 协议标准
- ✅ 支持电影和电视剧分类搜索
- ✅ XML 响应解析和元数据提取
- ✅ 定时自动同步索引器列表
- ✅ 代理支持
- ✅ 完善的错误处理和日志记录

## 安装说明

### 方式一：自动安装（推荐）

1. 插件 - 插件市场 - 插件市场设置

2. 新起一行添加本项目地址 `https://github.com/mitlearn/MoviePilot-PluginsV2/`，保存

3. 点击更新按钮，找到本项目提供的插件

### 方式二：手动安装

1. 在 MoviePilot 的 `plugins` 目录下创建以下目录：
   ```
   plugins/
   ├── prowlarrindexer/
   └── jackettindexer/
   ```

2. 将对应的 `__init__.py` 文件复制到各自目录

3. 将图标文件复制到 `icons/` 目录：
   - `Prowlarr.png`
   - `Jackett_A.png`

4. 更新 `package.v2.json` 文件

5. 重启 MoviePilot

## 配置说明

### ProwlarrIndexer 配置

| 配置项 | 说明 | 必填 | 默认值 |
|-------|------|------|--------|
| 启用插件 | 是否启用 Prowlarr 索引器 | 是 | 否 |
| 服务器地址 | Prowlarr 服务器地址 | 是 | - |
| API密钥 | Prowlarr API Key | 是 | - |
| 同步周期 | 索引器列表同步周期（Cron表达式） | 否 | `0 0 */6 * *` |
| 使用代理 | 是否使用系统代理访问 | 否 | 否 |
| 立即运行一次 | 立即同步索引器列表 | 否 | 否 |

**获取 API 密钥：**
1. 打开 Prowlarr Web 界面
2. 进入 `Settings` → `General` → `Security`
3. 复制 `API Key`

**服务器地址示例：**
- `http://127.0.0.1:9696`
- `http://192.168.1.100:9696`
- `https://prowlarr.example.com`

### JackettIndexer 配置

| 配置项 | 说明 | 必填 | 默认值 |
|-------|------|------|--------|
| 启用插件 | 是否启用 Jackett 索引器 | 是 | 否 |
| 服务器地址 | Jackett 服务器地址 | 是 | - |
| API密钥 | Jackett API Key | 是 | - |
| 同步周期 | 索引器列表同步周期（Cron表达式） | 否 | `0 0 */6 * *` |
| 使用代理 | 是否使用系统代理访问 | 否 | 否 |
| 立即运行一次 | 立即同步索引器列表 | 否 | 否 |

**获取 API 密钥：**
1. 打开 Jackett Web 界面
2. 点击右上角扳手图标
3. 复制 `API Key`

**服务器地址示例：**
- `http://127.0.0.1:9117`
- `http://192.168.1.100:9117`
- `https://jackett.example.com`

## 核心功能说明

### 站点认证机制

插件实现了严格的站点认证检查，确保只使用可靠的索引器：

**Prowlarr 插件：**
- ✅ 仅同步 Prowlarr 中**已启用**（`enable=true`）的索引器
- ✅ 确保索引器已在 Prowlarr 中完成配置和认证
- ℹ️ 在 Prowlarr 中禁用的索引器将被自动忽略

**Jackett 插件：**
- ✅ 仅同步 Jackett 中**已配置**（`configured=true`）的索引器
- ✅ 确保索引器已在 Jackett 中完成配置和认证
- ℹ️ 未配置的索引器将被自动忽略

### 私有站点过滤

插件自动过滤公开站点，仅索引私有站点，确保资源质量：

**过滤规则：**

| 索引器类型 | 是否索引 | 说明 |
|-----------|---------|------|
| 私有站点（Private） | ✅ 索引 | PT站点，需要邀请注册 |
| 半私有站点（Semi-Private） | ❌ 过滤 | 部分开放注册的站点 |
| 公开站点（Public） | ❌ 过滤 | 公共BT站点 |

**Prowlarr 判断标准：**
- `privacy = 0` → 公开站点 → ❌ 过滤
- `privacy = 1` → 私有站点 → ✅ 索引
- `privacy = 2` → 半私有站点 → ❌ 过滤

**Jackett 判断标准：**
- `type = "public"` → 公开站点 → ❌ 过滤
- `type = "semi-public"` → 半私有站点 → ❌ 过滤
- `type = "private"` → 私有站点 → ✅ 索引

**过滤效果：**
- 日志中会显示过滤的公开站点名称
- 插件详情页只显示私有站点
- 搜索时只使用私有站点进行查询

## 使用说明

### 首次配置步骤

1. **安装插件**
   - 按照上述安装说明完成插件安装

2. **配置 Prowlarr/Jackett**
   - 确保 Prowlarr 或 Jackett 已正确安装并运行
   - 在 Prowlarr/Jackett 中配置并启用索引器

3. **配置 MoviePilot 插件**
   - 在 MoviePilot 插件页面找到对应插件
   - 填写服务器地址和 API 密钥
   - 勾选"启用插件"和"立即运行一次"
   - 保存配置

4. **验证配置**
   - 查看插件详情页，确认索引器已成功同步
   - 复制插件详情页中的站点domain
   - 站点管理 - 添加站点 - 站点域名填写复制的站点domain，其他不填，保存
   - 在 MoviePilot 搜索页面，应该能看到新增的站点
   - 执行搜索测试

### 搜索功能

插件启用后，MoviePilot 的搜索功能会自动包含所有同步的索引器：

1. **自动搜索**
   - 订阅影片后，MoviePilot 会自动在所有索引器中搜索

2. **手动搜索**
   - 在搜索页面输入关键词
   - 选择媒体类型（电影/电视剧）
   - 插件会自动根据类型过滤分类

3. **分类支持**
   - 电影：自动使用分类 2000
   - 电视剧：自动使用分类 5000
   - 通用搜索：同时使用 2000 和 5000

### 站点识别

- **Prowlarr 索引器**：站点名称格式为 `Prowlarr索引器-{索引器名称}`
- **Jackett 索引器**：站点名称格式为 `Jackett索引器-{索引器名称}`

每个索引器都会注册为独立的站点，可在站点管理中查看。

## 常见问题

### 1. 插件配置后自动禁用

**原因：**
- 服务器地址或 API 密钥错误
- Prowlarr/Jackett 服务未运行
- 网络连接问题

**解决方法：**
1. 检查服务器地址是否正确（必须包含 `http://` 或 `https://`）
2. 验证 API 密钥是否正确
3. 确认 Prowlarr/Jackett 服务正常运行
4. 查看 MoviePilot 日志获取详细错误信息

### 2. 搜索无结果

**原因：**
- 索引器未正确配置
- 索引器不支持搜索的分类
- 关键词过于严格

**解决方法：**
1. 在 Prowlarr/Jackett 中测试索引器是否正常工作
2. 检查索引器是否支持电影（2000）或电视剧（5000）分类
3. 尝试更宽泛的搜索关键词
4. 查看插件详情页确认索引器已同步

### 3. 索引器列表不更新

**原因：**
- 同步周期未到
- 定时任务未启动

**解决方法：**
1. 点击"立即运行一次"手动同步
2. 检查同步周期配置是否正确
3. 重启插件重新初始化定时任务

### 4. API 请求超时

**原因：**
- 网络延迟过高
- Prowlarr/Jackett 响应慢
- 索引器数量过多

**解决方法：**
1. 如需要，启用代理配置
2. 在 Prowlarr/Jackett 中禁用响应慢的索引器
3. 适当增加请求超时时间（需修改代码）

### 5. 与其他搜索插件冲突

**原因：**
- 多个插件同时启用可能产生冲突

**解决方法：**
1. 确保其他索引器插件已禁用或正确配置
2. 查看日志确认是否有重复注册的站点
3. 必要时只启用一个索引器插件

## 技术说明

### 架构设计

插件采用模块劫持（Module Hijacking）方式集成到 MoviePilot：

1. **初始化阶段**
   - 从 Prowlarr/Jackett 获取索引器列表
   - 为每个索引器创建站点配置
   - 注册到 MoviePilot 站点管理器

2. **搜索阶段**
   - 劫持 `search_torrents` 方法
   - 根据站点名称判断是否由本插件处理
   - 调用对应的 API 进行搜索
   - 解析结果并返回标准 TorrentInfo 对象

3. **同步阶段**
   - 定时任务定期同步索引器列表
   - 注销已删除的索引器
   - 注册新增的索引器

### API 端点

**Prowlarr API:**
- 索引器列表：`GET /api/v1/indexer`
- 搜索接口：`GET /api/v1/search`
- 认证方式：`X-Api-Key` 请求头

**Jackett API:**
- 索引器列表：通过 Torznab 协议获取
- 搜索接口：`GET /api/v2.0/indexers/{id}/results/torznab/api`
- 认证方式：`apikey` 查询参数

### 数据结构

插件返回的 TorrentInfo 包含以下字段：

| 字段 | 类型 | 说明 |
|-----|------|------|
| title | str | 种子标题 |
| enclosure | str | 下载链接或磁力链接 |
| size | int | 文件大小（字节） |
| seeders | int | 做种人数 |
| peers | int | 下载人数 |
| pubdate | str | 发布时间 |
| description | str | 种子描述 |
| page_url | str | 详情页链接 |
| site_name | str | 站点名称 |
| imdbid | str | IMDB ID |
| downloadvolumefactor | float | 下载计数因子（0.0=免费） |
| uploadvolumefactor | float | 上传计数因子 |
| grabs | int | 完成下载数 |

## 开发说明

### 项目结构

```
prowalarr/
├── plugins.v2/
│   ├── prowlarrindexer/
│   │   └── __init__.py          # Prowlarr 插件主文件
│   └── jackettindexer/
│       └── __init__.py          # Jackett 插件主文件
├── icons/
│   ├── Prowlarr.png            # Prowlarr 图标
│   └── Jackett_A.png           # Jackett 图标
├── package.v2.json             # 插件元数据
├── README.md                   # 本文件

```

## 故障排查

### 搜索无结果或出现错误

如果遇到以下错误：
```
【ERROR】- indexer - ProwlarrIndexer-XXX 搜索出错：'NoneType' object has no attribute 'get'
```

**诊断步骤**：

1. **检查日志中是否出现以下内容**：
   ```
   【INFO】【Prowlarr索引器】get_module 被调用，注册 search_torrents 方法
   【DEBUG】【Prowlarr索引器】search_torrents 被调用：site={...}, keyword=xxx
   ```

2. **如果缺少上述日志**：
   - 完全重启 MoviePilot：`docker restart moviepilot`
   - 在 Web 界面禁用插件 → 保存 → 重新启用 → 立即运行一次 → 保存
   - 检查插件版本是否为 0.1.2 或更高

3. **如果看到 `search_torrents 被调用`**：
   - 问题在于 API 调用，检查 Prowlarr/Jackett 地址和密钥
   - 查看是否有网络连接错误日志

4. **查看插件详情页**：
   - 确认索引器已同步
   - 查看域名列是否显示正确（如 `http://prowlarr.4.indexer`）

### 查看数据页不显示新字段

需要完全重启 MoviePilot 并清除浏览器缓存：
```bash
docker restart moviepilot
```
浏览器强制刷新：Ctrl+Shift+R (Windows/Linux) 或 Cmd+Shift+R (Mac)

### 插件配置后自动禁用

常见原因：
- Prowlarr/Jackett 地址或 API 密钥错误
- 服务器地址缺少 `http://` 或 `https://` 前缀
- Prowlarr/Jackett 服务未运行
- 网络连接问题

查看 MoviePilot 日志获取详细错误信息。

## 版本历史

| 版本 | 日期 | 更新内容 |
|------|------|----------|
| 0.9.0 | 2026-02-13 | 🔒 站点认证与过滤：需求一：仅使用已在Prowlarr/Jackett中启用和认证的索引器；需求二：自动过滤公开站点（PublicTracker），仅索引私有站点（PrivateTracker），确保高质量资源 |
| 0.8.0 | 2026-02-13 | 📝 优化体验：清理日志输出，移除装饰性符号（★✓✅），调整日志等级（详细调试信息移至DEBUG）；API密钥字段改为密码类型（固定遮罩显示，增强安全性） |
| 0.7.2 | 2026-02-13 | 🎯 关键修复：解决domain被MoviePilot转换为URL格式导致索引器ID提取失败的问题，在解析前先剥离`http://`前缀和`/`后缀，**彻底修复搜索请求未发送到Prowlarr/Jackett的问题** |
| 0.7.1 | 2026-02-12 | 🔍 增强调试能力：添加domain生成、索引器ID提取的详细日志（含类型信息），便于诊断搜索请求未发送问题；明确API密钥字段类型 |
| 0.7.0 | 2026-02-12 | 🐛 修复Prowlarr索引器搜索失败问题：移除错误的StringUtils.get_url_domain()调用，改用直接字符串分割提取索引器ID；🔧 修复API密钥显示问题：移除不可用的密码遮罩和眼睛图标，改为明文显示便于配置；同时修复Jackett插件相同问题 |
| 0.1.6 | 2026-02-12 | 修复站点管理注册逻辑：实现正确的站点检查和注册流程，使用get_indexer检查站点是否存在，仅在不存在时通过深拷贝添加；分离初始化流程为获取索引器和同步站点管理两个阶段，确保所有索引器正确显示在站点管理列表中 |
| 0.1.5 | 2026-02-12 | 修复站点可见性：优先使用add_site；添加active/limit字段；强制public=true |
| 0.1.4 | 2026-02-12 | 优化域名可读性：使用索引器名称生成域名；重写get_page使用标准表格；简化显示 |
| 0.1.3 | 2026-02-12 | 修复站点注册问题：恢复torrents/parser字典结构确保add_indexer成功；增加详细注册日志 |
| 0.1.2 | 2026-02-12 | 彻底修复模块劫持问题：将torrents和parser设置为None；添加type='indexer'标记；完善诊断日志 |
| 0.1.1 | 2026-02-12 | 修复爬虫冲突：优化域名格式；改进查看数据页；增强日志记录 |
| 0.1.0 | 2026-02-11 | 初始版本发布 |

## 许可证

本项目遵循 MIT 许可证。

## 致谢

- [ProwlarrExtend/JackettExtend](https://github.com/jtcymc/MoviePilot-PluginsV2) - 本项目起源
- [MoviePilot](https://github.com/jxxghp/MoviePilot) - 优秀的媒体库管理工具
- [Prowlarr](https://github.com/Prowlarr/Prowlarr) - 强大的索引器管理器
- [Jackett](https://github.com/Jackett/Jackett) - 经典的索引器代理

## 支持

如遇到问题或有改进建议，欢迎：
- 提交 Issue
- 发起 Pull Request
- 参与讨论

---

**版本**: 0.9.0
**作者**: Claude
**最后更新**: 2026-02-13
