#!/usr/bin/env python3
"""Session bookkeeping for the wiki-deep-research skill.

This script deliberately does not call an LLM or perform web research. It keeps
the filesystem state deterministic while the agent performs planning, browsing,
synthesis, and wiki promotion.
"""

from __future__ import annotations

import argparse
import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

SESSION_FILES = {
    "plan.md": "# Research Plan\n\n",
    "findings.md": "# Findings\n\n",
    "critique.md": "# Critique\n\n",
    "report.md": "# Report Draft\n\n",
}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="wiki_deep_research.py")
    subparsers = parser.add_subparsers(dest="command", required=True)

    init_parser = subparsers.add_parser("init", help="Create a research session")
    init_parser.add_argument("--topic", required=True)
    init_parser.add_argument("--vault", required=True)

    status_parser = subparsers.add_parser("status", help="Print session state")
    status_parser.add_argument("--session", required=True)
    status_parser.add_argument("--vault", required=True)

    source_parser = subparsers.add_parser("record-source", help="Add or update a source")
    source_parser.add_argument("--session", required=True)
    source_parser.add_argument("--vault", required=True)
    source_parser.add_argument("--url", required=True)
    source_parser.add_argument("--title", default="")
    source_parser.add_argument("--domain", default="")

    stage_parser = subparsers.add_parser("set-stage", help="Update session stage")
    stage_parser.add_argument("--session", required=True)
    stage_parser.add_argument("--vault", required=True)
    stage_parser.add_argument("--stage", required=True)

    manifest_parser = subparsers.add_parser(
        "export-manifest-entry", help="Print a manifest entry for the session"
    )
    manifest_parser.add_argument("--session", required=True)
    manifest_parser.add_argument("--vault", required=True)

    args = parser.parse_args(argv)

    if args.command == "init":
        created_session_dir = init_session(Path(args.vault), args.topic)
        print(created_session_dir.name)
        return 0
    if args.command == "status":
        print_json(read_state(session_dir(Path(args.vault), args.session)))
        return 0
    if args.command == "record-source":
        source = record_source(
            session_dir(Path(args.vault), args.session),
            url=args.url,
            title=args.title,
            domain=args.domain,
        )
        print_json(source)
        return 0
    if args.command == "set-stage":
        state = set_stage(session_dir(Path(args.vault), args.session), args.stage)
        print_json(state)
        return 0
    if args.command == "export-manifest-entry":
        print_json(export_manifest_entry(session_dir(Path(args.vault), args.session)))
        return 0

    parser.error(f"Unknown command: {args.command}")
    return 2


def init_session(vault: Path, topic: str) -> Path:
    root = research_root(vault)
    root.mkdir(parents=True, exist_ok=True)
    slug_base = slugify(topic)
    slug = slug_base
    index = 2
    while (root / slug).exists():
        slug = f"{slug_base}-{index}"
        index += 1

    path = root / slug
    path.mkdir()
    now = now_iso()
    state = {
        "type": "deep_research",
        "topic": topic,
        "slug": slug,
        "stage": "planning",
        "created": now,
        "updated": now,
        "rounds_completed": 0,
        "sources_fetched": 0,
        "pages_created": [],
        "pages_updated": [],
    }
    write_json(path / "state.json", state)
    write_json(path / "sources.json", {"sources": []})
    for filename, content in SESSION_FILES.items():
        (path / filename).write_text(content, encoding="utf-8")
    return path


def record_source(path: Path, url: str, title: str = "", domain: str = "") -> dict[str, Any]:
    ensure_session(path)
    sources_path = path / "sources.json"
    payload = read_json(sources_path)
    sources = payload.setdefault("sources", [])
    existing = next((item for item in sources if item.get("url") == url), None)
    now = now_iso()
    if existing:
        if title:
            existing["title"] = title
        if domain:
            existing["domain"] = domain
        existing["updated"] = now
        source = existing
    else:
        source = {
            "id": f"src-{len(sources) + 1}",
            "url": url,
            "title": title or url,
            "domain": domain,
            "created": now,
            "updated": now,
        }
        sources.append(source)
    write_json(sources_path, payload)

    state = read_state(path)
    state["sources_fetched"] = len(sources)
    state["updated"] = now
    write_json(path / "state.json", state)
    return source


def set_stage(path: Path, stage: str) -> dict[str, Any]:
    ensure_session(path)
    state = read_state(path)
    state["stage"] = stage
    state["updated"] = now_iso()
    if stage in {"critiquing", "composing", "promoted"}:
        state["rounds_completed"] = max(int(state.get("rounds_completed", 0)), 1)
    write_json(path / "state.json", state)
    return state


def export_manifest_entry(path: Path) -> dict[str, Any]:
    ensure_session(path)
    state = read_state(path)
    sources = read_json(path / "sources.json").get("sources", [])
    return {
        "type": "research",
        "mode": "deep_research",
        "topic": state["topic"],
        "session": state["slug"],
        "researched_at": state.get("updated", now_iso()),
        "rounds_completed": state.get("rounds_completed", 0),
        "sources_fetched": len(sources),
        "pages_created": state.get("pages_created", []),
        "pages_updated": state.get("pages_updated", []),
    }


def research_root(vault: Path) -> Path:
    return vault / "_research"


def session_dir(vault: Path, session: str) -> Path:
    return research_root(vault) / session


def ensure_session(path: Path) -> None:
    if not path.exists():
        raise FileNotFoundError(f"Session not found: {path}")
    if not (path / "state.json").exists():
        raise FileNotFoundError(f"Session state not found: {path / 'state.json'}")


def read_state(path: Path) -> dict[str, Any]:
    ensure_session(path)
    return read_json(path / "state.json")


def slugify(value: str) -> str:
    text = value.lower().strip()
    text = re.sub(r"[^a-z0-9]+", "-", text)
    text = re.sub(r"-+", "-", text).strip("-")
    return text[:60].strip("-") or "research"


def now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, value: dict[str, Any]) -> None:
    path.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def print_json(value: dict[str, Any]) -> None:
    print(json.dumps(value, indent=2, sort_keys=True))


if __name__ == "__main__":
    raise SystemExit(main())
