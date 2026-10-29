# 资料终端：GUI 与 TUI

源码版本：2.10.8。首次启动 GUI 时自动使用默认 `resources` 目录；源码和便携版默认位于程序目录内，`.deb` 版默认位于当前用户的 `~/.local/share/m3-reader/resources/`。自定义目录可在安装向导或 GUI「导入 → resources 目录」设置。`.deb` 可用 `M3_READER_HOME` 指定用户数据根。
如通过非编辑模式安装，将 `M3_READER_HOME` 设为包含 `resources/` 的项目目录。

## 安装与启动

CLI 不需要 pip 或虚拟环境。在项目根运行一次：

```bash
bash scripts/install_cli.sh
```

它会在 `~/.local/bin` 建立 `m3-reader` / `m3-reader-gui` 软链接（不复制代码），
之后可在任意终端目录运行 `m3-reader update`、`m3-reader gui`、`m3-reader tui`。
Linux 源码/便携安装会将 `~/.local/bin` 写入 Bash 启动配置；新开终端即可使用。
`.deb` 版由 `/usr/bin/m3-reader` 提供入口。Windows 安装向导会把所选程序目录下的
`bin\windows` 加入当前用户 PATH；安装后新开 PowerShell 或 CMD 即可直接运行相同命令。
项目移动或外置盘重新挂载后，重新运行该脚本即可。默认使用系统 `python3`
（需要 `click`，Ubuntu 可 `sudo apt install python3-click`）；
`M3_READER_PYTHON` 可指定解释器，`M3_READER_HOME` 可指定包含 `resources/` 和 `workspace/` 的数据根目录；启动脚本始终按自身位置定位源码。

需要隔离依赖时，可再建立虚拟环境并安装可选依赖：

```bash
python -m venv .venv
# Windows: .venv\Scripts\python -m pip install -e ".[all]"
# Ubuntu:  .venv/bin/python -m pip install -e ".[all]"
```

GUI 基于 PySide6，TUI 基于 prompt_toolkit。原有 `python prts_crawler.py` 入口继续可用。

### Ubuntu 依赖

本机使用的系统组件（一次性安装）：

```bash
sudo apt install python3-click python3-prompt-toolkit \
  python3-pyside6.qtcore python3-pyside6.qtgui python3-pyside6.qtwidgets \
  python3-pyside6.qtsvg python3-pyside6.qtnetwork \
  python3-pyside6.qtpdf python3-pyside6.qtpdfwidgets \
  tesseract-ocr tesseract-ocr-chi-sim poppler-utils fonts-noto-cjk
```

| 组件 | 用途 |
| --- | --- |
| `python3-click` | CLI 采集命令 |
| `python3-pyside6.qtcore/qtgui/qtwidgets/qtsvg/qtnetwork/qtpdf/qtpdfwidgets` | GUI 与 PDF 阅读（Qt 包按模块拆分，QtPdf 缺失时 GUI 会启动失败） |
| `python3-prompt-toolkit` | TUI 资料终端 |
| `tesseract-ocr` + `tesseract-ocr-chi-sim` | 《大地巡旅》OCR（中文） |
| `poppler-utils` | `pdftoppm` / `pdftotext`，OCR 与 PDF 检查 |
| `fonts-noto-cjk` | 中文显示；GUI 首选 `Maple Mono NF CN`，未安装时回退到 Noto |
| `python3-venv`、`python3-pip` | 可选，隔离环境 |
| `pyinstaller` | 可选，重新打包 `bin/` 与 `installpacks/` |

给其他设备使用的安装包见项目根目录 `installpacks/README.md`。Windows 运行
`m3-reader-*-windows-x64-setup.exe`，向导可分别选择安装目录和 `resources` 目录；升级时默认选中旧目录，
保留 `resources/` 和 `workspace/`。Ubuntu 可用 `sudo apt install ./m3-reader_*_amd64.deb`
安装或升级；也可解压便携包并运行 `bash scripts/install_ubuntu_portable.sh`，再次运行会升级程序。
源码包运行 `bash scripts/install_ubuntu.sh`。
这些包不带现有采集文本、OCR、用户文档和意见。

GUI 会优先使用 `Maple Mono NF CN`；
TUI 的字体由终端设置，请将终端字体设为 Maple Nerd Font。GUI 的深色绿色调取自本机
Notepad++ DarkModeDefault 主题的正文、行号、当前行和搜索配色。

## 阅读与维护

GUI 左侧目录树可按文件或目录名筛选；点击打开文本、长图或 PDF。Markdown 默认格式化
显示，使用「视图 → Markdown 格式化显示」（`Ctrl+M`）在格式化和带行号源码之间切换。
恢复阅读位置仍保持格式化；从检索结果跳到具体行仅让当前文件临时切到源码，便于核对行号，后续文件仍默认格式化。文本可用 `Ctrl+F` 查找、`F3`
查下一个；`Ctrl+Shift+F` 全库检索打开阅读区的检索结果标签，左侧为资源树，
中间每条结果用完整路径与出处、正文两行展示。右侧标签整行可点击：按下表示包含该类，未按下表示不限定；“显示全部”临时忽略标签但保留当前选择，“清空已选”一次性取消选择；「干员」匹配干员目录下的文件。
全局搜索框旁的「文件格式」是勾选菜单，可同时选择多种格式；文本格式（Markdown、
纯文本、CSV、TSV）默认勾选，PDF、JPEG、PNG、WebP、GIF、BMP 默认不勾选，以免无谓扫描。
PDF 和图片按文件名匹配；OCR 正文仍在文本资源中检索。菜单底部提供「仅文本格式」
「全选」「清空」；未勾选任何格式时不会开始检索。来源由右侧标签筛选，按钮颜色区分选中状态。
检索结果标签页仍可用顶部文件内查找、`Ctrl+F` 或 `find 关键词` 二次定位，`F3` 查找下一个。
命中数量显示在标签标题和状态栏；单击普通命中直接定位原文，PDF 须点击独立链接。
文件名命中优先显示。双击命中可打开文件并定位行。《大地巡旅》OCR 命中可打开 PDF
对应页。文本默认自动换行，可在「视图」切换，并用 `Ctrl+滚轮` 缩放字体。
文本阅读器左侧显示绝对行号，当前行号高亮。图片使用 `Ctrl+滚轮` 缩放，PDF 顶部输入页码跳转。
启动时右侧的「本地更新意见」和「变动栏」默认隐藏。顶部菜单左侧依次是「导入」
（在线采集、本地资料、resources 目录）、「阅读」、「检索」、「工具」（Vim、命令栏、变动栏）、
「视图」（自动换行、Markdown）、「外观」（字号 → 阅读字号/任务栏字号；主题 → 经典/柔亮/深海蓝/暖棕/夜紫/赤铜）和「帮助」（更新意见）；
搜索与程序版本在菜单下方靠右的工具栏。大字号时搜索控件自动分行，菜单始终保留完整空间。
GUI 的按钮、输入框、页签和菜单采用圆角；切换普通阅读页时有短时淡入，图片、PDF 与超长文本跳过效果。
主题选择保存在用户配置中。切换 resources 后，新窗口显示就绪才关闭当前窗口；启动失败保留当前窗口。
「工具 → 变动栏」打开逐行更新历史。单击目录时会打开该目录合适的最高层索引。
GUI 文本阅读支持只读 Vim：h/j/k/l、0/$、w/b、gg/G、数字前缀、Ctrl+D/U/B、
/ 搜索、n/N/`,` 和 :行号。按 Ctrl+L 可显示或隐藏底部命令栏；隐藏后 Vim 阅读仍可使用。
显示命令栏时，Vim `:` 和 `/` 共用命令栏；`find` 在当前原文或检索结果中定位。
`Alt+1/2/3` 分别将焦点移至目录、当前阅读或检索结果、命令栏；`Alt+3` 会打开隐藏的命令栏。
命令栏中 Tab 补全命令名，↑/↓ 浏览已执行命令。
命令栏支持 `font size 16`（阅读字号 8–40 pt）、`font menu 14`（任务栏字号 8–32 pt）、
`markdown source|render`、`search --scope local 关键词`、
find/search/jump/update/preview/images/history/diff/notes/note/save/page/
open/import/replace/resume/next/prev/back/help/quit。阅读位置保存在本地
`workspace/reading.json`，可由「阅读 → 继续阅读」或 `resume` 回到上次的位置。
程序图标使用项目 `assets/icon.png`。

更新区可选择模块与 changed/missing/force，先“预览”或点击“更新”。点击更新会选择
“纯文本”（当前模块）或“完整资料”（全部可采集文本，随后下载 terra 图片）。
本地 PDF 与 OCR 不属于爬虫拉取范围；terra 图片也可用独立按钮下载。
CLI 可用 `m3-reader update --images` 执行文本和图片两阶段更新。
底部显示任务输出；右侧“逐行更新历史”列出每次运行和实际变化。双击变化查看差异，
差异显示旧、新行号及增删颜色，双击新增或上下文行跳到当前文件。删除行留在差异中阅读。
历史从 2.3.0 起的运行开始；
旧 `new/` 不能恢复更早的逐行历史。

“更新意见”是项目本地的 `workspace/更新意见.md`。GUI 右侧可直接编辑并用 `Ctrl+S`
保存，无需先打开资源。TUI 可用 `note 内容` 直接追加；不带参数的 `note` 会显示
`note:` 提示，输入后回车保存，直接回车退出；多行内容可用 `note+` 续写后 `save`。
也可用任意文本编辑器修改该文件。旧版 `notes.json` 保留供查阅。
“导入本地资料”复制文件到所选 `resources/local/`；“替换当前本地资料”会备份旧文件并记录历史。
“导入 → resources 目录”可查看位置、切换目录、校验后移动整个目录，或把已有目录导入当前目录。导入遇到同名不同内容的文件会停止且不覆盖；移动完成后程序会重启。目录选择保存在当前用户的设置中，爬虫与 GUI 使用同一位置。也可用 `M3_READER_RESOURCES` 临时覆盖。
采集文本、terra 图文和 OCR 资料分别由各自更新方式维护。
`operator` 会将 PRTS 干员语音页的多语言台词保存为各干员目录下的 `语音记录.txt`。
`external-story` 将 ORACLE_DATABASE 的 PV1–PV4 等解谜页面保存至采集资源的 `外部剧情/解谜档案/`，另将《记录者的故事》《大拓荒周报》《午间邮报特刊》保存至 `外部剧情/世界观文本/`。两类均可按页面修订号增量刷新，并可用右侧标签筛选。
资源树对内部采集模块显示中文名称。剧情数据仍保存在独立的采集模块中；旧版主线章节
与特殊活动目录会自动迁移为 `主线/第01章…`、`特殊/四月辑录/…`、
`特殊/危机合约/…`、`特殊/荷谟伊智境/…`，清单与索引随之更新。

TUI 顶部直接显示资源目录和「阅读区」两个面板，不再额外占一行显示重复横幅。
左侧目录限宽，右侧阅读区占余下宽度，阅读区左侧显示绝对行号。启动后焦点直接在
命令栏；目录区输入任意字符会回到命令栏，阅读区是只读 vim 模式，用 `:` 或 `Alt+3`
回到命令栏。`Alt+1` / `Alt+2` / `Alt+3` 切换目录 / 阅读 / 命令，`Alt+←` / `Alt+→`
循环焦点。
命令栏中 `Tab` 补全（唯一匹配立即生效），`Enter` 执行并清空，`Backspace` 编辑，
`Ctrl+U` / `Ctrl+C` 清空，`↑`/`↓` 或 `Ctrl+P` / `Ctrl+N` 翻历史，`Esc` 取消补全或
参数输入。
阅读区 vim 操作不需要 Enter：`h`/`j`/`k`/`l` 移动，`0`/`$` 行首尾，`w`/`b` 词移动，
`gg`/`G` 文件首尾，`3G` 第 3 行，`5j`/`2k` 按行移动，`Ctrl+D` / `Ctrl+U` 半页，
`Ctrl+B` 上翻一页，`n`/`N`/`,` 查下一个或上一个匹配，`/` 查找，`?` 帮助，空格下翻，
`Ctrl+O` 返回上一个页面；不提供 `a`/`i`/`x`/`r` 等修改源文件的操作。
`back` 命令返回上一个打开的页面（文档、搜索结果、历史/差异/帮助等），阅读区
`Ctrl+O` 等价；页面栈最多保留 50 层，更新进行中暂不允许返回。
`next` 打开当前文件所在目录的下一个文件（按目录树顺序）；到达末尾时提示
“已经是本目录最后一个文件”。
`find`、`search`、`jump`、`go`、`run`、`diff`、`page`、`note`、`note+`、`import`、
`replace` 省略参数时会显示 `命令:` 提示，输入后回车执行，直接回车退出。
全库搜索结果每条占两行：第一行是文档路径与行号，第二行是匹配内容；`↑`/`↓` 选择，
`Enter` 直接打开对应文档并跳到该行，输入字符或按 `:` 回到命令栏。
`find` 与 `/` 则在当前文档直接定位并返回阅读区；`n`/`N`/`,` 可继续查找。
`Ctrl+F`、`Ctrl+G`、`Ctrl+H`、`Ctrl+N` 在目录或阅读区分别打开查找、全库搜索、历史、
写意见；命令栏中这些键保持终端编辑习惯。
`update` / `preview` / `images` 接受模块、模式，以及 `--force` / `--missing` /
`--dry-run`、`-m` / `--mode`。更新时状态栏实时显示用时、输出行数和最后一行，
`Ctrl+C` 取消；命令失败会以黄色/红色留在状态栏，并给出参数范围或相近命令提示。
命令栏输入 `help` 可查看完整命令。终端无法统一显示图片/PDF 像素，`open` 交给系统
查看器（Windows 默认程序、Linux `xdg-open`/`gio`）；《大地巡旅》可用 `page 页号`
直接阅读对应页 OCR。

### 资源占用

- GUI 资源树启动时只创建顶层节点，展开目录时才生成子项；筛选只构建匹配分支。
- 图片标签页只保留当前可见图片的解码结果，切走后释放，切回时按原缩放比例重载。
- 《大地巡旅》PDF 使用本地 `images/page_XXXX.jpg` 逐页显示（当前页一张图），不把整本
  ~400 MB 扫描件载入内存；其他 PDF 仍使用 QtPdf。页码输入、上一页/下一页、缩放、
  搜索命中跳页与续读位置保持不变。
- TUI 的 `back` 对已打开文档保存路径与行号，返回时从磁盘重开，不长期保留多份全文。
- 构建脚本排除未使用的 Qt3D / Quick / WebEngine / Multimedia 等模块，Ubuntu 版使用
  `--strip`；需重新构建才能得到更小的可执行文件。TUI 的 `search --scope local 关键词` 可限定来源（all、collected、
local、ocr）；`markdown source|render` 可切换 Markdown 源码与表格按阅读区宽度对齐、折行的终端排版；折行后的屏幕行仍可跳回原文行号。
`font size N`、`font reader N`、`font menu N` 会提示在终端程序里调整字号；
终端字体不受 TUI 控制。

## 平台检查

独立可执行程序在各自系统上构建，运行时不需要用户手动输入 Python 命令。
构建机先安装 `.[all]` 与 `pyinstaller`（Windows 图标转换还需 `pillow`），然后运行：

```powershell
# Windows 构建机
powershell -File scripts/build_windows.ps1
```

```bash
# Ubuntu 构建机
bash scripts/build_ubuntu.sh
```

Windows 双击 `bin/windows/m3-reader-gui.exe`，Ubuntu 双击或从应用菜单启动
`bin/ubuntu/m3-reader-gui`。同目录的 `m3-reader.exe` 或 `m3-reader`
是命令行程序，可直接运行 `gui`、`tui`、`update` 等子命令。
两个程序应保持在对应 `bin/平台/` 目录中，以便读取项目根的 `resources/`
与 `workspace/`，并让 GUI 的更新功能找到同目录 CLI。

Windows 上已验证 GUI 初始化、文本、图片及 454 页 PDF 打开与页码定位，并验证 TUI 启动。
Windows 与 Ubuntu 使用同一套 GUI/TUI 源码，但安装包分别只包含本平台程序。
2.10.1 的 Linux CLI/GUI、便携包与 `.deb` 在 Ubuntu 26.04 构建，并完成离屏 GUI 启动、
便携版重复安装保留资料及 `.deb` 解包检查。Windows 2.10.1 向导已在 Windows 编译，
并通过独立安装目录、自定义 resources 路径、PATH 与升级保留资料的 CI 检查；
其他 Linux 发行版和桌面会话仍需实际验证。没有图形桌面时可继续使用 CLI/TUI。



