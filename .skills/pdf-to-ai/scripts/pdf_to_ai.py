#!/usr/bin/env python3
r"""
pdf_to_ai.py

Batch convert PDFs into:
- Markdown (.md) with page headers
- JSONL chunks (.jsonl) for AI ingestion / RAG

Optional: auto-detect when OCR is needed and run OCR using ocrmypdf.

Usage (Windows examples):
  py -3.11 pdf_to_ai.py --in "C:/path/to/pdfs" --out "C:/path/to/out" --combine
  py -3.11 pdf_to_ai.py --in "C:\\path\\to\\pdfs" --out "C:\\path\\to\\out" --ocr auto

OCR notes:
- Requires ocrmypdf + system deps (Tesseract + Ghostscript).
- Install (common Windows approach):
    py -m pip install ocrmypdf
    choco install tesseract ghostscript -y
"""

from __future__ import annotations

import argparse
import json
import re
import shutil
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import List, Tuple

import fitz  # PyMuPDF


PAGE_BREAK = "\n\n---\n\n"


def normalize_text(s: str) -> str:
    # Basic cleanup without being too destructive.
    s = s.replace("\u00ad", "")  # soft hyphen
    s = re.sub(r"[ \t]+\n", "\n", s)  # trailing spaces
    s = re.sub(r"\n{3,}", "\n\n", s)  # collapse huge blank runs
    s = re.sub(r"[ \t]{2,}", " ", s)  # collapse multi-spaces (lightly)
    return s.strip()


def extract_pages(pdf_path: Path) -> List[Tuple[int, str]]:
    doc = fitz.open(pdf_path)
    pages: List[Tuple[int, str]] = []
    for i in range(len(doc)):
        page = doc[i]
        txt = page.get_text("text") or ""
        txt = normalize_text(txt)
        pages.append((i + 1, txt))
    doc.close()
    return pages


def pdf_needs_ocr(
    pdf_path: Path,
    *,
    sample_pages: int = 8,
    min_total_chars: int = 300,
    max_empty_ratio: float = 0.6,
    min_page_chars: int = 25,
) -> bool:
    """
    Heuristic OCR detection:
    - sample up to first N pages
    - if too many pages are "empty" or overall extracted text is small -> OCR likely needed
    """
    try:
        doc = fitz.open(pdf_path)
    except Exception:
        return False

    n = min(len(doc), max(1, sample_pages))
    total_chars = 0
    empty_pages = 0

    for i in range(n):
        txt = (doc[i].get_text("text") or "").strip()
        txt = normalize_text(txt)
        total_chars += len(txt)
        if len(txt) < min_page_chars:
            empty_pages += 1

    doc.close()

    empty_ratio = empty_pages / n
    if total_chars < min_total_chars:
        return True
    if empty_ratio >= max_empty_ratio:
        return True
    return False


def run_ocrmypdf(
    in_pdf: Path,
    out_pdf: Path,
    *,
    lang: str = "eng",
    deskew: bool = True,
    force_ocr: bool = False,
    skip_text: bool = True,
    jobs: int = 0,
    quiet: bool = True,
) -> bool:
    """
    Run OCR using the `ocrmypdf` CLI (preferred for robustness).

    Returns True if OCR output was produced, False otherwise.
    """
    exe = shutil.which("ocrmypdf")
    if not exe:
        print(
            "OCR requested but 'ocrmypdf' was not found on PATH.\n"
            "Install: py -m pip install ocrmypdf (and install Tesseract + Ghostscript).\n"
            "Continuing WITHOUT OCR.",
            file=sys.stderr,
        )
        return False

    out_pdf.parent.mkdir(parents=True, exist_ok=True)

    cmd = [exe]
    if quiet:
        cmd.append("--quiet")

    # Skip OCR on pages that already contain text (helpful for hybrid PDFs)
    if skip_text and not force_ocr:
        cmd.append("--skip-text")

    # Force OCR even if text exists (useful if text layer is garbage)
    if force_ocr:
        cmd.append("--force-ocr")

    if deskew:
        cmd.append("--deskew")

    if lang:
        cmd += ["-l", lang]

    # jobs=0 lets ocrmypdf decide; you can override
    if jobs and jobs > 0:
        cmd += ["-j", str(jobs)]

    cmd += [str(in_pdf), str(out_pdf)]

    try:
        res = subprocess.run(cmd, capture_output=True, text=True)
    except Exception as e:
        print(f"OCR failed to start: {e}\nContinuing WITHOUT OCR.", file=sys.stderr)
        return False

    if res.returncode != 0:
        # OCR failures are common when dependencies are missing (tesseract/gs).
        msg = (res.stderr or res.stdout or "").strip()
        print(
            "OCR failed (ocrmypdf returned non-zero). Continuing WITHOUT OCR.\n"
            f"Command: {' '.join(cmd)}\n"
            f"Output:\n{msg[:2000]}",
            file=sys.stderr,
        )
        return False

    if out_pdf.exists() and out_pdf.stat().st_size > 0:
        return True

    return False


@dataclass
class Chunk:
    source_file: str
    chunk_index: int
    page_start: int
    page_end: int
    text: str


def chunk_pages(
    source_file: str,
    pages: List[Tuple[int, str]],
    chunk_chars: int = 4000,
    overlap_chars: int = 400,
) -> List[Chunk]:
    """
    Create chunks across pages, keeping rough page ranges.
    chunk_chars is character-based (simple + robust). overlap helps retrieval.
    """
    chunks: List[Chunk] = []
    buf = ""
    start_page = None
    last_page = None
    idx = 0

    def flush():
        nonlocal buf, start_page, last_page, idx
        t = normalize_text(buf)
        if t:
            chunks.append(
                Chunk(
                    source_file=source_file,
                    chunk_index=idx,
                    page_start=start_page or 1,
                    page_end=last_page or (start_page or 1),
                    text=t,
                )
            )
            idx += 1
        buf = ""
        start_page = None
        last_page = None

    for pno, txt in pages:
        if not txt:
            continue
        if start_page is None:
            start_page = pno
        last_page = pno

        candidate = (buf + "\n\n" + f"[p.{pno}]\n" + txt).strip()
        if buf and len(candidate) > chunk_chars:
            overlap = buf[-overlap_chars:] if overlap_chars and len(buf) > overlap_chars else ""
            flush()
            buf = overlap.strip()
            start_page = pno
            last_page = pno

        buf = (buf + "\n\n" + f"[p.{pno}]\n" + txt).strip()

    flush()
    return chunks


def write_markdown(out_md: Path, pages: List[Tuple[int, str]], title: str) -> None:
    parts = [f"# {title}\n"]
    for pno, txt in pages:
        if not txt:
            continue
        parts.append(f"## Page {pno}\n\n{txt}\n")
    out_md.write_text("\n".join(parts).strip() + "\n", encoding="utf-8")


def write_jsonl(out_jsonl: Path, chunks: List[Chunk]) -> None:
    with out_jsonl.open("w", encoding="utf-8") as f:
        for c in chunks:
            f.write(
                json.dumps(
                    {
                        "source_file": c.source_file,
                        "chunk_index": c.chunk_index,
                        "page_start": c.page_start,
                        "page_end": c.page_end,
                        "text": c.text,
                    },
                    ensure_ascii=False,
                )
                + "\n"
            )


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--in", dest="in_dir", required=True, help="Input folder containing PDFs")
    ap.add_argument("--out", dest="out_dir", required=True, help="Output folder")
    ap.add_argument("--chunk-chars", type=int, default=4000)
    ap.add_argument("--overlap-chars", type=int, default=400)
    ap.add_argument("--combine", action="store_true", help="Also write combined_corpus.jsonl across all PDFs")

    # OCR controls
    ap.add_argument(
        "--ocr",
        choices=["auto", "always", "never"],
        default="auto",
        help="OCR mode: auto (detect), always (force), never",
    )
    ap.add_argument("--ocr-lang", default="eng", help="OCR language(s), e.g. eng, eng+spa")
    ap.add_argument("--ocr-deskew", action="store_true", help="Deskew pages during OCR")
    ap.add_argument("--ocr-force", action="store_true", help="Force OCR even if text layer exists")
    ap.add_argument(
        "--ocr-cache-dir",
        default=None,
        help="Where to store OCR'd PDFs (default: <out>/_ocr_cache)",
    )
    ap.add_argument("--ocr-jobs", type=int, default=0, help="Parallel jobs for ocrmypdf (0=auto)")

    # OCR detection heuristics (tunable)
    ap.add_argument("--ocr-sample-pages", type=int, default=8)
    ap.add_argument("--ocr-min-total-chars", type=int, default=300)
    ap.add_argument("--ocr-max-empty-ratio", type=float, default=0.6)
    ap.add_argument("--ocr-min-page-chars", type=int, default=25)

    args = ap.parse_args()

    in_dir = Path(args.in_dir).expanduser()
    out_dir = Path(args.out_dir).expanduser()
    out_dir.mkdir(parents=True, exist_ok=True)

    ocr_cache_dir = Path(args.ocr_cache_dir).expanduser() if args.ocr_cache_dir else (out_dir / "_ocr_cache")
    ocr_cache_dir.mkdir(parents=True, exist_ok=True)

    pdfs = sorted(in_dir.glob("*.pdf"))
    if not pdfs:
        print(f"No PDFs found in: {in_dir}")
        return 2

    combined: List[dict] = []

    for pdf in pdfs:
        print(f"\nProcessing: {pdf.name}")

        pdf_for_extraction = pdf

        # OCR decision
        do_ocr = False
        if args.ocr == "always":
            do_ocr = True
        elif args.ocr == "auto":
            do_ocr = pdf_needs_ocr(
                pdf,
                sample_pages=args.ocr_sample_pages,
                min_total_chars=args.ocr_min_total_chars,
                max_empty_ratio=args.ocr_max_empty_ratio,
                min_page_chars=args.ocr_min_page_chars,
            )

        # Run OCR if needed/requested
        if do_ocr:
            ocr_out = ocr_cache_dir / f"{pdf.stem}.ocr.pdf"
            # Reuse cached OCR if exists unless forcing OCR (or cache is empty)
            if ocr_out.exists() and ocr_out.stat().st_size > 0 and not args.ocr_force:
                print(f"OCR: using cached OCR PDF -> {ocr_out.name}")
                pdf_for_extraction = ocr_out
            else:
                print("OCR: running ocrmypdf...")
                ok = run_ocrmypdf(
                    pdf,
                    ocr_out,
                    lang=args.ocr_lang,
                    deskew=args.ocr_deskew,
                    force_ocr=args.ocr_force,
                    skip_text=True,
                    jobs=args.ocr_jobs,
                    quiet=True,
                )
                if ok:
                    print(f"OCR: done -> {ocr_out.name}")
                    pdf_for_extraction = ocr_out
                else:
                    print("OCR: skipped/failed -> continuing with original PDF")

        # Extract and write outputs
        pages = extract_pages(pdf_for_extraction)

        title = pdf.stem
        out_md = out_dir / f"{pdf.stem}.md"
        out_jsonl = out_dir / f"{pdf.stem}.jsonl"

        write_markdown(out_md, pages, title)

        chunks = chunk_pages(
            source_file=pdf.name,  # keep original filename as source
            pages=pages,
            chunk_chars=args.chunk_chars,
            overlap_chars=args.overlap_chars,
        )
        write_jsonl(out_jsonl, chunks)

        if args.combine:
            for c in chunks:
                combined.append(
                    {
                        "source_file": c.source_file,
                        "chunk_index": c.chunk_index,
                        "page_start": c.page_start,
                        "page_end": c.page_end,
                        "text": c.text,
                    }
                )

    if args.combine:
        combined_path = out_dir / "combined_corpus.jsonl"
        with combined_path.open("w", encoding="utf-8") as f:
            for row in combined:
                f.write(json.dumps(row, ensure_ascii=False) + "\n")
        print(f"\nWrote combined corpus: {combined_path}")

    print("\nDone.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
