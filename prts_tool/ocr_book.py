#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""把扫描版《大地巡旅》PDF OCR 成可检索的纯文本。

前置：
    sudo apt-get install tesseract-ocr tesseract-ocr-chi-sim
    # 页面图由本脚本导出到 images/page_XXXX.jpg；缺失时会用 pdftoppm 重新渲染。

用法：
    python -m prts_tool.ocr_book                 # 增量：只 OCR 还没有非空 txt 的页面
    python -m prts_tool.ocr_book --force         # 454 页全部重跑
    python -m prts_tool.ocr_book --jobs 6        # 并行数（默认 4）
    python -m prts_tool.ocr_book --merge-only    # 不 OCR，只重新合并总 txt

存储布局（文本与图片分开）：
    images/page_XXXX.jpg               页面图
    text/pages/page_XXXX.txt           逐页 OCR
    text/manifest.tsv                  页号 / 图片 / 文本 / 字符数
    text/大地巡旅_OCR.txt              合并后的全文（带页码分隔，适合全文检索）

旧版把图片和逐页 txt 混在 `大地巡旅_OCR_pages/`，运行时会自动迁移到新布局。

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
import shutil
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

from .paths import BOOK_DIR

DEFAULT_IMAGE_DIR = BOOK_DIR / "images"
DEFAULT_TEXT_DIR = BOOK_DIR / "text"
DEFAULT_PAGE_TEXT_DIR = DEFAULT_TEXT_DIR / "pages"
DEFAULT_TXT = DEFAULT_TEXT_DIR / "大地巡旅_OCR.txt"
DEFAULT_MANIFEST = DEFAULT_TEXT_DIR / "manifest.tsv"
DEFAULT_PDF = BOOK_DIR / "【Ark-α01】世界观设定集丨大地巡旅-Qingqiu.pdf"
# 兼容旧调用（页面图目录）
DEFAULT_DIR = DEFAULT_IMAGE_DIR
LEGACY_IMAGE_DIR = BOOK_DIR / "大地巡旅_OCR_pages"
LEGACY_TXT = BOOK_DIR / "大地巡旅_OCR.txt"
CJK_RE = re.compile(r"[一-鿿]")
IMAGE_SUFFIXES = {".jpg", ".jpeg", ".png", ".tif", ".tiff", ".webp"}


def migrate_layout(book_dir: Path = BOOK_DIR) -> list[Path]:
    """Move the old mixed OCR directory into images/ and text/."""
    moved: list[Path] = []
    legacy = book_dir / "大地巡旅_OCR_pages"
    image_dir = book_dir / "images"
    text_dir = book_dir / "text"
    page_text_dir = text_dir / "pages"
    if legacy.is_dir():
        image_dir.mkdir(parents=True, exist_ok=True)
        page_text_dir.mkdir(parents=True, exist_ok=True)
        for item in legacy.iterdir():
            if not item.is_file():
                continue
            if item.suffix.lower() in IMAGE_SUFFIXES:
                target = image_dir / item.name
            elif item.name == "manifest.tsv":
                target = text_dir / item.name
            elif item.suffix.lower() == ".txt":
                target = page_text_dir / item.name
            else:
                continue
            if target.exists():
                continue
            shutil.move(str(item), str(target))
            moved.append(target)
        try:
            legacy.rmdir()
        except OSError:
            pass
    old_txt = book_dir / "大地巡旅_OCR.txt"
    if old_txt.is_file():
        text_dir.mkdir(parents=True, exist_ok=True)
        target = text_dir / old_txt.name
        if not target.exists():
            shutil.move(str(old_txt), str(target))
            moved.append(target)
    return moved


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


def ocr_one(image: Path, text_dir: Path, lang: str, psm: int) -> tuple[Path, int]:
    text_dir.mkdir(parents=True, exist_ok=True)
    txt = text_dir / (image.stem + ".txt")
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


def write_manifest(path: Path, images: list[Path], text_dir: Path) -> None:
    rows = []
    for image in images:
        txt = text_dir / (image.stem + ".txt")
        rows.append((page_number(image), image.name, txt.name,
                     len(txt.read_text(encoding="utf-8")) if txt.exists() else 0))
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as fh:
        writer = csv.writer(fh, delimiter="\t")
        writer.writerow(["page", "image", "text", "chars"])
        writer.writerows(rows)


def merge(images: list[Path], text_dir: Path, out_txt: Path) -> tuple[int, int]:
    pages = 0
    chars = 0
    parts: list[str] = ["《大地巡旅》OCR 全文", "",
                        "> 来源：大地巡旅 PDF（扫描件）· tesseract chi_sim+eng",
                        "> 每页以「===== 第 N 页 =====」分隔；OCR 可能有错字，检索时可放宽关键词。", ""]
    for image in images:
        txt = text_dir / (image.stem + ".txt")
        if not txt.exists():
            text = ""
        else:
            text = txt.read_text(encoding="utf-8").strip()
        parts += [f"===== 第 {page_number(image)} 页 =====", "", text, ""]
        if text:
            pages += 1
            chars += len(text)
    out_txt.parent.mkdir(parents=True, exist_ok=True)
    out_txt.write_text("\n".join(parts).rstrip() + "\n", encoding="utf-8")
    return pages, chars


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="OCR《大地巡旅》扫描 PDF")
    ap.add_argument("--images", "--dir", dest="images", type=Path, default=DEFAULT_IMAGE_DIR,
                    help="页面图目录（默认 images/）")
    ap.add_argument("--text-dir", type=Path, default=DEFAULT_PAGE_TEXT_DIR,
                    help="逐页 OCR 文本目录（默认 text/pages/）")
    ap.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST,
                    help="页清单路径（默认 text/manifest.tsv）")
    ap.add_argument("--pdf", type=Path, default=DEFAULT_PDF, help="PDF 路径（页面图缺失时使用）")
    ap.add_argument("--text", type=Path, default=DEFAULT_TXT, help="合并后的全文路径")
    ap.add_argument("--lang", default="chi_sim+eng")
    ap.add_argument("--psm", type=int, default=3)
    ap.add_argument("--jobs", type=int, default=4)
    ap.add_argument("--dpi", type=int, default=300, help="页面图缺失时的渲染 DPI")
    ap.add_argument("--force", action="store_true", help="已有非空 txt 也重跑")
    ap.add_argument("--merge-only", action="store_true", help="只合并，不 OCR")
    args = ap.parse_args(argv)

    moved = migrate_layout()
    if moved:
        print(f"已把旧布局的 {len(moved)} 个文件迁移到 images/ 与 text/")

    image_dir: Path = args.images
    text_dir: Path = args.text_dir
    if not image_dir.is_dir():
        if not args.pdf.is_file():
            ap.error(f"图片目录不存在：{image_dir}，也找不到 PDF：{args.pdf}")
        render_pages(args.pdf, image_dir, args.dpi)
    images = page_images(image_dir)
    if not images:
        ap.error(f"{image_dir} 里没有页面图（jpg/png）")
    print(f"页面图：{len(images)} 张（{image_dir}）")

    if not args.merge_only:
        todo = images
        if not args.force:
            todo = [im for im in images
                    if not ((text_dir / (im.stem + ".txt")).exists()
                            and (text_dir / (im.stem + ".txt")).read_text(
                                encoding="utf-8").strip())]
        print(f"需要 OCR：{len(todo)} 页；已有非空结果：{len(images) - len(todo)} 页")
        done = 0
        with ThreadPoolExecutor(max_workers=max(1, args.jobs)) as pool:
            futures = {pool.submit(ocr_one, im, text_dir, args.lang, args.psm): im for im in todo}
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

    pages, chars = merge(images, text_dir, args.text)
    write_manifest(args.manifest, images, text_dir)
    print(f"合并完成：{args.text}（{pages}/{len(images)} 页有正文，约 {chars} 字）")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
