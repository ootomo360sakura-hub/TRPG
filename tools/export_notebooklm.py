#!/usr/bin/env python3
"""ボールトのノートをNotebookLMアップロード用のソースにまとめる。

NotebookLMには公開APIがないため、このスクリプトでボールト全体を
カテゴリごとの結合Markdownに書き出し、それをNotebookLMの
「ソースを追加 > コピーされたテキスト/ファイル」で取り込む運用にする。

使い方:
    python3 tools/export_notebooklm.py
出力:
    notebooklm/コマ割りデータベース.md
    notebooklm/漫画制作知識.md
"""
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
VAULT = ROOT / "vault"
OUT_DIR = ROOT / "notebooklm"

EXPORTS = {
    "コマ割りデータベース.md": ["コマ割り"],
    "漫画制作知識.md": ["知識"],
}


def main():
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    today = date.today().isoformat()
    for out_name, folders in EXPORTS.items():
        parts = [
            f"# {out_name.removesuffix('.md')}",
            f"(TRPG漫画プロジェクト ボールトからの自動書き出し: {today})",
        ]
        for folder in folders:
            for note in sorted((VAULT / folder).glob("*.md")):
                parts.append("\n---\n")
                parts.append(f"## ソースノート: {note.stem}\n")
                parts.append(note.read_text(encoding="utf-8"))
        out = OUT_DIR / out_name
        out.write_text("\n".join(parts), encoding="utf-8")
        print(f"書き出し: {out.relative_to(ROOT)}")
    print("\nNotebookLMで「ソースを追加」からこれらのファイルを取り込んでください。")


if __name__ == "__main__":
    main()
