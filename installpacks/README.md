# M3 Reader 安装包

新版本在 Windows 和 Linux 分别构建；安装包不包含采集结果、OCR、手动资料、阅读位置或更新意见。当前源码版本为 2.10.3。Windows 向导已在本机生成；Linux 2.10.3 独立包由远程 CI 构建，本机尚未同步。新包成功生成后打包脚本会移除同平台旧归档。

| 平台 | 安装包 | 安装和升级 |
| --- | --- | --- |
| Windows x64 | `windows/m3-reader-2.10.3-windows-x64-setup.exe` | 运行安装向导，可分别选择程序与 resources 目录。再次运行会检测旧安装目录并替换程序；`resources/`、`workspace/` 保留。 |
| Ubuntu/Debian amd64 | `debian/m3-reader_2.10.3_amd64.deb` | `sudo apt install ./m3-reader_2.10.3_amd64.deb`；后续用同名包的新版升级。用户资料默认在 `~/.local/share/m3-reader/`。 |
| Ubuntu 便携 | `debian/m3-reader-2.10.3-ubuntu-x64-portable.tar.gz` | 解压并运行 `bash scripts/install_ubuntu_portable.sh`；再次运行原地更新。 |
| Ubuntu 源码 | `debian/m3-reader-2.10.3-ubuntu-source.tar.gz` | 解压并运行 `bash scripts/install_ubuntu.sh`；需要 Python 3.10+、pip 和依赖下载。 |

Windows 向导可识别同一 AppId 的旧安装，也会检查旧版安装脚本所建的桌面、开始菜单快捷方式。`resources` 可直接选择旧目录并保留现有文件；更改程序安装目录时，原位置的用户资料不会删除。Linux 便携脚本指定 `M3_READER_INSTALL_DIR` 可改位置，并会复制旧目录中缺失的资料，不覆盖目标已有文件。两端 GUI 均可在「导入 → resources 目录」切换资料位置。
Windows 向导会将所选程序目录的 `bin\windows` 加入当前用户 PATH，卸载时只移除自己的条目；新开终端可直接运行 `m3-reader gui` 或 `m3-reader tui`。Linux 源码/便携安装会把 `~/.local/bin` 加入 Bash 登录和交互配置；`.deb` 的命令位于 `/usr/bin`。

`.deb` 的程序位于 `/opt/m3-reader/`，启动命令位于 `/usr/bin/`；包管理器只管理程序文件。已有便携或源码安装的 `~/.local/bin/m3-reader` 软链接可帮助 `.deb` 启动器定位原资源目录。若旧软链接优先于 `/usr/bin`，终端中可直接运行 `/usr/bin/m3-reader` 或删除旧软链接。卸载 `.deb` 不删除用户资料。

本地 Linux 二进制在 Ubuntu 26.04 构建，`.deb` 的 `libc6` 依赖按构建环境设置；便携版也应在目标发行版实际验证。需要支持较旧系统时，请在目标兼容基线系统上重新构建。

更新版本后，在对应平台先构建可执行程序，再运行 `python scripts/package_installpacks.py --platform windows` 或 `--platform ubuntu`。脚本检查程序版本，避免把旧程序标为新版本；新包全部成功后才清理旧归档。`SHA256SUMS.txt` 用于校验发布文件。
