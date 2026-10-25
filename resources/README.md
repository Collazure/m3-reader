# 资源目录

程序默认从本目录读取资源。以下路径均相对于 `m3-reader/`，源代码通过自身位置定位项目，
不依赖启动命令所在的工作目录。

| 路径 | 类型 | 维护方式 |
| --- | --- | --- |
| `resources/collected/prts_text/` | PRTS 文本及其 manifest、索引 | `prts_crawler.py update/refresh` 自动采集 |
| `resources/collected/terra/` | PRTS 泰拉记事社说明、长图及 manifest、索引 | `terra` 更新说明；`terra-images` 单独下载图片 |
| `resources/ocr/terra_text/` | terra 图片 OCR Markdown | 本地派生结果；与 `terra` 原图对应，不由爬虫重抓 |
| `resources/local/大地巡旅/` | 整本 PDF、逐页图和 OCR 全文 | 本地资源；`python -m prts_tool.ocr_book` 重跑 OCR |
| `resources/local/` | 其他原有剧情参考文本 | 本地维护 |
| `resources/updates/new/` | 最近一次采集写入内容副本 | 采集器自动替换 |

`大地巡旅` 整本 PDF 与可采集的同名 terra 微博图文是不同资源。
原同级 `Arknights/` 中的 Python OCR 脚本已移入 `prts_tool/`，其说明在 `docs/OCR_README.md`。
更新意见保存在本地 `workspace/更新意见.md`，不写入采集文本或 OCR 文件。


