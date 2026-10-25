# M3 Reader 安装包

此目录仅放程序发布包，不存放采集结果、OCR、手动添加的资料、更新意见或历史。

| 包 | 用途 |
| --- | --- |
| `windows/m3-reader-2.5.0-windows-x64-portable.zip` | Windows 64 位便携版；解压后双击 `install_windows.cmd` 一键安装，或直接运行 GUI |
| `debian/m3-reader-2.5.0-ubuntu-source.tar.gz` | Ubuntu 源码安装版；解压后运行一次 `bash scripts/install_ubuntu.sh` |

Ubuntu 包需要 Python 3.10+、pip 和安装依赖时的网络连接。当前 Windows 环境无法构建或验证 Ubuntu 独立二进制；若需要，可在 Ubuntu 上运行 `bash scripts/build_ubuntu.sh`。

两个包均以空 `resources/` 和 `workspace/` 启动。首次采集后才生成资源内容；原设备的个人文件不会进入发布包。Windows 安装脚本再次运行时只替换程序文件，保留已采集资料和用户文件。`SHA256SUMS.txt` 可用于校验下载后的文件。

更新版本后运行 `python scripts/package_installpacks.py` 重建包；Windows 便携包要求先运行 `scripts/build_windows.ps1` 生成对应版本的可执行程序。
