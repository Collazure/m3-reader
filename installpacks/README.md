# M3 Reader 安装包

此目录仅放程序发布包，不存放采集结果、OCR、手动添加的资料、更新意见或历史。

| 包 | 用途 |
| --- | --- |
| `windows/m3-reader-2.9.0-windows-x64-portable.zip` | Windows 64 位便携版；解压后双击 `install_windows.cmd` 一键安装，或直接运行 GUI |
| `debian/m3-reader-2.9.0-ubuntu-source.tar.gz` | Ubuntu 源码安装版；解压后运行一次 `bash scripts/install_ubuntu.sh` |
| `debian/m3-reader-2.9.0-ubuntu-x64-portable.tar.gz` | Ubuntu 64 位便携版；从仓库 Ubuntu 构建工作流生成，解压后运行 `bash scripts/install_ubuntu_portable.sh` 一键创建应用菜单入口 |

Ubuntu 源码包需要 Python 3.10+、pip 和安装依赖时的网络连接。Windows 本机不能构建 Linux 二进制；远程工作流在 Ubuntu 环境独立生成便携包。

各包均以空 `resources/` 和 `workspace/` 启动。首次采集后才生成资源内容；原设备的个人文件不会进入发布包。Windows 安装脚本再次运行时只替换程序文件，保留已采集资料和用户文件。`SHA256SUMS.txt` 可用于校验下载后的文件。

更新版本后运行 `python scripts/package_installpacks.py` 重建本机包；也可用 `--platform windows`、`ubuntu-source` 或 `ubuntu` 分别打包。
