import discord
from discord.ext import commands, tasks
from discord import app_commands
import random
import asyncio
import sqlite3
import os
from typing import Optional
from datetime import datetime, timezone, timedelta
from dotenv import load_dotenv

load_dotenv()

# ─── Конфигурация из .env ─────────────────────────────────────────────────────
TARGET_CHANNEL_IDS = [
    int(x.strip())
    for x in os.getenv("TARGET_CHANNEL_IDS", "1189219118495318036").split(",")
]
PUNISH_ROLE_ID = int(os.getenv("PUNISH_ROLE_ID", "1507851659865227444"))
EVENT_DURATION = int(os.getenv("EVENT_DURATION", "180"))
MSK_HOUR_START = int(os.getenv("MSK_HOUR_START", "07"))
MSK_HOUR_END   = int(os.getenv("MSK_HOUR_END",   "23"))

SPECIAL_NUMBERS = [1, 31, 56, 78, 61, 67, 69, 42, 52, 120, 228, 230, 456, 1337, 1488, 333, 666, 777, 420, 999]
CHANCE_SPECIAL  = 10.0
CHANCE_NORMAL   = 90.0

SPECIAL_MEDIA: dict[int, str] = {
    1:    "https://i.imgur.com/2Kc9r61.gif",
    31:   "https://imgur.com/h0GEHiL",
    67:   "https://i.imgur.com/8NeIzfb.jpg",
    69:   "https://media4.giphy.com/media/v1.Y2lkPTZjMDliOTUya2NoNXZpNG1qaDkxOXJndGR1cXZoOGZ4anprN2lhODhiYmlrYmtlNyZlcD12MV9naWZzX3NlYXJjaCZjdD1n/f0dfHP73EjZ05M84Jq/200.gif",
    56:   "https://static.wikia.nocookie.net/mems/images/4/4d/56_%D0%B8%D0%BB%D0%B8_78.png/revision/latest?cb=20250905155709&path-prefix=ru",
    78:   "https://i.imgur.com/IOxJwy1.jpg",
    61:   "https://i.imgur.com/39sNurF.gif",
    42:   "https://i.ytimg.com/vi/V6aZeuXS4VQ/sddefault.jpg",
    52:   "https://i.ytimg.com/vi/dKIJ0sFYod0/maxresdefault.jpg",
    120:  "https://media1.tenor.com/m/T9_mANn8GKEAAAAC/squid-game.gif",
    228:  "https://i.imgur.com/Lqzep6H.jpg",
    230:  "https://i.imgur.com/d121qOk.jpg",
    456:  "https://i.imgur.com/mU15uFe.gif",
    1337: "https://images.meme-arsenal.com/76335912985092c5fa4dc45140d404a0.jpg",
    333:  "https://previews.123rf.com/images/surachai1/surachai12008/surachai1200800011/153330599-number-333-three-hundred-thirty-three-made-from-fire-flame-isolated-on-black-background.jpg",
    666:  "https://i.imgur.com/gUREEvt.jpg",
    777:  "https://i.imgur.com/lF8EJsd.gif",
    420:  "https://i.imgur.com/YQO4Nad.jpg",
    999:  "https://images-ext-1.discordapp.net/external/-E4HOd1ntFV_GJpwN0dhTE-9KvQfmLiXKJHFXnXgYOY/https/c.tenor.com/PUKOmpOFFg8AAAAd/tenor.gif",
    1488: "https://i.imgur.com/65CmFKj.jpg",
}

DB_PATH = "/data/bot_data.db"


# ─── База данных ──────────────────────────────────────────────────────────────
def db_init() -> None:
    with sqlite3.connect(DB_PATH) as conn:
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS tribute_log (
                id      INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                ts      TEXT    NOT NULL
            );
            CREATE TABLE IF NOT EXISTS event_clicks (
                user_id INTEGER PRIMARY KEY
            );
        """)


def db_event_clear() -> None:
    with sqlite3.connect(DB_PATH) as conn:
        conn.execute("DELETE FROM event_clicks")


def db_event_add_click(user_id: int) -> None:
    with sqlite3.connect(DB_PATH) as conn:
        conn.execute("INSERT OR IGNORE INTO event_clicks (user_id) VALUES (?)", (user_id,))


def db_event_has_clicked(user_id: int) -> bool:
    with sqlite3.connect(DB_PATH) as conn:
        return conn.execute(
            "SELECT 1 FROM event_clicks WHERE user_id = ?", (user_id,)
        ).fetchone() is not None


def db_log_tribute(user_id: int) -> None:
    with sqlite3.connect(DB_PATH) as conn:
        conn.execute(
            "INSERT INTO tribute_log (user_id, ts) VALUES (?, ?)",
            (user_id, datetime.now(timezone.utc).isoformat()),
        )


def db_leaderboard(limit: int = 10) -> list[tuple[int, int]]:
    with sqlite3.connect(DB_PATH) as conn:
        return conn.execute("""
            SELECT user_id, COUNT(*) AS cnt
            FROM tribute_log
            GROUP BY user_id
            ORDER BY cnt DESC
            LIMIT ?
        """, (limit,)).fetchall()


# ─── Вспомогательные функции ──────────────────────────────────────────────────
def make_event_embed(
    rolled_number: int,
    media_url: Optional[str],
    remaining: int,
) -> discord.Embed:
    m, s = divmod(remaining, 60)
    embed = discord.Embed(
        description=f"Выпало число **{rolled_number}**!\nУ вас есть время, чтобы отдать дань уважения.",
        color=discord.Color.gold(),
    )
    embed.add_field(name="⏱️ Осталось", value=f"{m}:{s:02d}", inline=False)
    if media_url:
        embed.set_image(url=media_url)
    return embed


# ─── Кнопка (persistent) ──────────────────────────────────────────────────────
class RespectButton(discord.ui.View):
    def __init__(self, cog: Optional["GameCog"] = None):
        super().__init__(timeout=None)
        self.cog = cog

    @discord.ui.button(
        label="Отдать дань уважения",
        style=discord.ButtonStyle.success,
        custom_id="pay_respect_btn",
    )
    async def pay_respect(self, interaction: discord.Interaction, button: discord.ui.Button):
        user = interaction.user

        if db_event_has_clicked(user.id):
            await interaction.response.send_message("Ты уже давал бля", ephemeral=True)
            return

        db_event_add_click(user.id)
        db_log_tribute(user.id)

        if isinstance(user, discord.Member):
            role = user.guild.get_role(PUNISH_ROLE_ID)
            if role and role in user.roles:
                try:
                    await user.remove_roles(role)
                    await interaction.response.send_message(
                        "Ты отдал дань уважения. Роль опущенного снята!", ephemeral=True
                    )
                except discord.Forbidden:
                    await interaction.response.send_message(
                        "Ты отдал дань, но у меня нет прав снять роль! "
                        "Попросите админов поднять роль бота выше.",
                        ephemeral=True,
                    )
                return

        await interaction.response.send_message("Ты отдал дань уважения (не опущенный)", ephemeral=True)


# ─── Основной Cog ─────────────────────────────────────────────────────────────
class GameCog(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        db_init()

        self.population = list(range(1501))
        normal_count = len(self.population) - len(SPECIAL_NUMBERS)
        w_special    = CHANCE_SPECIAL / len(SPECIAL_NUMBERS)
        w_normal     = CHANCE_NORMAL  / normal_count
        self.weights = [
            w_special if n in SPECIAL_NUMBERS else w_normal
            for n in self.population
        ]

    async def cog_load(self) -> None:
        self.bot.add_view(RespectButton(cog=self))
        self.hourly_roll.start()

    async def cog_unload(self) -> None:
        self.hourly_roll.cancel()

    # ── Таймер + наказание ────────────────────────────────────────────────────
    async def _event_timer_task(
        self,
        messages: list[discord.Message],
        rolled_number: int,
        media_url: Optional[str],
        eligible_ids: set[int],
        channels: list[discord.TextChannel],
    ) -> None:
        update_interval = 30
        remaining = EVENT_DURATION

        while remaining > update_interval:
            await asyncio.sleep(update_interval)
            remaining -= update_interval
            updated_embed = make_event_embed(rolled_number, media_url, remaining)
            for msg in messages:
                try:
                    await msg.edit(embed=updated_embed)
                except Exception:
                    pass

        await asyncio.sleep(remaining)

        final_embed = discord.Embed(
            description=f"Время вышло! Число было **{rolled_number}**.",
            color=discord.Color.red(),
        )
        if media_url:
            final_embed.set_image(url=media_url)

        for msg in messages:
            try:
                await msg.edit(embed=final_embed, view=None)
            except Exception:
                pass

        await self._apply_punishment(eligible_ids, channels)

    async def _apply_punishment(
        self,
        eligible_ids: set[int],
        channels: list[discord.TextChannel],
    ) -> None:
        guilds = {ch.guild for ch in channels}
        for guild in guilds:
            role = guild.get_role(PUNISH_ROLE_ID)
            if not role:
                print(f"ОШИБКА: Роль {PUNISH_ROLE_ID} не найдена на сервере {guild.name}")
                continue

            for member in guild.members:
                if member.bot:
                    continue
                if member.id not in eligible_ids:
                    continue
                if db_event_has_clicked(member.id):
                    continue
                if role not in member.roles:
                    try:
                        await member.add_roles(role)
                    except discord.Forbidden:
                        print(f"Нет прав выдать роль для {member.name}")

    # ── Основная логика ───────────────────────────────────────────────────────
    async def run_game_logic(
        self,
        channels: list[discord.TextChannel],
        bypass_time: bool = False,
    ) -> Optional[int]:
        if not bypass_time:
            msk_tz = timezone(timedelta(hours=3))
            if not (MSK_HOUR_START <= datetime.now(msk_tz).hour <= MSK_HOUR_END):
                return None

        rolled_number: int = random.choices(self.population, weights=self.weights, k=1)[0]

        if rolled_number in SPECIAL_NUMBERS:
            db_event_clear()
            media_url = SPECIAL_MEDIA.get(rolled_number)

            eligible_ids: set[int] = {
                member.id
                for ch in channels
                for member in ch.guild.members
                if not member.bot and ch.permissions_for(member).view_channel
            }

            sent_messages: list[discord.Message] = []
            for ch in channels:
                embed = make_event_embed(rolled_number, media_url, EVENT_DURATION)
                msg = await ch.send(embed=embed, view=RespectButton(cog=self))
                sent_messages.append(msg)

            asyncio.create_task(
                self._event_timer_task(sent_messages, rolled_number, media_url, eligible_ids, channels)
            )
        else:
            for ch in channels:
                await ch.send("")

        return rolled_number

    # ── Hourly loop ───────────────────────────────────────────────────────────
    @tasks.loop(hours=1)
    async def hourly_roll(self) -> None:
        target_channels = [
            ch for cid in TARGET_CHANNEL_IDS
            if (ch := self.bot.get_channel(cid)) is not None
        ]
        if target_channels:
            await self.run_game_logic(target_channels)

    @hourly_roll.before_loop
    async def before_hourly_roll(self) -> None:
        await self.bot.wait_until_ready()

    @hourly_roll.error
    async def hourly_roll_error(self, error: Exception) -> None:
        print(f"[hourly_roll] Необработанная ошибка: {error!r}")
        if not self.hourly_roll.is_running():
            self.hourly_roll.restart()

    # ── Slash-команды ─────────────────────────────────────────────────────────
    @app_commands.command(name="status", description="Проверить свой статус уважения")
    async def status(self, interaction: discord.Interaction) -> None:
        if not isinstance(interaction.user, discord.Member):
            await interaction.response.send_message(
                "Эту команду можно использовать только на сервере.", ephemeral=True
            )
            return

        role = interaction.user.guild.get_role(PUNISH_ROLE_ID)
        if role and role in interaction.user.roles:
            await interaction.response.send_message("Ваш статус: **Опущенный**. Фу бля пидра", ephemeral=True)
        else:
            await interaction.response.send_message("Ваш статус: **Не олух**.", ephemeral=True)

    @app_commands.command(name="force_roll", description="Принудительно запустить бросок (только для админов)")
    @app_commands.default_permissions(administrator=True)
    async def force_roll(self, interaction: discord.Interaction) -> None:
        if not isinstance(interaction.channel, discord.TextChannel):
            await interaction.response.send_message("Только в текстовых каналах!", ephemeral=True)
            return

        await interaction.response.send_message("Запускаю бросок...", ephemeral=True)
        rolled_number = await self.run_game_logic([interaction.channel], bypass_time=True)

        if rolled_number is None or rolled_number not in SPECIAL_NUMBERS:
            await interaction.edit_original_response(
                content="Бросок завершён. Выпало обычное число."
            )

    @app_commands.command(name="leaderboard", description="Топ пацыков")
    async def leaderboard(self, interaction: discord.Interaction) -> None:
        rows = db_leaderboard(10)
        if not rows:
            await interaction.response.send_message("Пока никто.", ephemeral=True)
            return

        medals = {1: "🥇", 2: "🥈", 3: "🥉"}
        lines: list[str] = []
        for i, (user_id, cnt) in enumerate(rows, 1):
            member = interaction.guild.get_member(user_id) if interaction.guild else None
            name   = member.display_name if member else f"<@{user_id}>"
            prefix = medals.get(i, f"**{i}.**")
            lines.append(f"{prefix} {name} — {cnt} раз(а)")

        embed = discord.Embed(
            title="🏆 Топ уважающих",
            description="\n".join(lines),
            color=discord.Color.gold(),
        )
        await interaction.response.send_message(embed=embed)

    @app_commands.command(name="penis", description="Измерить прибор (свой или чужой)")
    async def penis(self, interaction: discord.Interaction, user: discord.Member = None) -> None:
        target_user = user or interaction.user
        id_sum = sum(int(d) for d in str(target_user.id))
        x = id_sum % 69
        if x > 30:
            x = x % 33
            if x > 30:
                x = 30
        penis_str = "8" + "=" * x + "D"
        msg = f"Прибор **{target_user.display_name}**:\n" + penis_str
        await interaction.response.send_message(msg)


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(GameCog(bot))
