"""日時の解釈と、募集記事Embedの組み立て。"""

import os
import re
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import discord

from store import EXTRA_FIELDS, Recruitment

TZ = ZoneInfo(os.getenv("BOT_TIMEZONE", "Asia/Tokyo"))

JOIN_EMOJI = "✋"
INTEREST_EMOJI = "👀"

WEEK = timedelta(days=7)
DAY = timedelta(days=1)

OVER_CAPACITY_NOTE = "※定員を超えた場合はGM判断となります。"

COLOR_OPEN = discord.Color.green()
COLOR_FULL = discord.Color.orange()
COLOR_CANCELLED = discord.Color.dark_grey()

DATE_RE = re.compile(
    r"^\s*(?:(\d{4})\s*[/\-年.]\s*)?(\d{1,2})\s*[/\-月.]\s*(\d{1,2})\s*日?"
    r"(?:\s*\(.\))?(?:\s*（.）)?"
    r"\s+(\d{1,2})\s*[:：時]\s*(\d{1,2})?\s*分?\s*[〜~～-]?\s*$"
)

DATE_FORMAT_HINT = "例: 2026/10/20 21:00 ・ 10/20 21:00 ・ 10月20日 21時"


def parse_datetime(text: str, now: datetime | None = None) -> datetime:
    """開催日時の入力を解釈する。年を省略したら「次に来るその日」とみなす。

    解釈できない・過去の日時なら ValueError。
    """
    now = now or datetime.now(TZ)
    text = text.translate(str.maketrans("０１２３４５６７８９／：", "0123456789/:"))
    m = DATE_RE.match(text)
    if not m:
        raise ValueError(f"日時を読み取れませんでした。{DATE_FORMAT_HINT}")
    year, month, day, hour, minute = m.groups()
    try:
        if year:
            dt = datetime(int(year), int(month), int(day), int(hour), int(minute or 0), tzinfo=TZ)
        else:
            dt = datetime(now.year, int(month), int(day), int(hour), int(minute or 0), tzinfo=TZ)
            if dt <= now:
                dt = dt.replace(year=now.year + 1)
    except ValueError:
        raise ValueError(f"存在しない日時です。{DATE_FORMAT_HINT}") from None
    if dt <= now:
        raise ValueError("過去の日時は指定できません。")
    return dt


def format_input_datetime(ts: int) -> str:
    """編集フォームの初期値用。"""
    return datetime.fromtimestamp(ts, TZ).strftime("%Y/%m/%d %H:%M")


def mentions(ids: list[int]) -> str:
    return "\n".join(f"<@{uid}>" for uid in ids)


def build_embed(rec: Recruitment) -> discord.Embed:
    members = rec.participants[: rec.capacity]
    over = rec.participants[rec.capacity:]

    if rec.cancelled:
        title, color = f"【募集取消】{rec.title}", COLOR_CANCELLED
    elif rec.is_full:
        title, color = f"【満員・締切】{rec.title}", COLOR_FULL
    else:
        title, color = f"【TRPG募集】{rec.title}", COLOR_OPEN

    description = rec.details.strip()
    if not rec.cancelled:
        description = f"{description}\n\n{OVER_CAPACITY_NOTE}".strip()
    embed = discord.Embed(title=title, description=description, color=color)

    embed.add_field(name="GM", value=f"<@{rec.gm_id}>", inline=True)
    embed.add_field(name="日時", value=f"<t:{rec.start_at}:F>\n(<t:{rec.start_at}:R>)", inline=True)
    embed.add_field(name="定員", value=f"{rec.capacity}名", inline=True)
    for key, label in EXTRA_FIELDS.items():
        if rec.extras.get(key):
            embed.add_field(name=label, value=rec.extras[key], inline=True)
    embed.add_field(
        name="リマインド",
        value="あり(1週間前・前日に参加者へ通知)" if rec.reminder else "なし",
        inline=False,
    )

    status = " (満員)" if rec.is_full else ""
    embed.add_field(
        name=f"{JOIN_EMOJI} 参加希望 {len(members)}/{rec.capacity}{status}",
        value=mentions(members) or "まだいません",
        inline=False,
    )
    if over:
        embed.add_field(name=f"定員超過 {len(over)}名(GM判断)", value=mentions(over), inline=False)
    embed.add_field(
        name=f"{INTEREST_EMOJI} 興味あり {len(rec.interested)}名",
        value=mentions(rec.interested) or "まだいません",
        inline=False,
    )

    if rec.cancelled:
        embed.set_footer(text="この募集は取り消されました")
    elif rec.is_full:
        embed.set_footer(text=f"参加希望は締め切りました / {INTEREST_EMOJI} 興味ありは引き続き受付中")
    else:
        embed.set_footer(text=f"{JOIN_EMOJI} 参加希望 / {INTEREST_EMOJI} 興味あり ― リアクションを外すと取消")
    return embed
