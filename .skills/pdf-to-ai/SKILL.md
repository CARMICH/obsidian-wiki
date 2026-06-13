---
name: pdf-to-ai
description: Convert local PDF documents into AI-friendly Markdown and JSONL reference artifacts using the bundled pdf_to_ai converter. Use when Codex, Claude, or another agent needs to read, inspect, ingest, or convert PDFs for any project, especially PDFs placed in an inbox, destined for an Obsidian references folder, or needed for RAG/search without copying source PDFs.
---

# PDF to AI

Use this skill whenever a task involves converting a PDF into durable AI-readable artifacts. Leave the source PDF where it is and create sidecar outputs: one Markdown file for human reading and one JSONL file for chunked retrieval.

## Quick Start

For one PDF, prefer the wrapper script:

```powershell
python "$env:USERPROFILE\.codex\skills\pdf-to-ai\scripts\convert_pdf_reference.py" --pdf "C:\path\source.pdf" --out "C:\path\references" --ocr auto
```

In Claude, use the Claude global skill path:

```powershell
python "$env:USERPROFILE\.claude\skills\pdf-to-ai\scripts\convert_pdf_reference.py" --pdf "C:\path\source.pdf" --out "C:\path\references" --ocr auto
```

If neither global skill path exists, use the maintained local tool directly:

```powershell
python "C:\Users\reyno\Projects\0_tools\pdf_to_ai\pdf_to_ai.py" --in "C:\path\pdf-folder" --out "C:\path\references" --ocr auto
```

## Workflow

1. Confirm the source PDF path and intended output folder from the user request or local context.
2. Use `convert_pdf_reference.py` for a single PDF.
3. Use `pdf_to_ai.py` directly only when converting a folder of PDFs.
4. Use `--ocr never` for born-digital PDFs with a good text layer.
5. Use `--ocr auto` when the PDF may be scanned.
6. Use `--ocr always` only when explicitly needed.
7. Verify the resulting `.md` and `.jsonl` exist.

## Output Rules

- Do not copy the source PDF into the output folder.
- Keep both Markdown and JSONL by default.
- Keep OCR cache outside the target references folder unless the user explicitly asks to keep it.
- When working in `C:\Users\reyno\Documents\obsidian-wiki-vault`, default reusable converted sources to `C:\Users\reyno\Documents\obsidian-wiki-vault\references` unless the user names another destination.
- Keep the original PDF in its inbox/source folder unless the user explicitly asks to move or delete it.

## Batch Conversion

The original batch converter is bundled as `scripts/pdf_to_ai.py`. Use it for folders:

```powershell
python "$env:USERPROFILE\.codex\skills\pdf-to-ai\scripts\pdf_to_ai.py" --in "C:\path\pdfs" --out "C:\path\references" --ocr auto
```

Claude equivalent:

```powershell
python "$env:USERPROFILE\.claude\skills\pdf-to-ai\scripts\pdf_to_ai.py" --in "C:\path\pdfs" --out "C:\path\references" --ocr auto
```

When batch converting into an Obsidian references folder with OCR enabled, pass `--ocr-cache-dir` to a temp or non-vault cache path.

## Dependencies

- Required: Python 3.10+ and `pymupdf`.
- Optional OCR: `ocrmypdf`, Tesseract, and Ghostscript.
- If `fitz` is missing, install PyMuPDF into the active interpreter: `python -m pip install pymupdf`.
