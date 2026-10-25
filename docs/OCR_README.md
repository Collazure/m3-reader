# 《大地巡旅》PDF OCR 说明

## 结论

* 源文件：`【Ark-α01】世界观设定集丨大地巡旅-Qingqiu.pdf`（454 页，约 418 MB，扫描件，**无文字层**）。
* 2026-10-24 用 `tesseract 5.5.0`（`chi_sim+eng`）重跑全部 454 页：
  - **449/454 页**有可识别正文（其余 5 页是整页插画/装饰页）；
  - 页面图：`images/page_XXXX.jpg`；
  - 逐页文本：`text/pages/page_XXXX.txt`；
  - **合并全文：`text/大地巡旅_OCR.txt`**（约 47.7 万字符，1.2 MB，带页码分隔，适合 `grep` / 全文检索）；
  - 页清单：`text/manifest.tsv`。

## 用法

```bash
# 在 m3-reader 根目录直接检索
rg -n '伊比利亚|源石' resources/local/大地巡旅/text/大地巡旅_OCR.txt

# 看某一页
rg -n '^===== 第 200 页 =====$' resources/local/大地巡旅/text/大地巡旅_OCR.txt

# 重新 OCR（增量：跳过已有非空 txt）
python -m prts_tool.ocr_book

# 全部重跑
python -m prts_tool.ocr_book --force --jobs 4

# 只重新合并，不 OCR
python -m prts_tool.ocr_book --merge-only
```

前置依赖：

```bash
sudo apt-get install tesseract-ocr tesseract-ocr-chi-sim poppler-utils
```

## 质量与已知坑

* 正文页识别率尚可，专有名词、人名、艺术字、竖排/彩色背景页会有错字；
  引用前建议对照原图（`images/page_XXXX.jpg`）。
* OCR 会在中文词之间插入空格、把标点识别成近似字符（如 `,` / `。`），
  全文检索时建议用短关键词，或同时试简繁/近形字。
* 页眉“大地巡旅 / TERRA: A JOURNEY”和页码会混进正文；`ocr_book.py` 只清理
  纯符号行，不强行去页眉，避免误删正文。
* 原 PDF 没有文字层，`pdftotext` 输出为空，必须 OCR。
* 页面图由早期步骤导出（454 张）；如果换机器只有 PDF，`ocr_book.py` 会自动用
  `pdftoppm -r 300` 重新渲染。
* 页面图与文本分开存放：`images/` 只放页面图，`text/` 放逐页 OCR、页清单与合并全文。
  旧版混放的 `大地巡旅_OCR_pages/` 会在运行 `python -m prts_tool.ocr_book` 时自动迁移。
* `resources/local/大地巡旅/text/pages/` 中的逐页 txt 是 OCR 原文；**不要手工编辑**，否则重跑会被覆盖。
  校对版应另存于本地意见或校对区。

## 与 m3-reader 的关系

这个 PDF 是外部设定集，不属于 prts.wiki 采集范围，所以没有做成 m3-reader 的
采集器；OCR 脚本位于 `prts_tool/ocr_book.py`，PDF 与 OCR 产物位于
`resources/local/大地巡旅/`，采集文本位于 `resources/collected/prts_text/`。


