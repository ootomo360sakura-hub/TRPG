"""Discordに接続せずに確認できるロジックのテスト。 python3 -m pytest tests"""

import asyncio
import os
import sys
import tempfile
import time as _time
from datetime import date, datetime, time as dtime
from types import SimpleNamespace

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ["DB_PATH"] = os.path.join(tempfile.mkdtemp(), "test.db")

import pytest

import bot as botmod
from render import TZ, build_embed, calendar_text, combine, parse_time, reminder_times
from store import Recruitment, Store

NOW = datetime(2026, 10, 10, 12, 0, tzinfo=TZ)


@pytest.mark.parametrize(
    "text,expected",
    [("21:00", dtime(21, 0)), ("21時", dtime(21, 0)), ("21時30分", dtime(21, 30)), ("2130", dtime(21, 30)),
     ("９：０５", dtime(9, 5)), ("21:00〜", dtime(21, 0))],
)
def test_parse_time(text, expected):
    assert parse_time(text) == expected


@pytest.mark.parametrize("text", ["夜", "25:00", "21:75"])
def test_parse_time_invalid(text):
    with pytest.raises(ValueError):
        parse_time(text)


def test_combine_rejects_past():
    assert combine(date(2026, 10, 20), dtime(21), NOW) == datetime(2026, 10, 20, 21, tzinfo=TZ)
    with pytest.raises(ValueError):
        combine(date(2026, 10, 10), dtime(11), NOW)


def test_reminder_times_are_9am():
    start = int(datetime(2026, 10, 20, 21, 0, tzinfo=TZ).timestamp())
    week_at, day_at = reminder_times(start)
    assert datetime.fromtimestamp(week_at, TZ) == datetime(2026, 10, 13, 9, 0, tzinfo=TZ)
    assert datetime.fromtimestamp(day_at, TZ) == datetime(2026, 10, 19, 9, 0, tzinfo=TZ)


def test_calendar_text_marks_past_days():
    text = calendar_text(2026, 10, date(2026, 10, 10))
    assert " 日 月 火 水 木 金 土" in text and " ・ 10\n 11 12" in text


def make_rec(**kw):
    base = dict(message_id=1, channel_id=2, guild_id=3, gm_id=10, title="狂気山脈",
                start_at=int(_time.time()) + 30 * 86400, capacity=2)
    base.update(kw)
    return Recruitment(**base)


def test_store_roundtrip(tmp_path):
    store = Store(tmp_path / "x.db")
    rec = make_rec(extras={"system": "CoC6版"}, participants=[5, 3], interested=[7])
    store.save(rec)
    assert store.get(1) == rec


def test_embed_full_and_over_capacity():
    rec = make_rec(participants=[5, 3, 9], interested=[7], extras={"system": "CoC6版"})
    embed = build_embed(rec)
    assert embed.title.startswith("【満員・締切】")
    assert "GM判断" in embed.description
    names = [f.name for f in embed.fields]
    assert "システム" in names and any(n.startswith("定員超過") for n in names)


class FakeReaction:
    def __init__(self, emoji, ids, me=True):
        self.emoji, self.ids, self.me = emoji, ids, me

    async def users(self):
        for uid in self.ids:
            yield SimpleNamespace(id=uid, bot=uid == 999)


def run_sync(rec, join, interest):
    b = botmod.bot
    b.store.save(rec)
    message = SimpleNamespace(reactions=[FakeReaction("✋", join), FakeReaction("👀", interest)])
    saved = {}

    async def fake_refresh(r, m=None):
        saved["rec"] = r

    b.save_and_refresh = fake_refresh
    asyncio.run(b.sync_reactions(rec, message))
    return saved.get("rec")


def test_sync_keeps_order_and_excludes_gm_and_bots():
    rec = make_rec(participants=[5])
    out = run_sync(rec, join=[3, 5, 10, 999], interest=[3, 7])
    assert out.participants == [5, 3]  # 既存の5が先、GM(10)とBot(999)は除外
    assert out.interested == [7]  # 参加希望の3は興味ありから除く


def test_reminders(monkeypatch):
    b = botmod.bot
    sent = []

    async def fake_notify(rec, text, include_gm=False):
        sent.append(text)

    b.notify = fake_notify
    start = int(datetime(2026, 10, 20, 21, 0, tzinfo=TZ).timestamp())
    for mid in (100, 101, 102):
        b.store.save(make_rec(message_id=mid, start_at=start))
    b.store.save(make_rec(message_id=103, start_at=start, reminder=False))  # リマインドなし
    b.store.save(make_rec(message_id=104, start_at=start, week_sent=True, day_sent=True))  # 送信済み

    def at(dt):
        monkeypatch.setattr(botmod.time, "time", lambda: dt.timestamp())
        sent.clear()
        asyncio.run(b.reminder_loop.coro(b))
        return list(sent)

    assert at(datetime(2026, 10, 13, 8, 59, tzinfo=TZ)) == []  # 1週間前の9時より前
    week = at(datetime(2026, 10, 13, 9, 0, tzinfo=TZ))
    assert len(week) == 3 and all("1週間後" in t for t in week)
    assert at(datetime(2026, 10, 15, 12, 0, tzinfo=TZ)) == []  # 二重送信しない
    day = at(datetime(2026, 10, 19, 9, 0, tzinfo=TZ))
    assert len(day) == 3 and all("明日" in t for t in day)
    assert at(datetime(2026, 10, 19, 10, 0, tzinfo=TZ)) == []
