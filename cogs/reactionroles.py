import json
import os
import discord
from discord import app_commands
from discord.ext import commands

RR_FILE = "data/reactionroles.json"
ER_FILE = "data/emojiroles.json"


def load_data() -> dict:
    if not os.path.exists(RR_FILE):
        return {}
    with open(RR_FILE, "r", encoding="utf-8") as f:
        return json.load(f)


def save_data(data: dict):
    os.makedirs("data", exist_ok=True)
    with open(RR_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def load_er() -> dict:
    if not os.path.exists(ER_FILE):
        return {}
    with open(ER_FILE, "r", encoding="utf-8") as f:
        return json.load(f)


def save_er(data: dict):
    os.makedirs("data", exist_ok=True)
    with open(ER_FILE, "w", encoding="utf-8") as f:
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
emojirole_group = app_commands.Group(name="emojirole", description="Rôles attribués via réaction emoji sur un message")


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

    @rolerole_group.command(name="creer", description="Créer un panneau de rôles réactions")
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

    # ── Emoji reaction roles ───────────────────────────────────────────────────

    @emojirole_group.command(name="ajouter", description="Associer un emoji sur un message à un rôle")
    @app_commands.describe(
        message_id="ID du message cible (clic droit → Copier l'identifiant)",
        emoji="L'emoji à surveiller (ex: 👍 ou :nom:)",
        role="Rôle à attribuer / retirer",
    )
    @app_commands.default_permissions(manage_roles=True)
    async def er_add(self, interaction: discord.Interaction, message_id: str, emoji: str, role: discord.Role):
        if not message_id.isdigit():
            await interaction.response.send_message("L'ID du message doit être un nombre.", ephemeral=True)
            return

        emoji = emoji.strip()
        data = load_er()
        guild_key = str(interaction.guild_id)
        msg_entries = data.setdefault(guild_key, {}).setdefault(message_id, [])

        # Vérifie les doublons
        for entry in msg_entries:
            if entry["emoji"] == emoji:
                await interaction.response.send_message(
                    f"L'emoji {emoji} est déjà configuré sur ce message (rôle <@&{entry['role_id']}> ).",
                    ephemeral=True,
                )
                return

        msg_entries.append({"emoji": emoji, "role_id": role.id})
        save_er(data)

        # Ajoute la réaction de démo sur le message si accessible
        try:
            for ch in interaction.guild.text_channels:
                try:
                    msg = await ch.fetch_message(int(message_id))
                    await msg.add_reaction(emoji)
                    break
                except (discord.NotFound, discord.HTTPException):
                    continue
        except Exception:
            pass

        embed = discord.Embed(title="✅ Emoji-rôle configuré", color=discord.Color.green())
        embed.add_field(name="Message ID", value=message_id)
        embed.add_field(name="Emoji", value=emoji)
        embed.add_field(name="Rôle", value=role.mention)
        embed.set_footer(text="Réagir avec cet emoji attribuera / retirera le rôle automatiquement.")
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @emojirole_group.command(name="retirer", description="Supprimer l'association emoji → rôle sur un message")
    @app_commands.describe(
        message_id="ID du message",
        emoji="L'emoji à dissocier",
    )
    @app_commands.default_permissions(manage_roles=True)
    async def er_remove(self, interaction: discord.Interaction, message_id: str, emoji: str):
        emoji = emoji.strip()
        data = load_er()
        guild_key = str(interaction.guild_id)
        msg_entries = data.get(guild_key, {}).get(message_id, [])

        new_entries = [e for e in msg_entries if e["emoji"] != emoji]
        if len(new_entries) == len(msg_entries):
            await interaction.response.send_message("Aucune association trouvée pour cet emoji sur ce message.", ephemeral=True)
            return

        data[guild_key][message_id] = new_entries
        if not new_entries:
            del data[guild_key][message_id]
        save_er(data)
        await interaction.response.send_message(f"Association {emoji} supprimée du message `{message_id}`.", ephemeral=True)

    @emojirole_group.command(name="liste", description="Voir toutes les associations emoji → rôle")
    @app_commands.default_permissions(manage_roles=True)
    async def er_list(self, interaction: discord.Interaction):
        data = load_er()
        guild_entries = data.get(str(interaction.guild_id), {})

        if not guild_entries:
            await interaction.response.send_message("Aucune association emoji-rôle configurée.", ephemeral=True)
            return

        embed = discord.Embed(title="Associations emoji → rôle", color=discord.Color.blurple())
        for msg_id, entries in guild_entries.items():
            lines = []
            for e in entries:
                role = interaction.guild.get_role(e["role_id"])
                role_str = role.mention if role else f"ID {e['role_id']}"
                lines.append(f"{e['emoji']} → {role_str}")
            embed.add_field(name=f"Message `{msg_id}`", value="\n".join(lines), inline=False)
        await interaction.response.send_message(embed=embed, ephemeral=True)

    # ── Raw reaction events ────────────────────────────────────────────────────

    @commands.Cog.listener()
    async def on_raw_reaction_add(self, payload: discord.RawReactionActionEvent):
        if payload.user_id == self.bot.user.id:
            return
        await self._handle_reaction(payload, add=True)

    @commands.Cog.listener()
    async def on_raw_reaction_remove(self, payload: discord.RawReactionActionEvent):
        if payload.user_id == self.bot.user.id:
            return
        await self._handle_reaction(payload, add=False)

    async def _handle_reaction(self, payload: discord.RawReactionActionEvent, add: bool):
        data = load_er()
        guild_key = str(payload.guild_id)
        msg_entries = data.get(guild_key, {}).get(str(payload.message_id), [])
        if not msg_entries:
            return

        emoji_str = str(payload.emoji)
        for entry in msg_entries:
            if entry["emoji"] == emoji_str:
                guild = self.bot.get_guild(payload.guild_id)
                if not guild:
                    return
                role = guild.get_role(entry["role_id"])
                if not role:
                    return
                member = guild.get_member(payload.user_id) or await guild.fetch_member(payload.user_id)
                if not member:
                    return
                try:
                    if add:
                        await member.add_roles(role, reason="Emoji-rôle automatique")
                    else:
                        await member.remove_roles(role, reason="Emoji-rôle automatique")
                except (discord.Forbidden, discord.HTTPException):
                    pass
                break


async def setup(bot: commands.Bot):
    cog = ReactionRoles(bot)
    bot.tree.add_command(rolerole_group)
    bot.tree.add_command(emojirole_group)
    await bot.add_cog(cog)
