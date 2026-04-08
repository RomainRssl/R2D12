import json
import os
import datetime
import discord
from discord import app_commands
from discord.ext import commands

WARNINGS_FILE = "data/warnings.json"


def load_warnings() -> dict:
    if not os.path.exists(WARNINGS_FILE):
        return {}
    with open(WARNINGS_FILE, "r", encoding="utf-8") as f:
        return json.load(f)


def save_warnings(data: dict):
    os.makedirs("data", exist_ok=True)
    with open(WARNINGS_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


class Moderation(commands.Cog):
    """Commandes de modération du bot R2D12."""

    def __init__(self, bot: commands.Bot):
        self.bot = bot

    # ── Commandes de base ─────────────────────────────────────────────────────

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
            await membre.send(f"Vous avez été expulsé du serveur **{interaction.guild.name}**.\nRaison : {raison}")
        except discord.Forbidden:
            pass
        await membre.kick(reason=f"{interaction.user} : {raison}")
        embed = discord.Embed(title="Membre expulsé", description=f"{membre.mention} a été expulsé par {interaction.user.mention}.", color=discord.Color.orange())
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
            await membre.send(f"Vous avez été banni du serveur **{interaction.guild.name}**.\nRaison : {raison}")
        except discord.Forbidden:
            pass
        await membre.ban(reason=f"{interaction.user} : {raison}", delete_message_days=supprimer_messages)
        embed = discord.Embed(title="Membre banni", description=f"{membre.mention} a été banni par {interaction.user.mention}.", color=discord.Color.red())
        embed.add_field(name="Raison", value=raison)
        await interaction.response.send_message(embed=embed)

    @app_commands.command(name="clear", description="Supprimer un nombre de messages dans le salon")
    @app_commands.describe(nombre="Nombre de messages à supprimer (1-100)")
    @app_commands.default_permissions(manage_messages=True)
    async def clear(self, interaction: discord.Interaction, nombre: app_commands.Range[int, 1, 100] = 10):
        await interaction.response.defer(ephemeral=True)
        deleted = await interaction.channel.purge(limit=nombre)
        await interaction.followup.send(f"{len(deleted)} message(s) supprimé(s).", ephemeral=True)

    # ── Avertissements ────────────────────────────────────────────────────────

    @app_commands.command(name="warn", description="Avertir un membre")
    @app_commands.describe(membre="Le membre à avertir", raison="Raison de l'avertissement")
    @app_commands.default_permissions(kick_members=True)
    async def warn(self, interaction: discord.Interaction, membre: discord.Member, raison: str = "Aucune raison fournie"):
        if membre.bot:
            await interaction.response.send_message("Impossible d'avertir un bot.", ephemeral=True)
            return
        data = load_warnings()
        guild_key = str(interaction.guild_id)
        user_key = str(membre.id)
        data.setdefault(guild_key, {}).setdefault(user_key, []).append({
            "raison": raison,
            "date": datetime.datetime.utcnow().isoformat(),
            "moderateur_id": str(interaction.user.id),
        })
        save_warnings(data)
        nb = len(data[guild_key][user_key])
        embed = discord.Embed(title="Avertissement", description=f"{membre.mention} a reçu un avertissement.", color=discord.Color.yellow())
        embed.add_field(name="Raison", value=raison)
        embed.add_field(name="Total avertissements", value=str(nb))
        embed.set_footer(text=f"Modérateur : {interaction.user}")
        try:
            await membre.send(f"Vous avez reçu un avertissement sur **{interaction.guild.name}**.\nRaison : {raison}\nTotal : {nb} avertissement(s).")
        except discord.Forbidden:
            pass
        await interaction.response.send_message(embed=embed)

    @app_commands.command(name="warnings", description="Voir les avertissements d'un membre")
    @app_commands.describe(membre="Le membre dont voir les avertissements")
    @app_commands.default_permissions(kick_members=True)
    async def warnings(self, interaction: discord.Interaction, membre: discord.Member):
        data = load_warnings()
        warns = data.get(str(interaction.guild_id), {}).get(str(membre.id), [])
        if not warns:
            await interaction.response.send_message(f"{membre.mention} n'a aucun avertissement.", ephemeral=True)
            return
        embed = discord.Embed(title=f"Avertissements de {membre.display_name}", color=discord.Color.yellow())
        embed.set_thumbnail(url=membre.display_avatar.url)
        for i, w in enumerate(warns, 1):
            mod = interaction.guild.get_member(int(w["moderateur_id"]))
            mod_name = mod.display_name if mod else f"ID {w['moderateur_id']}"
            date = w["date"][:10]
            embed.add_field(name=f"#{i} — {date}", value=f"Raison : {w['raison']}\nModérateur : {mod_name}", inline=False)
        embed.set_footer(text=f"Total : {len(warns)} avertissement(s)")
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @app_commands.command(name="clearwarnings", description="Effacer tous les avertissements d'un membre")
    @app_commands.describe(membre="Le membre dont effacer les avertissements")
    @app_commands.default_permissions(kick_members=True)
    async def clearwarnings(self, interaction: discord.Interaction, membre: discord.Member):
        data = load_warnings()
        guild_key = str(interaction.guild_id)
        user_key = str(membre.id)
        if not data.get(guild_key, {}).get(user_key):
            await interaction.response.send_message(f"{membre.mention} n'a aucun avertissement.", ephemeral=True)
            return
        data[guild_key].pop(user_key)
        save_warnings(data)
        await interaction.response.send_message(f"Avertissements de {membre.mention} effacés.", ephemeral=True)

    # ── Mute / Unmute ─────────────────────────────────────────────────────────

    @app_commands.command(name="mute", description="Mettre un membre en sourdine (timeout)")
    @app_commands.describe(membre="Le membre à mettre en sourdine", minutes="Durée en minutes (défaut : 10)", raison="Raison")
    @app_commands.default_permissions(moderate_members=True)
    async def mute(self, interaction: discord.Interaction, membre: discord.Member, minutes: app_commands.Range[int, 1, 40320] = 10, raison: str = "Aucune raison fournie"):
        if membre.top_role >= interaction.user.top_role:
            await interaction.response.send_message("Vous ne pouvez pas mettre en sourdine un membre avec un rôle supérieur ou égal au vôtre.", ephemeral=True)
            return
        duration = datetime.timedelta(minutes=minutes)
        await membre.timeout(duration, reason=f"{interaction.user} : {raison}")
        embed = discord.Embed(title="Membre mis en sourdine", description=f"{membre.mention} a été mis en sourdine par {interaction.user.mention}.", color=discord.Color.orange())
        embed.add_field(name="Durée", value=f"{minutes} minute(s)")
        embed.add_field(name="Raison", value=raison)
        await interaction.response.send_message(embed=embed)

    @app_commands.command(name="unmute", description="Retirer le timeout d'un membre")
    @app_commands.describe(membre="Le membre à réactiver")
    @app_commands.default_permissions(moderate_members=True)
    async def unmute(self, interaction: discord.Interaction, membre: discord.Member):
        if not membre.is_timed_out():
            await interaction.response.send_message(f"{membre.mention} n'est pas en sourdine.", ephemeral=True)
            return
        await membre.timeout(None)
        embed = discord.Embed(title="Sourdine retirée", description=f"{membre.mention} n'est plus en sourdine.", color=discord.Color.green())
        await interaction.response.send_message(embed=embed)

    # ── Unban ─────────────────────────────────────────────────────────────────

    @app_commands.command(name="unban", description="Débannir un utilisateur par son ID")
    @app_commands.describe(user_id="L'ID Discord de l'utilisateur à débannir", raison="Raison du déban")
    @app_commands.default_permissions(ban_members=True)
    async def unban(self, interaction: discord.Interaction, user_id: str, raison: str = "Aucune raison fournie"):
        try:
            uid = int(user_id)
        except ValueError:
            await interaction.response.send_message("ID invalide. Fournissez un ID numérique.", ephemeral=True)
            return
        try:
            ban_entry = await interaction.guild.fetch_ban(discord.Object(id=uid))
        except discord.NotFound:
            await interaction.response.send_message("Cet utilisateur n'est pas banni.", ephemeral=True)
            return
        await interaction.guild.unban(ban_entry.user, reason=f"{interaction.user} : {raison}")
        embed = discord.Embed(title="Utilisateur débanni", description=f"**{ban_entry.user}** a été débanni.", color=discord.Color.green())
        embed.add_field(name="Raison", value=raison)
        await interaction.response.send_message(embed=embed)


async def setup(bot: commands.Bot):
    await bot.add_cog(Moderation(bot))
