#!/usr/bin/env python3
"""Single-PDF wrapper for the bundled pdf_to_ai converter.

This keeps source PDFs in place, writes only Markdown/JSONL artifacts to the
requested output directory, and keeps OCR cache files in a temporary location
unless the caller explicitly provides one.
"""

from __future__ import annotations

import argparse
import shutil
import tempfile
from pathlib import Path

from pdf_to_ai import (
    chunk_pages,
    extract_pages,
    pdf_needs_ocr,
    run_ocrmypdf,
    write_jsonl,
    write_markdown,
)


def convert_pdf(
    pdf_path: Path,
    out_dir: Path,
    *,
    ocr: str = "auto",
    chunk_chars: int = 4000,
    overlap_chars: int = 400,
    ocr_lang: str = "eng",
    ocr_cache_dir: Path | None = None,
    keep_ocr_cache: bool = False,
) -> tuple[Path, Path]:
    pdf_path = pdf_path.expanduser().resolve()
    out_dir = out_dir.expanduser().resolve()

    if not pdf_path.exists():
        raise FileNotFoundError(f"PDF not found: {pdf_path}")
    if pdf_path.suffix.lower() != ".pdf":
        raise ValueError(f"Expected a .pdf file: {pdf_path}")

    out_dir.mkdir(parents=True, exist_ok=True)

    owned_temp_cache = False
    if ocr_cache_dir is None:
        ocr_cache_dir = Path(tempfile.mkdtemp(prefix="pdf-to-ai-ocr-"))
        owned_temp_cache = True
    else:
        ocr_cache_dir = ocr_cache_dir.expanduser().resolve()
        ocr_cache_dir.mkdir(parents=True, exist_ok=True)

    try:
        pdf_for_extraction = pdf_path
        do_ocr = False
        if ocr == "always":
            do_ocr = True
        elif ocr == "auto":
            do_ocr = pdf_needs_ocr(pdf_path)
        elif ocr != "never":
            raise ValueError("--ocr must be one of: auto, always, never")

        if do_ocr:
            ocr_out = ocr_cache_dir / f"{pdf_path.stem}.ocr.pdf"
            ok = run_ocrmypdf(
                pdf_path,
                ocr_out,
                lang=ocr_lang,
                deskew=True,
                force_ocr=(ocr == "always"),
                skip_text=True,
                jobs=0,
                quiet=True,
            )
            if ok:
                pdf_for_extraction = ocr_out

        pages = extract_pages(pdf_for_extraction)
        out_md = out_dir / f"{pdf_path.stem}.md"
        out_jsonl = out_dir / f"{pdf_path.stem}.jsonl"

        write_markdown(out_md, pages, pdf_path.stem)
        write_jsonl(
            out_jsonl,
            chunk_pages(
                source_file=pdf_path.name,
                pages=pages,
                chunk_chars=chunk_chars,
                overlap_chars=overlap_chars,
            ),
        )
        return out_md, out_jsonl
    finally:
        if owned_temp_cache and not keep_ocr_cache:
            shutil.rmtree(ocr_cache_dir, ignore_errors=True)


def main() -> int:
    parser = argparse.ArgumentParser(description="Convert one PDF to Markdown and JSONL.")
    parser.add_argument("--pdf", required=True, help="Source PDF path. The PDF is not copied.")
    parser.add_argument("--out", required=True, help="Directory for Markdown and JSONL outputs.")
    parser.add_argument("--ocr", choices=["auto", "always", "never"], default="auto")
    parser.add_argument("--ocr-lang", default="eng")
    parser.add_argument("--ocr-cache-dir", default=None)
    parser.add_argument("--keep-ocr-cache", action="store_true")
    parser.add_argument("--chunk-chars", type=int, default=4000)
    parser.add_argument("--overlap-chars", type=int, default=400)
    args = parser.parse_args()

    md_path, jsonl_path = convert_pdf(
        Path(args.pdf),
        Path(args.out),
        ocr=args.ocr,
        chunk_chars=args.chunk_chars,
        overlap_chars=args.overlap_chars,
        ocr_lang=args.ocr_lang,
        ocr_cache_dir=Path(args.ocr_cache_dir) if args.ocr_cache_dir else None,
        keep_ocr_cache=args.keep_ocr_cache,
    )
    print(f"Markdown: {md_path}")
    print(f"JSONL: {jsonl_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
