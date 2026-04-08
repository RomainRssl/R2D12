import json
import os
import discord
from discord import app_commands
from discord.ext import commands

RR_FILE = "data/reactionroles.json"


def load_data() -> dict:
    if not os.path.exists(RR_FILE):
        return {}
    with open(RR_FILE, "r", encoding="utf-8") as f:
        return json.load(f)


def save_data(data: dict):
    os.makedirs("data", exist_ok=True)
    with open(RR_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


class RoleButton(discord.ui.Button):
    def __init__(self, role_id: int, label: str, emoji: str | None = None):
        super().__init__(
            style=discord.ButtonStyle.secondary,
            label=label,
            emoji=emoji or None,
            custom_id=f"rr:{role_id}",
        )
        self.role_id = role_id

    async def callback(self, interaction: discord.Interaction):
        role = interaction.guild.get_role(self.role_id)
        if not role:
            await interaction.response.send_message("Ce rôle n'existe plus.", ephemeral=True)
            return
        if role in interaction.user.roles:
            await interaction.user.remove_roles(role)
            await interaction.response.send_message(f"Rôle {role.mention} retiré.", ephemeral=True)
        else:
            await interaction.user.add_roles(role)
            await interaction.response.send_message(f"Rôle {role.mention} attribué.", ephemeral=True)


class RoleView(discord.ui.View):
    def __init__(self, roles: list[dict]):
        super().__init__(timeout=None)
        for item in roles:
            self.add_item(RoleButton(
                role_id=item["role_id"],
                label=item["label"],
                emoji=item.get("emoji"),
            ))


rolerole_group = app_commands.Group(name="rolerole", description="Gestion des menus de rôles réactions")


class ReactionRoles(commands.Cog):
    """Menus de rôles avec boutons."""

    def __init__(self, bot: commands.Bot):
        self.bot = bot

    async def cog_load(self):
        """Recharge les vues persistantes au démarrage."""
        data = load_data()
        for guild_data in data.values():
            for panel in guild_data.values():
                if panel.get("roles"):
                    self.bot.add_view(RoleView(panel["roles"]))

    @rolerole_group.command(name="créer", description="Créer un panneau de rôles réactions")
    @app_commands.describe(salon="Salon où envoyer le panneau", titre="Titre du panneau", description="Description du panneau")
    @app_commands.default_permissions(manage_roles=True)
    async def rr_create(self, interaction: discord.Interaction, salon: discord.TextChannel, titre: str, description: str):
        embed = discord.Embed(title=titre, description=description, color=discord.Color.blurple())
        embed.set_footer(text="Cliquez sur un bouton pour obtenir ou retirer un rôle.")
        # Message vide pour l'instant, boutons ajoutés ensuite avec /rolerole ajouter
        msg = await salon.send(embed=embed)

        data = load_data()
        data.setdefault(str(interaction.guild_id), {})[str(msg.id)] = {
            "channel_id": salon.id,
            "titre": titre,
            "roles": [],
        }
        save_data(data)
        await interaction.response.send_message(
            f"Panneau créé dans {salon.mention} (ID : `{msg.id}`).\nUtilisez `/rolerole ajouter {msg.id} @role label` pour ajouter des boutons.",
            ephemeral=True,
        )

    @rolerole_group.command(name="ajouter", description="Ajouter un bouton de rôle à un panneau existant")
    @app_commands.describe(message_id="ID du message panneau", role="Rôle à attribuer", label="Texte du bouton", emoji="Emoji du bouton (optionnel)")
    @app_commands.default_permissions(manage_roles=True)
    async def rr_add(self, interaction: discord.Interaction, message_id: str, role: discord.Role, label: str, emoji: str = None):
        data = load_data()
        guild_key = str(interaction.guild_id)
        panel = data.get(guild_key, {}).get(message_id)
        if not panel:
            await interaction.response.send_message("Panneau introuvable. Vérifiez l'ID.", ephemeral=True)
            return
        if len(panel["roles"]) >= 25:
            await interaction.response.send_message("Maximum 25 boutons par panneau.", ephemeral=True)
            return

        panel["roles"].append({"role_id": role.id, "label": label, "emoji": emoji})
        save_data(data)

        channel = interaction.guild.get_channel(panel["channel_id"])
        if channel:
            try:
                msg = await channel.fetch_message(int(message_id))
                view = RoleView(panel["roles"])
                self.bot.add_view(view)
                await msg.edit(view=view)
            except (discord.NotFound, discord.Forbidden):
                pass

        await interaction.response.send_message(f"Bouton pour {role.mention} ajouté au panneau.", ephemeral=True)

    @rolerole_group.command(name="supprimer", description="Supprimer un panneau de rôles réactions")
    @app_commands.describe(message_id="ID du message panneau à supprimer")
    @app_commands.default_permissions(manage_roles=True)
    async def rr_delete(self, interaction: discord.Interaction, message_id: str):
        data = load_data()
        guild_key = str(interaction.guild_id)
        panel = data.get(guild_key, {}).get(message_id)
        if not panel:
            await interaction.response.send_message("Panneau introuvable.", ephemeral=True)
            return

        channel = interaction.guild.get_channel(panel["channel_id"])
        if channel:
            try:
                msg = await channel.fetch_message(int(message_id))
                await msg.delete()
            except (discord.NotFound, discord.Forbidden):
                pass

        del data[guild_key][message_id]
        save_data(data)
        await interaction.response.send_message("Panneau supprimé.", ephemeral=True)


async def setup(bot: commands.Bot):
    cog = ReactionRoles(bot)
    bot.tree.add_command(rolerole_group)
    await bot.add_cog(cog)
