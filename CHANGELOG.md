# 版本日志（CHANGELOG）

本文件记录会影响输出结构、增量判断或数据完整性的改动。
每次改采集器 / 加模块 / 清理旧数据时，请在这里补一条，并同步更新
`README_剧情爬虫.md` 的「维护、已知坑与版本日志」。

## 2.5.1 — 2026-10-25

* 新增免安装 CLI 启动器：`bash scripts/install_cli.sh` 在 `~/.local/bin` 建立
  `m3-reader` / `m3-reader-gui` 软链接，不依赖 pip 或虚拟环境；从任意工作目录
  运行仍使用项目内的 `resources/`。`M3_READER_HOME` 可覆盖项目根，
  `M3_READER_PYTHON` 可指定解释器。
* 命令行帮助的用法行统一显示为 `m3-reader`；README 与界面文档中的启动示例改为
  `m3-reader …`。
* 记录 Ubuntu 运行依赖：PySide6 的 QtPdf / QtPdfWidgets 与 QtNetwork、prompt_toolkit、
  tesseract（chi_sim）、poppler、中文字体；GUI 与 TUI 已在本机完成导入和启动烟测。
* `install_ubuntu.sh` 在没有可用 venv/pip 时回退到免安装启动器。

## 2.5.0 — 2026-10-25

* 项目更名为 M3 Reader，目录、发布包、CLI 命令、GUI 标题、构建程序和环境变量统一使用 `m3-reader` / `M3_READER_HOME`。
* 新增 `installpacks/` 最小安装包：Windows 便携版和 Ubuntu 源码安装版。发布包只包含程序与空资源目录，不含采集结果、OCR、个人文档、意见或历史。
* Ubuntu 源码包提供一次性安装脚本，安装后可从应用菜单启动 GUI，终端可直接运行 `m3-reader`。
* Windows 包提供双击安装脚本与桌面、开始菜单快捷方式。GUI 点击“更新”时选择纯文本或包含 terra 图片的完整采集；CLI 新增 `update --images`。

## 2.4.0 — 2026-10-25

* 非采集资料统一放在 `resources/local/`，包括《大地巡旅》PDF 与 OCR 和两份参考文本。
* 更新意见改为直接维护 `workspace/更新意见.md`，GUI 可独立编辑，TUI 无需先打开资源即可追加。
* GUI 文本默认自动换行，支持 `Ctrl+滚轮` 缩放字体；TUI 阅读区扩大。历史差异增加旧、新行号与增删颜色。
* 增加独立 CLI 与 GUI 可执行程序的 Windows、Ubuntu 构建入口；GUI 内的更新任务可调用同目录的 CLI 程序。

## 2.3.0 — 2026-10-25

* 新增 PySide6 GUI：资源树、带行号的绿色文本阅读、图片缩放、PDF 查看和页码跳转，
  文件内与全库搜索、采集任务、逐行差异、本地意见及本地资料导入替换。
* 新增 prompt_toolkit TUI，通过 `prts_crawler.py tui` 进入；支持树状浏览、阅读、
  搜索、更新、历史、意见和调用系统媒体查看器。
* 更新命令现在记录运行状态与变化前后文本，可直接显示逐行差异；
  本地资料替换保存旧版本。更新任务使用跨进程文件锁，防止并发写入。
* 新增 Windows / Ubuntu GUI 和 TUI 启动脚本、可选依赖声明与界面使用说明。
  程序版本更新为 2.3.0。

## 2.2.0 — 2026-10-25

### 资源目录

* 将采集文本、terra 图文、terra 图片 OCR、《大地巡旅》PDF 与 OCR、其他本地参考文本
  移入 `resources/`。采集结果归入 `collected/`，OCR、整本 PDF 与其他本地文本各自存放。
* 默认采集文本改为 `resources/collected/prts_text/`，terra 改为
  `resources/collected/terra/`。自定义 `--out` 时继续使用自定义根的兄弟 terra 目录。
* 最近写入副本移至 `resources/updates/new/`；OCR 源图链接随目录迁移修复。
* OCR 脚本移至 `prts_tool/ocr_book.py`，以 `python -m prts_tool.ocr_book` 运行；
  默认输入和输出均指向 `resources/大地巡旅/`。修复 terra_text 的 169 个原图链接，
  包括文件名括号的 URL 编码。
* 更新资源、OCR、已知信息和架构说明；程序版本更新为 2.2.0。

### 文档 — 2026-10-25

* 固化 GUI / TUI 全部需求，包括绿色明日方舟风格、Maple Nerd Font、左侧目录树、
  阅读、图片/PDF、文件内与全局搜索、逐行更新历史、Windows / Ubuntu 适配。
* 确认更新意见仅保存在本地；规划 Python 程序与阅读资源分开存放，允许调整目录，
  manifest 与索引继续跟随资源。
* 明确按来源和具体文件区分维护方式：PRTS 内容由采集器维护；《大地巡旅》整本 PDF
  作为本地导入资料；OCR 为关联原件的派生资料；同名 terra 微博条目仍可采集。
* 新增 docs/REQUIREMENTS.md、docs/KNOWN_INFO.md、docs/ARCHITECTURE.md，
  记录调研证据、已知限制和目标结构。GUI / TUI 尚未实现。

## 2.1.0 — 2026-10-24

### 新增

* **`activity` 模块**：抓取活动页面里不属于关卡剧情的正文，输出到
  `prts_text/activity/<活动名>/<子页面>.txt`。
  - 覆盖 `活动公告`（含 `分类:复刻活动` 的 45 个复刻页，如 `孤星2024`），
    以及综合调查数据库、审判庭纪要、待办事项记录、
    PRTS 金律记录、信息端口、PRTS 绿洲记录、日志、敌袭记录、剧情链等长文。
  - 典型补漏：`孤星/综合调查数据库`（克丽斯腾在静滞所终端里见到“神”/保存者的通信）、
    `叙拉古人/待办事项记录`、`崔林特尔梅之金/PRTS金律记录`、`愚人号/审判庭纪要`、
    `长夜临光/信息端口`、`沙中之火/PRTS绿洲记录`。
  - 用 `action=parse&prop=text` 取渲染后的 HTML，再由新增的
    `prts_tool/htmltext.py` 转纯文本，避免表格 / 样式语法污染。
  - 与 `avg` / `reclamation` / `roguelike` 去重：已由这些模块负责的页面不重复写。
* `prts_tool/htmltext.py`：HTML → 纯文本工具（丢弃目录、编辑链接、音频降级提示等）。

### 修复

* **干员密录重复**：`avg` 不再收录 `干员名/干员密录/N`。旧版误收在
  `avg/特殊 <干员>/` 的 394 个文件已由本次 `avg` 运行自动清理；
  内容仍完整保存在 `operator/<干员>/avgN-*.txt`。
  - `avg/_manifest.json` 条目 2242 → 1848。
  - 清理只删除清单里记录过、且 `operator/<干员>/` 已存在的文件；不认识的文件不碰。
* **肉鸽结局 part 重复**：过滤结局表里每张卡片都重复的装饰性文案
  （`探索走向了不同的结局……`、`我走入了不同的结局……`、`—— · ——`、
  HTML 注释 / 脚本残片、`css=…` 样式行），不再写进每个结局的 `partN.txt`。
  全库正文完全重复的文件从 394 组降为 0。
* **肉鸽刷新**：`沉沦者的黑流树海` 事件 36 → 39（补 3 个）；
  `萨卡兹的无终奇语` 关卡 56 → 57；`岁的界园志异` 关卡 73 → 74；
  各主题藏品 / 月度小队 / 加载文本按当前 wiki 版本增量更新。
* **集成战略道具图鉴**：`roguelike` 的「其他文本/」新增 8 个文件：
  思绪（萨卡兹·佚散思维辑录）、密文板（银凇止境·密文板研究）、
  通宝（岁的界园·藏钱木盒）、零件（黑流树海·引擎配件目录）、
  战术道具箱、活页剧目集、坍缩范式辑录、易与互动记录。
  这些页面用 `{{:主题/思绪|名称=…}}` 转写模板，原来的 `{{收藏品}}` 解析收不到。
* **链接清理**：`wikitext.clean_markup` 现在会整段丢弃 `[[文件:…]]` / `[[分类:…]]`
  并支持多段链接 `[[页|参数|显示名]]`；`extract_boxes` 跳过 `----` 分隔线。
  肉鸽「其他文本」里的 `[[文件:…|64px|link=]]`、`64px`、`----` 噪声已清除。
* **生息演算事件**：`reclamation` 新增「事件一览」解析，把
  `沙中之火/事件一览`（45 条）与 `沙洲遗闻/事件一览`（67 条）拆成
  `reclamation/<场次>/事件/<分类>/<事件名>.txt`。同名的多分支事件按
  `(分类, 事件名)` 合并、选项去重，共写出 **100 个事件文件**；
  事件描述与选项/结果文本不再漏采。

### 数据结果（2026-10-24 运行）

* `avg`：1848 条清单 / 1841 段有正文 / 113 个分组；`avg/特殊 <干员>` 已清空。
* `activity`：146 个文件 / 115 个活动（含复刻公告）；首轮 105 个，复刻补充 41 个。
* `roguelike`：7 个主题；事件 31/45/53/44/52/58/39；藏品 182/245/262/263/296/294/251；
  结局 part 去重；`沉沦者的黑流树海` 4 个结局全部保留。
* `reclamation`：16 段剧情 + 100 个事件文件（沙中之火 37 / 沙洲遗闻 63）。
* `prts_text` 全库正文完全重复：0 组。

### 文档

* README 新增活动模块说明、已知坑、日常维护流程、完整性检查命令。
* 新增本 `CHANGELOG.md`。

### 已知未完成

* `../Arknights/【Ark-α01】世界观设定集丨大地巡旅-Qingqiu.pdf` 是扫描件，没有文字层。
  2026-10-24 已安装 `tesseract-ocr` + `tesseract-ocr-chi-sim`，用 `Arknights/ocr_book.py`
  重跑全部 454 页：449 页有正文，合并为 `Arknights/大地巡旅_OCR.txt`（约 47.7 万字）。
  用法、质量与重跑方式见 `Arknights/OCR_README.md`。
* `activity` 的长文选取是名称启发式；新活动若用了全新的子页面名，可能漏收，
  见 README「已知坑」第 6 条。
* 以下文本类型仍未单独采集（wiki 上有，但不在当前模块范围）：
  - 干员语音记录（`干员名/语音记录`，`{{VoiceTable}}`）
  - 时装介绍（`{{CharinfoV2|时装N介绍=…}}`）
  - 道具描述（Cargo `item` 表）
  - 相关道具（干员页 `{{相关道具}}`）
  - 泰拉大典（ns 3000 世界观条目）
  - Cargo 里的基建技能 / 材料掉落等纯机制数据（一般不需要）
  需要时按 README 第 6 节新增采集器，或先加到「已知未完成」再排期。

## 2.0.0 — 2026-10-10

* 重构为 click 命令行：`avg` / `stage` / `operator` / `furniture` / `enemies` /
  `roguelike` / `reclamation` / `terra` / `update` / `refresh` / `info` / `fetch`。
* 采集器放在 `prts_tool/collectors/`，启动时自动发现并注册成子命令。
* 三种增量模式：`changed`（按 wiki revid）/ `missing`（只补缺失）/ `force`（全部重抓）。
* `new/` 保存最近一次实际写入的内容。
* `terra` 默认只写说明与索引，图片用 `terra-images` 单独抓。

## 2.0.0 之前

* 早期脚本 `prts_crawler.py` / `prts_story_crawler.py` 直接抓 avg 剧情；
  旧参数由 `prts_story_crawler.py` 兼容翻译到新 CLI。
