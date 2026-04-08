import json
import os
import discord
from discord import app_commands
from discord.ext import commands

SUGGESTIONS_FILE = "data/suggestions.json"


def load_data() -> dict:
    if not os.path.exists(SUGGESTIONS_FILE):
        return {}
    with open(SUGGESTIONS_FILE, "r", encoding="utf-8") as f:
        return json.load(f)


def save_data(data: dict):
    os.makedirs("data", exist_ok=True)
    with open(SUGGESTIONS_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


class SuggestionVoteView(discord.ui.View):
    def __init__(self, guild_id: str, message_id: str):
        super().__init__(timeout=None)
        self.guild_id = guild_id
        self.message_id = message_id

    @discord.ui.button(label="👍 Pour", style=discord.ButtonStyle.success, custom_id="suggestion:pour")
    async def vote_pour(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self._vote(interaction, "pour")

    @discord.ui.button(label="👎 Contre", style=discord.ButtonStyle.danger, custom_id="suggestion:contre")
    async def vote_contre(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self._vote(interaction, "contre")

    async def _vote(self, interaction: discord.Interaction, vote: str):
        data = load_data()
        guild_key = str(interaction.guild_id)
        msg_id = str(interaction.message.id)
        suggestion = data.get(guild_key, {}).get("suggestions", {}).get(msg_id)
        if not suggestion:
            await interaction.response.send_message("Suggestion introuvable.", ephemeral=True)
            return
        if suggestion.get("statut") != "pending":
            await interaction.response.send_message("Cette suggestion a déjà été traitée.", ephemeral=True)
            return

        user_key = str(interaction.user.id)
        voters = suggestion.setdefault("voters", {})
        if voters.get(user_key) == vote:
            await interaction.response.send_message("Vous avez déjà voté dans ce sens.", ephemeral=True)
            return
        if voters.get(user_key):
            # Changer de vote
            old = voters[user_key]
            suggestion[f"votes_{old}"] = max(0, suggestion.get(f"votes_{old}", 0) - 1)
        voters[user_key] = vote
        suggestion[f"votes_{vote}"] = suggestion.get(f"votes_{vote}", 0) + 1
        save_data(data)

        embed = _build_suggestion_embed(suggestion)
        await interaction.response.edit_message(embed=embed)


def _build_suggestion_embed(suggestion: dict, statut_override: str = None) -> discord.Embed:
    statut = statut_override or suggestion.get("statut", "pending")
    colors = {"pending": discord.Color.blurple(), "acceptée": discord.Color.green(), "refusée": discord.Color.red()}
    labels = {"pending": "En attente", "acceptée": "Acceptée ✅", "refusée": "Refusée ❌"}
    embed = discord.Embed(
        title=f"Suggestion — {labels.get(statut, statut)}",
        description=suggestion["texte"],
        color=colors.get(statut, discord.Color.blurple()),
    )
    embed.add_field(name="👍 Pour", value=str(suggestion.get("votes_pour", 0)), inline=True)
    embed.add_field(name="👎 Contre", value=str(suggestion.get("votes_contre", 0)), inline=True)
    if suggestion.get("commentaire_admin"):
        embed.add_field(name="Commentaire", value=suggestion["commentaire_admin"], inline=False)
    embed.set_footer(text=f"Suggéré par ID {suggestion['auteur_id']}")
    return embed


suggestion_group = app_commands.Group(name="suggestion", description="Système de suggestions communautaires")


class Suggestions(commands.Cog):
    """Système de suggestions avec vote."""

    def __init__(self, bot: commands.Bot):
        self.bot = bot

    async def cog_load(self):
        data = load_data()
        for guild_id, guild_data in data.items():
            for msg_id, suggestion in guild_data.get("suggestions", {}).items():
                if suggestion.get("statut") == "pending":
                    self.bot.add_view(SuggestionVoteView(guild_id, msg_id))

    @suggestion_group.command(name="configurer", description="Définir le salon des suggestions")
    @app_commands.describe(salon="Salon où envoyer les suggestions")
    @app_commands.default_permissions(manage_guild=True)
    async def suggestion_config(self, interaction: discord.Interaction, salon: discord.TextChannel):
        data = load_data()
        data.setdefault(str(interaction.guild_id), {})["channel_id"] = salon.id
        save_data(data)
        await interaction.response.send_message(f"Salon des suggestions défini sur {salon.mention}.", ephemeral=True)

    @suggestion_group.command(name="soumettre", description="Soumettre une suggestion")
    @app_commands.describe(texte="Votre suggestion")
    async def suggestion_submit(self, interaction: discord.Interaction, texte: str):
        data = load_data()
        guild_key = str(interaction.guild_id)
        channel_id = data.get(guild_key, {}).get("channel_id")
        if not channel_id:
            await interaction.response.send_message("Aucun salon de suggestions configuré. Contactez un admin.", ephemeral=True)
            return
        channel = interaction.guild.get_channel(channel_id)
        if not channel:
            await interaction.response.send_message("Le salon de suggestions est introuvable.", ephemeral=True)
            return

        suggestion = {
            "auteur_id": str(interaction.user.id),
            "texte": texte,
            "statut": "pending",
            "votes_pour": 0,
            "votes_contre": 0,
            "voters": {},
        }
        embed = _build_suggestion_embed(suggestion)
        embed.set_footer(text=f"Suggéré par {interaction.user.display_name}")

        await interaction.response.defer(ephemeral=True)
        msg = await channel.send(embed=embed)
        view = SuggestionVoteView(guild_key, str(msg.id))
        self.bot.add_view(view)
        await msg.edit(view=view)

        data.setdefault(guild_key, {}).setdefault("suggestions", {})[str(msg.id)] = suggestion
        save_data(data)
        await interaction.followup.send(f"Suggestion soumise dans {channel.mention}.", ephemeral=True)

    @suggestion_group.command(name="accepter", description="Accepter une suggestion")
    @app_commands.describe(message_id="ID du message de la suggestion", commentaire="Commentaire optionnel")
    @app_commands.default_permissions(manage_guild=True)
    async def suggestion_accept(self, interaction: discord.Interaction, message_id: str, commentaire: str = None):
        await self._update_suggestion(interaction, message_id, "acceptée", commentaire)

    @suggestion_group.command(name="refuser", description="Refuser une suggestion")
    @app_commands.describe(message_id="ID du message de la suggestion", commentaire="Commentaire optionnel")
    @app_commands.default_permissions(manage_guild=True)
    async def suggestion_refuse(self, interaction: discord.Interaction, message_id: str, commentaire: str = None):
        await self._update_suggestion(interaction, message_id, "refusée", commentaire)

    async def _update_suggestion(self, interaction: discord.Interaction, message_id: str, statut: str, commentaire: str | None):
        data = load_data()
        guild_key = str(interaction.guild_id)
        suggestion = data.get(guild_key, {}).get("suggestions", {}).get(message_id)
        if not suggestion:
            await interaction.response.send_message("Suggestion introuvable.", ephemeral=True)
            return
        suggestion["statut"] = statut
        if commentaire:
            suggestion["commentaire_admin"] = commentaire
        save_data(data)

        channel_id = data.get(guild_key, {}).get("channel_id")
        channel = interaction.guild.get_channel(channel_id) if channel_id else None
        if channel:
            try:
                msg = await channel.fetch_message(int(message_id))
                await msg.edit(embed=_build_suggestion_embed(suggestion), view=None)
            except (discord.NotFound, discord.Forbidden):
                pass
        await interaction.response.send_message(f"Suggestion marquée comme **{statut}**.", ephemeral=True)


async def setup(bot: commands.Bot):
    cog = Suggestions(bot)
    bot.tree.add_command(suggestion_group)
    await bot.add_cog(cog)
