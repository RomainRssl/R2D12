import discord
from discord import app_commands
from discord.ext import commands


class Moderation(commands.Cog):
    """Commandes de modération du bot R2D12."""

    def __init__(self, bot: commands.Bot):
        self.bot = bot

    @app_commands.command(name="kick", description="Expulser un membre du serveur")
    @app_commands.describe(membre="Le membre à expulser", raison="Raison de l'expulsion")
    @app_commands.default_permissions(kick_members=True)
    async def kick(self, interaction: discord.Interaction, membre: discord.Member, raison: str = "Aucune raison fournie"):
        if membre == interaction.user:
            await interaction.response.send_message("Vous ne pouvez pas vous expulser vous-même.", ephemeral=True)
            return
        if membre.top_role >= interaction.user.top_role:
            await interaction.response.send_message("Vous ne pouvez pas expulser un membre avec un rôle supérieur ou égal au vôtre.", ephemeral=True)
            return

        try:
            await membre.send(
                f"Vous avez été expulsé du serveur **{interaction.guild.name}**.\nRaison : {raison}"
            )
        except discord.Forbidden:
            pass

        await membre.kick(reason=f"{interaction.user} : {raison}")
        embed = discord.Embed(
            title="Membre expulsé",
            description=f"{membre.mention} a été expulsé par {interaction.user.mention}.",
            color=discord.Color.orange(),
        )
        embed.add_field(name="Raison", value=raison)
        await interaction.response.send_message(embed=embed)

    @app_commands.command(name="ban", description="Bannir un membre du serveur")
    @app_commands.describe(membre="Le membre à bannir", raison="Raison du bannissement", supprimer_messages="Nombre de jours de messages à supprimer (0-7)")
    @app_commands.default_permissions(ban_members=True)
    async def ban(self, interaction: discord.Interaction, membre: discord.Member, raison: str = "Aucune raison fournie", supprimer_messages: app_commands.Range[int, 0, 7] = 0):
        if membre == interaction.user:
            await interaction.response.send_message("Vous ne pouvez pas vous bannir vous-même.", ephemeral=True)
            return
        if membre.top_role >= interaction.user.top_role:
            await interaction.response.send_message("Vous ne pouvez pas bannir un membre avec un rôle supérieur ou égal au vôtre.", ephemeral=True)
            return

        try:
            await membre.send(
                f"Vous avez été banni du serveur **{interaction.guild.name}**.\nRaison : {raison}"
            )
        except discord.Forbidden:
            pass

        await membre.ban(reason=f"{interaction.user} : {raison}", delete_message_days=supprimer_messages)
        embed = discord.Embed(
            title="Membre banni",
            description=f"{membre.mention} a été banni par {interaction.user.mention}.",
            color=discord.Color.red(),
        )
        embed.add_field(name="Raison", value=raison)
        await interaction.response.send_message(embed=embed)

    @app_commands.command(name="clear", description="Supprimer un nombre de messages dans le salon")
    @app_commands.describe(nombre="Nombre de messages à supprimer (1-100)")
    @app_commands.default_permissions(manage_messages=True)
    async def clear(self, interaction: discord.Interaction, nombre: app_commands.Range[int, 1, 100] = 10):
        await interaction.response.defer(ephemeral=True)
        deleted = await interaction.channel.purge(limit=nombre)
        await interaction.followup.send(
            f"{len(deleted)} message(s) supprimé(s).",
            ephemeral=True,
        )


async def setup(bot: commands.Bot):
    await bot.add_cog(Moderation(bot))
