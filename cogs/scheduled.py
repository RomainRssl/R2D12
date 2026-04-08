import json
import os
import datetime
import discord
from discord import app_commands
from discord.ext import commands, tasks

SCHEDULED_FILE = "data/scheduled.json"


def load_data() -> dict:
    if not os.path.exists(SCHEDULED_FILE):
        return {}
    with open(SCHEDULED_FILE, "r", encoding="utf-8") as f:
        return json.load(f)


def save_data(data: dict):
    os.makedirs("data", exist_ok=True)
    with open(SCHEDULED_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


planifie_group = app_commands.Group(name="planifié", description="Gestion des messages récurrents")


class Scheduled(commands.Cog):
    """Messages récurrents automatiques."""

    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.send_scheduled.start()

    def cog_unload(self):
        self.send_scheduled.cancel()

    @tasks.loop(minutes=1)
    async def send_scheduled(self):
        data = load_data()
        now = datetime.datetime.utcnow()
        changed = False

        for guild_id, messages in data.items():
            for nom, config in messages.items():
                last_sent = config.get("last_sent")
                interval_hours = config.get("interval_hours", 24)

                if last_sent:
                    elapsed = (now - datetime.datetime.fromisoformat(last_sent)).total_seconds()
                    if elapsed < interval_hours * 3600:
                        continue

                guild = self.bot.get_guild(int(guild_id))
                if not guild:
                    continue
                channel = guild.get_channel(config["channel_id"])
                if not channel:
                    continue

                embed = discord.Embed(description=config["message"], color=discord.Color.blurple())
                embed.set_footer(text=f"Message planifié : {nom}")
                await channel.send(embed=embed)
                config["last_sent"] = now.isoformat()
                changed = True

        if changed:
            save_data(data)

    @send_scheduled.before_loop
    async def before_send(self):
        await self.bot.wait_until_ready()

    @planifie_group.command(name="créer", description="Créer un message récurrent")
    @app_commands.describe(
        nom="Nom du message planifié",
        salon="Salon de destination",
        message="Contenu du message",
        intervalle_heures="Intervalle en heures entre chaque envoi",
    )
    @app_commands.default_permissions(manage_guild=True)
    async def scheduled_create(
        self, interaction: discord.Interaction,
        nom: str, salon: discord.TextChannel, message: str,
        intervalle_heures: app_commands.Range[int, 1, 8760] = 24,
    ):
        nom = nom.lower().strip()
        data = load_data()
        guild_key = str(interaction.guild_id)
        if nom in data.get(guild_key, {}):
            await interaction.response.send_message(f"Un message planifié `{nom}` existe déjà.", ephemeral=True)
            return
        data.setdefault(guild_key, {})[nom] = {
            "channel_id": salon.id,
            "message": message,
            "interval_hours": intervalle_heures,
            "last_sent": None,
        }
        save_data(data)
        embed = discord.Embed(title="Message planifié créé", color=discord.Color.green())
        embed.add_field(name="Nom", value=f"`{nom}`")
        embed.add_field(name="Salon", value=salon.mention)
        embed.add_field(name="Intervalle", value=f"Toutes les {intervalle_heures}h")
        embed.add_field(name="Message", value=message[:200], inline=False)
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @planifie_group.command(name="supprimer", description="Supprimer un message récurrent")
    @app_commands.describe(nom="Nom du message planifié à supprimer")
    @app_commands.default_permissions(manage_guild=True)
    async def scheduled_delete(self, interaction: discord.Interaction, nom: str):
        nom = nom.lower().strip()
        data = load_data()
        guild_key = str(interaction.guild_id)
        if nom not in data.get(guild_key, {}):
            await interaction.response.send_message(f"Message planifié `{nom}` introuvable.", ephemeral=True)
            return
        del data[guild_key][nom]
        save_data(data)
        await interaction.response.send_message(f"Message planifié `{nom}` supprimé.", ephemeral=True)

    @planifie_group.command(name="liste", description="Voir tous les messages planifiés")
    async def scheduled_list(self, interaction: discord.Interaction):
        data = load_data()
        messages = data.get(str(interaction.guild_id), {})
        if not messages:
            await interaction.response.send_message("Aucun message planifié.", ephemeral=True)
            return
        embed = discord.Embed(title="Messages planifiés", color=discord.Color.blurple())
        for nom, config in messages.items():
            channel = interaction.guild.get_channel(config["channel_id"])
            last = config.get("last_sent")
            next_send = "Prochain envoi imminent" if not last else discord.utils.format_dt(
                datetime.datetime.fromisoformat(last) + datetime.timedelta(hours=config["interval_hours"]),
                style="R",
            )
            embed.add_field(
                name=f"`{nom}`",
                value=f"Salon : {channel.mention if channel else 'introuvable'}\nIntervalle : {config['interval_hours']}h\nProchain envoi : {next_send}",
                inline=False,
            )
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @scheduled_delete.autocomplete("nom")
    async def autocomplete_nom(self, interaction: discord.Interaction, current: str):
        data = load_data()
        messages = data.get(str(interaction.guild_id), {})
        return [
            app_commands.Choice(name=n, value=n)
            for n in messages if current.lower() in n.lower()
        ][:25]


async def setup(bot: commands.Bot):
    cog = Scheduled(bot)
    bot.tree.add_command(planifie_group)
    await bot.add_cog(cog)
