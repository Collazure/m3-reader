# 资料终端：GUI 与 TUI

程序版本：2.5.1。资源默认位于项目内的 `resources/`；从其他工作目录启动仍按程序位置定位。
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

需要隔离依赖或使用 TUI 时，再建立虚拟环境并安装可选依赖：

```bash
python -m venv .venv
# Windows: .venv\Scripts\python -m pip install -e ".[all]"
# Ubuntu:  .venv/bin/python -m pip install -e ".[all]"
```

GUI 基于 PySide6，TUI 基于 prompt_toolkit。原有 `python prts_crawler.py` 入口继续可用。

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

TUI 左侧目录限宽，右侧阅读区占余下宽度。打开后左侧用方向键选目录或文件，
`Enter` 展开或阅读，`Tab` 切换焦点。
`Ctrl+F` 文件查找、`Ctrl+G` 全局搜索、`Ctrl+U` 更新、`Ctrl+H` 历史、`Ctrl+N` 写意见。
命令栏输入 `help` 可查看 `go`、`run`、`diff`、`page`、`open`、`import` 和 `replace` 用法。
终端无法统一显示图片/PDF 像素，`open` 交给系统查看器；《大地巡旅》可用 `page 页号`
直接阅读对应页 OCR。

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



