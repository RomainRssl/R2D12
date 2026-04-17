import json
import os
import datetime
import discord
from discord import app_commands
from discord.ext import commands

ECONOMY_FILE = "data/economy.json"
DAILY_AMOUNT = 200
DAILY_COOLDOWN_HOURS = 24


def load_data() -> dict:
    if not os.path.exists(ECONOMY_FILE):
        return {}
    with open(ECONOMY_FILE, "r", encoding="utf-8") as f:
        return json.load(f)


def save_data(data: dict):
    os.makedirs("data", exist_ok=True)
    with open(ECONOMY_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def get_guild(data: dict, guild_id: int) -> dict:
    return data.setdefault(str(guild_id), {"monnaie": "coins", "shop": [], "members": {}})


def get_member(guild_data: dict, user_id: int) -> dict:
    return guild_data["members"].setdefault(str(user_id), {"balance": 0, "last_daily": None, "inventaire": []})


class Economy(commands.Cog):
    """Économie virtuelle avec boutique et inventaire."""

    boutique_group = app_commands.Group(name="boutique", description="Boutique du serveur")

    def __init__(self, bot: commands.Bot):
        self.bot = bot

    @app_commands.command(name="argent", description="Voir votre solde ou celui d'un membre")
    @app_commands.describe(membre="Le membre dont voir le solde (vous par défaut)")
    async def argent(self, interaction: discord.Interaction, membre: discord.Member = None):
        membre = membre or interaction.user
        data = load_data()
        guild_data = get_guild(data, interaction.guild_id)
        member_data = get_member(guild_data, membre.id)
        monnaie = guild_data["monnaie"]
        embed = discord.Embed(title=f"Solde de {membre.display_name}", color=discord.Color.gold())
        embed.set_thumbnail(url=membre.display_avatar.url)
        embed.add_field(name="Solde", value=f"**{member_data['balance']}** {monnaie}")
        await interaction.response.send_message(embed=embed)

    @app_commands.command(name="daily", description="Réclamer votre récompense quotidienne")
    async def daily(self, interaction: discord.Interaction):
        data = load_data()
        guild_data = get_guild(data, interaction.guild_id)
        member_data = get_member(guild_data, interaction.user.id)
        monnaie = guild_data["monnaie"]

        now = datetime.datetime.utcnow()
        last = member_data.get("last_daily")
        if last:
            elapsed = now - datetime.datetime.fromisoformat(last)
            remaining = datetime.timedelta(hours=DAILY_COOLDOWN_HOURS) - elapsed
            if remaining.total_seconds() > 0:
                hours, rem = divmod(int(remaining.total_seconds()), 3600)
                minutes = rem // 60
                await interaction.response.send_message(
                    f"Vous avez déjà réclamé votre daily. Revenez dans **{hours}h {minutes}min**.",
                    ephemeral=True,
                )
                return

        member_data["balance"] += DAILY_AMOUNT
        member_data["last_daily"] = now.isoformat()
        save_data(data)
        embed = discord.Embed(
            title="Daily réclamé !",
            description=f"Vous avez reçu **{DAILY_AMOUNT} {monnaie}** !\nSolde : **{member_data['balance']} {monnaie}**",
            color=discord.Color.gold(),
        )
        await interaction.response.send_message(embed=embed)

    @app_commands.command(name="donner", description="Donner de l'argent à un membre")
    @app_commands.describe(membre="Le membre à qui donner", montant="Montant à donner")
    async def donner(self, interaction: discord.Interaction, membre: discord.Member, montant: app_commands.Range[int, 1, 1000000]):
        if membre == interaction.user:
            await interaction.response.send_message("Vous ne pouvez pas vous donner de l'argent à vous-même.", ephemeral=True)
            return
        if membre.bot:
            await interaction.response.send_message("Impossible de donner de l'argent à un bot.", ephemeral=True)
            return
        data = load_data()
        guild_data = get_guild(data, interaction.guild_id)
        sender = get_member(guild_data, interaction.user.id)
        receiver = get_member(guild_data, membre.id)
        monnaie = guild_data["monnaie"]

        if sender["balance"] < montant:
            await interaction.response.send_message(f"Solde insuffisant. Vous avez **{sender['balance']} {monnaie}**.", ephemeral=True)
            return

        sender["balance"] -= montant
        receiver["balance"] += montant
        save_data(data)
        embed = discord.Embed(
            title="Transfert effectué",
            description=f"{interaction.user.mention} a donné **{montant} {monnaie}** à {membre.mention}.",
            color=discord.Color.green(),
        )
        await interaction.response.send_message(embed=embed)

    @app_commands.command(name="classement-argent", description="Top 10 des membres les plus riches")
    async def rich_leaderboard(self, interaction: discord.Interaction):
        data = load_data()
        guild_data = get_guild(data, interaction.guild_id)
        members = guild_data.get("members", {})
        if not members:
            await interaction.response.send_message("Aucune donnée économique.", ephemeral=True)
            return
        sorted_members = sorted(members.items(), key=lambda x: x[1]["balance"], reverse=True)[:10]
        monnaie = guild_data["monnaie"]
        embed = discord.Embed(title=f"Classement — {monnaie}", color=discord.Color.gold())
        medals = ["🥇", "🥈", "🥉"]
        for i, (user_id, mdata) in enumerate(sorted_members):
            member = interaction.guild.get_member(int(user_id))
            name = member.display_name if member else f"ID {user_id}"
            prefix = medals[i] if i < 3 else f"`#{i+1}`"
            embed.add_field(name=f"{prefix} {name}", value=f"**{mdata['balance']}** {monnaie}", inline=False)
        await interaction.response.send_message(embed=embed)

    @app_commands.command(name="inventaire", description="Voir votre inventaire ou celui d'un membre")
    @app_commands.describe(membre="Le membre dont voir l'inventaire (vous par défaut)")
    async def inventaire(self, interaction: discord.Interaction, membre: discord.Member = None):
        membre = membre or interaction.user
        data = load_data()
        guild_data = get_guild(data, interaction.guild_id)
        member_data = get_member(guild_data, membre.id)
        inv = member_data.get("inventaire", [])
        embed = discord.Embed(title=f"Inventaire de {membre.display_name}", color=discord.Color.blurple())
        embed.set_thumbnail(url=membre.display_avatar.url)
        if inv:
            from collections import Counter
            counts = Counter(inv)
            embed.description = "\n".join(f"**{item}** x{count}" for item, count in counts.items())
        else:
            embed.description = "_Inventaire vide_"
        await interaction.response.send_message(embed=embed)

    # ── Boutique ──────────────────────────────────────────────────────────────

    @boutique_group.command(name="liste", description="Voir les articles de la boutique")
    async def shop_list(self, interaction: discord.Interaction):
        data = load_data()
        guild_data = get_guild(data, interaction.guild_id)
        shop = guild_data.get("shop", [])
        monnaie = guild_data["monnaie"]
        if not shop:
            await interaction.response.send_message("La boutique est vide.", ephemeral=True)
            return
        embed = discord.Embed(title="Boutique", color=discord.Color.gold())
        for item in shop:
            role = interaction.guild.get_role(item.get("role_id", 0)) if item.get("role_id") else None
            value = f"Prix : **{item['prix']} {monnaie}**\n{item['description']}"
            if role:
                value += f"\nRôle attribué : {role.mention}"
            embed.add_field(name=item["nom"], value=value, inline=False)
        await interaction.response.send_message(embed=embed)

    @boutique_group.command(name="ajouter", description="Ajouter un article à la boutique")
    @app_commands.describe(nom="Nom de l'article", prix="Prix en monnaie", description="Description", role="Rôle attribué à l'achat (optionnel)")
    @app_commands.default_permissions(manage_guild=True)
    async def shop_add(self, interaction: discord.Interaction, nom: str, prix: app_commands.Range[int, 1, 10000000], description: str, role: discord.Role = None):
        data = load_data()
        guild_data = get_guild(data, interaction.guild_id)
        guild_data.setdefault("shop", []).append({
            "nom": nom, "prix": prix, "description": description,
            "role_id": role.id if role else None,
        })
        save_data(data)
        await interaction.response.send_message(f"Article **{nom}** ajouté à la boutique.", ephemeral=True)

    @boutique_group.command(name="retirer", description="Retirer un article de la boutique")
    @app_commands.describe(nom="Nom de l'article à retirer")
    @app_commands.default_permissions(manage_guild=True)
    async def shop_remove(self, interaction: discord.Interaction, nom: str):
        data = load_data()
        guild_data = get_guild(data, interaction.guild_id)
        shop = guild_data.get("shop", [])
        new_shop = [i for i in shop if i["nom"].lower() != nom.lower()]
        if len(new_shop) == len(shop):
            await interaction.response.send_message(f"Article `{nom}` introuvable.", ephemeral=True)
            return
        guild_data["shop"] = new_shop
        save_data(data)
        await interaction.response.send_message(f"Article **{nom}** retiré.", ephemeral=True)

    @boutique_group.command(name="acheter", description="Acheter un article de la boutique")
    @app_commands.describe(nom="Nom de l'article à acheter")
    async def shop_buy(self, interaction: discord.Interaction, nom: str):
        data = load_data()
        guild_data = get_guild(data, interaction.guild_id)
        shop = guild_data.get("shop", [])
        monnaie = guild_data["monnaie"]

        item = next((i for i in shop if i["nom"].lower() == nom.lower()), None)
        if not item:
            await interaction.response.send_message(f"Article `{nom}` introuvable. Utilisez `/boutique liste`.", ephemeral=True)
            return

        member_data = get_member(guild_data, interaction.user.id)
        if member_data["balance"] < item["prix"]:
            await interaction.response.send_message(
                f"Solde insuffisant. Vous avez **{member_data['balance']} {monnaie}**, il en faut **{item['prix']}**.",
                ephemeral=True,
            )
            return

        member_data["balance"] -= item["prix"]
        member_data.setdefault("inventaire", []).append(item["nom"])
        save_data(data)

        if item.get("role_id"):
            role = interaction.guild.get_role(item["role_id"])
            if role:
                try:
                    await interaction.user.add_roles(role, reason=f"Achat boutique : {item['nom']}")
                except discord.Forbidden:
                    pass

        embed = discord.Embed(
            title="Achat effectué !",
            description=f"Vous avez acheté **{item['nom']}** pour **{item['prix']} {monnaie}**.\nSolde restant : **{member_data['balance']} {monnaie}**",
            color=discord.Color.green(),
        )
        await interaction.response.send_message(embed=embed)

    @shop_buy.autocomplete("nom")
    @shop_remove.autocomplete("nom")
    async def autocomplete_shop(self, interaction: discord.Interaction, current: str):
        data = load_data()
        shop = data.get(str(interaction.guild_id), {}).get("shop", [])
        return [
            app_commands.Choice(name=i["nom"], value=i["nom"])
            for i in shop if current.lower() in i["nom"].lower()
        ][:25]


async def setup(bot: commands.Bot):
    await bot.add_cog(Economy(bot))
