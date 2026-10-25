#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""把扫描版《大地巡旅》PDF OCR 成可检索的纯文本。

前置：
    sudo apt-get install tesseract-ocr tesseract-ocr-chi-sim
    # 页面图已由早期步骤导出到 大地巡旅_OCR_pages/page_XXXX.jpg
    # 若页面图缺失，本脚本会用 pdftoppm 重新渲染（需要 poppler-utils）。

用法：
    python -m prts_tool.ocr_book                 # 增量：只 OCR 还没有非空 txt 的页面
    python -m prts_tool.ocr_book --force         # 454 页全部重跑
    python -m prts_tool.ocr_book --jobs 6        # 并行数（默认 4）
    python -m prts_tool.ocr_book --merge-only    # 不 OCR，只重新合并总 txt

输出：
    大地巡旅_OCR_pages/page_XXXX.txt   逐页 OCR
    大地巡旅_OCR_pages/manifest.tsv    页号 / 图片 / 字符数
    大地巡旅_OCR.txt                   合并后的全文（带页码分隔，适合全文检索）

已知坑：
  * 原 PDF 没有文字层，pdftotext 为空；必须 OCR。
  * 封面 / 整页插画 / 装饰页几乎没有正文，OCR 结果会很短或为空，属正常。
  * Tesseract 对竖排、艺术字、彩色背景的识别率有限；正文页效果尚可。
  * 脚本不修改原 PDF，也不删除页面图。
"""

from __future__ import annotations

import argparse
import csv
import re
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

from .paths import BOOK_DIR

DEFAULT_DIR = BOOK_DIR / "大地巡旅_OCR_pages"
DEFAULT_PDF = BOOK_DIR / "【Ark-α01】世界观设定集丨大地巡旅-Qingqiu.pdf"
DEFAULT_TXT = BOOK_DIR / "大地巡旅_OCR.txt"
CJK_RE = re.compile(r"[一-鿿]")
IMAGE_SUFFIXES = {".jpg", ".jpeg", ".png", ".tif", ".tiff", ".webp"}


def page_number(path: Path) -> int:
    m = re.search(r"(\d+)", path.stem)
    return int(m.group(1)) if m else 0


def page_images(folder: Path) -> list[Path]:
    images = [p for p in folder.iterdir()
              if p.is_file() and p.suffix.lower() in IMAGE_SUFFIXES]
    return sorted(images, key=page_number)


def clean_ocr(text: str) -> str:
    """去掉纯符号行和 Tesseract 常见的孤立噪声，保留可读正文。"""
    out: list[str] = []
    for raw in text.splitlines():
        line = raw.strip()
        if not line:
            if out and out[-1]:
                out.append("")
            continue
        letters = len(re.findall(r"[A-Za-z一-鿿]", line))
        symbols = len(re.findall(r"[^\w\s一-鿿]", line))
        if letters == 0:
            continue
        if letters <= 2 and symbols >= 2:
            continue
        out.append(line)
    while out and not out[-1]:
        out.pop()
    return "\n".join(out).strip()


def ocr_one(image: Path, lang: str, psm: int) -> tuple[Path, int]:
    txt = image.with_suffix(".txt")
    cmd = ["tesseract", str(image), "stdout", "-l", lang, "--psm", str(psm)]
    proc = subprocess.run(cmd, capture_output=True, text=True, errors="replace")
    text = clean_ocr(proc.stdout or "")
    if proc.returncode != 0 and not text:
        raise RuntimeError(f"tesseract 失败（{image.name}）：{proc.stderr.strip()[:200]}")
    txt.write_text(text + ("\n" if text else ""), encoding="utf-8")
    return txt, len(text)


def render_pages(pdf: Path, folder: Path, dpi: int) -> None:
    """页面图缺失时，用 pdftoppm 渲染。"""
    folder.mkdir(parents=True, exist_ok=True)
    if page_images(folder):
        return
    subprocess.run(["pdftoppm", "-r", str(dpi), "-jpeg", "-jpegopt", "quality=90",
                    str(pdf), str(folder / "page")], check=True)


def write_manifest(folder: Path, images: list[Path]) -> None:
    rows = []
    for image in images:
        txt = image.with_suffix(".txt")
        rows.append((page_number(image), image.name, len(txt.read_text(encoding="utf-8")) if txt.exists() else 0))
    with (folder / "manifest.tsv").open("w", encoding="utf-8", newline="") as fh:
        writer = csv.writer(fh, delimiter="\t")
        writer.writerow(["page", "path", "chars"])
        writer.writerows(rows)


def merge(folder: Path, out_txt: Path) -> tuple[int, int]:
    pages = 0
    chars = 0
    parts: list[str] = ["《大地巡旅》OCR 全文", "",
                        "> 来源：大地巡旅 PDF（扫描件）· tesseract chi_sim+eng",
                        "> 每页以「===== 第 N 页 =====」分隔；OCR 可能有错字，检索时可放宽关键词。", ""]
    for image in page_images(folder):
        txt = image.with_suffix(".txt")
        if not txt.exists():
            text = ""
        else:
            text = txt.read_text(encoding="utf-8").strip()
        parts += [f"===== 第 {page_number(image)} 页 =====", "", text, ""]
        if text:
            pages += 1
            chars += len(text)
    out_txt.write_text("\n".join(parts).rstrip() + "\n", encoding="utf-8")
    return pages, chars


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="OCR《大地巡旅》扫描 PDF")
    ap.add_argument("--dir", type=Path, default=DEFAULT_DIR, help="页面图与逐页 txt 目录")
    ap.add_argument("--pdf", type=Path, default=DEFAULT_PDF, help="PDF 路径（页面图缺失时使用）")
    ap.add_argument("--text", type=Path, default=DEFAULT_TXT, help="合并后的全文路径")
    ap.add_argument("--lang", default="chi_sim+eng")
    ap.add_argument("--psm", type=int, default=3)
    ap.add_argument("--jobs", type=int, default=4)
    ap.add_argument("--dpi", type=int, default=300, help="页面图缺失时的渲染 DPI")
    ap.add_argument("--force", action="store_true", help="已有非空 txt 也重跑")
    ap.add_argument("--merge-only", action="store_true", help="只合并，不 OCR")
    args = ap.parse_args(argv)

    folder: Path = args.dir
    if not folder.is_dir():
        if not args.pdf.is_file():
            ap.error(f"目录不存在：{folder}，也找不到 PDF：{args.pdf}")
        render_pages(args.pdf, folder, args.dpi)
    images = page_images(folder)
    if not images:
        ap.error(f"{folder} 里没有页面图（jpg/png）")
    print(f"页面图：{len(images)} 张（{folder}）")

    if not args.merge_only:
        todo = images
        if not args.force:
            todo = [im for im in images
                    if not (im.with_suffix(".txt").exists()
                            and im.with_suffix(".txt").read_text(encoding="utf-8").strip())]
        print(f"需要 OCR：{len(todo)} 页；已有非空结果：{len(images) - len(todo)} 页")
        done = 0
        with ThreadPoolExecutor(max_workers=max(1, args.jobs)) as pool:
            futures = {pool.submit(ocr_one, im, args.lang, args.psm): im for im in todo}
            for fut in as_completed(futures):
                im = futures[fut]
                try:
                    _txt, chars = fut.result()
                except Exception as exc:
                    print(f"  ! {im.name}: {exc}", file=sys.stderr)
                    continue
                done += 1
                if done % 20 == 0 or done == len(todo):
                    print(f"  …{done}/{len(todo)}（{im.name}，{chars} 字）")
        write_manifest(folder, images)

    pages, chars = merge(folder, args.text)
    print(f"合并完成：{args.text}（{pages}/{len(images)} 页有正文，约 {chars} 字）")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
