import json
import os
import datetime
import asyncio
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


def get_config(guild_id: int) -> dict:
    return load_data().get(str(guild_id), {})


class CategorySelectView(discord.ui.View):
    """Panel principal avec le select menu des catégories."""

    def __init__(self):
        super().__init__(timeout=None)
        self.add_item(CategorySelect())


class CategorySelect(discord.ui.Select):
    def __init__(self):
        super().__init__(
            placeholder="Pour quelle raison souhaites-tu nous contacter ?",
            min_values=1,
            max_values=1,
            custom_id="ticket:categorie_select",
        )
        # Les options sont re-générées dynamiquement à chaque interaction
        self.options = [discord.SelectOption(label="Chargement...", value="__placeholder__")]

    async def callback(self, interaction: discord.Interaction):
        # Ignorer le placeholder si jamais
        if self.values[0] == "__placeholder__":
            await interaction.response.defer()
            return

        data = load_data()
        guild_key = str(interaction.guild_id)
        config = data.get(guild_key, {})

        if not config.get("categorie_id"):
            await interaction.response.send_message("Les tickets ne sont pas encore configurés.", ephemeral=True)
            return

        # Vérifier ticket déjà ouvert
        tickets = config.get("tickets", {})
        for ch_id, ticket in tickets.items():
            if str(ticket["user_id"]) == str(interaction.user.id):
                channel = interaction.guild.get_channel(int(ch_id))
                if channel:
                    await interaction.response.send_message(
                        f"Vous avez déjà un ticket ouvert : {channel.mention}", ephemeral=True
                    )
                    return

        categorie = interaction.guild.get_channel(config["categorie_id"])
        if not categorie:
            await interaction.response.send_message("La catégorie de tickets est introuvable.", ephemeral=True)
            return

        categorie_choisie = self.values[0]
        categories = config.get("categories", {})
        cat_info = categories.get(categorie_choisie, {})

        role_support_id = config.get("role_support_id")
        role_support = interaction.guild.get_role(role_support_id) if role_support_id else None

        overwrites = {
            interaction.guild.default_role: discord.PermissionOverwrite(view_channel=False),
            interaction.user: discord.PermissionOverwrite(view_channel=True, send_messages=True, read_message_history=True),
            interaction.guild.me: discord.PermissionOverwrite(view_channel=True, send_messages=True, manage_channels=True),
        }
        if role_support:
            overwrites[role_support] = discord.PermissionOverwrite(
                view_channel=True, send_messages=True, read_message_history=True
            )

        channel_name = f"ticket-{interaction.user.name}"
        channel = await interaction.guild.create_text_channel(
            name=channel_name,
            category=categorie,
            overwrites=overwrites,
            reason=f"Ticket ouvert par {interaction.user} — {categorie_choisie}",
        )

        data.setdefault(guild_key, {}).setdefault("tickets", {})[str(channel.id)] = {
            "user_id": interaction.user.id,
            "categorie": categorie_choisie,
            "ouvert_le": datetime.datetime.utcnow().isoformat(),
        }
        save_data(data)

        # Embed d'accueil
        embed = discord.Embed(
            title=f"Ticket — {cat_info.get('label', categorie_choisie)}",
            description=(
                f"Bonjour {interaction.user.mention} !\n\n"
                f"{cat_info.get('message_auto', 'L\'équipe support va vous répondre prochainement.')}\n\n"
                "Utilisez `/ticket fermer` ou le bouton ci-dessous pour fermer ce ticket."
            ),
            color=discord.Color.green(),
        )
        if role_support:
            embed.set_footer(text=f"Support : {role_support.name}")

        close_view = CloseTicketView()
        await channel.send(embed=embed, view=close_view)
        if role_support:
            await channel.send(f"{role_support.mention}", delete_after=1)

        await interaction.response.send_message(f"Ticket créé : {channel.mention}", ephemeral=True)


class DynamicCategorySelectView(discord.ui.View):
    """View reconstruite avec les vraies options depuis la config."""

    def __init__(self, config: dict):
        super().__init__(timeout=None)
        categories = config.get("categories", {})
        options = []
        for key, cat in categories.items():
            opt = discord.SelectOption(
                label=cat.get("label", key),
                value=key,
                description=cat.get("description", "")[:100] if cat.get("description") else None,
            )
            options.append(opt)

        if not options:
            options = [discord.SelectOption(label="Aucune catégorie configurée", value="__vide__")]

        select = discord.ui.Select(
            placeholder="Pour quelle raison souhaites-tu nous contacter ?",
            min_values=1,
            max_values=1,
            custom_id="ticket:categorie_select",
            options=options,
        )
        select.callback = self._on_select
        self.add_item(select)

    async def _on_select(self, interaction: discord.Interaction):
        await CategorySelect.callback(self.children[0], interaction)


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
        await interaction.response.send_message(
            "Seul le créateur du ticket ou un modérateur peut le fermer.", ephemeral=True
        )
        return

    await interaction.response.send_message("Fermeture du ticket dans 5 secondes...")
    await asyncio.sleep(5)

    del data[guild_key]["tickets"][channel_key]
    save_data(data)
    await interaction.channel.delete(reason=f"Ticket fermé par {interaction.user}")


class Tickets(commands.Cog):
    """Système de tickets de support."""

    ticket_group = app_commands.Group(name="ticket", description="Système de tickets de support")

    def __init__(self, bot: commands.Bot):
        self.bot = bot

    async def cog_load(self):
        self.bot.add_view(CloseTicketView())
        # Le select menu est reconstruit dynamiquement à chaque interaction
        # On enregistre quand même le custom_id pour que Discord le reconnaisse
        self.bot.add_view(CategorySelectView())

    # ── Configuration ────────────────────────────────────────────────────────

    @ticket_group.command(name="configurer", description="Configurer le système de tickets")
    @app_commands.describe(
        categorie="Catégorie Discord où créer les salons de ticket",
        role_support="Rôle de l'équipe support (optionnel)",
    )
    @app_commands.default_permissions(manage_guild=True)
    async def ticket_config(
        self,
        interaction: discord.Interaction,
        categorie: discord.CategoryChannel,
        role_support: discord.Role = None,
    ):
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

    # ── Gestion des catégories ────────────────────────────────────────────────

    @ticket_group.command(name="categorie_ajouter", description="Ajouter une catégorie de ticket")
    @app_commands.describe(
        identifiant="Identifiant court (ex: partenariat, bug, support)",
        label="Nom affiché dans le menu",
        description="Sous-titre affiché dans le menu (optionnel)",
        message_auto="Message automatique envoyé à l'ouverture (optionnel)",
    )
    @app_commands.default_permissions(manage_guild=True)
    async def ticket_cat_add(
        self,
        interaction: discord.Interaction,
        identifiant: str,
        label: str,
        description: str = "",
        message_auto: str = "",
    ):
        data = load_data()
        guild_key = str(interaction.guild_id)
        cats = data.setdefault(guild_key, {}).setdefault("categories", {})

        identifiant = identifiant.lower().replace(" ", "_")
        cats[identifiant] = {
            "label": label,
            "description": description,
            "message_auto": message_auto,
        }
        save_data(data)

        embed = discord.Embed(
            title="Catégorie ajoutée",
            description=f"**{label}** (`{identifiant}`) ajoutée avec succès.",
            color=discord.Color.green(),
        )
        if message_auto:
            embed.add_field(name="Message automatique", value=message_auto, inline=False)
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @ticket_group.command(name="categorie_supprimer", description="Supprimer une catégorie de ticket")
    @app_commands.describe(identifiant="Identifiant de la catégorie à supprimer")
    @app_commands.default_permissions(manage_guild=True)
    async def ticket_cat_remove(self, interaction: discord.Interaction, identifiant: str):
        data = load_data()
        guild_key = str(interaction.guild_id)
        cats = data.get(guild_key, {}).get("categories", {})

        if identifiant not in cats:
            await interaction.response.send_message(f"Catégorie `{identifiant}` introuvable.", ephemeral=True)
            return

        label = cats[identifiant].get("label", identifiant)
        del cats[identifiant]
        save_data(data)
        await interaction.response.send_message(f"Catégorie **{label}** supprimée.", ephemeral=True)

    @ticket_group.command(name="categories_liste", description="Lister les catégories de ticket configurées")
    @app_commands.default_permissions(manage_guild=True)
    async def ticket_cat_list(self, interaction: discord.Interaction):
        config = get_config(interaction.guild_id)
        cats = config.get("categories", {})

        if not cats:
            await interaction.response.send_message("Aucune catégorie configurée.", ephemeral=True)
            return

        embed = discord.Embed(title="Catégories de tickets", color=discord.Color.blurple())
        for key, cat in cats.items():
            val = f"Description : {cat.get('description') or '—'}\nMessage auto : {cat.get('message_auto') or '—'}"
            embed.add_field(name=f"{cat.get('label', key)} (`{key}`)", value=val, inline=False)

        await interaction.response.send_message(embed=embed, ephemeral=True)

    # ── Panel ────────────────────────────────────────────────────────────────

    @ticket_group.command(name="panel", description="Envoyer le panel d'ouverture de ticket dans un salon")
    @app_commands.describe(
        salon="Salon où envoyer le panel",
        titre="Titre de l'embed (optionnel)",
        message="Message d'invitation (optionnel)",
    )
    @app_commands.default_permissions(manage_guild=True)
    async def ticket_panel(
        self,
        interaction: discord.Interaction,
        salon: discord.TextChannel,
        titre: str = "📩 Ouvrir un ticket",
        message: str = "Clique sur le menu ci-dessous pour ouvrir un ticket et indiquer la raison de ta demande.",
    ):
        config = get_config(interaction.guild_id)
        cats = config.get("categories", {})

        if not cats:
            await interaction.response.send_message(
                "Ajoutez d'abord des catégories avec `/ticket categorie_ajouter`.", ephemeral=True
            )
            return

        options = [
            discord.SelectOption(
                label=cat.get("label", key),
                value=key,
                description=cat.get("description", "")[:100] if cat.get("description") else None,
            )
            for key, cat in cats.items()
        ]

        view = discord.ui.View(timeout=None)
        select = discord.ui.Select(
            placeholder="Pour quelle raison souhaites-tu nous contacter ?",
            min_values=1,
            max_values=1,
            custom_id="ticket:categorie_select",
            options=options,
        )
        view.add_item(select)

        embed = discord.Embed(title=titre, description=message, color=discord.Color.blurple())
        await salon.send(embed=embed, view=view)
        await interaction.response.send_message(f"Panel envoyé dans {salon.mention}.", ephemeral=True)

    # ── Actions ticket ───────────────────────────────────────────────────────

    @ticket_group.command(name="fermer", description="Fermer le ticket actuel")
    async def ticket_close(self, interaction: discord.Interaction):
        await _close_ticket(interaction)

    @ticket_group.command(name="ajouter", description="Ajouter un membre au ticket actuel")
    @app_commands.describe(membre="Membre à ajouter")
    @app_commands.default_permissions(manage_channels=True)
    async def ticket_add(self, interaction: discord.Interaction, membre: discord.Member):
        data = load_data()
        ticket = data.get(str(interaction.guild_id), {}).get("tickets", {}).get(str(interaction.channel_id))
        if not ticket:
            await interaction.response.send_message("Ce salon n'est pas un ticket.", ephemeral=True)
            return
        await interaction.channel.set_permissions(
            membre, view_channel=True, send_messages=True, read_message_history=True
        )
        await interaction.response.send_message(f"{membre.mention} a été ajouté au ticket.")

    # ── Listener select menu (persistent après redémarrage) ──────────────────

    @commands.Cog.listener()
    async def on_interaction(self, interaction: discord.Interaction):
        if interaction.type != discord.InteractionType.component:
            return
        if interaction.data.get("custom_id") != "ticket:categorie_select":
            return
        if interaction.response.is_done():
            return

        # Reconstruire la logique d'ouverture
        data = load_data()
        guild_key = str(interaction.guild_id)
        config = data.get(guild_key, {})
        categorie_choisie = interaction.data["values"][0]

        if categorie_choisie in ("__placeholder__", "__vide__"):
            await interaction.response.defer()
            return

        if not config.get("categorie_id"):
            await interaction.response.send_message("Les tickets ne sont pas encore configurés.", ephemeral=True)
            return

        tickets = config.get("tickets", {})
        for ch_id, ticket in tickets.items():
            if str(ticket["user_id"]) == str(interaction.user.id):
                channel = interaction.guild.get_channel(int(ch_id))
                if channel:
                    await interaction.response.send_message(
                        f"Vous avez déjà un ticket ouvert : {channel.mention}", ephemeral=True
                    )
                    return

        categorie_discord = interaction.guild.get_channel(config["categorie_id"])
        if not categorie_discord:
            await interaction.response.send_message("La catégorie de tickets est introuvable.", ephemeral=True)
            return

        categories = config.get("categories", {})
        cat_info = categories.get(categorie_choisie, {})

        role_support_id = config.get("role_support_id")
        role_support = interaction.guild.get_role(role_support_id) if role_support_id else None

        overwrites = {
            interaction.guild.default_role: discord.PermissionOverwrite(view_channel=False),
            interaction.user: discord.PermissionOverwrite(view_channel=True, send_messages=True, read_message_history=True),
            interaction.guild.me: discord.PermissionOverwrite(view_channel=True, send_messages=True, manage_channels=True),
        }
        if role_support:
            overwrites[role_support] = discord.PermissionOverwrite(
                view_channel=True, send_messages=True, read_message_history=True
            )

        channel = await interaction.guild.create_text_channel(
            name=f"ticket-{interaction.user.name}",
            category=categorie_discord,
            overwrites=overwrites,
            reason=f"Ticket ouvert par {interaction.user} — {categorie_choisie}",
        )

        data.setdefault(guild_key, {}).setdefault("tickets", {})[str(channel.id)] = {
            "user_id": interaction.user.id,
            "categorie": categorie_choisie,
            "ouvert_le": datetime.datetime.utcnow().isoformat(),
        }
        save_data(data)

        embed = discord.Embed(
            title=f"Ticket — {cat_info.get('label', categorie_choisie)}",
            description=(
                f"Bonjour {interaction.user.mention} !\n\n"
                f"{cat_info.get('message_auto', 'L\'équipe support va vous répondre prochainement.')}\n\n"
                "Utilisez `/ticket fermer` ou le bouton ci-dessous pour fermer ce ticket."
            ),
            color=discord.Color.green(),
        )
        if role_support:
            embed.set_footer(text=f"Support : {role_support.name}")

        await channel.send(embed=embed, view=CloseTicketView())
        if role_support:
            await channel.send(f"{role_support.mention}", delete_after=1)

        await interaction.response.send_message(f"Ticket créé : {channel.mention}", ephemeral=True)


async def setup(bot: commands.Bot):
    await bot.add_cog(Tickets(bot))
