import json
import os
import discord
from discord import app_commands
from discord.ext import commands, tasks

COUNTERS_FILE = "data/counters.json"

COUNTER_TYPES = {
    "membres": {"emoji": "👥", "label": "Membres"},
    "bots": {"emoji": "🤖", "label": "Bots"},
    "salons": {"emoji": "📋", "label": "Salons"},
    "boosts": {"emoji": "✨", "label": "Boosts"},
}


def load_data() -> dict:
    if not os.path.exists(COUNTERS_FILE):
        return {}
    with open(COUNTERS_FILE, "r", encoding="utf-8") as f:
        return json.load(f)


def save_data(data: dict):
    os.makedirs("data", exist_ok=True)
    with open(COUNTERS_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def get_counter_value(guild: discord.Guild, counter_type: str) -> int:
    if counter_type == "membres":
        return sum(1 for m in guild.members if not m.bot)
    elif counter_type == "bots":
        return sum(1 for m in guild.members if m.bot)
    elif counter_type == "salons":
        return len(guild.channels)
    elif counter_type == "boosts":
        return guild.premium_subscription_count
    return 0


def get_channel_name(guild: discord.Guild, counter_type: str) -> str:
    info = COUNTER_TYPES[counter_type]
    value = get_counter_value(guild, counter_type)
    return f"{info['emoji']} {info['label']}: {value}"


compteur_group = app_commands.Group(name="compteur", description="Gestion des compteurs vocaux automatiques")


class Counters(commands.Cog):
    """Compteurs en temps réel dans des salons vocaux."""

    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.update_counters.start()

    def cog_unload(self):
        self.update_counters.cancel()

    @tasks.loop(minutes=10)
    async def update_counters(self):
        data = load_data()
        for guild_id, counters in data.items():
            guild = self.bot.get_guild(int(guild_id))
            if not guild:
                continue
            for counter_type, channel_id in counters.items():
                if counter_type not in COUNTER_TYPES:
                    continue
                channel = guild.get_channel(channel_id)
                if not channel:
                    continue
                new_name = get_channel_name(guild, counter_type)
                if channel.name != new_name:
                    try:
                        await channel.edit(name=new_name)
                    except discord.Forbidden:
                        pass

    @update_counters.before_loop
    async def before_update(self):
        await self.bot.wait_until_ready()

    @compteur_group.command(name="créer", description="Créer un salon compteur")
    @app_commands.describe(type="Type de compteur")
    @app_commands.choices(type=[
        app_commands.Choice(name="Membres", value="membres"),
        app_commands.Choice(name="Bots", value="bots"),
        app_commands.Choice(name="Salons", value="salons"),
        app_commands.Choice(name="Boosts", value="boosts"),
    ])
    @app_commands.default_permissions(manage_channels=True)
    async def counter_create(self, interaction: discord.Interaction, type: str):
        data = load_data()
        guild_key = str(interaction.guild_id)
        if data.get(guild_key, {}).get(type):
            channel = interaction.guild.get_channel(data[guild_key][type])
            if channel:
                await interaction.response.send_message(f"Ce compteur existe déjà : {channel.mention}", ephemeral=True)
                return

        name = get_channel_name(interaction.guild, type)
        overwrites = {
            interaction.guild.default_role: discord.PermissionOverwrite(connect=False, view_channel=True),
        }
        channel = await interaction.guild.create_voice_channel(
            name=name,
            overwrites=overwrites,
            reason=f"Compteur {type} créé par {interaction.user}",
        )
        data.setdefault(guild_key, {})[type] = channel.id
        save_data(data)
        await interaction.response.send_message(f"Compteur **{COUNTER_TYPES[type]['label']}** créé : {channel.mention}", ephemeral=True)

    @compteur_group.command(name="supprimer", description="Supprimer un salon compteur")
    @app_commands.describe(type="Type de compteur à supprimer")
    @app_commands.choices(type=[
        app_commands.Choice(name="Membres", value="membres"),
        app_commands.Choice(name="Bots", value="bots"),
        app_commands.Choice(name="Salons", value="salons"),
        app_commands.Choice(name="Boosts", value="boosts"),
    ])
    @app_commands.default_permissions(manage_channels=True)
    async def counter_delete(self, interaction: discord.Interaction, type: str):
        data = load_data()
        guild_key = str(interaction.guild_id)
        channel_id = data.get(guild_key, {}).get(type)
        if not channel_id:
            await interaction.response.send_message(f"Aucun compteur **{COUNTER_TYPES[type]['label']}** configuré.", ephemeral=True)
            return
        channel = interaction.guild.get_channel(channel_id)
        if channel:
            try:
                await channel.delete()
            except discord.Forbidden:
                pass
        del data[guild_key][type]
        save_data(data)
        await interaction.response.send_message(f"Compteur **{COUNTER_TYPES[type]['label']}** supprimé.", ephemeral=True)

    @compteur_group.command(name="liste", description="Voir les compteurs configurés")
    async def counter_list(self, interaction: discord.Interaction):
        data = load_data()
        counters = data.get(str(interaction.guild_id), {})
        if not counters:
            await interaction.response.send_message("Aucun compteur configuré.", ephemeral=True)
            return
        embed = discord.Embed(title="Compteurs actifs", color=discord.Color.blurple())
        for ctype, channel_id in counters.items():
            info = COUNTER_TYPES.get(ctype, {})
            channel = interaction.guild.get_channel(channel_id)
            embed.add_field(
                name=f"{info.get('emoji', '')} {info.get('label', ctype)}",
                value=channel.mention if channel else "`introuvable`",
                inline=True,
            )
        await interaction.response.send_message(embed=embed, ephemeral=True)


async def setup(bot: commands.Bot):
    cog = Counters(bot)
    bot.tree.add_command(compteur_group)
    await bot.add_cog(cog)
