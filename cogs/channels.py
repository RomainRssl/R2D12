import discord
from discord import app_commands
from discord.ext import commands


class Channels(commands.Cog):
    """Création, modification et suppression de salons textuels et vocaux."""

    salon_group = app_commands.Group(name="salon", description="Gestion des salons du serveur")

    def __init__(self, bot: commands.Bot):
        self.bot = bot

    # ── Création ──────────────────────────────────────────────────────────────

    @salon_group.command(name="creer", description="Créer un salon textuel ou vocal")
    @app_commands.describe(
        type="Type de salon",
        nom="Nom du salon",
        categorie="Catégorie dans laquelle placer le salon (optionnel)",
        description="Description / sujet du salon (texte uniquement)",
        limite_membres="Limite d'utilisateurs simultanés (vocal uniquement, 0 = illimitée)",
        prive="Rendre le salon invisible pour @everyone",
    )
    @app_commands.choices(type=[
        app_commands.Choice(name="Textuel", value="texte"),
        app_commands.Choice(name="Vocal",   value="vocal"),
    ])
    @app_commands.default_permissions(manage_channels=True)
    async def channel_create(
        self,
        interaction: discord.Interaction,
        type: str,
        nom: str,
        categorie: discord.CategoryChannel = None,
        description: str = None,
        limite_membres: app_commands.Range[int, 0, 99] = 0,
        prive: bool = False,
    ):
        overwrites = {}
        if prive:
            overwrites[interaction.guild.default_role] = discord.PermissionOverwrite(view_channel=False)
            overwrites[interaction.guild.me] = discord.PermissionOverwrite(view_channel=True)

        try:
            if type == "texte":
                channel = await interaction.guild.create_text_channel(
                    name=nom,
                    category=categorie,
                    topic=description,
                    overwrites=overwrites,
                    reason=f"Créé par {interaction.user} via /salon creer",
                )
            else:
                channel = await interaction.guild.create_voice_channel(
                    name=nom,
                    category=categorie,
                    user_limit=limite_membres,
                    overwrites=overwrites,
                    reason=f"Créé par {interaction.user} via /salon creer",
                )
        except discord.Forbidden:
            await interaction.response.send_message("Je n'ai pas la permission de créer des salons.", ephemeral=True)
            return

        embed = discord.Embed(title="✅ Salon créé", color=discord.Color.green())
        embed.add_field(name="Salon", value=channel.mention)
        embed.add_field(name="Type", value="Textuel 💬" if type == "texte" else "Vocal 🔊")
        if categorie:
            embed.add_field(name="Catégorie", value=categorie.name)
        if description and type == "texte":
            embed.add_field(name="Description", value=description, inline=False)
        if type == "vocal" and limite_membres:
            embed.add_field(name="Limite", value=f"{limite_membres} membres")
        embed.add_field(name="Privé", value="Oui" if prive else "Non")
        embed.set_footer(text=f"ID : {channel.id}")
        await interaction.response.send_message(embed=embed)

    # ── Modification ──────────────────────────────────────────────────────────

    @salon_group.command(name="modifier", description="Modifier un salon existant")
    @app_commands.describe(
        salon="Le salon à modifier",
        nom="Nouveau nom",
        description="Nouveau sujet / description (salons textuels uniquement)",
        categorie="Déplacer vers une autre catégorie",
        limite_membres="Nouvelle limite de membres (vocaux, 0 = illimitée)",
        ralentissement="Délai entre messages en secondes (0 = désactivé, texte uniquement)",
        prive="Rendre visible ou invisible pour @everyone",
    )
    @app_commands.default_permissions(manage_channels=True)
    async def channel_edit(
        self,
        interaction: discord.Interaction,
        salon: discord.abc.GuildChannel,
        nom: str = None,
        description: str = None,
        categorie: discord.CategoryChannel = None,
        limite_membres: app_commands.Range[int, 0, 99] = None,
        ralentissement: app_commands.Range[int, 0, 21600] = None,
        prive: bool = None,
    ):
        if not isinstance(salon, (discord.TextChannel, discord.VoiceChannel)):
            await interaction.response.send_message(
                "Seuls les salons textuels et vocaux peuvent être modifiés via cette commande.", ephemeral=True
            )
            return

        kwargs = {}
        if nom:
            kwargs["name"] = nom
        if categorie is not None:
            kwargs["category"] = categorie
        if isinstance(salon, discord.TextChannel):
            if description is not None:
                kwargs["topic"] = description
            if ralentissement is not None:
                kwargs["slowmode_delay"] = ralentissement
        if isinstance(salon, discord.VoiceChannel) and limite_membres is not None:
            kwargs["user_limit"] = limite_membres

        if not kwargs and prive is None:
            await interaction.response.send_message("Aucune modification spécifiée.", ephemeral=True)
            return

        try:
            if prive is not None:
                overwrite = salon.overwrites_for(interaction.guild.default_role)
                overwrite.view_channel = not prive
                await salon.set_permissions(
                    interaction.guild.default_role,
                    overwrite=overwrite,
                    reason=f"Visibilité modifiée par {interaction.user}",
                )
            if kwargs:
                await salon.edit(reason=f"Modifié par {interaction.user} via /salon modifier", **kwargs)
        except discord.Forbidden:
            await interaction.response.send_message("Je n'ai pas la permission de modifier ce salon.", ephemeral=True)
            return

        embed = discord.Embed(title="✅ Salon modifié", color=discord.Color.blurple())
        embed.add_field(name="Salon", value=salon.mention)
        if nom:
            embed.add_field(name="Nouveau nom", value=nom)
        if description is not None and isinstance(salon, discord.TextChannel):
            embed.add_field(name="Description", value=description or "_(effacée)_", inline=False)
        if categorie:
            embed.add_field(name="Catégorie", value=categorie.name)
        if limite_membres is not None and isinstance(salon, discord.VoiceChannel):
            embed.add_field(name="Limite", value=f"{limite_membres} membres" if limite_membres else "Illimitée")
        if ralentissement is not None and isinstance(salon, discord.TextChannel):
            embed.add_field(name="Ralentissement", value=f"{ralentissement}s" if ralentissement else "Désactivé")
        if prive is not None:
            embed.add_field(name="Privé", value="Oui" if prive else "Non")
        await interaction.response.send_message(embed=embed)

    # ── Suppression ───────────────────────────────────────────────────────────

    @salon_group.command(name="supprimer", description="Supprimer un salon")
    @app_commands.describe(salon="Le salon à supprimer", raison="Raison de la suppression (optionnel)")
    @app_commands.default_permissions(manage_channels=True)
    async def channel_delete(
        self,
        interaction: discord.Interaction,
        salon: discord.abc.GuildChannel,
        raison: str = None,
    ):
        if salon.id == interaction.channel_id:
            await interaction.response.send_message(
                "Impossible de supprimer le salon dans lequel vous utilisez cette commande.", ephemeral=True
            )
            return

        nom = salon.name
        try:
            await salon.delete(reason=f"Supprimé par {interaction.user}" + (f" — {raison}" if raison else ""))
        except discord.Forbidden:
            await interaction.response.send_message("Je n'ai pas la permission de supprimer ce salon.", ephemeral=True)
            return

        await interaction.response.send_message(f"✅ Salon **#{nom}** supprimé.", ephemeral=True)

    # ── Liste ─────────────────────────────────────────────────────────────────

    @salon_group.command(name="liste", description="Voir tous les salons du serveur")
    async def channel_list(self, interaction: discord.Interaction):
        text_channels = interaction.guild.text_channels
        voice_channels = interaction.guild.voice_channels

        embed = discord.Embed(
            title=f"Salons du serveur ({len(text_channels)} textuels, {len(voice_channels)} vocaux)",
            color=discord.Color.blurple(),
        )

        if text_channels:
            lines = [f"{ch.mention}" for ch in text_channels[:25]]
            if len(text_channels) > 25:
                lines.append(f"_… et {len(text_channels) - 25} autres_")
            embed.add_field(name="💬 Textuels", value="\n".join(lines), inline=True)

        if voice_channels:
            limit = lambda ch: f" ({ch.user_limit})" if ch.user_limit else ""
            lines = [f"🔊 {ch.name}{limit(ch)}" for ch in voice_channels[:25]]
            if len(voice_channels) > 25:
                lines.append(f"_… et {len(voice_channels) - 25} autres_")
            embed.add_field(name="🔊 Vocaux", value="\n".join(lines), inline=True)

        await interaction.response.send_message(embed=embed, ephemeral=True)


async def setup(bot: commands.Bot):
    await bot.add_cog(Channels(bot))
