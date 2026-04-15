import json
import os
import random
import datetime
import discord
from discord import app_commands
from discord.ext import commands

LEVELS_FILE = "data/levels.json"

XP_MIN, XP_MAX = 15, 25
XP_COOLDOWN = 60  # secondes


def load_data() -> dict:
    if not os.path.exists(LEVELS_FILE):
        return {}
    with open(LEVELS_FILE, "r", encoding="utf-8") as f:
        return json.load(f)


def save_data(data: dict):
    os.makedirs("data", exist_ok=True)
    with open(LEVELS_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def xp_needed(level: int) -> int:
    """XP nécessaire pour passer au niveau suivant."""
    return 100 * (level + 1) ** 2


def level_from_total_xp(total_xp: int) -> tuple[int, int]:
    """Retourne (level, xp_dans_niveau_actuel)."""
    level = 0
    while total_xp >= xp_needed(level):
        total_xp -= xp_needed(level)
        level += 1
    return level, total_xp


def progress_bar(current: int, total: int, length: int = 10) -> str:
    filled = int(length * current / total) if total > 0 else 0
    return "█" * filled + "░" * (length - filled)


niveau_group = app_commands.Group(name="niveau", description="Système de niveaux et d'expérience")


class Levels(commands.Cog):
    """Système XP et niveaux par message."""

    def __init__(self, bot: commands.Bot):
        self.bot = bot

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message):
        if message.author.bot or not message.guild:
            return

        data = load_data()
        guild_key = str(message.guild.id)
        user_key = str(message.author.id)

        guild_data = data.setdefault(guild_key, {"enabled": True, "channel_id": None, "rewards": {}, "members": {}})

        # Vérifie si le système XP est activé
        if not guild_data.get("enabled", True):
            return

        member_data = guild_data["members"].setdefault(user_key, {"xp": 0, "level": 0, "last_message": None})

        # Cooldown
        now = datetime.datetime.utcnow()
        last = member_data.get("last_message")
        if last:
            elapsed = (now - datetime.datetime.fromisoformat(last)).total_seconds()
            if elapsed < XP_COOLDOWN:
                return

        xp_gain = random.randint(XP_MIN, XP_MAX)
        member_data["xp"] += xp_gain
        member_data["last_message"] = now.isoformat()

        # Calcul niveau
        level, xp_in_level = level_from_total_xp(member_data["xp"])
        old_level = member_data["level"]
        member_data["level"] = level
        save_data(data)

        # Level up
        if level > old_level:
            channel_id = guild_data.get("channel_id")
            channel = message.guild.get_channel(channel_id) if channel_id else message.channel
            if channel:
                embed = discord.Embed(
                    title="Niveau supérieur !",
                    description=f"Félicitations {message.author.mention}, tu passes au **niveau {level}** !",
                    color=discord.Color.gold(),
                )
                embed.set_thumbnail(url=message.author.display_avatar.url)
                await channel.send(embed=embed)

            # Récompenses de rôles
            rewards = guild_data.get("rewards", {})
            for lvl_str, role_id in rewards.items():
                if int(lvl_str) <= level:
                    role = message.guild.get_role(role_id)
                    if role and role not in message.author.roles:
                        try:
                            await message.author.add_roles(role, reason=f"Récompense niveau {lvl_str}")
                        except discord.Forbidden:
                            pass

    @niveau_group.command(name="voir", description="Voir votre niveau et XP")
    @app_commands.describe(membre="Le membre dont voir le niveau (vous par défaut)")
    async def niveau_check(self, interaction: discord.Interaction, membre: discord.Member = None):
        membre = membre or interaction.user
        data = load_data()
        member_data = data.get(str(interaction.guild_id), {}).get("members", {}).get(str(membre.id))
        if not member_data:
            await interaction.response.send_message(f"{membre.mention} n'a pas encore de XP.", ephemeral=True)
            return

        total_xp = member_data["xp"]
        level, xp_in_level = level_from_total_xp(total_xp)
        needed = xp_needed(level)
        bar = progress_bar(xp_in_level, needed)

        embed = discord.Embed(title=f"Niveau de {membre.display_name}", color=discord.Color.gold())
        embed.set_thumbnail(url=membre.display_avatar.url)
        embed.add_field(name="Niveau", value=str(level), inline=True)
        embed.add_field(name="XP total", value=str(total_xp), inline=True)
        embed.add_field(name=f"Progression vers niveau {level + 1}", value=f"`{bar}` {xp_in_level}/{needed} XP", inline=False)
        await interaction.response.send_message(embed=embed)

    @app_commands.command(name="classement", description="Top 10 des membres par niveau")
    async def leaderboard(self, interaction: discord.Interaction):
        data = load_data()
        guild_data = data.get(str(interaction.guild_id), {})
        if not guild_data.get("classement_enabled", True):
            await interaction.response.send_message("Le classement est désactivé sur ce serveur.", ephemeral=True)
            return
        members_data = guild_data.get("members", {})
        if not members_data:
            await interaction.response.send_message("Aucun membre avec de l'XP.", ephemeral=True)
            return

        sorted_members = sorted(members_data.items(), key=lambda x: x[1]["xp"], reverse=True)[:10]
        embed = discord.Embed(title="Classement XP", color=discord.Color.gold())
        medals = ["🥇", "🥈", "🥉"]
        for i, (user_id, mdata) in enumerate(sorted_members):
            member = interaction.guild.get_member(int(user_id))
            name = member.display_name if member else f"ID {user_id}"
            level, _ = level_from_total_xp(mdata["xp"])
            prefix = medals[i] if i < 3 else f"`#{i+1}`"
            embed.add_field(name=f"{prefix} {name}", value=f"Niveau {level} • {mdata['xp']} XP", inline=False)
        await interaction.response.send_message(embed=embed)

    @app_commands.command(name="xp-on", description="Activer le système de niveaux et XP")
    @app_commands.default_permissions(manage_guild=True)
    async def niveau_enable(self, interaction: discord.Interaction):
        data = load_data()
        data.setdefault(str(interaction.guild_id), {"enabled": True, "channel_id": None, "rewards": {}, "members": {}})["enabled"] = True
        save_data(data)
        await interaction.response.send_message("✅ Système de niveaux & XP **activé**.", ephemeral=True)

    @app_commands.command(name="xp-off", description="Désactiver le système de niveaux et XP")
    @app_commands.default_permissions(manage_guild=True)
    async def niveau_disable(self, interaction: discord.Interaction):
        data = load_data()
        data.setdefault(str(interaction.guild_id), {"enabled": True, "channel_id": None, "rewards": {}, "members": {}})["enabled"] = False
        save_data(data)
        await interaction.response.send_message("❌ Système de niveaux & XP **désactivé**. Les données sont conservées.", ephemeral=True)

    @app_commands.command(name="classement-on", description="Activer la commande /classement")
    @app_commands.default_permissions(manage_guild=True)
    async def classement_enable(self, interaction: discord.Interaction):
        data = load_data()
        data.setdefault(str(interaction.guild_id), {"enabled": True, "classement_enabled": True, "channel_id": None, "rewards": {}, "members": {}})["classement_enabled"] = True
        save_data(data)
        await interaction.response.send_message("✅ Commande `/classement` **activée**.", ephemeral=True)

    @app_commands.command(name="classement-off", description="Désactiver la commande /classement")
    @app_commands.default_permissions(manage_guild=True)
    async def classement_disable(self, interaction: discord.Interaction):
        data = load_data()
        data.setdefault(str(interaction.guild_id), {"enabled": True, "classement_enabled": True, "channel_id": None, "rewards": {}, "members": {}})["classement_enabled"] = False
        save_data(data)
        await interaction.response.send_message("❌ Commande `/classement` **désactivée**.", ephemeral=True)

    @niveau_group.command(name="configurer", description="Définir le salon des annonces de level up")
    @app_commands.describe(salon="Salon pour les messages de level up (aucun = salon du message)")
    @app_commands.default_permissions(manage_guild=True)
    async def niveau_config(self, interaction: discord.Interaction, salon: discord.TextChannel):
        data = load_data()
        data.setdefault(str(interaction.guild_id), {"channel_id": None, "rewards": {}, "members": {}})["channel_id"] = salon.id
        save_data(data)
        await interaction.response.send_message(f"Salon de level up défini sur {salon.mention}.", ephemeral=True)

    @niveau_group.command(name="recompense-ajouter", description="Ajouter un rôle récompense à un niveau")
    @app_commands.describe(niveau="Niveau déclencheur", role="Rôle à attribuer")
    @app_commands.default_permissions(manage_roles=True)
    async def reward_add(self, interaction: discord.Interaction, niveau: app_commands.Range[int, 1, 500], role: discord.Role):
        data = load_data()
        guild_data = data.setdefault(str(interaction.guild_id), {"channel_id": None, "rewards": {}, "members": {}})
        guild_data.setdefault("rewards", {})[str(niveau)] = role.id
        save_data(data)
        await interaction.response.send_message(f"Rôle {role.mention} attribué au niveau **{niveau}**.", ephemeral=True)

    @niveau_group.command(name="recompense-retirer", description="Retirer une récompense de niveau")
    @app_commands.describe(niveau="Niveau dont retirer la récompense")
    @app_commands.default_permissions(manage_roles=True)
    async def reward_remove(self, interaction: discord.Interaction, niveau: int):
        data = load_data()
        rewards = data.get(str(interaction.guild_id), {}).get("rewards", {})
        if str(niveau) not in rewards:
            await interaction.response.send_message(f"Aucune récompense au niveau {niveau}.", ephemeral=True)
            return
        del rewards[str(niveau)]
        save_data(data)
        await interaction.response.send_message(f"Récompense du niveau **{niveau}** supprimée.", ephemeral=True)

    @niveau_group.command(name="recompense-liste", description="Voir les récompenses de niveaux")
    async def reward_list(self, interaction: discord.Interaction):
        data = load_data()
        rewards = data.get(str(interaction.guild_id), {}).get("rewards", {})
        if not rewards:
            await interaction.response.send_message("Aucune récompense configurée.", ephemeral=True)
            return
        embed = discord.Embed(title="Récompenses de niveaux", color=discord.Color.gold())
        for lvl, role_id in sorted(rewards.items(), key=lambda x: int(x[0])):
            role = interaction.guild.get_role(role_id)
            embed.add_field(name=f"Niveau {lvl}", value=role.mention if role else f"`ID {role_id}`", inline=True)
        await interaction.response.send_message(embed=embed, ephemeral=True)


async def setup(bot: commands.Bot):
    cog = Levels(bot)
    bot.tree.add_command(niveau_group)
    await bot.add_cog(cog)
