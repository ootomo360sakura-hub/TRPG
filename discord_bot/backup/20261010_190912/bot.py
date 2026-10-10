"""TRPGプレイヤー募集Bot

/募集 で募集記事(Embed)を投稿し、参加リアクションを付けた人のメンションを
記事内の「参加者」欄に自動で書き加える。

募集の状態(GM・定員・参加者の並び順)はすべて記事のEmbed自体に持たせているので、
Botを再起動しても既存の募集記事はそのまま動き続ける。
"""

import asyncio
import os
import re
from collections import defaultdict

import discord
from discord import app_commands

try:
    from dotenv import load_dotenv

    load_dotenv()
except ImportError:
    pass

JOIN_EMOJI = "✋"

FOOTER_OPEN = f"{JOIN_EMOJI} リアクションで参加 / 外すと参加取消"
FOOTER_CLOSED = "この募集は締め切られました"
TITLE_PREFIX = "【TRPG募集】"
CLOSED_PREFIX = "【締切】"

FIELD_GM = "GM"
FIELD_DATE = "日時"
FIELD_SYSTEM = "システム"
FIELD_CAPACITY = "定員"
FIELD_MEMBERS = "参加者"
FIELD_WAITLIST = "補欠"

COLOR_OPEN = discord.Color.green()
COLOR_FULL = discord.Color.orange()
COLOR_CLOSED = discord.Color.dark_grey()

MENTION_RE = re.compile(r"<@!?(\d+)>")


def parse_ids(text: str | None) -> list[int]:
    return [int(m) for m in MENTION_RE.findall(text or "")]


def is_recruitment(message: discord.Message, bot_user: discord.ClientUser) -> bool:
    if message.author.id != bot_user.id or not message.embeds:
        return False
    title = message.embeds[0].title or ""
    return title.startswith(TITLE_PREFIX) or title.startswith(CLOSED_PREFIX)


def is_closed(embed: discord.Embed) -> bool:
    return (embed.title or "").startswith(CLOSED_PREFIX)


def get_field(embed: discord.Embed, name: str) -> str | None:
    for field in embed.fields:
        if field.name.startswith(name):
            return field.value
    return None


def get_capacity(embed: discord.Embed) -> int:
    value = get_field(embed, FIELD_CAPACITY) or ""
    m = re.search(r"\d+", value)
    return int(m.group()) if m else 0


def build_embed(
    *,
    title: str,
    gm_id: int,
    capacity: int,
    date: str | None,
    system: str | None,
    details: str | None,
    participants: list[int],
    closed: bool = False,
) -> discord.Embed:
    members = participants[:capacity]
    waitlist = participants[capacity:]
    full = len(members) >= capacity

    if closed:
        color = COLOR_CLOSED
        prefix = CLOSED_PREFIX
    else:
        color = COLOR_FULL if full else COLOR_OPEN
        prefix = TITLE_PREFIX

    embed = discord.Embed(title=f"{prefix}{title}", description=details or None, color=color)
    embed.add_field(name=FIELD_GM, value=f"<@{gm_id}>", inline=True)
    if date:
        embed.add_field(name=FIELD_DATE, value=date, inline=True)
    if system:
        embed.add_field(name=FIELD_SYSTEM, value=system, inline=True)
    embed.add_field(name=FIELD_CAPACITY, value=f"{capacity}名", inline=True)

    status = " (満員)" if full and not closed else ""
    embed.add_field(
        name=f"{FIELD_MEMBERS} {len(members)}/{capacity}{status}",
        value="\n".join(f"<@{uid}>" for uid in members) or "まだいません",
        inline=False,
    )
    if waitlist:
        embed.add_field(
            name=f"{FIELD_WAITLIST} {len(waitlist)}名",
            value="\n".join(f"<@{uid}>" for uid in waitlist),
            inline=False,
        )
    embed.set_footer(text=FOOTER_CLOSED if closed else FOOTER_OPEN)
    return embed


def rebuild_from(embed: discord.Embed, participants: list[int], closed: bool) -> discord.Embed:
    """既存の募集Embedの基本情報を引き継ぎ、参加者だけ差し替えたEmbedを作る。"""
    raw_title = embed.title or ""
    for prefix in (TITLE_PREFIX, CLOSED_PREFIX):
        if raw_title.startswith(prefix):
            raw_title = raw_title[len(prefix):]
            break
    gm_ids = parse_ids(get_field(embed, FIELD_GM))
    return build_embed(
        title=raw_title,
        gm_id=gm_ids[0] if gm_ids else 0,
        capacity=get_capacity(embed),
        date=get_field(embed, FIELD_DATE),
        system=get_field(embed, FIELD_SYSTEM),
        details=embed.description,
        participants=participants,
        closed=closed,
    )


class RecruitBot(discord.Client):
    def __init__(self) -> None:
        # リアクションイベントと既定のギルド情報だけで動く(特権インテント不要)
        intents = discord.Intents.default()
        super().__init__(intents=intents)
        self.tree = app_commands.CommandTree(self)
        # 同じ記事に連続でリアクションされても編集が競合しないよう記事ごとに直列化
        self.locks: defaultdict[int, asyncio.Lock] = defaultdict(asyncio.Lock)

    async def setup_hook(self) -> None:
        guild_id = os.getenv("GUILD_ID")
        if guild_id:
            guild = discord.Object(id=int(guild_id))
            self.tree.copy_global_to(guild=guild)
            await self.tree.sync(guild=guild)
        else:
            await self.tree.sync()

    async def on_ready(self) -> None:
        print(f"ログインしました: {self.user} (id={self.user.id})")

    async def on_raw_reaction_add(self, payload: discord.RawReactionActionEvent) -> None:
        await self.handle_reaction(payload)

    async def on_raw_reaction_remove(self, payload: discord.RawReactionActionEvent) -> None:
        await self.handle_reaction(payload)

    async def handle_reaction(self, payload: discord.RawReactionActionEvent) -> None:
        if str(payload.emoji) != JOIN_EMOJI or payload.user_id == self.user.id:
            return
        channel = self.get_channel(payload.channel_id) or await self.fetch_channel(payload.channel_id)
        async with self.locks[payload.message_id]:
            try:
                message = await channel.fetch_message(payload.message_id)
            except discord.NotFound:
                return
            if not is_recruitment(message, self.user):
                return
            await self.sync_participants(message)

    async def sync_participants(self, message: discord.Message) -> None:
        """記事の参加者欄を、実際に付いているリアクションと一致させる。"""
        embed = message.embeds[0]
        if is_closed(embed):
            return

        gm_ids = parse_ids(get_field(embed, FIELD_GM))
        reacted: list[int] = []
        for reaction in message.reactions:
            if str(reaction.emoji) == JOIN_EMOJI:
                async for user in reaction.users():
                    if not user.bot and user.id not in gm_ids:
                        reacted.append(user.id)
                break

        # 記事に載っている順番(=リアクションした順)を保ちつつ、外した人を除き、新しい人を末尾に追加
        current = parse_ids(get_field(embed, FIELD_MEMBERS)) + parse_ids(get_field(embed, FIELD_WAITLIST))
        reacted_set = set(reacted)
        ordered = [uid for uid in current if uid in reacted_set]
        ordered += [uid for uid in reacted if uid not in ordered]

        if ordered == current:
            return
        await message.edit(embed=rebuild_from(embed, ordered, closed=False))


bot = RecruitBot()


@bot.tree.command(name="募集", description="TRPGのプレイヤー募集記事を投稿します")
@app_commands.guild_only()
@app_commands.rename(title="タイトル", capacity="定員", date="日時", system="システム", details="詳細")
@app_commands.describe(
    title="シナリオ名・卓の名前",
    capacity="募集するプレイヤー人数(GMを除く)",
    date="開催日時(例: 10/20(日) 21:00〜)",
    system="ゲームシステム(例: CoC6版)",
    details="募集の詳細・注意事項など",
)
async def recruit(
    interaction: discord.Interaction,
    title: str,
    capacity: app_commands.Range[int, 1, 20],
    date: str | None = None,
    system: str | None = None,
    details: str | None = None,
) -> None:
    embed = build_embed(
        title=title,
        gm_id=interaction.user.id,
        capacity=capacity,
        date=date,
        system=system,
        details=details,
        participants=[],
    )
    await interaction.response.send_message(embed=embed)
    message = await interaction.original_response()
    await message.add_reaction(JOIN_EMOJI)


@bot.tree.context_menu(name="募集を締め切る")
@app_commands.guild_only()
async def close_recruitment(interaction: discord.Interaction, message: discord.Message) -> None:
    if not is_recruitment(message, bot.user):
        await interaction.response.send_message("これは募集記事ではありません。", ephemeral=True)
        return
    embed = message.embeds[0]
    if is_closed(embed):
        await interaction.response.send_message("この募集はすでに締め切られています。", ephemeral=True)
        return
    gm_ids = parse_ids(get_field(embed, FIELD_GM))
    perms = interaction.channel.permissions_for(interaction.user)
    if interaction.user.id not in gm_ids and not perms.manage_messages:
        await interaction.response.send_message("締め切れるのはGM(募集者)だけです。", ephemeral=True)
        return

    await interaction.response.defer(ephemeral=True)
    async with bot.locks[message.id]:
        participants = parse_ids(get_field(embed, FIELD_MEMBERS)) + parse_ids(get_field(embed, FIELD_WAITLIST))
        await message.edit(embed=rebuild_from(embed, participants, closed=True))
    await interaction.followup.send("募集を締め切りました。", ephemeral=True)


def main() -> None:
    token = os.getenv("DISCORD_TOKEN")
    if not token:
        raise SystemExit("環境変数 DISCORD_TOKEN が設定されていません(.env を確認してください)")
    bot.run(token)


if __name__ == "__main__":
    main()
