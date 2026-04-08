import json
import os
import discord
from discord import app_commands
from discord.ext import commands

LOGS_FILE = "data/logs.json"


def load_logs() -> dict:
    if not os.path.exists(LOGS_FILE):
        return {}
    with open(LOGS_FILE, "r", encoding="utf-8") as f:
        return json.load(f)


def save_logs(data: dict):
    os.makedirs("data", exist_ok=True)
    with open(LOGS_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


async def get_log_channel(guild: discord.Guild) -> discord.TextChannel | None:
    data = load_logs()
    config = data.get(str(guild.id))
    if not config or not config.get("enabled", True):
        return None
    return guild.get_channel(config.get("channel_id", 0))


logs_group = app_commands.Group(name="logs", description="Configuration des logs d'audit du serveur")


class Logs(commands.Cog):
    """Logs d'audit automatiques."""

    def __init__(self, bot: commands.Bot):
        self.bot = bot

    # ── Commandes admin ───────────────────────────────────────────────────────

    @logs_group.command(name="configurer", description="Définir le salon des logs")
    @app_commands.describe(salon="Salon où envoyer les logs")
    @app_commands.default_permissions(manage_guild=True)
    async def logs_set(self, interaction: discord.Interaction, salon: discord.TextChannel):
        data = load_logs()
        data[str(interaction.guild_id)] = {"channel_id": salon.id, "enabled": True}
        save_logs(data)
        embed = discord.Embed(title="Logs configurés", color=discord.Color.green())
        embed.add_field(name="Salon", value=salon.mention)
        embed.add_field(name="Activé", value="Oui")
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @logs_group.command(name="désactiver", description="Désactiver les logs")
    @app_commands.default_permissions(manage_guild=True)
    async def logs_disable(self, interaction: discord.Interaction):
        data = load_logs()
        if str(interaction.guild_id) not in data:
            await interaction.response.send_message("Aucun log configuré.", ephemeral=True)
            return
        data[str(interaction.guild_id)]["enabled"] = False
        save_logs(data)
        await interaction.response.send_message("Logs désactivés.", ephemeral=True)

    @logs_group.command(name="statut", description="Voir la configuration des logs")
    async def logs_status(self, interaction: discord.Interaction):
        data = load_logs()
        config = data.get(str(interaction.guild_id))
        if not config:
            await interaction.response.send_message("Aucun log configuré.", ephemeral=True)
            return
        channel = interaction.guild.get_channel(config.get("channel_id", 0))
        embed = discord.Embed(title="Configuration des logs", color=discord.Color.blurple())
        embed.add_field(name="Salon", value=channel.mention if channel else "`introuvable`")
        embed.add_field(name="Activé", value="Oui" if config.get("enabled", True) else "Non")
        await interaction.response.send_message(embed=embed, ephemeral=True)

    # ── Events ────────────────────────────────────────────────────────────────

    @commands.Cog.listener()
    async def on_member_join(self, member: discord.Member):
        channel = await get_log_channel(member.guild)
        if not channel:
            return
        embed = discord.Embed(title="Membre rejoint", description=f"{member.mention} a rejoint le serveur.", color=discord.Color.green())
        embed.set_thumbnail(url=member.display_avatar.url)
        embed.add_field(name="Compte créé le", value=discord.utils.format_dt(member.created_at, style="D"))
        embed.set_footer(text=f"ID : {member.id}")
        await channel.send(embed=embed)

    @commands.Cog.listener()
    async def on_member_remove(self, member: discord.Member):
        channel = await get_log_channel(member.guild)
        if not channel:
            return
        embed = discord.Embed(title="Membre parti", description=f"**{member}** a quitté le serveur.", color=discord.Color.red())
        embed.set_thumbnail(url=member.display_avatar.url)
        roles = [r.mention for r in member.roles if r.name != "@everyone"]
        embed.add_field(name="Rôles", value=" ".join(roles) if roles else "Aucun", inline=False)
        embed.set_footer(text=f"ID : {member.id}")
        await channel.send(embed=embed)

    @commands.Cog.listener()
    async def on_member_ban(self, guild: discord.Guild, user: discord.User):
        channel = await get_log_channel(guild)
        if not channel:
            return
        embed = discord.Embed(title="Membre banni", description=f"**{user}** a été banni.", color=discord.Color.dark_red())
        embed.set_thumbnail(url=user.display_avatar.url)
        embed.set_footer(text=f"ID : {user.id}")
        await channel.send(embed=embed)

    @commands.Cog.listener()
    async def on_member_unban(self, guild: discord.Guild, user: discord.User):
        channel = await get_log_channel(guild)
        if not channel:
            return
        embed = discord.Embed(title="Membre débanni", description=f"**{user}** a été débanni.", color=discord.Color.orange())
        embed.set_thumbnail(url=user.display_avatar.url)
        embed.set_footer(text=f"ID : {user.id}")
        await channel.send(embed=embed)

    @commands.Cog.listener()
    async def on_message_delete(self, message: discord.Message):
        if message.author.bot or not message.guild:
            return
        channel = await get_log_channel(message.guild)
        if not channel:
            return
        embed = discord.Embed(title="Message supprimé", color=discord.Color.yellow())
        embed.add_field(name="Auteur", value=message.author.mention, inline=True)
        embed.add_field(name="Salon", value=message.channel.mention, inline=True)
        embed.add_field(name="Contenu", value=message.content[:1000] or "_[vide]_", inline=False)
        embed.set_footer(text=f"ID message : {message.id}")
        await channel.send(embed=embed)

    @commands.Cog.listener()
    async def on_message_edit(self, before: discord.Message, after: discord.Message):
        if before.author.bot or not before.guild or before.content == after.content:
            return
        channel = await get_log_channel(before.guild)
        if not channel:
            return
        embed = discord.Embed(title="Message modifié", color=discord.Color.blue())
        embed.add_field(name="Auteur", value=before.author.mention, inline=True)
        embed.add_field(name="Salon", value=before.channel.mention, inline=True)
        embed.add_field(name="Avant", value=before.content[:500] or "_[vide]_", inline=False)
        embed.add_field(name="Après", value=after.content[:500] or "_[vide]_", inline=False)
        embed.set_footer(text=f"ID message : {before.id}")
        await channel.send(embed=embed)

    @commands.Cog.listener()
    async def on_member_update(self, before: discord.Member, after: discord.Member):
        if before.roles == after.roles:
            return
        channel = await get_log_channel(before.guild)
        if not channel:
            return
        added = [r for r in after.roles if r not in before.roles]
        removed = [r for r in before.roles if r not in after.roles]
        if not added and not removed:
            return
        embed = discord.Embed(title="Rôles mis à jour", color=discord.Color.purple())
        embed.set_thumbnail(url=after.display_avatar.url)
        embed.add_field(name="Membre", value=after.mention)
        if added:
            embed.add_field(name="Rôles ajoutés", value=" ".join(r.mention for r in added), inline=False)
        if removed:
            embed.add_field(name="Rôles retirés", value=" ".join(r.mention for r in removed), inline=False)
        embed.set_footer(text=f"ID : {after.id}")
        await channel.send(embed=embed)


async def setup(bot: commands.Bot):
    cog = Logs(bot)
    bot.tree.add_command(logs_group)
    await bot.add_cog(cog)
