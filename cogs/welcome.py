import json
import os
import discord
from discord import app_commands
from discord.ext import commands

WELCOME_FILE = "data/welcome.json"

DEFAULT_MESSAGE = (
    "Bienvenue sur **{server}**, {mention} ! \n"
    "Tu es notre **{count}e** membre. N'hésite pas à te présenter !"
)


def load_welcome() -> dict:
    if not os.path.exists(WELCOME_FILE):
        return {}
    with open(WELCOME_FILE, "r", encoding="utf-8") as f:
        return json.load(f)


def save_welcome(data: dict):
    os.makedirs("data", exist_ok=True)
    with open(WELCOME_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def format_welcome(message: str, member: discord.Member) -> str:
    return message.format(
        mention=member.mention,
        name=member.display_name,
        username=member.name,
        server=member.guild.name,
        count=member.guild.member_count,
    )


welcome_group = app_commands.Group(
    name="bienvenue",
    description="Configuration du message de bienvenue pour les nouveaux membres",
)


class Welcome(commands.Cog):
    """Message automatique pour les nouveaux arrivants."""

    def __init__(self, bot: commands.Bot):
        self.bot = bot

    @commands.Cog.listener()
    async def on_member_join(self, member: discord.Member):
        data = load_welcome()
        config = data.get(str(member.guild.id))
        if not config or not config.get("enabled", True):
            return

        channel = member.guild.get_channel(config["channel_id"])
        if not channel:
            return

        message = config.get("message", DEFAULT_MESSAGE)
        text = format_welcome(message, member)

        embed = discord.Embed(description=text, color=discord.Color.green())
        if member.avatar:
            embed.set_thumbnail(url=member.display_avatar.url)
        embed.set_footer(text=f"{member.guild.name} • {member.guild.member_count} membres")

        await channel.send(embed=embed)

    @welcome_group.command(name="configurer", description="Définir le salon et le message de bienvenue")
    @app_commands.describe(
        salon="Salon où envoyer le message de bienvenue",
        message=(
            "Message de bienvenue. "
            "Variables : {mention} {name} {username} {server} {count}"
        ),
    )
    @app_commands.default_permissions(manage_guild=True)
    async def welcome_set(
        self,
        interaction: discord.Interaction,
        salon: discord.TextChannel,
        message: str = DEFAULT_MESSAGE,
    ):
        data = load_welcome()
        data[str(interaction.guild_id)] = {
            "channel_id": salon.id,
            "message": message,
            "enabled": True,
        }
        save_welcome(data)

        embed = discord.Embed(
            title="Bienvenue configuré",
            color=discord.Color.green(),
        )
        embed.add_field(name="Salon", value=salon.mention, inline=True)
        embed.add_field(name="Activé", value="Oui", inline=True)
        embed.add_field(
            name="Variables disponibles",
            value="`{mention}` `{name}` `{username}` `{server}` `{count}`",
            inline=False,
        )
        embed.add_field(name="Message", value=message[:500], inline=False)
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @welcome_group.command(name="tester", description="Simuler un message de bienvenue pour vous-même")
    async def welcome_test(self, interaction: discord.Interaction):
        data = load_welcome()
        config = data.get(str(interaction.guild_id))

        if not config:
            await interaction.response.send_message(
                "Aucun message de bienvenue configuré. Utilisez `/bienvenue configurer` d'abord.",
                ephemeral=True,
            )
            return

        channel = interaction.guild.get_channel(config["channel_id"])
        message = config.get("message", DEFAULT_MESSAGE)
        text = format_welcome(message, interaction.user)

        embed = discord.Embed(description=text, color=discord.Color.green())
        if interaction.user.avatar:
            embed.set_thumbnail(url=interaction.user.display_avatar.url)
        embed.set_footer(
            text=f"[TEST] {interaction.guild.name} • {interaction.guild.member_count} membres"
        )

        await interaction.response.send_message(
            f"Aperçu du message de bienvenue (salon cible : {channel.mention if channel else '`introuvable`'}) :",
            embed=embed,
            ephemeral=True,
        )

    @welcome_group.command(name="désactiver", description="Désactiver les messages de bienvenue")
    @app_commands.default_permissions(manage_guild=True)
    async def welcome_disable(self, interaction: discord.Interaction):
        data = load_welcome()
        guild_key = str(interaction.guild_id)

        if guild_key not in data:
            await interaction.response.send_message(
                "Aucun message de bienvenue configuré.", ephemeral=True
            )
            return

        data[guild_key]["enabled"] = False
        save_welcome(data)
        await interaction.response.send_message(
            "Messages de bienvenue désactivés. Utilisez `/bienvenue configurer` pour les réactiver.",
            ephemeral=True,
        )

    @welcome_group.command(name="statut", description="Voir la configuration actuelle des messages de bienvenue")
    async def welcome_status(self, interaction: discord.Interaction):
        data = load_welcome()
        config = data.get(str(interaction.guild_id))

        if not config:
            await interaction.response.send_message(
                "Aucun message de bienvenue configuré.", ephemeral=True
            )
            return

        channel = interaction.guild.get_channel(config["channel_id"])
        embed = discord.Embed(title="Configuration bienvenue", color=discord.Color.blurple())
        embed.add_field(name="Salon", value=channel.mention if channel else "`introuvable`", inline=True)
        embed.add_field(name="Activé", value="Oui" if config.get("enabled", True) else "Non", inline=True)
        embed.add_field(name="Message", value=config.get("message", DEFAULT_MESSAGE)[:500], inline=False)
        await interaction.response.send_message(embed=embed, ephemeral=True)


async def setup(bot: commands.Bot):
    cog = Welcome(bot)
    bot.tree.add_command(welcome_group)
    await bot.add_cog(cog)
