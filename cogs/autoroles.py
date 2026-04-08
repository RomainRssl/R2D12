import json
import os
import discord
from discord import app_commands
from discord.ext import commands

AUTOROLES_FILE = "data/autoroles.json"


def load_data() -> dict:
    if not os.path.exists(AUTOROLES_FILE):
        return {}
    with open(AUTOROLES_FILE, "r", encoding="utf-8") as f:
        return json.load(f)


def save_data(data: dict):
    os.makedirs("data", exist_ok=True)
    with open(AUTOROLES_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


autorole_group = app_commands.Group(name="autorole", description="Gestion des rôles attribués automatiquement à l'arrivée")


class AutoRoles(commands.Cog):
    """Attribue automatiquement des rôles aux nouveaux membres."""

    def __init__(self, bot: commands.Bot):
        self.bot = bot

    @commands.Cog.listener()
    async def on_member_join(self, member: discord.Member):
        data = load_data()
        role_ids = data.get(str(member.guild.id), [])
        if not role_ids:
            return
        roles = [member.guild.get_role(rid) for rid in role_ids]
        roles = [r for r in roles if r is not None]
        if roles:
            try:
                await member.add_roles(*roles, reason="AutoRôle à l'arrivée")
            except discord.Forbidden:
                pass

    @autorole_group.command(name="ajouter", description="Ajouter un rôle automatique à l'arrivée")
    @app_commands.describe(role="Le rôle à attribuer aux nouveaux membres")
    @app_commands.default_permissions(manage_roles=True)
    async def autorole_add(self, interaction: discord.Interaction, role: discord.Role):
        if role >= interaction.guild.me.top_role:
            await interaction.response.send_message("Je ne peux pas attribuer un rôle supérieur ou égal au mien.", ephemeral=True)
            return
        data = load_data()
        guild_key = str(interaction.guild_id)
        ids = data.setdefault(guild_key, [])
        if role.id in ids:
            await interaction.response.send_message(f"{role.mention} est déjà dans les auto-rôles.", ephemeral=True)
            return
        ids.append(role.id)
        save_data(data)
        await interaction.response.send_message(f"{role.mention} ajouté aux auto-rôles.", ephemeral=True)

    @autorole_group.command(name="retirer", description="Retirer un rôle automatique")
    @app_commands.describe(role="Le rôle à retirer des auto-rôles")
    @app_commands.default_permissions(manage_roles=True)
    async def autorole_remove(self, interaction: discord.Interaction, role: discord.Role):
        data = load_data()
        guild_key = str(interaction.guild_id)
        ids = data.get(guild_key, [])
        if role.id not in ids:
            await interaction.response.send_message(f"{role.mention} n'est pas dans les auto-rôles.", ephemeral=True)
            return
        ids.remove(role.id)
        save_data(data)
        await interaction.response.send_message(f"{role.mention} retiré des auto-rôles.", ephemeral=True)

    @autorole_group.command(name="liste", description="Voir les rôles attribués automatiquement")
    async def autorole_list(self, interaction: discord.Interaction):
        data = load_data()
        ids = data.get(str(interaction.guild_id), [])
        if not ids:
            await interaction.response.send_message("Aucun auto-rôle configuré.", ephemeral=True)
            return
        roles = [interaction.guild.get_role(rid) for rid in ids]
        embed = discord.Embed(title="Auto-rôles", color=discord.Color.blurple())
        embed.description = "\n".join(r.mention if r else f"`ID {rid} (introuvable)`" for r, rid in zip(roles, ids))
        await interaction.response.send_message(embed=embed, ephemeral=True)


async def setup(bot: commands.Bot):
    cog = AutoRoles(bot)
    bot.tree.add_command(autorole_group)
    await bot.add_cog(cog)
