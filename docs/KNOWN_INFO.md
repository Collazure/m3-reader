# 已知信息与待验证事项

文档版本：1.4；最近核实：2026-10-25。
维护规则：记录证据位置和核实日期；实现后更新状态，区分现状、设计和待验证事项。

## 已核实事实

| 编号 | 信息 | 证据 / 影响 |
| --- | --- | --- |
| K01 | 工程代码由 Git 仓库管理（2026-10-25 于 m3-reader/ 初始化）；resources/ 采集资料、workspace/ 运行数据与 bin/、installpacks/ 产物被忽略 | .gitignore；内容历史依赖 Git 提交，资源可重新采集 |
| K02 | 当前版本为 2.5.2 | prts_tool/__init__.py、pyproject.toml、CHANGELOG.md |
| K03 | CLI 使用 click，采集器按注册表发现；GUI/TUI 共用资源、搜索、历史和意见服务 | prts_tool/cli.py、registry.py、library.py、history.py、jobs.py |
| K04 | 支持 changed / missing / force 和 dry-run | registry.py、cli.py；GUI/TUI 已沿用这些模式 |
| K05 | 普通 update 不下载 terra 图片，图片有 terra-images 独立命令 | README、cli.py、collectors/terra.py |
| K06 | resources/updates/new/ 只保留最近一次实际写入内容，路径压缩到直接父目录，同名会编号 | latest.py；不能反推出 2.3.0 之前的完整多次历史 |
| K07 | LatestCapture 保留最近一次写入副本；history.py 独立保存每次运行的旧新文本与完整路径 | latest.py、history.py；图片按内容哈希比较 |
| K08 | write_text 跳过相同内容，可忽略抓取时间变化 | output.py；历史也需区分正文变化和时间元数据变化 |
| K09 | 资源规模：prts_text 下 4916 个文件，terra 下 238 个文件，其中图片 169 张 | 2026-10-25 文件清点；计数含索引等辅助文件，不等同于正文数量 |
| K10 | prts_text 与 terra 中此次清点无 PDF | 《大地巡旅》PDF 现位于 resources/local/大地巡旅/；按本地原件维护 |
| K11 | 《大地巡旅》PDF 约 418 MB，454 页，没有文字层 | docs/OCR_README.md；GUI 按需加载，全文搜索使用关联 OCR |
| K12 | 《大地巡旅》有合并 OCR、逐页文本及页清单；449 页有可识别正文 | resources/local/大地巡旅/大地巡旅_OCR.txt、同目录 OCR_pages/；可按页映射搜索结果 |
| K13 | terra_text 是 terra 图片的 OCR 派生 Markdown，带来源图片链接 | resources/ocr/terra_text/；相对链接已随迁移修复 |
| K14 | 同名“大地巡旅”也出现在可采集 terra 微博条目中 | resources/collected/terra/其它档案/ 下四期目录；整本 PDF 与微博条目维护方式不同 |
| K15 | 旧 README 已有十项采集和 OCR 已知问题 | README 第 8 节；迁移文档时保留原有事实和维护约定 |
| K16 | DarkModeDefault 主题正文为 #A8CFA7 / #1F2329，默认字体为 Maple Mono NF CN、14 点 | 用户 APPDATA/Notepad++/themes/DarkModeDefault.xml；GUI 采用该配色，尚未确认用户当前启用的主题 |
| K17 | 默认采集根已改为 resources/collected/，Python 程序仍在 prts_tool/，旧 Arknights 资源已迁移 | prts_tool/paths.py、resources/README.md；默认路径与工作目录无关 |
| K18 | Windows GUI 已初始化并打开文本、terra 图片及 454 页《大地巡旅》PDF，PDF 页码跳转正常 | 2026-10-25 PySide6 本机运行验证；无窗口渲染缺少中文字体，正常 Windows Qt 字体库可识别 Maple Mono NF CN |
| K19 | TUI 已在 Windows PTY 启动；共享层的搜索、历史和本地导入替换经过测试 | 2026-10-25；入口和操作说明见 docs/APP_README.md |
| K20 | 非采集资料统一位于 resources/local/，《大地巡旅》OCR 默认位置随 PDF 一并调整 | prts_tool/paths.py、resources/README.md；爬虫更新只作用于 collected/ |
| K21 | 用户意见是可直接编辑的 workspace/更新意见.md，无需打开任何资源 | prts_tool/library.py、gui.py、tui.py；旧 notes.json 仅保留供查阅 |
| K22 | Windows 已构建并启动 GUI 和 CLI；Ubuntu 有独立构建入口，需在 Ubuntu 上构建验证 | bin/windows/、scripts/build_windows.ps1、build_ubuntu.sh、prts_tool/paths.py；冻结程序从 bin/平台/ 定位资源 |
| K23 | 项目名与 CLI 已改为 m3-reader，项目位于 /run/media/collazure/Static/texts/m3-reader | pyproject.toml、prts_tool/paths.py；`M3_READER_HOME` 可覆盖资源根 |
| K24 | installpacks 仅打包白名单内程序文件和空资源目录 | scripts/package_installpacks.py；已检查 Windows ZIP 与 Ubuntu tar.gz 无资源或工作区文件，并校验 SHA-256 |
| K25 | GUI 完整更新分两阶段：先刷新所有可采集文本，再下载 terra 图片；纯文本遵循当前模块 | prts_tool/jobs.py、gui.py；本地 PDF/OCR 不被爬虫抓取 |
| K26 | Windows 便携包解压后 CLI 与 GUI 可启动；Ubuntu 源码包解压后 CLI 可启动 | 2026-10-25 本机空资源包烟测；Ubuntu 安装脚本及桌面会话仍需在 Ubuntu 验证 |
| K27 | TUI 命令栏支持补全/历史、更新实时进度与 Ctrl+C 取消；GUI 启动默认隐藏意见和变动栏，顶部「变动栏」开关控制历史 | prts_tool/tui.py、gui.py；tests/test_tui.py、tests/test_gui_layout.py |

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

