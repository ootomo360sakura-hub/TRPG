"""TRPGプレイヤー募集Bot

- /募集 → フォームで基本項目を入力 → 下書きで追加項目・リマインド有無を決めて投稿
- ✋(参加希望)/👀(興味あり)のリアクションをした人のメンションを記事内に書き加える
- 参加希望が定員に達したら自動で締切(👀興味ありは引き続き受付)
- リマインドありの募集は、開催1週間前と前日(24時間前)に参加者へメンションで通知
- 投稿者は記事の「GMメニュー」から内容編集・リマインド切替・募集取消ができる
"""

import asyncio
import logging
import os
import time
from collections import defaultdict

import discord
from discord import app_commands
from discord.ext import tasks

try:
    from dotenv import load_dotenv

    load_dotenv()
except ImportError:
    pass

from render import DAY, INTEREST_EMOJI, JOIN_EMOJI, WEEK, build_embed
from store import Recruitment, Store
from ui import BasicModal, GmMenuView

log = logging.getLogger("recruit-bot")

DB_PATH = os.getenv("DB_PATH", os.path.join(os.path.dirname(os.path.abspath(__file__)), "data", "recruit.db"))


class RecruitBot(discord.Client):
    def __init__(self) -> None:
        # リアクションイベントと既定のギルド情報だけで動く(特権インテント不要)
        super().__init__(intents=discord.Intents.default())
        self.tree = app_commands.CommandTree(self)
        self.store = Store(DB_PATH)
        # 同じ記事への同時操作で編集が競合しないよう記事ごとに直列化
        self.locks: defaultdict[int, asyncio.Lock] = defaultdict(asyncio.Lock)

    async def setup_hook(self) -> None:
        self.add_view(GmMenuView())  # 再起動前に投稿した記事のボタンも有効にする
        guild_id = os.getenv("GUILD_ID")
        if guild_id:
            guild = discord.Object(id=int(guild_id))
            self.tree.copy_global_to(guild=guild)
            await self.tree.sync(guild=guild)
        else:
            await self.tree.sync()
        self.reminder_loop.start()

    async def on_ready(self) -> None:
        log.info("ログインしました: %s (id=%s)", self.user, self.user.id)

    # ------------------------------------------------------------ 記事の更新

    async def fetch_post(self, rec: Recruitment) -> discord.Message | None:
        try:
            channel = self.get_channel(rec.channel_id) or await self.fetch_channel(rec.channel_id)
            return await channel.fetch_message(rec.message_id)
        except (discord.NotFound, discord.Forbidden):
            return None

    async def save_and_refresh(self, rec: Recruitment, message: discord.Message | None = None) -> None:
        """DBに保存し、募集記事の表示とBot自身の✋リアクションを最新状態にする。"""
        self.store.save(rec)
        message = message or await self.fetch_post(rec)
        if message is None:
            return
        await message.edit(embed=build_embed(rec), view=None if rec.cancelled else GmMenuView())

        # 満員(締切)の間はBotの✋を外して受付終了を示し、空きが出たら付け直す
        bot_has_join = any(str(r.emoji) == JOIN_EMOJI and r.me for r in message.reactions)
        want_join = not rec.cancelled and not rec.is_full
        if bot_has_join and not want_join:
            await message.remove_reaction(JOIN_EMOJI, self.user)
        elif want_join and not bot_has_join:
            await message.add_reaction(JOIN_EMOJI)

    async def notify(self, rec: Recruitment, text: str, include_gm: bool = False) -> None:
        """募集記事への返信として、参加希望者にメンション付きで知らせる。"""
        message = await self.fetch_post(rec)
        if message is None:
            return
        targets = rec.participants + ([rec.gm_id] if include_gm and rec.gm_id not in rec.participants else [])
        body = text if not targets else f"{text}\n{' '.join(f'<@{u}>' for u in targets)}"
        await message.reply(body, allowed_mentions=discord.AllowedMentions(users=True), mention_author=False)

    # ------------------------------------------------------------ リアクション

    async def on_raw_reaction_add(self, payload: discord.RawReactionActionEvent) -> None:
        await self.handle_reaction(payload)

    async def on_raw_reaction_remove(self, payload: discord.RawReactionActionEvent) -> None:
        await self.handle_reaction(payload)

    async def handle_reaction(self, payload: discord.RawReactionActionEvent) -> None:
        if str(payload.emoji) not in (JOIN_EMOJI, INTEREST_EMOJI) or payload.user_id == self.user.id:
            return
        async with self.locks[payload.message_id]:
            rec = self.store.get(payload.message_id)
            if rec is None or rec.cancelled:
                return
            message = await self.fetch_post(rec)
            if message is None:
                return
            await self.sync_reactions(rec, message)

    async def sync_reactions(self, rec: Recruitment, message: discord.Message) -> None:
        """記事に実際に付いているリアクションと、DBの参加者・興味あり一覧を一致させる。"""
        reacted: dict[str, list[int]] = {JOIN_EMOJI: [], INTEREST_EMOJI: []}
        for reaction in message.reactions:
            key = str(reaction.emoji)
            if key in reacted:
                async for user in reaction.users():
                    if not user.bot and user.id != rec.gm_id:
                        reacted[key].append(user.id)

        def merge(current: list[int], now: list[int]) -> list[int]:
            # 記録済みの順番(=リアクションした順)を保ち、外した人を除いて新しい人を末尾に足す
            kept = [u for u in current if u in now]
            return kept + [u for u in now if u not in kept]

        participants = merge(rec.participants, reacted[JOIN_EMOJI])
        interested = [u for u in merge(rec.interested, reacted[INTEREST_EMOJI]) if u not in participants]
        if participants == rec.participants and interested == rec.interested:
            return
        rec.participants, rec.interested = participants, interested
        await self.save_and_refresh(rec, message)

    async def on_raw_message_delete(self, payload: discord.RawMessageDeleteEvent) -> None:
        self.store.delete(payload.message_id)

    # ------------------------------------------------------------ リマインド

    @tasks.loop(minutes=1)
    async def reminder_loop(self) -> None:
        now = int(time.time())
        week, day = int(WEEK.total_seconds()), int(DAY.total_seconds())
        for rec in self.store.pending_reminders(now):
            async with self.locks[rec.message_id]:
                rec = self.store.get(rec.message_id)
                if rec is None or rec.cancelled or not rec.reminder:
                    continue
                try:
                    if not rec.day_sent and now >= rec.start_at - day:
                        # Bot停止などで1週間前の分を逃していたら、前日分だけ送る
                        rec.week_sent = rec.day_sent = True
                        await self.notify(rec, self.reminder_text(rec, "明日"), include_gm=True)
                    elif not rec.week_sent and now >= rec.start_at - week:
                        rec.week_sent = True
                        await self.notify(rec, self.reminder_text(rec, "1週間後"), include_gm=True)
                    else:
                        continue
                except discord.HTTPException:
                    log.exception("リマインド送信に失敗しました: %s", rec.message_id)
                    continue
                self.store.save(rec)

    @reminder_loop.before_loop
    async def before_reminder_loop(self) -> None:
        await self.wait_until_ready()

    @staticmethod
    def reminder_text(rec: Recruitment, when: str) -> str:
        return f"🔔 **リマインド** 「{rec.title}」は{when}、<t:{rec.start_at}:F> 開催です!"


bot = RecruitBot()


@bot.tree.command(name="募集", description="TRPGのプレイヤー募集記事を作成します")
@app_commands.guild_only()
async def recruit(interaction: discord.Interaction) -> None:
    await interaction.response.send_modal(BasicModal())


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    token = os.getenv("DISCORD_TOKEN")
    if not token:
        raise SystemExit("環境変数 DISCORD_TOKEN が設定されていません(.env を確認してください)")
    bot.run(token, log_handler=None)


if __name__ == "__main__":
    main()
