import discord
from discord import app_commands
from discord.ext import commands
import time


class General(commands.Cog):
    """Commandes générales du bot R2D12."""

    def __init__(self, bot: commands.Bot):
        self.bot = bot

    @app_commands.command(name="ping", description="Affiche la latence du bot")
    async def ping(self, interaction: discord.Interaction):
        latency = round(self.bot.latency * 1000)
        embed = discord.Embed(
            title="Pong !",
            description=f"Latence : **{latency}ms**",
            color=discord.Color.green() if latency < 100 else discord.Color.orange(),
        )
        await interaction.response.send_message(embed=embed)

    @app_commands.command(name="help", description="Liste toutes les commandes disponibles")
    async def help(self, interaction: discord.Interaction):
        embed = discord.Embed(
            title="R2D12 — Aide",
            description="Voici toutes les commandes disponibles :",
            color=discord.Color.blurple(),
        )
        embed.add_field(
            name="Général",
            value=(
                "`/ping` — Latence du bot\n"
                "`/help` — Cette aide\n"
                "`/serverinfo` — Infos sur le serveur\n"
                "`/userinfo [@membre]` — Infos sur un membre"
            ),
            inline=False,
        )
        embed.add_field(
            name="Modération",
            value=(
                "`/kick @membre [raison]` — Expulser un membre\n"
                "`/ban @membre [raison]` — Bannir un membre\n"
                "`/clear [nombre]` — Supprimer des messages"
            ),
            inline=False,
        )
        embed.add_field(
            name="Templates & Annonces",
            value=(
                "`/template créer <nom> <message>` — Créer un template avec `{variables}`\n"
                "`/template utiliser <nom> [#salon]` — Utiliser un template (formulaire)\n"
                "`/template liste` — Voir tous les templates\n"
                "`/template supprimer <nom>` — Supprimer un template\n"
                "`/annonce #salon <titre> <message>` — Envoyer une annonce formatée"
            ),
            inline=False,
        )
        embed.add_field(
            name="Bienvenue",
            value=(
                "`/bienvenue configurer #salon [message]` — Configurer le message d'accueil\n"
                "`/bienvenue tester` — Prévisualiser le message de bienvenue\n"
                "`/bienvenue statut` — Voir la configuration actuelle\n"
                "`/bienvenue désactiver` — Désactiver les messages de bienvenue"
            ),
            inline=False,
        )
        embed.set_footer(text="R2D12 • Beep boop !")
        await interaction.response.send_message(embed=embed)

    @app_commands.command(name="serverinfo", description="Affiche les informations du serveur")
    async def serverinfo(self, interaction: discord.Interaction):
        guild = interaction.guild
        embed = discord.Embed(
            title=guild.name,
            color=discord.Color.blurple(),
        )
        if guild.icon:
            embed.set_thumbnail(url=guild.icon.url)
        embed.add_field(name="Propriétaire", value=guild.owner.mention if guild.owner else "Inconnu")
        embed.add_field(name="Membres", value=guild.member_count)
        embed.add_field(name="Salons", value=len(guild.channels))
        embed.add_field(name="Rôles", value=len(guild.roles))
        embed.add_field(name="Créé le", value=discord.utils.format_dt(guild.created_at, style="D"))
        embed.set_footer(text=f"ID : {guild.id}")
        await interaction.response.send_message(embed=embed)

    @app_commands.command(name="userinfo", description="Affiche les informations d'un membre")
    @app_commands.describe(membre="Le membre dont vous voulez voir les infos (vous par défaut)")
    async def userinfo(self, interaction: discord.Interaction, membre: discord.Member = None):
        membre = membre or interaction.user
        roles = [r.mention for r in membre.roles if r.name != "@everyone"]
        embed = discord.Embed(
            title=str(membre),
            color=membre.color,
        )
        embed.set_thumbnail(url=membre.display_avatar.url)
        embed.add_field(name="Pseudo", value=membre.display_name)
        embed.add_field(name="Compte créé le", value=discord.utils.format_dt(membre.created_at, style="D"))
        embed.add_field(name="A rejoint le", value=discord.utils.format_dt(membre.joined_at, style="D") if membre.joined_at else "Inconnu")
        embed.add_field(
            name=f"Rôles ({len(roles)})",
            value=" ".join(roles) if roles else "Aucun",
            inline=False,
        )
        embed.set_footer(text=f"ID : {membre.id}")
        await interaction.response.send_message(embed=embed)


async def setup(bot: commands.Bot):
    await bot.add_cog(General(bot))
