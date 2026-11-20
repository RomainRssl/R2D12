import logging
import os
import discord
from discord import app_commands
from discord.ext import commands
from dotenv import load_dotenv

load_dotenv()

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logging.getLogger("discord").setLevel(logging.WARNING)

TOKEN = os.getenv("DISCORD_TOKEN")
GUILD_ID = os.getenv("GUILD_ID")


class R2D12(commands.Bot):
    def __init__(self):
        intents = discord.Intents.default()
        intents.message_content = True
        intents.members = True
        super().__init__(command_prefix="!", intents=intents)

    async def setup_hook(self):
        self.tree.on_error = self.on_app_command_error
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
        await self.load_extension("cogs.pilots")
        await self.load_extension("cogs.credits_admin")
        await self.load_extension("cogs.pregrid")
        await self.load_extension("cogs.splits")
        await self.load_extension("cogs.message")
        await self.load_extension("cogs.tournois")
        await self.load_extension("cogs.lmu_sync")

        if GUILD_ID:
            guild = discord.Object(id=int(GUILD_ID))
            self.tree.copy_global_to(guild=guild)
            synced = await self.tree.sync(guild=guild)
            print(f"Slash commands synchronisées sur le serveur {GUILD_ID} : {[c.name for c in synced]}", flush=True)
        else:
            synced = await self.tree.sync()
            print(f"Slash commands synchronisées globalement : {[c.name for c in synced]}", flush=True)

    async def on_app_command_error(self, interaction: discord.Interaction, error: app_commands.AppCommandError):
        """Réponse éphémère quand une vérification de permission échoue."""
        if isinstance(error, app_commands.MissingPermissions):
            msg = "⛔ Tu n'as pas les permissions nécessaires pour utiliser cette commande."
        elif isinstance(error, (app_commands.MissingRole, app_commands.MissingAnyRole)):
            msg = "⛔ Cette commande est réservée à un rôle que tu n'as pas."
        elif isinstance(error, app_commands.NoPrivateMessage):
            msg = "Cette commande ne fonctionne que sur un serveur."
        elif isinstance(error, app_commands.CheckFailure):
            msg = "⛔ Tu ne peux pas utiliser cette commande."
        else:
            name = interaction.command.qualified_name if interaction.command else "?"
            logging.getLogger("r2d12").error("Erreur dans /%s", name, exc_info=error)
            msg = "❌ Une erreur est survenue pendant l'exécution de la commande."
        try:
            if interaction.response.is_done():
                await interaction.followup.send(msg, ephemeral=True)
            else:
                await interaction.response.send_message(msg, ephemeral=True)
        except discord.HTTPException:
            pass

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
