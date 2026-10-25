# 资料终端：GUI 与 TUI

程序版本：2.5.3。资源默认位于项目内的 `resources/`；从其他工作目录启动仍按程序位置定位。
如通过非编辑模式安装，将 `M3_READER_HOME` 设为包含 `resources/` 的项目目录。

## 安装与启动

CLI 不需要 pip 或虚拟环境。在项目根运行一次：

```bash
bash scripts/install_cli.sh
```

它会在 `~/.local/bin` 建立 `m3-reader` / `m3-reader-gui` 软链接（不复制代码），
之后可在任意终端目录运行 `m3-reader update`、`m3-reader gui`、`m3-reader tui`。
项目移动或外置盘重新挂载后，重新运行该脚本即可。默认使用系统 `python3`
（需要 `click`，Ubuntu 可 `sudo apt install python3-click`）；
`M3_READER_PYTHON` 可指定解释器，`M3_READER_HOME` 可指定项目根。

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

给其他设备使用的最小包见项目根目录 `installpacks/README.md`。Windows 包解压后双击
`install_windows.cmd` 即可安装并创建桌面、开始菜单快捷方式；也可直接运行便携版 GUI。
Ubuntu 源码包解压后运行一次 `bash scripts/install_ubuntu.sh`，随后可在应用菜单启动 GUI。
这些包不带现有采集文本、OCR、用户文档和意见。

GUI 会优先使用 `Maple Mono NF CN`；
TUI 的字体由终端设置，请将终端字体设为 Maple Nerd Font。GUI 的深色绿色调取自本机
Notepad++ DarkModeDefault 主题的正文、行号、当前行和搜索配色。

## 阅读与维护

GUI 左侧目录树点击打开文本、长图或 PDF。文本可用 `Ctrl+F` 查找、`F3` 查下一个；
`Ctrl+Shift+F` 全局搜索，双击命中可打开文件并定位行。《大地巡旅》OCR 命中可打开 PDF
对应页。文本默认自动换行，可用工具栏开关切换，并用 `Ctrl+滚轮` 缩放字体。
图片使用 `Ctrl+滚轮` 缩放，PDF 顶部输入页码跳转。
启动时右侧的「本地更新意见」和「变动栏」默认隐藏；顶部工具栏的「变动栏」可勾选
打开逐行更新历史，「更新意见」按钮打开意见栏。

更新区可选择模块与 changed/missing/force，先“预览”或点击“更新”。点击更新会选择
“纯文本”（当前模块）或“完整资料”（全部可采集文本，随后下载 terra 图片）。
本地 PDF 与 OCR 不属于爬虫拉取范围；terra 图片也可用独立按钮下载。
CLI 可用 `m3-reader update --images` 执行文本和图片两阶段更新。
底部显示任务输出；右侧“逐行更新历史”列出每次运行和实际变化。双击变化查看差异，
差异显示旧、新行号及增删颜色，双击新增或上下文行跳到当前文件。删除行留在差异中阅读。
历史从 2.3.0 起的运行开始；
旧 `new/` 不能恢复更早的逐行历史。

“更新意见”是项目本地的 `workspace/更新意见.md`。GUI 右侧可直接编辑并用 `Ctrl+S`
保存，无需先打开资源。TUI 可用 `note 内容` 追加，也可用任意文本编辑器修改该文件。
旧版 `notes.json` 保留供查阅。
“导入本地资料”复制文件到 `resources/local/`；“替换当前本地资料”会备份旧文件并记录历史。
采集文本、terra 图文和 OCR 资料分别由各自更新方式维护。

TUI 左侧目录限宽，右侧阅读区占余下宽度。启动后焦点直接在命令栏，输入命令即可；
在目录或阅读区敲任意字符也会回到命令栏。`Tab` 在目录与阅读间切换，命令栏中 `Tab`
补全（唯一匹配立即生效）；`Enter` 执行当前行，`Backspace` 编辑，`Ctrl+U` / `Ctrl+C`
清空，`↑`/`↓` 或 `Ctrl+P` / `Ctrl+N` 翻历史，`Esc` 清空或返回目录。
`PageUp` / `PageDown`（阅读区也可用空格）滚动阅读区；目录或阅读区按 `/` 直接查找，
`?` 显示帮助。
`Ctrl+F`、`Ctrl+G`、`Ctrl+H`、`Ctrl+N` 在目录或阅读区分别打开查找、全库搜索、历史、
写意见；命令栏中这些键保持终端编辑习惯。
命令栏支持 `Tab` 补全和 `↑`/`↓` 翻历史；`update`/`preview`/`images` 接受模块、模式，
以及 `--force`/`--missing`/`--dry-run`、`-m`/`--mode`。更新时状态栏实时显示用时、
输出行数和最后一行，`Ctrl+C` 取消；命令失败会以黄色/红色留在状态栏，并给出参数范围
或相近命令提示。
命令栏输入 `help` 可查看 `go`、`run`、`diff`、`page`、`open`、`import` 和 `replace` 用法。
终端无法统一显示图片/PDF 像素，`open` 交给系统查看器（Windows 默认程序、Linux
`xdg-open`/`gio`）；《大地巡旅》可用 `page 页号` 直接阅读对应页 OCR。

## 平台检查

独立可执行程序在各自系统上构建，运行时不需要用户手动输入 Python 命令。
构建机先安装 `.[all]` 与 `pyinstaller`，然后运行：

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
Ubuntu 启动脚本和源码使用跨平台路径及 Qt / prompt_toolkit API；尚需在 Ubuntu 实机验证
桌面会话、字体和系统 PDF 查看器。没有图形桌面时可继续使用 CLI/TUI。



