import os
import discord
from discord.ext import commands
from dotenv import load_dotenv

load_dotenv()

TOKEN = os.getenv("DISCORD_TOKEN")
GUILD_ID = os.getenv("GUILD_ID")


class R2D12(commands.Bot):
    def __init__(self):
        intents = discord.Intents.default()
        intents.message_content = True
        intents.members = True
        super().__init__(command_prefix="!", intents=intents)

    async def setup_hook(self):
        await self.load_extension("cogs.general")
        await self.load_extension("cogs.moderation")

        # Sync les slash commands sur le serveur de test si GUILD_ID défini,
        # sinon sync global (peut prendre jusqu'à 1h)
        if GUILD_ID:
            guild = discord.Object(id=int(GUILD_ID))
            self.tree.copy_global_to(guild=guild)
            await self.tree.sync(guild=guild)
            print(f"Slash commands synchronisées sur le serveur {GUILD_ID}")
        else:
            await self.tree.sync()
            print("Slash commands synchronisées globalement")

    async def on_ready(self):
        print(f"R2D12 est en ligne ! Connecté en tant que {self.user} (ID: {self.user.id})")
        await self.change_presence(
            activity=discord.Activity(
                type=discord.ActivityType.watching,
                name="la galaxie | /help"
            )
        )


bot = R2D12()

if __name__ == "__main__":
    if not TOKEN:
        raise ValueError("DISCORD_TOKEN manquant dans le fichier .env")
    bot.run(TOKEN)
