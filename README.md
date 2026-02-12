# MoviePilot Indexer Plugins

MoviePilot 插件，集成 Prowlarr 和 Jackett 索引器搜索功能。

## 插件列表

### 1. ProwlarrIndexer - Prowlarr索引器

通过 Prowlarr API 集成多个索引器搜索功能。

**主要特性：**
- ✅ 自动同步 Prowlarr 中已启用的索引器
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
- ✅ 支持 Torznab 协议标准
- ✅ 支持电影和电视剧分类搜索
- ✅ XML 响应解析和元数据提取
- ✅ 定时自动同步索引器列表
- ✅ 代理支持
- ✅ 完善的错误处理和日志记录

## 安装说明

### 方式一：自动安装（推荐）

1. 将整个 `plugins.v2` 目录复制到 MoviePilot 的插件目录
2. 将 `icons` 目录中的图标文件复制到 MoviePilot 的 `icons` 目录
3. 将 `package.v2.json` 合并到 MoviePilot 的 `package.v2.json` 文件中
4. 重启 MoviePilot

### 方式二：手动安装

1. 在 MoviePilot 的 `plugins.v2` 目录下创建以下目录：
   ```
   plugins.v2/
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
├── CHANGELOG.md                # 更新日志
└── API_DOCUMENTATION.md        # API 文档

```

### 代码规范

- **语言**: Python 3.8+
- **编码**: UTF-8
- **风格**: PEP 8
- **类型注解**: 完整的类型提示
- **文档字符串**: Google 风格
- **错误处理**: 全面的异常捕获和日志记录

### 关键改进

相比参考实现，本插件做了以下改进：

1. **完整的数据结构**
   - 包含 `torrents` 和 `parser` 字段防止系统崩溃

2. **健壮的错误处理**
   - 验证所有输入参数
   - 捕获并记录所有异常
   - 失败时返回空列表而非抛出异常

3. **详细的日志记录**
   - INFO 级别：正常操作
   - WARNING 级别：可恢复的问题
   - ERROR 级别：失败情况（含堆栈跟踪）

4. **配置验证**
   - 初始化时验证所有必需字段
   - URL 格式检查
   - API 连通性测试

5. **资源管理**
   - 正确关闭定时任务
   - 注销索引器避免内存泄漏
   - 异常情况下也能清理资源

6. **用户体验**
   - 清晰的配置表单
   - 实时状态显示
   - 索引器列表页面
   - 友好的错误提示

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

- [MoviePilot](https://github.com/jxxghp/MoviePilot) - 优秀的媒体库管理工具
- [Prowlarr](https://github.com/Prowlarr/Prowlarr) - 强大的索引器管理器
- [Jackett](https://github.com/Jackett/Jackett) - 经典的索引器代理

## 支持

如遇到问题或有改进建议，欢迎：
- 提交 Issue
- 发起 Pull Request
- 参与讨论

---

**版本**: 0.1.6
**作者**: Claude
**最后更新**: 2026-02-12
