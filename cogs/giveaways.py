import json
import os
import random
import datetime
import discord
from discord import app_commands
from discord.ext import commands, tasks

GIVEAWAYS_FILE = "data/giveaways.json"


def load_data() -> dict:
    if not os.path.exists(GIVEAWAYS_FILE):
        return {}
    with open(GIVEAWAYS_FILE, "r", encoding="utf-8") as f:
        return json.load(f)


def save_data(data: dict):
    os.makedirs("data", exist_ok=True)
    with open(GIVEAWAYS_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def build_giveaway_embed(giveaway: dict, ended: bool = False) -> discord.Embed:
    ends_at = datetime.datetime.fromisoformat(giveaway["ends_at"])
    nb = len(giveaway["participants"])
    color = discord.Color.gold() if not ended else discord.Color.greyple()
    embed = discord.Embed(
        title=("🎉 GIVEAWAY 🎉" if not ended else "🎉 GIVEAWAY TERMINÉ 🎉"),
        description=f"**{giveaway['prix']}**",
        color=color,
    )
    embed.add_field(name="Gagnant(s)", value=str(giveaway["nb_gagnants"]), inline=True)
    embed.add_field(name="Participants", value=str(nb), inline=True)
    if not ended:
        embed.add_field(name="Se termine", value=discord.utils.format_dt(ends_at, style="R"), inline=True)
    else:
        gagnants = giveaway.get("gagnants", [])
        if gagnants:
            embed.add_field(name="Gagnant(s)", value=", ".join(f"<@{uid}>" for uid in gagnants), inline=False)
        else:
            embed.add_field(name="Gagnant(s)", value="Pas assez de participants.", inline=False)
    embed.set_footer(text=f"Cliquez sur 🎉 pour participer • {nb} participant(s)")
    return embed


class GiveawayView(discord.ui.View):
    def __init__(self, guild_id: str, message_id: str):
        super().__init__(timeout=None)
        self.guild_id = guild_id
        self.message_id = message_id

    @discord.ui.button(label="🎉 Participer", style=discord.ButtonStyle.success, custom_id="giveaway:participer")
    async def participer(self, interaction: discord.Interaction, button: discord.ui.Button):
        data = load_data()
        giveaway = data.get(self.guild_id, {}).get(self.message_id)
        if not giveaway or giveaway.get("terminé"):
            await interaction.response.send_message("Ce giveaway est terminé.", ephemeral=True)
            return
        user_id = str(interaction.user.id)
        if user_id in giveaway["participants"]:
            giveaway["participants"].remove(user_id)
            save_data(data)
            await interaction.response.send_message("Vous vous êtes retiré du giveaway.", ephemeral=True)
        else:
            giveaway["participants"].append(user_id)
            save_data(data)
            await interaction.response.send_message("Vous participez au giveaway !", ephemeral=True)
        embed = build_giveaway_embed(giveaway)
        await interaction.message.edit(embed=embed)


def pick_winners(giveaway: dict) -> list[str]:
    participants = giveaway["participants"]
    nb = min(giveaway["nb_gagnants"], len(participants))
    return random.sample(participants, nb) if nb > 0 else []


class Giveaways(commands.Cog):
    """Système de giveaways avec tirage automatique."""

    giveaway_group = app_commands.Group(name="giveaway", description="Gestion des giveaways")

    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.check_giveaways.start()

    def cog_unload(self):
        self.check_giveaways.cancel()

    async def cog_load(self):
        data = load_data()
        for guild_id, giveaways in data.items():
            for msg_id, gw in giveaways.items():
                if not gw.get("terminé"):
                    self.bot.add_view(GiveawayView(guild_id, msg_id))

    @tasks.loop(seconds=30)
    async def check_giveaways(self):
        data = load_data()
        now = datetime.datetime.utcnow()
        changed = False
        for guild_id, giveaways in data.items():
            for msg_id, gw in giveaways.items():
                if gw.get("terminé"):
                    continue
                ends_at = datetime.datetime.fromisoformat(gw["ends_at"])
                if now >= ends_at:
                    gw["terminé"] = True
                    gw["gagnants"] = pick_winners(gw)
                    changed = True
                    guild = self.bot.get_guild(int(guild_id))
                    if guild:
                        channel = guild.get_channel(gw["channel_id"])
                        if channel:
                            try:
                                msg = await channel.fetch_message(int(msg_id))
                                await msg.edit(embed=build_giveaway_embed(gw, ended=True), view=None)
                                if gw["gagnants"]:
                                    winners_str = " ".join(f"<@{uid}>" for uid in gw["gagnants"])
                                    await channel.send(f"Félicitations {winners_str} ! Vous avez gagné **{gw['prix']}** !")
                                else:
                                    await channel.send(f"Le giveaway pour **{gw['prix']}** est terminé, mais il n'y avait pas assez de participants.")
                            except (discord.NotFound, discord.Forbidden):
                                pass
        if changed:
            save_data(data)

    @check_giveaways.before_loop
    async def before_check(self):
        await self.bot.wait_until_ready()

    @giveaway_group.command(name="lancer", description="Lancer un giveaway")
    @app_commands.describe(
        salon="Salon du giveaway", duree_heures="Durée en heures",
        prix="Ce que l'on peut gagner", gagnants="Nombre de gagnants (défaut : 1)",
    )
    @app_commands.default_permissions(manage_guild=True)
    async def giveaway_start(
        self, interaction: discord.Interaction,
        salon: discord.TextChannel,
        duree_heures: app_commands.Range[int, 1, 720],
        prix: str,
        gagnants: app_commands.Range[int, 1, 20] = 1,
    ):
        ends_at = datetime.datetime.utcnow() + datetime.timedelta(hours=duree_heures)
        await interaction.response.defer(ephemeral=True)
        msg = await salon.send(embed=discord.Embed(title="Création..."))

        gw = {
            "channel_id": salon.id,
            "prix": prix,
            "nb_gagnants": gagnants,
            "ends_at": ends_at.isoformat(),
            "participants": [],
            "gagnants": [],
            "terminé": False,
        }
        data = load_data()
        guild_key = str(interaction.guild_id)
        data.setdefault(guild_key, {})[str(msg.id)] = gw
        save_data(data)

        view = GiveawayView(guild_key, str(msg.id))
        self.bot.add_view(view)
        await msg.edit(embed=build_giveaway_embed(gw), view=view)
        await interaction.followup.send(f"Giveaway lancé dans {salon.mention} !", ephemeral=True)

    @giveaway_group.command(name="terminer", description="Terminer un giveaway manuellement")
    @app_commands.describe(message_id="ID du message du giveaway")
    @app_commands.default_permissions(manage_guild=True)
    async def giveaway_end(self, interaction: discord.Interaction, message_id: str):
        data = load_data()
        gw = data.get(str(interaction.guild_id), {}).get(message_id)
        if not gw:
            await interaction.response.send_message("Giveaway introuvable.", ephemeral=True)
            return
        if gw.get("terminé"):
            await interaction.response.send_message("Ce giveaway est déjà terminé.", ephemeral=True)
            return
        gw["terminé"] = True
        gw["gagnants"] = pick_winners(gw)
        save_data(data)
        channel = interaction.guild.get_channel(gw["channel_id"])
        if channel:
            try:
                msg = await channel.fetch_message(int(message_id))
                await msg.edit(embed=build_giveaway_embed(gw, ended=True), view=None)
                if gw["gagnants"]:
                    winners_str = " ".join(f"<@{uid}>" for uid in gw["gagnants"])
                    await channel.send(f"Félicitations {winners_str} ! Vous avez gagné **{gw['prix']}** !")
            except (discord.NotFound, discord.Forbidden):
                pass
        await interaction.response.send_message("Giveaway terminé.", ephemeral=True)

    @giveaway_group.command(name="relancer", description="Re-tirer au sort les gagnants d'un giveaway terminé")
    @app_commands.describe(message_id="ID du message du giveaway")
    @app_commands.default_permissions(manage_guild=True)
    async def giveaway_reroll(self, interaction: discord.Interaction, message_id: str):
        data = load_data()
        gw = data.get(str(interaction.guild_id), {}).get(message_id)
        if not gw:
            await interaction.response.send_message("Giveaway introuvable.", ephemeral=True)
            return
        new_winners = pick_winners(gw)
        gw["gagnants"] = new_winners
        save_data(data)
        if new_winners:
            winners_str = " ".join(f"<@{uid}>" for uid in new_winners)
            await interaction.response.send_message(f"Nouveaux gagnants : {winners_str} !")
        else:
            await interaction.response.send_message("Pas assez de participants pour un re-roll.", ephemeral=True)

    @giveaway_group.command(name="liste", description="Voir les giveaways en cours")
    async def giveaway_list(self, interaction: discord.Interaction):
        data = load_data()
        giveaways = {k: v for k, v in data.get(str(interaction.guild_id), {}).items() if not v.get("terminé")}
        if not giveaways:
            await interaction.response.send_message("Aucun giveaway en cours.", ephemeral=True)
            return
        embed = discord.Embed(title="Giveaways en cours", color=discord.Color.gold())
        for msg_id, gw in giveaways.items():
            ends_at = datetime.datetime.fromisoformat(gw["ends_at"])
            channel = interaction.guild.get_channel(gw["channel_id"])
            embed.add_field(
                name=gw["prix"],
                value=f"Salon : {channel.mention if channel else 'inconnu'}\nFin : {discord.utils.format_dt(ends_at, style='R')}\nParticipants : {len(gw['participants'])}",
                inline=False,
            )
        await interaction.response.send_message(embed=embed, ephemeral=True)


async def setup(bot: commands.Bot):
    await bot.add_cog(Giveaways(bot))
