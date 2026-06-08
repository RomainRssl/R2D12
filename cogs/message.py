import discord
from discord import app_commands
from discord.ext import commands


class Message(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    @app_commands.command(
        name="message",
        description="Envoie un message via le bot dans un channel (expéditeur invisible)",
    )
    @app_commands.describe(
        contenu="Texte du message à envoyer",
        channel="Channel cible (défaut : channel actuel)",
    )
    async def message(
        self,
        interaction: discord.Interaction,
        contenu: str,
        channel: discord.TextChannel | None = None,
    ):
        if not interaction.user.guild_permissions.manage_guild and not interaction.user.guild_permissions.administrator:
            await interaction.response.send_message("❌ Commande réservée au staff.", ephemeral=True)
            return
        target = channel or interaction.channel
        await target.send(contenu)
        mention = target.mention if channel else "ce channel"
        await interaction.response.send_message(
            f"✅ Message envoyé dans {mention}.", ephemeral=True
        )


async def setup(bot: commands.Bot):
    await bot.add_cog(Message(bot))
