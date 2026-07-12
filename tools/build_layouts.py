#!/usr/bin/env python3
"""Obsidianボールトのコマ割りノート(YAMLフロントマター)を収集し、
data/layouts.json にコンパイルする。

使い方:
    python3 tools/build_layouts.py
"""
import json
import re
import sys
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent
VAULT = ROOT / "vault"
OUT = ROOT / "data" / "layouts.json"

FRONTMATTER_RE = re.compile(r"^---\s*\n(.*?)\n---\s*\n", re.DOTALL)


def parse_note(path: Path):
    text = path.read_text(encoding="utf-8")
    m = FRONTMATTER_RE.match(text)
    if not m:
        return None
    try:
        meta = yaml.safe_load(m.group(1))
    except yaml.YAMLError:
        return None
    if not isinstance(meta, dict) or meta.get("type") != "komawari":
        return None
    if "id" not in meta or "panels" not in meta:
        return None
    meta["source_note"] = str(path.relative_to(ROOT))
    return meta


def main():
    layouts = {}
    for path in sorted(VAULT.rglob("*.md")):
        if "テンプレート" in path.parts:
            continue
        meta = parse_note(path)
        if meta is None:
            continue
        lid = meta["id"]
        if lid in layouts:
            print(f"警告: ID重複 {lid} ({path})", file=sys.stderr)
            continue
        layouts[lid] = meta
        print(f"収集: {lid} <- {meta['source_note']}")

    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(
        json.dumps(layouts, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(f"\n{len(layouts)}件のコマ割りを {OUT.relative_to(ROOT)} に書き出しました")


if __name__ == "__main__":
    main()
