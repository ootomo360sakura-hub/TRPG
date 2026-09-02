"""テキスト共有(簡易クリップボード)。

URLや認証コードのような短いテキストをPC⇄iPhone間でやり取りするための保管庫。
共有フォルダ内の ``.lanshare/clips.json`` に保存する。
"""

from __future__ import annotations

import json
import threading
import time
from pathlib import Path

MAX_CLIPS = 100
MAX_TEXT_LENGTH = 8000


class ClipStore:
    def __init__(self, path: Path, max_clips: int = MAX_CLIPS):
        self.path = Path(path)
        self.max_clips = max_clips
        self._lock = threading.Lock()

    def _load(self) -> list[dict]:
        try:
            with open(self.path, "r", encoding="utf-8") as handle:
                data = json.load(handle)
        except (OSError, ValueError):
            return []
        return data if isinstance(data, list) else []

    def _save(self, clips: list[dict]) -> None:
        temp = self.path.with_suffix(".json.tmp")
        with open(temp, "w", encoding="utf-8") as handle:
            json.dump(clips, handle, ensure_ascii=False, indent=1)
        temp.replace(self.path)

    def list(self) -> list[dict]:
        with self._lock:
            return self._load()

    def add(self, text: str, source: str = "") -> dict:
        text = (text or "").strip()
        if not text:
            raise ValueError("テキストが空です")
        if len(text) > MAX_TEXT_LENGTH:
            raise ValueError(f"テキストが長すぎます(上限{MAX_TEXT_LENGTH}文字)")
        clip = {
            "id": f"{time.time_ns():x}",
            "text": text,
            "ts": time.time(),
            "source": source,
        }
        with self._lock:
            clips = self._load()
            clips.insert(0, clip)
            self._save(clips[: self.max_clips])
        return clip

    def delete(self, clip_id: str) -> bool:
        with self._lock:
            clips = self._load()
            remaining = [c for c in clips if c.get("id") != clip_id]
            if len(remaining) == len(clips):
                return False
            self._save(remaining)
            return True
