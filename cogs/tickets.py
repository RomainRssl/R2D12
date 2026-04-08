import json
import os
import datetime
import discord
from discord import app_commands
from discord.ext import commands

TICKETS_FILE = "data/tickets.json"


def load_data() -> dict:
    if not os.path.exists(TICKETS_FILE):
        return {}
    with open(TICKETS_FILE, "r", encoding="utf-8") as f:
        return json.load(f)


def save_data(data: dict):
    os.makedirs("data", exist_ok=True)
    with open(TICKETS_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


class OpenTicketView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(label="📩 Ouvrir un ticket", style=discord.ButtonStyle.primary, custom_id="ticket:ouvrir")
    async def open_ticket(self, interaction: discord.Interaction, button: discord.ui.Button):
        data = load_data()
        guild_key = str(interaction.guild_id)
        config = data.get(guild_key, {})

        if not config.get("categorie_id"):
            await interaction.response.send_message("Les tickets ne sont pas encore configurés.", ephemeral=True)
            return

        # Vérifier si l'utilisateur a déjà un ticket ouvert
        tickets = config.get("tickets", {})
        for ch_id, ticket in tickets.items():
            if str(ticket["user_id"]) == str(interaction.user.id):
                channel = interaction.guild.get_channel(int(ch_id))
                if channel:
                    await interaction.response.send_message(f"Vous avez déjà un ticket ouvert : {channel.mention}", ephemeral=True)
                    return

        categorie = interaction.guild.get_channel(config["categorie_id"])
        if not categorie:
            await interaction.response.send_message("La catégorie de tickets est introuvable.", ephemeral=True)
            return

        role_support_id = config.get("role_support_id")
        role_support = interaction.guild.get_role(role_support_id) if role_support_id else None

        overwrites = {
            interaction.guild.default_role: discord.PermissionOverwrite(view_channel=False),
            interaction.user: discord.PermissionOverwrite(view_channel=True, send_messages=True, read_message_history=True),
            interaction.guild.me: discord.PermissionOverwrite(view_channel=True, send_messages=True, manage_channels=True),
        }
        if role_support:
            overwrites[role_support] = discord.PermissionOverwrite(view_channel=True, send_messages=True, read_message_history=True)

        channel = await interaction.guild.create_text_channel(
            name=f"ticket-{interaction.user.name}",
            category=categorie,
            overwrites=overwrites,
            reason=f"Ticket ouvert par {interaction.user}",
        )

        data.setdefault(guild_key, {}).setdefault("tickets", {})[str(channel.id)] = {
            "user_id": interaction.user.id,
            "sujet": "Aucun sujet",
            "ouvert_le": datetime.datetime.utcnow().isoformat(),
        }
        save_data(data)

        embed = discord.Embed(
            title="Ticket ouvert",
            description=f"Bonjour {interaction.user.mention} ! L'équipe support va vous répondre prochainement.\nUtilisez `/ticket fermer` pour fermer ce ticket.",
            color=discord.Color.green(),
        )
        if role_support:
            embed.set_footer(text=f"Support : {role_support.name}")
        close_view = CloseTicketView()
        await channel.send(embed=embed, view=close_view)
        if role_support:
            await channel.send(f"{role_support.mention}", delete_after=1)

        await interaction.response.send_message(f"Ticket créé : {channel.mention}", ephemeral=True)


class CloseTicketView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(label="🔒 Fermer le ticket", style=discord.ButtonStyle.danger, custom_id="ticket:fermer_btn")
    async def fermer(self, interaction: discord.Interaction, button: discord.ui.Button):
        await _close_ticket(interaction)


async def _close_ticket(interaction: discord.Interaction):
    data = load_data()
    guild_key = str(interaction.guild_id)
    channel_key = str(interaction.channel_id)
    ticket = data.get(guild_key, {}).get("tickets", {}).get(channel_key)

    if not ticket:
        await interaction.response.send_message("Ce salon n'est pas un ticket.", ephemeral=True)
        return

    is_owner = str(interaction.user.id) == str(ticket["user_id"])
    is_mod = interaction.user.guild_permissions.manage_channels
    if not is_owner and not is_mod:
        await interaction.response.send_message("Seul le créateur du ticket ou un modérateur peut le fermer.", ephemeral=True)
        return

    await interaction.response.send_message("Fermeture du ticket dans 5 secondes...")
    import asyncio
    await asyncio.sleep(5)

    del data[guild_key]["tickets"][channel_key]
    save_data(data)
    await interaction.channel.delete(reason=f"Ticket fermé par {interaction.user}")


ticket_group = app_commands.Group(name="ticket", description="Système de tickets de support")


class Tickets(commands.Cog):
    """Système de tickets de support."""

    def __init__(self, bot: commands.Bot):
        self.bot = bot

    async def cog_load(self):
        self.bot.add_view(OpenTicketView())
        self.bot.add_view(CloseTicketView())

    @ticket_group.command(name="configurer", description="Configurer le système de tickets")
    @app_commands.describe(categorie="Catégorie où créer les tickets", role_support="Rôle de l'équipe support")
    @app_commands.default_permissions(manage_guild=True)
    async def ticket_config(self, interaction: discord.Interaction, categorie: discord.CategoryChannel, role_support: discord.Role = None):
        data = load_data()
        guild_key = str(interaction.guild_id)
        data.setdefault(guild_key, {}).update({
            "categorie_id": categorie.id,
            "role_support_id": role_support.id if role_support else None,
        })
        save_data(data)
        embed = discord.Embed(title="Tickets configurés", color=discord.Color.green())
        embed.add_field(name="Catégorie", value=categorie.name)
        embed.add_field(name="Rôle support", value=role_support.mention if role_support else "Non défini")
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @ticket_group.command(name="panel", description="Envoyer le bouton d'ouverture de ticket dans un salon")
    @app_commands.describe(salon="Salon où envoyer le bouton", message="Message d'invitation")
    @app_commands.default_permissions(manage_guild=True)
    async def ticket_panel(self, interaction: discord.Interaction, salon: discord.TextChannel, message: str = "Cliquez sur le bouton ci-dessous pour ouvrir un ticket."):
        embed = discord.Embed(description=message, color=discord.Color.blurple())
        await salon.send(embed=embed, view=OpenTicketView())
        await interaction.response.send_message(f"Panel de tickets envoyé dans {salon.mention}.", ephemeral=True)

    @ticket_group.command(name="fermer", description="Fermer le ticket actuel")
    async def ticket_close(self, interaction: discord.Interaction):
        await _close_ticket(interaction)

    @ticket_group.command(name="ajouter", description="Ajouter un membre au ticket actuel")
    @app_commands.describe(membre="Membre à ajouter au ticket")
    @app_commands.default_permissions(manage_channels=True)
    async def ticket_add(self, interaction: discord.Interaction, membre: discord.Member):
        data = load_data()
        ticket = data.get(str(interaction.guild_id), {}).get("tickets", {}).get(str(interaction.channel_id))
        if not ticket:
            await interaction.response.send_message("Ce salon n'est pas un ticket.", ephemeral=True)
            return
        await interaction.channel.set_permissions(membre, view_channel=True, send_messages=True, read_message_history=True)
        await interaction.response.send_message(f"{membre.mention} a été ajouté au ticket.")


async def setup(bot: commands.Bot):
    cog = Tickets(bot)
    bot.tree.add_command(ticket_group)
    await bot.add_cog(cog)
