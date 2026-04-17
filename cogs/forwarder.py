import json
import os
import discord
from discord import app_commands
from discord.ext import commands

FORWARDER_FILE = "data/forwarder.json"


def load_data() -> dict:
    if not os.path.exists(FORWARDER_FILE):
        return {}
    with open(FORWARDER_FILE, "r", encoding="utf-8") as f:
        return json.load(f)


def save_data(data: dict):
    os.makedirs("data", exist_ok=True)
    with open(FORWARDER_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


async def get_or_create_webhook(channel: discord.TextChannel, bot_name: str) -> discord.Webhook:
    """Récupère ou crée un webhook R2D12 dans le salon de destination."""
    webhooks = await channel.webhooks()
    for wh in webhooks:
        if wh.name == f"R2D12-Relais":
            return wh
    return await channel.create_webhook(name="R2D12-Relais")


class Forwarder(commands.Cog):
    """Reposte automatiquement les messages d'un salon externe vers un salon local."""

    relais_group = app_commands.Group(name="relais", description="Relais automatique de messages depuis un autre serveur")

    def __init__(self, bot: commands.Bot):
        self.bot = bot
        # Cache : source_channel_id -> liste de configs
        self._cache: dict[int, list[dict]] = {}
        self._build_cache()

    def _build_cache(self):
        self._cache.clear()
        data = load_data()
        for guild_id, relays in data.items():
            for relay in relays:
                src = int(relay["source_channel_id"])
                self._cache.setdefault(src, []).append({**relay, "dest_guild_id": guild_id})

    # ── Event principal ───────────────────────────────────────────────────────

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message):
        if message.author.bot and not message.webhook_id:
            return
        if not message.guild:
            return

        relays = self._cache.get(message.channel.id)
        if not relays:
            return

        for relay in relays:
            dest_guild = self.bot.get_guild(int(relay["dest_guild_id"]))
            if not dest_guild:
                continue
            dest_channel = dest_guild.get_channel(int(relay["dest_channel_id"]))
            if not dest_channel:
                continue

            try:
                await self._forward(message, dest_channel, relay)
            except (discord.Forbidden, discord.HTTPException):
                pass

    async def _forward(self, message: discord.Message, dest: discord.TextChannel, relay: dict):
        """Reposte le message via webhook (préserve nom + avatar de l'auteur)."""
        webhook = await get_or_create_webhook(dest, self.bot.user.name)

        # Fichiers joints
        files = []
        for att in message.attachments:
            try:
                files.append(await att.to_file())
            except Exception:
                pass

        # Embeds (on les transmet tels quels)
        embeds = message.embeds[:10]

        # Contenu texte
        content = message.content or None

        # Ajout d'un en-tête discret si configuré
        if relay.get("show_source"):
            source_channel = self.bot.get_channel(int(relay["source_channel_id"]))
            source_guild = message.guild
            header = f"-# 📡 Relayé depuis **{source_guild.name}**" + (f" — #{source_channel.name}" if source_channel else "")
            content = f"{header}\n{content}" if content else header

        await webhook.send(
            content=content,
            username=message.author.display_name,
            avatar_url=message.author.display_avatar.url,
            embeds=embeds,
            files=files,
            allowed_mentions=discord.AllowedMentions.none(),
        )

    # ── Commandes ─────────────────────────────────────────────────────────────

    @relais_group.command(name="configurer", description="Configurer un relais depuis un salon d'un autre serveur")
    @app_commands.describe(
        source_guild_id="ID du serveur source (clic droit sur le serveur → Copier l'identifiant)",
        source_channel_id="ID du salon source (clic droit sur le salon → Copier l'identifiant)",
        destination="Salon de ce serveur où reposer les messages",
        afficher_source="Afficher une mention discrète du serveur source sous chaque message",
    )
    @app_commands.default_permissions(manage_guild=True)
    async def relais_set(
        self,
        interaction: discord.Interaction,
        source_guild_id: str,
        source_channel_id: str,
        destination: discord.TextChannel,
        afficher_source: bool = True,
    ):
        if not source_guild_id.isdigit() or not source_channel_id.isdigit():
            await interaction.response.send_message("Les IDs doivent être des nombres. Clic droit → Copier l'identifiant.", ephemeral=True)
            return

        # Vérifier que le bot est dans le serveur source
        source_guild = self.bot.get_guild(int(source_guild_id))
        if not source_guild:
            await interaction.response.send_message(
                "Le bot n'est pas membre de ce serveur. Invitez-le d'abord sur le serveur source.",
                ephemeral=True,
            )
            return

        source_channel = source_guild.get_channel(int(source_channel_id))
        if not source_channel:
            await interaction.response.send_message(
                f"Salon `{source_channel_id}` introuvable sur **{source_guild.name}**. Vérifiez l'ID.",
                ephemeral=True,
            )
            return

        # Vérifier les permissions d'écriture dans la destination
        if not destination.permissions_for(interaction.guild.me).manage_webhooks:
            await interaction.response.send_message(
                f"Je n'ai pas la permission de gérer les webhooks dans {destination.mention}.",
                ephemeral=True,
            )
            return

        data = load_data()
        guild_key = str(interaction.guild_id)
        relays = data.setdefault(guild_key, [])

        # Éviter les doublons
        for relay in relays:
            if relay["source_channel_id"] == source_channel_id and relay["dest_channel_id"] == str(destination.id):
                await interaction.response.send_message("Ce relais est déjà configuré.", ephemeral=True)
                return

        relays.append({
            "source_guild_id": source_guild_id,
            "source_channel_id": source_channel_id,
            "dest_channel_id": str(destination.id),
            "show_source": afficher_source,
        })
        save_data(data)
        self._build_cache()

        embed = discord.Embed(title="✅ Relais configuré", color=discord.Color.green())
        embed.add_field(name="Serveur source", value=f"**{source_guild.name}**")
        embed.add_field(name="Salon source", value=f"#{source_channel.name}")
        embed.add_field(name="Destination", value=destination.mention)
        embed.add_field(name="Afficher la source", value="Oui" if afficher_source else "Non")
        embed.set_footer(text="Les prochains messages dans ce salon seront automatiquement repostés.")
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @relais_group.command(name="liste", description="Voir tous les relais configurés")
    @app_commands.default_permissions(manage_guild=True)
    async def relais_list(self, interaction: discord.Interaction):
        data = load_data()
        relays = data.get(str(interaction.guild_id), [])

        if not relays:
            await interaction.response.send_message("Aucun relais configuré.", ephemeral=True)
            return

        embed = discord.Embed(title="Relais actifs", color=discord.Color.blurple())
        for i, relay in enumerate(relays, 1):
            src_guild = self.bot.get_guild(int(relay["source_guild_id"]))
            src_channel = src_guild.get_channel(int(relay["source_channel_id"])) if src_guild else None
            dest_channel = interaction.guild.get_channel(int(relay["dest_channel_id"]))

            src_label = f"**{src_guild.name}** — #{src_channel.name}" if src_guild and src_channel else f"ID {relay['source_channel_id']}"
            dest_label = dest_channel.mention if dest_channel else f"ID {relay['dest_channel_id']}"

            embed.add_field(
                name=f"Relais #{i}",
                value=f"📥 Source : {src_label}\n📤 Destination : {dest_label}",
                inline=False,
            )
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @relais_group.command(name="supprimer", description="Supprimer un relais")
    @app_commands.describe(numero="Numéro du relais (voir /relais liste)")
    @app_commands.default_permissions(manage_guild=True)
    async def relais_delete(self, interaction: discord.Interaction, numero: app_commands.Range[int, 1, 50]):
        data = load_data()
        guild_key = str(interaction.guild_id)
        relays = data.get(guild_key, [])

        if numero > len(relays):
            await interaction.response.send_message(f"Relais #{numero} introuvable.", ephemeral=True)
            return

        removed = relays.pop(numero - 1)
        save_data(data)
        self._build_cache()

        src_guild = self.bot.get_guild(int(removed["source_guild_id"]))
        name = src_guild.name if src_guild else f"ID {removed['source_guild_id']}"
        await interaction.response.send_message(f"Relais #{numero} (depuis **{name}**) supprimé.", ephemeral=True)

    @relais_group.command(name="tester", description="Envoyer un message de test dans la destination d'un relais")
    @app_commands.describe(numero="Numéro du relais à tester")
    @app_commands.default_permissions(manage_guild=True)
    async def relais_test(self, interaction: discord.Interaction, numero: app_commands.Range[int, 1, 50]):
        data = load_data()
        relays = data.get(str(interaction.guild_id), [])

        if numero > len(relays):
            await interaction.response.send_message(f"Relais #{numero} introuvable.", ephemeral=True)
            return

        relay = relays[numero - 1]
        dest = interaction.guild.get_channel(int(relay["dest_channel_id"]))
        if not dest:
            await interaction.response.send_message("Le salon de destination est introuvable.", ephemeral=True)
            return

        try:
            webhook = await get_or_create_webhook(dest, self.bot.user.name)
            src_guild = self.bot.get_guild(int(relay["source_guild_id"]))
            embed = discord.Embed(
                description="Ceci est un message de test pour vérifier que le relais fonctionne correctement.",
                color=discord.Color.blurple(),
            )
            embed.set_footer(text=f"Relais #{numero} — Source : {src_guild.name if src_guild else 'Inconnu'}")
            await webhook.send(
                content="-# 📡 [TEST] Message de vérification du relais",
                username=interaction.user.display_name,
                avatar_url=interaction.user.display_avatar.url,
                embed=embed,
            )
            await interaction.response.send_message(f"Message de test envoyé dans {dest.mention}.", ephemeral=True)
        except (discord.Forbidden, discord.HTTPException) as e:
            await interaction.response.send_message(f"Erreur : {e}", ephemeral=True)


async def setup(bot: commands.Bot):
    await bot.add_cog(Forwarder(bot))
