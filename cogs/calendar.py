import os
import json
import re
import unicodedata
import logging
import aiohttp
from datetime import datetime
from zoneinfo import ZoneInfo
from discord.ext import commands, tasks
import discord
from bs4 import BeautifulSoup

logger = logging.getLogger(__name__)

SITE_URL = os.getenv("RACES_SITE_URL", "https://paramourduspin.fun")
RACES_CHANNEL_ID = int(os.getenv("RACES_CHANNEL_ID", "0"))
RACES_CATEGORY_ID = int(os.getenv("RACES_CATEGORY_ID", "1399427481945247817"))
RACES_STAFF_ROLE_ID = int(os.getenv("RACES_STAFF_ROLE_ID", "1424791316881211412"))
DATA_FILE = "data/known_races.json"
DATA_MESSAGES = "data/race_messages.json"
DATA_REGISTRATIONS = "data/race_registrations.json"
PARIS = ZoneInfo("Europe/Paris")
TAG_COLORS = ("text-blue-400", "text-green-400", "text-orange-400")


def _slugify(text: str) -> str:
    text = unicodedata.normalize("NFD", text)
    text = text.encode("ascii", "ignore").decode("ascii")
    text = re.sub(r"[^\w\s-]", "", text.lower())
    return re.sub(r"[-\s]+", "-", text).strip("-")


def _clean_class_name(name: str) -> str:
    """Retire les suffixes parasites comme '(toute classe)'."""
    name = re.sub(r"\(.*?\)", "", name).strip()
    return name


# ── Helpers registrations (standalone pour les callbacks) ────────

def _load_registrations() -> dict:
    try:
        with open(DATA_REGISTRATIONS) as f:
            return json.load(f)
    except FileNotFoundError:
        return {}


def _save_registrations(data: dict):
    os.makedirs("data", exist_ok=True)
    with open(DATA_REGISTRATIONS, "w") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def _build_class_embed(title: str, classes_data: dict) -> discord.Embed:
    """Construit l'embed de sélection de classe style Apollo."""
    total = sum(len(v) for v in classes_data.values())
    embed = discord.Embed(
        title=f"🏁 {title}",
        description=(
            "Choisissez votre classe en cliquant sur le bouton correspondant.\n"
            "Cliquez à nouveau sur votre classe pour vous désinscrire."
        ),
        color=0xE63946,
    )
    for class_name, members in classes_data.items():
        count = len(members)
        if members:
            value = "\n".join(f"• {m['name']}" for m in members)
        else:
            value = "*Aucun inscrit*"
        embed.add_field(
            name=f"🏎️ {class_name} ({count})",
            value=value,
            inline=True,
        )
    embed.set_footer(text=f"Par amour du spin · {total} pilote(s) inscrit(s)")
    return embed


# ── Bouton classe ─────────────────────────────────────────────────

class ClassButton(discord.ui.Button):
    def __init__(self, class_name: str, channel_id: int):
        super().__init__(
            label=class_name[:80],
            style=discord.ButtonStyle.secondary,
            custom_id=f"cls_{channel_id}_{_slugify(class_name)}",
        )
        self.class_name = class_name
        self.channel_id = channel_id

    async def callback(self, interaction: discord.Interaction):
        regs = _load_registrations()
        key = str(self.channel_id)

        if key not in regs:
            await interaction.response.send_message(
                "Données de course introuvables.", ephemeral=True
            )
            return

        data = regs[key]
        uid = str(interaction.user.id)

        # Vérifier si déjà dans cette classe
        already_here = any(
            m["id"] == uid for m in data["classes"].get(self.class_name, [])
        )

        # Retirer de toutes les classes
        for cls in data["classes"]:
            data["classes"][cls] = [
                m for m in data["classes"][cls] if m["id"] != uid
            ]

        if already_here:
            # Désinscription
            msg_text = f"❌ Vous avez été désinscrit de **{self.class_name}**."
        else:
            # Inscription dans la nouvelle classe
            if self.class_name not in data["classes"]:
                data["classes"][self.class_name] = []
            data["classes"][self.class_name].append(
                {"id": uid, "name": interaction.user.display_name}
            )
            msg_text = f"✅ Inscrit en **{self.class_name}** !"

        _save_registrations(regs)

        # Mettre à jour le message dans le channel
        try:
            channel = interaction.guild.get_channel(self.channel_id)
            if channel and data.get("message_id"):
                msg = await channel.fetch_message(int(data["message_id"]))
                await msg.edit(
                    embed=_build_class_embed(data["title"], data["classes"])
                )
        except Exception as e:
            logger.warning("Impossible de mettre à jour le message de classe : %s", e)

        await interaction.response.send_message(msg_text, ephemeral=True)


class ClassRegistrationView(discord.ui.View):
    def __init__(self, class_names: list, channel_id: int):
        super().__init__(timeout=None)
        for name in class_names[:5]:
            self.add_item(ClassButton(name, channel_id))


# ── Bouton inscription simple ─────────────────────────────────────

class RaceButton(discord.ui.Button):
    def __init__(self, race_title: str, role_id: int):
        super().__init__(
            label=f"Inscription {race_title}",
            style=discord.ButtonStyle.primary,
            custom_id=f"race_register_{role_id}",
        )
        self.role_id = role_id

    async def callback(self, interaction: discord.Interaction):
        role = interaction.guild.get_role(self.role_id)
        if not role:
            await interaction.response.send_message("Rôle introuvable.", ephemeral=True)
            return
        if role in interaction.user.roles:
            await interaction.user.remove_roles(role)
            await interaction.response.send_message(
                f"❌ Désinscrit de **{role.name}**.", ephemeral=True
            )
        else:
            await interaction.user.add_roles(role)
            await interaction.response.send_message(
                f"✅ Inscrit pour **{role.name}** !", ephemeral=True
            )


class RaceRegistrationView(discord.ui.View):
    def __init__(self, race_title: str, role_id: int):
        super().__init__(timeout=None)
        self.add_item(RaceButton(race_title, role_id))


# ── Cog principal ─────────────────────────────────────────────────

class Calendar(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.check_new_races.start()

    def cog_unload(self):
        self.check_new_races.cancel()

    @commands.Cog.listener()
    async def on_ready(self):
        # Restaurer les boutons d'inscription simples
        for msg_id, data in self._load_messages().items():
            view = RaceRegistrationView(data["title"], data["role_id"])
            self.bot.add_view(view, message_id=int(msg_id))

        # Restaurer les vues de sélection de classe
        for key, data in _load_registrations().items():
            classes = list(data.get("classes", {}).keys())
            if classes and data.get("message_id"):
                view = ClassRegistrationView(classes, int(key))
                self.bot.add_view(view, message_id=int(data["message_id"]))

    # ── Known races ───────────────────────────────────────────────

    def _load_known(self) -> set | None:
        try:
            with open(DATA_FILE) as f:
                return set(json.load(f).get("known_ids", []))
        except FileNotFoundError:
            return None

    def _save_known(self, ids: set):
        with open(DATA_FILE, "w") as f:
            json.dump({"known_ids": list(ids)}, f)

    # ── Message mapping ───────────────────────────────────────────

    def _load_messages(self) -> dict:
        try:
            with open(DATA_MESSAGES) as f:
                return json.load(f)
        except FileNotFoundError:
            return {}

    def _save_message(self, message_id: str, data: dict):
        messages = self._load_messages()
        messages[message_id] = data
        with open(DATA_MESSAGES, "w") as f:
            json.dump(messages, f)

    # ── HTML scraping ─────────────────────────────────────────────

    def _parse_races(self, html: str) -> list:
        soup = BeautifulSoup(html, "html.parser")

        og_image = soup.find("meta", property="og:image")
        og_image_url = og_image.get("content") if og_image else None

        races = []
        for article in soup.find_all("article"):
            time_el = article.find("time")
            if not time_el or not time_el.get("datetime"):
                continue
            title_el = article.find("h3")
            desc_el = article.find("p", class_=lambda c: c and "line-clamp-2" in c)
            tag_els = article.find_all(
                "span",
                class_=lambda c: c and any(color in c for color in TAG_COLORS),
            )
            img_el = article.find("img")
            image_url = None
            if img_el:
                src = img_el.get("src") or img_el.get("data-src") or ""
                if src:
                    image_url = src if src.startswith("http") else f"{SITE_URL}{src}"
            if not image_url:
                image_url = og_image_url

            raw_tags = [t.get_text(strip=True) for t in tag_els]
            # Nettoyer les noms de classe (retire "(toute classe)" etc.)
            classes = [_clean_class_name(t) for t in raw_tags if _clean_class_name(t)]

            races.append({
                "id": time_el["datetime"],
                "title": title_el.get_text(strip=True) if title_el else "?",
                "date": time_el["datetime"],
                "tags": raw_tags,
                "classes": classes,
                "description": desc_el.get_text(strip=True) if desc_el else "",
                "image": image_url,
            })
        return races

    # ── Annonce ───────────────────────────────────────────────────

    async def _announce_race(self, race: dict):
        try:
            channel = await self.bot.fetch_channel(RACES_CHANNEL_ID)
        except (discord.NotFound, discord.Forbidden) as e:
            logger.error("Impossible de trouver le channel %s : %s", RACES_CHANNEL_ID, e)
            return

        guild = channel.guild
        role = await guild.create_role(name=race["title"], mentionable=True)

        category = guild.get_channel(RACES_CATEGORY_ID)
        overwrites = {
            guild.default_role: discord.PermissionOverwrite(view_channel=False),
            role: discord.PermissionOverwrite(
                view_channel=True, send_messages=True, read_message_history=True
            ),
        }
        staff_role = guild.get_role(RACES_STAFF_ROLE_ID)
        if staff_role:
            overwrites[staff_role] = discord.PermissionOverwrite(
                view_channel=True, send_messages=True, read_message_history=True
            )
        race_channel = await guild.create_text_channel(
            name=_slugify(race["title"]),
            category=category,
            overwrites=overwrites,
        )

        # Annonce dans le channel principal
        view = RaceRegistrationView(race["title"], role.id)
        msg = await channel.send(embed=self._build_embed(race, race_channel), view=view)

        self._save_message(str(msg.id), {
            "role_id": role.id,
            "channel_id": race_channel.id,
            "title": race["title"],
        })

        # Sélection de classe dans le channel privé (si multiclasse)
        classes = race.get("classes", [])
        if len(classes) >= 2:
            await self._post_class_selection(race_channel, race, classes)

    async def _post_class_selection(
        self,
        channel: discord.TextChannel,
        race: dict,
        classes: list,
    ):
        """Poste le message de sélection de classe dans le channel privé de la course."""
        classes = [c for c in classes if c][:5]
        classes_data = {c: [] for c in classes}
        view = ClassRegistrationView(classes, channel.id)
        msg = await channel.send(
            content="@here Choisissez votre classe ci-dessous :",
            embed=_build_class_embed(race["title"], classes_data),
            view=view,
        )
        regs = _load_registrations()
        regs[str(channel.id)] = {
            "title": race["title"],
            "message_id": str(msg.id),
            "classes": classes_data,
        }
        _save_registrations(regs)

    # ── Tâche planifiée ───────────────────────────────────────────

    @tasks.loop(minutes=5)
    async def check_new_races(self):
        if not RACES_CHANNEL_ID:
            return
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(
                    SITE_URL, timeout=aiohttp.ClientTimeout(total=10)
                ) as resp:
                    html = await resp.text()
        except Exception as e:
            logger.error("Impossible de joindre %s : %s", SITE_URL, e)
            return

        races = self._parse_races(html)
        known = self._load_known()
        current_ids = {r["id"] for r in races}

        if known is None:
            self._save_known(current_ids)
            return

        new_races = [r for r in races if r["id"] not in known]
        if not new_races:
            return

        for race in new_races:
            try:
                await self._announce_race(race)
            except Exception as e:
                logger.error("Erreur lors de l'annonce de '%s' : %s", race.get("title"), e)
                continue
            known.add(race["id"])

        self._save_known(known)

    @check_new_races.before_loop
    async def before_check(self):
        await self.bot.wait_until_ready()

    # ── Commandes admin ───────────────────────────────────────────

    def _is_admin(self, user: discord.Member) -> bool:
        return user.guild_permissions.administrator or any(
            r.id == RACES_STAFF_ROLE_ID for r in user.roles
        )

    @discord.app_commands.command(
        name="coursediag",
        description="Diagnostique le système d'annonces de courses",
    )
    async def course_diagnostic(self, interaction: discord.Interaction):
        if not self._is_admin(interaction.user):
            await interaction.response.send_message(
                "Commande réservée aux administrateurs.", ephemeral=True
            )
            return
        await interaction.response.defer(ephemeral=True)
        lines = []

        lines.append(f"**RACES_CHANNEL_ID** : `{RACES_CHANNEL_ID}`")
        if RACES_CHANNEL_ID:
            try:
                ch = await self.bot.fetch_channel(RACES_CHANNEL_ID)
                lines.append(f"Channel trouvé : {ch.mention}")
            except Exception as e:
                lines.append(f"Channel **introuvable** : {e}")
        else:
            lines.append("Channel **non configuré** — définir `RACES_CHANNEL_ID` dans `.env`")

        lines.append(f"\n**Site** : `{SITE_URL}`")
        try:
            async with aiohttp.ClientSession() as s:
                async with s.get(SITE_URL, timeout=aiohttp.ClientTimeout(total=10)) as r:
                    html = await r.text()
            races = self._parse_races(html)
            lines.append(f"Site accessible — {len(races)} course(s) trouvée(s)")
            known = self._load_known() or set()
            new = [r for r in races if r["id"] not in known]
            lines.append(f"Courses connues : {len(known)} | Nouvelles : **{len(new)}**")
            for r in races:
                status = "✅ connue" if r["id"] in known else "🆕 nouvelle"
                classes_str = ", ".join(r["classes"]) if r["classes"] else "*aucune classe détectée*"
                lines.append(f"  • **{r['title']}** — {status}")
                lines.append(f"    Classes : {classes_str}")
        except Exception as e:
            lines.append(f"Site **inaccessible** : {e}")

        await interaction.followup.send("\n".join(lines), ephemeral=True)

    @discord.app_commands.command(
        name="coursereset",
        description="Réinitialise la liste des courses connues (force les annonces)",
    )
    async def course_reset(self, interaction: discord.Interaction):
        if not self._is_admin(interaction.user):
            await interaction.response.send_message(
                "Commande réservée aux administrateurs.", ephemeral=True
            )
            return
        if os.path.exists(DATA_FILE):
            os.remove(DATA_FILE)
            await interaction.response.send_message(
                "Liste réinitialisée. Au prochain scan (≤5 min), toutes les courses actuelles seront annoncées.",
                ephemeral=True,
            )
        else:
            await interaction.response.send_message(
                "Aucun fichier de courses connues trouvé.", ephemeral=True
            )

    @discord.app_commands.command(
        name="courseforcer",
        description="Force l'annonce immédiate des courses non encore annoncées",
    )
    async def course_forcer(self, interaction: discord.Interaction):
        if not self._is_admin(interaction.user):
            await interaction.response.send_message(
                "Commande réservée aux administrateurs.", ephemeral=True
            )
            return
        await interaction.response.defer(ephemeral=True)
        if not RACES_CHANNEL_ID:
            await interaction.followup.send("RACES_CHANNEL_ID non configuré.", ephemeral=True)
            return
        try:
            async with aiohttp.ClientSession() as s:
                async with s.get(SITE_URL, timeout=aiohttp.ClientTimeout(total=10)) as r:
                    html = await r.text()
        except Exception as e:
            await interaction.followup.send(f"Site inaccessible : {e}", ephemeral=True)
            return

        races = self._parse_races(html)
        known = self._load_known() or set()
        new_races = [r for r in races if r["id"] not in known]

        if not new_races:
            await interaction.followup.send("Aucune nouvelle course à annoncer.", ephemeral=True)
            return

        count = 0
        for race in new_races:
            try:
                await self._announce_race(race)
                known.add(race["id"])
                count += 1
            except Exception as e:
                logger.error("Erreur annonce forcée '%s' : %s", race.get("title"), e)

        self._save_known(known)
        await interaction.followup.send(f"{count} course(s) annoncée(s).", ephemeral=True)

    # ── Embed annonce principale ──────────────────────────────────

    def _build_embed(self, race: dict, race_channel=None) -> discord.Embed:
        dt = datetime.fromisoformat(race["date"].replace("Z", "+00:00")).astimezone(PARIS)
        date_str = dt.strftime("%A %d %B %Y à %H:%M").capitalize()
        embed = discord.Embed(
            title=f"🏁 Nouvelle course : {race['title']}",
            description=race.get("description") or "",
            color=0xE63946,
            url=SITE_URL,
        )
        embed.add_field(name="📅 Date", value=date_str, inline=False)
        if race.get("classes"):
            embed.add_field(
                name="🏎️ Classes",
                value=" · ".join(race["classes"]),
                inline=False,
            )
        elif race.get("tags"):
            embed.add_field(name="🏎️ Infos", value=" · ".join(race["tags"]), inline=False)
        if race_channel:
            embed.add_field(name="💬 Salon", value=race_channel.mention, inline=False)
        if race.get("image"):
            embed.set_image(url=race["image"])
        embed.set_footer(text="Par amour du spin")
        return embed


async def setup(bot):
    await bot.add_cog(Calendar(bot))
