import json
import os
import re
import discord
from discord import app_commands
from discord.ext import commands

WR_FILE = "data/wordreplace.json"


def load_data() -> dict:
    if not os.path.exists(WR_FILE):
        return {}
    with open(WR_FILE, "r", encoding="utf-8") as f:
        return json.load(f)


def save_data(data: dict):
    os.makedirs("data", exist_ok=True)
    with open(WR_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


async def get_or_create_webhook(channel: discord.TextChannel) -> discord.Webhook:
    webhooks = await channel.webhooks()
    for wh in webhooks:
        if wh.name == "R2D12-Relais":
            return wh
    return await channel.create_webhook(name="R2D12-Relais")


def apply_replacements(content: str, rules: dict) -> tuple[str, bool]:
    """Applique les règles de remplacement au contenu. Retourne (nouveau_contenu, modifié)."""
    modified = False
    for banned, replacement in rules.items():
        pattern = re.compile(re.escape(banned), re.IGNORECASE)
        new_content, count = pattern.subn(replacement, content)
        if count:
            content = new_content
            modified = True
    return content, modified


remplacer_group = app_commands.Group(
    name="remplacer",
    description="Gestion du remplacement automatique de mots",
)


class WordReplace(commands.Cog):
    """Remplace automatiquement les mots bannis dans les messages."""

    def __init__(self, bot: commands.Bot):
        self.bot = bot

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message):
        if message.author.bot:
            return
        if not message.guild:
            return
        if not message.content:
            return

        data = load_data()
        guild_cfg = data.get(str(message.guild.id), {})
        if not guild_cfg.get("enabled", True):
            return
        rules = guild_cfg.get("rules", {})
        if not rules:
            return

        new_content, modified = apply_replacements(message.content, rules)
        if not modified:
            return

        # Vérifie les permissions avant d'essayer de supprimer
        if not message.channel.permissions_for(message.guild.me).manage_messages:
            return
        if not message.channel.permissions_for(message.guild.me).manage_webhooks:
            return

        try:
            await message.delete()
        except (discord.Forbidden, discord.NotFound):
            return

        try:
            webhook = await get_or_create_webhook(message.channel)
            files = []
            for att in message.attachments:
                try:
                    files.append(await att.to_file())
                except Exception:
                    pass
            await webhook.send(
                content=new_content,
                username=message.author.display_name,
                avatar_url=message.author.display_avatar.url,
                embeds=message.embeds[:10],
                files=files,
                allowed_mentions=discord.AllowedMentions(
                    everyone=False, roles=False, users=True
                ),
            )
        except (discord.Forbidden, discord.HTTPException):
            pass

    # ── Commandes ─────────────────────────────────────────────────────────────

    @remplacer_group.command(name="ajouter", description="Ajouter une règle de remplacement")
    @app_commands.describe(
        mot="Le mot ou l'expression à remplacer (insensible à la casse)",
        remplacement="Ce par quoi le remplacer",
    )
    @app_commands.default_permissions(manage_guild=True)
    async def wr_add(self, interaction: discord.Interaction, mot: str, remplacement: str):
        mot = mot.strip().lower()
        remplacement = remplacement.strip()
        if not mot or not remplacement:
            await interaction.response.send_message("Le mot et le remplacement ne peuvent pas être vides.", ephemeral=True)
            return

        data = load_data()
        guild_cfg = data.setdefault(str(interaction.guild_id), {"enabled": True, "rules": {}})
        guild_cfg["rules"][mot] = remplacement
        save_data(data)

        embed = discord.Embed(title="✅ Règle ajoutée", color=discord.Color.green())
        embed.add_field(name="Mot banni", value=f"`{mot}`")
        embed.add_field(name="Remplacé par", value=f"`{remplacement}`")
        embed.set_footer(text="La règle s'applique immédiatement, sans distinction de casse.")
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @remplacer_group.command(name="retirer", description="Supprimer une règle de remplacement")
    @app_commands.describe(mot="Le mot dont vous souhaitez retirer la règle")
    @app_commands.default_permissions(manage_guild=True)
    async def wr_remove(self, interaction: discord.Interaction, mot: str):
        mot = mot.strip().lower()
        data = load_data()
        rules = data.get(str(interaction.guild_id), {}).get("rules", {})
        if mot not in rules:
            await interaction.response.send_message(f"Aucune règle trouvée pour `{mot}`.", ephemeral=True)
            return

        del rules[mot]
        save_data(data)
        await interaction.response.send_message(f"Règle pour `{mot}` supprimée.", ephemeral=True)

    @remplacer_group.command(name="liste", description="Voir toutes les règles de remplacement")
    @app_commands.default_permissions(manage_guild=True)
    async def wr_list(self, interaction: discord.Interaction):
        data = load_data()
        guild_cfg = data.get(str(interaction.guild_id), {})
        rules = guild_cfg.get("rules", {})

        if not rules:
            await interaction.response.send_message("Aucune règle configurée.", ephemeral=True)
            return

        statut = "✅ Activé" if guild_cfg.get("enabled", True) else "❌ Désactivé"
        embed = discord.Embed(
            title=f"Règles de remplacement — {statut}",
            color=discord.Color.blurple(),
        )
        lines = [f"`{banned}` → `{replacement}`" for banned, replacement in rules.items()]
        # Découpe en champs de 1024 caractères max
        chunk, chunks = [], []
        for line in lines:
            if sum(len(l) + 1 for l in chunk) + len(line) > 1020:
                chunks.append(chunk)
                chunk = []
            chunk.append(line)
        if chunk:
            chunks.append(chunk)

        for i, c in enumerate(chunks):
            embed.add_field(
                name=f"Règles {i + 1}" if len(chunks) > 1 else "Règles",
                value="\n".join(c),
                inline=False,
            )
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @remplacer_group.command(name="activer", description="Activer le remplacement automatique")
    @app_commands.default_permissions(manage_guild=True)
    async def wr_enable(self, interaction: discord.Interaction):
        data = load_data()
        data.setdefault(str(interaction.guild_id), {"enabled": True, "rules": {}})["enabled"] = True
        save_data(data)
        await interaction.response.send_message("✅ Remplacement automatique **activé**.", ephemeral=True)

    @remplacer_group.command(name="désactiver", description="Désactiver le remplacement automatique")
    @app_commands.default_permissions(manage_guild=True)
    async def wr_disable(self, interaction: discord.Interaction):
        data = load_data()
        data.setdefault(str(interaction.guild_id), {"enabled": True, "rules": {}})["enabled"] = False
        save_data(data)
        await interaction.response.send_message("❌ Remplacement automatique **désactivé**.", ephemeral=True)

    @remplacer_group.command(name="tester", description="Tester une phrase avec les règles actives")
    @app_commands.describe(phrase="La phrase à tester")
    @app_commands.default_permissions(manage_guild=True)
    async def wr_test(self, interaction: discord.Interaction, phrase: str):
        data = load_data()
        rules = data.get(str(interaction.guild_id), {}).get("rules", {})
        new_phrase, modified = apply_replacements(phrase, rules)

        embed = discord.Embed(title="Test de remplacement", color=discord.Color.orange())
        embed.add_field(name="Phrase originale", value=phrase, inline=False)
        embed.add_field(name="Après remplacement", value=new_phrase, inline=False)
        embed.set_footer(text="✅ Modifiée" if modified else "Aucun mot banni détecté")
        await interaction.response.send_message(embed=embed, ephemeral=True)


async def setup(bot: commands.Bot):
    cog = WordReplace(bot)
    bot.tree.add_command(remplacer_group)
    await bot.add_cog(cog)
