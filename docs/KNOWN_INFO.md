# 已知信息与待验证事项

文档版本：1.6；最近核实：2026-10-26。
维护规则：记录证据位置和核实日期；实现后更新状态，区分现状、设计和待验证事项。

## 已核实事实

| 编号 | 信息 | 证据 / 影响 |
| --- | --- | --- |
| K01 | 工程代码由 Git 仓库管理（2026-10-25 于 m3-reader/ 初始化）；resources/ 采集资料、workspace/ 运行数据与 bin/、installpacks/ 产物被忽略 | .gitignore；内容历史依赖 Git 提交，资源可重新采集 |
| K02 | 当前源码版本为 2.10.5；TUI Markdown 表格按宽度排版、折行并映射原文行号 | prts_tool/__init__.py、pyproject.toml、CHANGELOG.md、markdown.py、tui.py；2026-10-27 |
| K03 | CLI 使用 click，采集器按注册表发现；GUI/TUI 共用资源、搜索、历史和意见服务 | prts_tool/cli.py、registry.py、library.py、history.py、jobs.py |
| K04 | 支持 changed / missing / force 和 dry-run | registry.py、cli.py；GUI/TUI 已沿用这些模式 |
| K05 | 普通 update 不下载 terra 图片，图片有 terra-images 独立命令 | README、cli.py、collectors/terra.py |
| K06 | resources/updates/new/ 只保留最近一次实际写入内容，路径压缩到直接父目录，同名会编号 | latest.py；不能反推出 2.3.0 之前的完整多次历史 |
| K07 | LatestCapture 保留最近一次写入副本；history.py 独立保存每次运行的旧新文本与完整路径 | latest.py、history.py；图片按内容哈希比较 |
| K08 | write_text 跳过相同内容，可忽略抓取时间变化 | output.py；历史也需区分正文变化和时间元数据变化 |
| K09 | 资源规模：prts_text 下 4916 个文件，terra 下 238 个文件，其中图片 169 张 | 2026-10-25 文件清点；计数含索引等辅助文件，不等同于正文数量 |
| K10 | prts_text 与 terra 中此次清点无 PDF | 《大地巡旅》PDF 现位于 resources/local/大地巡旅/；按本地原件维护 |
| K11 | 《大地巡旅》PDF 约 418 MB，454 页，没有文字层 | docs/OCR_README.md；GUI 按需加载，全文搜索使用关联 OCR |
| K12 | 《大地巡旅》有合并 OCR、逐页文本及页清单；449 页有可识别正文 | resources/local/大地巡旅/text/大地巡旅_OCR.txt、text/pages/；页面图在 images/；可按页映射搜索结果 |
| K13 | terra_text 是 terra 图片的 OCR 派生 Markdown，带来源图片链接 | resources/ocr/terra_text/；相对链接已随迁移修复 |
| K14 | 同名“大地巡旅”也出现在可采集 terra 微博条目中 | resources/collected/terra/其它档案/ 下四期目录；整本 PDF 与微博条目维护方式不同 |
| K15 | 旧 README 已有十项采集和 OCR 已知问题 | README 第 8 节；迁移文档时保留原有事实和维护约定 |
| K16 | DarkModeDefault 主题正文为 #A8CFA7 / #1F2329，默认字体为 Maple Mono NF CN、14 点 | 用户 APPDATA/Notepad++/themes/DarkModeDefault.xml；GUI 采用该配色，尚未确认用户当前启用的主题 |
| K17 | 默认采集根已改为 resources/collected/，Python 程序仍在 prts_tool/，旧 Arknights 资源已迁移 | prts_tool/paths.py、resources/README.md；默认路径与工作目录无关 |
| K18 | Windows GUI 已初始化并打开文本、terra 图片及 454 页《大地巡旅》PDF，PDF 页码跳转正常 | 2026-10-25 PySide6 本机运行验证；无窗口渲染缺少中文字体，正常 Windows Qt 字体库可识别 Maple Mono NF CN |
| K19 | TUI 已在 Windows PTY 启动；共享层的搜索、历史和本地导入替换经过测试 | 2026-10-25；入口和操作说明见 docs/APP_README.md |
| K20 | 非采集资料统一位于 resources/local/，《大地巡旅》页面图与 OCR 文本分存 images/ 与 text/ | prts_tool/paths.py、resources/README.md；爬虫更新只作用于 collected/ |
| K21 | 用户意见是可直接编辑的 workspace/更新意见.md，无需打开任何资源 | prts_tool/library.py、gui.py、tui.py；旧 notes.json 仅保留供查阅 |
| K22 | Windows 与 Ubuntu 2.10.4 CLI/GUI 均已构建；Ubuntu 二进制从已校验的 CI 便携包同步到本地 | bin/windows/、bin/ubuntu/、installpacks/debian/、scripts/build_ubuntu.sh；2026-10-27 |
| K23 | 项目名与 CLI 已改为 m3-reader，项目位于 /run/media/collazure/Static/texts/m3-reader | pyproject.toml、prts_tool/paths.py；`M3_READER_HOME` 可覆盖资源根 |
| K24 | installpacks 仅打包白名单内程序文件和空资源目录 | scripts/package_installpacks.py；已检查 Windows ZIP 与 Ubuntu tar.gz 无资源或工作区文件，并校验 SHA-256 |
| K25 | GUI 完整更新分两阶段：先刷新所有可采集文本，再下载 terra 图片；纯文本遵循当前模块 | prts_tool/jobs.py、gui.py；本地 PDF/OCR 不被爬虫抓取 |
| K26 | Windows 便携包解压后 CLI 与 GUI 可启动；Ubuntu 源码包解压后 CLI 可启动 | 2026-10-25 本机空资源包烟测；Ubuntu 安装脚本及桌面会话仍需在 Ubuntu 验证 |
| K27 | TUI 命令栏支持补全/历史、更新实时进度与 Ctrl+C 取消；GUI 启动默认隐藏意见和变动栏，顶部「变动栏」开关控制历史 | prts_tool/tui.py、gui.py；tests/test_tui.py、tests/test_gui_layout.py |
| K28 | TUI 启动焦点在命令栏；目录/阅读区控件层接管 `n`/`N`/`/`/`?`，保证任意字符都能开始命令 | prts_tool/tui.py；prompt_toolkit 只读缓冲默认绑定这些键为缓冲内搜索，须在控件层覆盖 |
| K29 | TUI 支持 Alt 焦点、单参数命令两步提示、两行搜索结果 Enter 打开、阅读区只读 vim 移动；TUI/GUI 均显示绝对行号 | prts_tool/tui.py、gui.py；tests/test_tui.py、tests/test_gui_layout.py |
| K30 | TUI `back` / 阅读区 `Ctrl+O` 返回上一个页面；页面栈保存文本、行号、选中资源、结果列表与 OCR 页码，最多 50 层 | prts_tool/tui.py；更新进行中拒绝返回，避免与流式输出冲突 |
| K31 | 泰拉年表由 activity 采集器顺带抓取并写到 prts_text/泰拉年表.txt；TUI `next` 打开同目录下一个文件；大地巡旅页面图与文本分存 | prts_tool/collectors/activity.py、ocr_book.py、tui.py；tests/test_activity_timeline.py、test_resource_paths.py、test_tui.py |
| K32 | 参考阅读器 ArkPlots-APP_Release 有本地阅读记录与前后导航；M3 Reader 已借鉴为共用 `reading.json`、续读和 GUI 前后导航 | reference/ArkPlots-APP_Release；prts_tool/reading.py、gui.py、tui.py；2026-10-26 |
| K33 | GUI/TUI 点击目录自动打开最高层合适索引，GUI 命令栏可独立于只读 Vim 开关隐藏 | prts_tool/library.py、gui.py、tui.py；tests/test_reading.py、test_gui_layout.py |
| K34 | Windows 与 Ubuntu GUI 共用 gui.py，差异仅在启动与打包脚本；图标放在 assets/icon.png | prts_tool/gui.py、paths.py、scripts/build_windows.ps1、build_ubuntu.sh；Ubuntu 实机显示仍待验证 |
| K35 | Markdown 由 Qt QTextBrowser 格式化显示，源码仍由带行号的只读 TextReader 提供；具体行跳转切换到源码 | prts_tool/gui.py；tests/test_gui_layout.py |
| K36 | 参考工程建议改进信息层级与检索；2.8.0 采用按文件归组、文件名优先、来源范围和树筛选 | reference/ArkPlots参考价值分析-m3-reader.md、WikiTransporter参考价值分析-m3-reader.md；prts_tool/library.py、gui.py、tui.py |
| K37 | GUI `font size N` 调整阅读字号；TUI 字号由所在终端控制，prompt_toolkit 无跨终端字体设置接口 | prts_tool/gui.py、tui.py；2026-10-26 |
| K38 | 资源树以中文显示内部采集模块；AVG 旧目录自动迁移，主线 0–9 章补零，四月辑录和特殊活动归入「特殊」；CLI 模块名仍保持兼容 | prts_tool/library.py、story_layout.py、collectors/avg.py；2026-10-26 |
| K39 | GUI 全库检索为阅读标签页，右侧标签支持包含与排除；当前目录依阅读位置确定，命中保持原文行号 | prts_tool/gui.py、library.py；2026-10-26 |
| K40 | GUI 任务栏和阅读字号独立；TUI 无权更改终端字体。`find` 在原文中定位；TUI Markdown 宽表格可折行，每个屏幕行映射回原文行号 | prts_tool/gui.py、tui.py、markdown.py；2026-10-27 |
| K41 | GitHub Actions 首次 Ubuntu 任务在导入 PySide6 时缺少 `libEGL.so.1`；工作流已增加 Qt 运行库安装步骤 | .github/workflows/build.yml；2026-10-26 |
| K42 | 检索命中改为可换行的富文本两行卡片；统计放标签/状态栏；普通命中只打开原文，PDF 显式选择；Markdown 定位按需渲染 | prts_tool/gui.py；2026-10-26 |
| K43 | Ubuntu CI 曾因 build_ubuntu.sh 中混入 CRLF 在打包末尾失败；.gitattributes 固定 shell 脚本 LF | .gitattributes、scripts/build_ubuntu.sh；2026-10-26 |
| K44 | GUI 全局检索的文件格式筛选为可多选勾选菜单（复选框）；文本默认开启，PDF/图片默认关闭且仅按文件名匹配；右侧标签用绿/暖红区分包含/排除 | prts_tool/gui.py、prts_tool/library.py；2026-10-26 |
| K45 | Qt 全局样式中的固定字号导致任务栏字号不一致；菜单与搜索区分行，放大时搜索控件再分两行 | prts_tool/gui.py；2026-10-26 |
| K46 | 轻量化：GUI 树按需展开、图片标签释放非活动 pixmap、大地巡旅 PDF 用页面图；TUI back 按路径重开；构建排除未用 Qt 模块 | prts_tool/gui.py、tui.py、scripts/build_*；实测启动 125→114 MB、5 图 203→131 MB、巡旅 PDF 525→127 MB、搜索后 241→159 MB |
| K47 | 更新历史仅把运行前快照写入临时磁盘数据库，结束时逐文件比较并清理；pytest 只收集项目测试 | prts_tool/history.py、jobs.py、pyproject.toml、tests/test_library_history.py；本机 5145 文件无变化对比，峰值约 84→35 MiB、耗时 0.91→1.12 秒；共用代码覆盖 Windows/Linux，跨平台 CI 已加入测试；2026-10-26 |
| K48 | 两端构建脚本先写暂存目录，构建成功后替换程序；模拟构建失败验证原二进制未变 | scripts/build_windows.ps1、scripts/build_ubuntu.sh；2.10.4 Windows/Ubuntu CI 构建与测试均通过；2026-10-27 |
| K49 | Windows 安装向导和 Linux 便携脚本支持升级并保留用户资源；`.deb` 只拥有程序文件，用户数据在个人目录 | scripts/windows_installer.iss、install_ubuntu_portable.sh、deb_launcher.sh、package_installpacks.py、tests/test_installers.py；CI 已验证 Windows 安装/升级、独立 resources 路径与 PATH，及 Ubuntu 便携重复安装和 `.deb` 解包；2026-10-26 |
| K50 | Windows 向导添加当前用户 PATH 并在卸载时移除自己的条目；Linux 源码/便携安装幂等设置 Bash 用户命令路径 | scripts/windows_installer.iss、scripts/ensure_user_path.sh；2026-10-26 |

## 待实现 / 待验证

| 编号 | 事项 | 处理方向 |
| --- | --- | --- |
| V01 | Ubuntu 上 Maple Mono NF CN 是否安装 | Windows Qt 字体库已识别此字体；TUI 字体由终端配置，Ubuntu 未实测 |
| V02 | Notepad++ 当前启用的主题与换行细节 | GUI 已按本机 DarkModeDefault 配色和字体实现；当前启用状态未核实 |
| V03 | Ubuntu 的发行版、显示环境和终端兼容性 | 已提供跨平台入口；待 Ubuntu 实机验证后记录版本 |
| V04 | 2.3.0 之前的多次更新历史不存在 | 新运行开始记录；不能伪造过去运行的逐行差异 |
| V05 | 持续运行时的大文件 PDF、长图和文本搜索性能 | 454 页 PDF 已打开；全局搜索在后台运行，长期使用性能仍待观察 |
| V06 | 旧版 notes.json 内意见可能失去原位置 | 旧结构化意见数据保留；新版意见文件由用户直接维护，可自行写入路径和行号 |
| V07 | 目录迁移可能影响外部脚本所写的旧路径 | 已改默认 CLI、terra 定位和 OCR 链接；外部自写脚本需按 resources/README.md 调整 |

本文件记录工程事实；采集运行产生的正文变更由内容历史管理；工程发布变化写入根目录 CHANGELOG.md。

