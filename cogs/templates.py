import re
import json
import os
import discord
from discord import app_commands
from discord.ext import commands

TEMPLATES_FILE = "data/templates.json"


def load_templates() -> dict:
    if not os.path.exists(TEMPLATES_FILE):
        return {}
    with open(TEMPLATES_FILE, "r", encoding="utf-8") as f:
        return json.load(f)


def save_templates(data: dict):
    os.makedirs("data", exist_ok=True)
    with open(TEMPLATES_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def get_guild_templates(guild_id: int) -> dict:
    data = load_templates()
    return data.get(str(guild_id), {})


def extract_placeholders(text: str) -> list[str]:
    """Retourne les noms de variables {variable} dans l'ordre d'apparition (sans doublons)."""
    seen = set()
    result = []
    for name in re.findall(r"\{(\w+)\}", text):
        if name not in seen:
            seen.add(name)
            result.append(name)
    return result


class FillTemplateModal(discord.ui.Modal):
    """Modal Discord pour remplir les trous d'un template."""

    def __init__(self, template_name: str, template_content: str, channel: discord.TextChannel | None):
        super().__init__(title=f"Template : {template_name[:40]}")
        self.template_content = template_content
        self.channel = channel
        self.placeholders = extract_placeholders(template_content)

        for placeholder in self.placeholders[:5]:  # max 5 champs par modal Discord
            self.add_item(
                discord.ui.TextInput(
                    label=placeholder.replace("_", " ").capitalize(),
                    placeholder=f"Valeur pour {{{placeholder}}}",
                    required=True,
                    max_length=200,
                )
            )

    async def on_submit(self, interaction: discord.Interaction):
        result = self.template_content
        for i, placeholder in enumerate(self.placeholders[:5]):
            result = result.replace(f"{{{placeholder}}}", self.children[i].value)

        destination = self.channel or interaction.channel
        embed = discord.Embed(description=result, color=discord.Color.blurple())
        embed.set_footer(text=f"Envoyé par {interaction.user.display_name}")

        if self.channel and self.channel != interaction.channel:
            await destination.send(embed=embed)
            await interaction.response.send_message(
                f"Message envoyé dans {self.channel.mention}.", ephemeral=True
            )
        else:
            await interaction.response.send_message(embed=embed)


class Templates(commands.Cog):
    """Messages pré-enregistrés avec trous à remplir et annonces."""

    template_group = app_commands.Group(
        name="template",
        description="Gestion des messages pré-enregistrés avec variables",
    )

    def __init__(self, bot: commands.Bot):
        self.bot = bot

    @template_group.command(name="creer", description="Créer un template avec des {variables} à remplir")
    @app_commands.describe(
        nom="Nom du template (ex: bienvenue)",
        message="Contenu du template. Utilisez {variable} pour les trous (ex: Bonjour {prénom} !)",
    )
    @app_commands.default_permissions(manage_messages=True)
    async def template_create(self, interaction: discord.Interaction, nom: str, message: str):
        nom = nom.lower().strip()
        data = load_templates()
        guild_key = str(interaction.guild_id)
        if guild_key not in data:
            data[guild_key] = {}

        placeholders = extract_placeholders(message)
        data[guild_key][nom] = message
        save_templates(data)

        embed = discord.Embed(
            title="Template créé",
            color=discord.Color.green(),
        )
        embed.add_field(name="Nom", value=f"`{nom}`", inline=True)
        embed.add_field(
            name="Variables détectées",
            value=", ".join(f"`{{{p}}}`" for p in placeholders) if placeholders else "Aucune",
            inline=True,
        )
        embed.add_field(name="Aperçu", value=message[:500], inline=False)
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @template_group.command(name="utiliser", description="Utiliser un template (ouvre un formulaire pour remplir les trous)")
    @app_commands.describe(
        nom="Nom du template à utiliser",
        salon="Salon où envoyer le message (salon actuel par défaut)",
    )
    async def template_use(self, interaction: discord.Interaction, nom: str, salon: discord.TextChannel = None):
        templates = get_guild_templates(interaction.guild_id)
        nom = nom.lower().strip()

        if nom not in templates:
            await interaction.response.send_message(
                f"Template `{nom}` introuvable. Utilisez `/template liste` pour voir les templates disponibles.",
                ephemeral=True,
            )
            return

        content = templates[nom]
        placeholders = extract_placeholders(content)

        if not placeholders:
            # Pas de trous : envoi direct
            destination = salon or interaction.channel
            embed = discord.Embed(description=content, color=discord.Color.blurple())
            embed.set_footer(text=f"Envoyé par {interaction.user.display_name}")
            if salon and salon != interaction.channel:
                await destination.send(embed=embed)
                await interaction.response.send_message(f"Message envoyé dans {salon.mention}.", ephemeral=True)
            else:
                await interaction.response.send_message(embed=embed)
        else:
            # Ouvre le modal pour remplir les trous
            await interaction.response.send_modal(FillTemplateModal(nom, content, salon))

    @template_group.command(name="liste", description="Voir tous les templates du serveur")
    async def template_list(self, interaction: discord.Interaction):
        templates = get_guild_templates(interaction.guild_id)

        if not templates:
            await interaction.response.send_message("Aucun template enregistré sur ce serveur.", ephemeral=True)
            return

        embed = discord.Embed(
            title="Templates du serveur",
            color=discord.Color.blurple(),
        )
        for nom, content in templates.items():
            placeholders = extract_placeholders(content)
            variables = ", ".join(f"`{{{p}}}`" for p in placeholders) if placeholders else "—"
            embed.add_field(
                name=f"`{nom}`",
                value=f"Variables : {variables}\n_{content[:80]}{'...' if len(content) > 80 else ''}_",
                inline=False,
            )
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @template_group.command(name="supprimer", description="Supprimer un template")
    @app_commands.describe(nom="Nom du template à supprimer")
    @app_commands.default_permissions(manage_messages=True)
    async def template_delete(self, interaction: discord.Interaction, nom: str):
        nom = nom.lower().strip()
        data = load_templates()
        guild_key = str(interaction.guild_id)

        if guild_key not in data or nom not in data[guild_key]:
            await interaction.response.send_message(f"Template `{nom}` introuvable.", ephemeral=True)
            return

        del data[guild_key][nom]
        save_templates(data)
        await interaction.response.send_message(f"Template `{nom}` supprimé.", ephemeral=True)

    # ── Autocomplete sur le nom du template ──────────────────────────────────

    @template_use.autocomplete("nom")
    @template_delete.autocomplete("nom")
    async def autocomplete_template_name(self, interaction: discord.Interaction, current: str):
        templates = get_guild_templates(interaction.guild_id)
        return [
            app_commands.Choice(name=name, value=name)
            for name in templates
            if current.lower() in name.lower()
        ][:25]

    # ── Commande /annonce ─────────────────────────────────────────────────────

    @app_commands.command(name="annonce", description="Envoyer une annonce formatée dans un salon")
    @app_commands.describe(
        salon="Salon de destination",
        titre="Titre de l'annonce",
        message="Contenu de l'annonce",
        couleur="Couleur de l'embed (rouge, vert, bleu, orange, violet) — bleu par défaut",
    )
    @app_commands.choices(couleur=[
        app_commands.Choice(name="Bleu", value="bleu"),
        app_commands.Choice(name="Vert", value="vert"),
        app_commands.Choice(name="Rouge", value="rouge"),
        app_commands.Choice(name="Orange", value="orange"),
        app_commands.Choice(name="Violet", value="violet"),
    ])
    @app_commands.default_permissions(manage_messages=True)
    async def annonce(
        self,
        interaction: discord.Interaction,
        salon: discord.TextChannel,
        titre: str,
        message: str,
        couleur: str = "bleu",
    ):
        color_map = {
            "bleu": discord.Color.blurple(),
            "vert": discord.Color.green(),
            "rouge": discord.Color.red(),
            "orange": discord.Color.orange(),
            "violet": discord.Color.purple(),
        }
        embed = discord.Embed(
            title=titre,
            description=message,
            color=color_map.get(couleur, discord.Color.blurple()),
        )
        embed.set_footer(text=f"Annonce de {interaction.user.display_name} • {interaction.guild.name}")

        await salon.send(embed=embed)
        await interaction.response.send_message(f"Annonce envoyée dans {salon.mention}.", ephemeral=True)


async def setup(bot: commands.Bot):
    await bot.add_cog(Templates(bot))
