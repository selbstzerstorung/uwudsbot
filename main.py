import discord
from discord.ext import commands
import os
from dotenv import load_dotenv

# Загружаем переменные из .env файла
load_dotenv()


class RespectBot(commands.Bot):
    def __init__(self):
        intents = discord.Intents.default()
        intents.message_content = True
        intents.members = True  # Обязательно для итерации по участникам

        super().__init__(command_prefix="!", intents=intents)

    async def setup_hook(self):
        await self.load_extension("cogs.game_cog")
        await self.load_extension("cogs.nickname_cog")  # ← сюда
        synced = await self.tree.sync()
        print(f"Синхронизировано команд: {len(synced)}")
        print("Бот готов к работе.")


def main():
    bot = RespectBot()
    # Достаем токен из окружения
    TOKEN = os.getenv("BOT_TOKEN")

    if not TOKEN:
        raise ValueError("Токен не найден! Проверь файл .env")

    bot.run(TOKEN)


if __name__ == "__main__":
    main()
