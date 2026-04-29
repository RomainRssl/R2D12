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
        await self.load_extension("cogs.templates")
        await self.load_extension("cogs.welcome")
        await self.load_extension("cogs.birthday")
        await self.load_extension("cogs.logs")
        await self.load_extension("cogs.autoroles")
        await self.load_extension("cogs.reactionroles")
        await self.load_extension("cogs.polls")
        await self.load_extension("cogs.suggestions")
        await self.load_extension("cogs.levels")
        await self.load_extension("cogs.economy")
        await self.load_extension("cogs.giveaways")
        await self.load_extension("cogs.tickets")
        await self.load_extension("cogs.scheduled")
        await self.load_extension("cogs.counters")
        await self.load_extension("cogs.laptimes")
        await self.load_extension("cogs.sessions")
        await self.load_extension("cogs.championship")
        await self.load_extension("cogs.forwarder")
        await self.load_extension("cogs.wordreplace")
        await self.load_extension("cogs.roles")
        await self.load_extension("cogs.channels")
        await self.load_extension("cogs.calendar")

        if GUILD_ID:
            guild = discord.Object(id=int(GUILD_ID))
            self.tree.copy_global_to(guild=guild)
            synced = await self.tree.sync(guild=guild)
            print(f"Slash commands synchronisées sur le serveur {GUILD_ID} : {[c.name for c in synced]}", flush=True)
        else:
            synced = await self.tree.sync()
            print(f"Slash commands synchronisées globalement : {[c.name for c in synced]}", flush=True)

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
