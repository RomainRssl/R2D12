import os
import json
import re
import unicodedata
import logging
import aiohttp
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo
from discord.ext import commands, tasks
import discord

logger = logging.getLogger(__name__)

SITE_URL = os.getenv("RACES_SITE_URL", "https://paramourduspin.fun")
RACES_CHANNEL_ID = int(os.getenv("RACES_CHANNEL_ID", "0"))
RACES_CATEGORY_ID = int(os.getenv("RACES_CATEGORY_ID", "1399427481945247817"))
RACES_STAFF_ROLE_ID = int(os.getenv("RACES_STAFF_ROLE_ID", "1424791316881211412"))
RACES_NOTIFY_ROLE_ID = int(os.getenv("RACES_NOTIFY_ROLE_ID", "1505321380420255784"))
DATA_FILE = "data/known_races.json"
DATA_MESSAGES = "data/race_messages.json"
DATA_REGISTRATIONS = "data/race_registrations.json"
PARIS = ZoneInfo("Europe/Paris")
TAG_SIMULATOR = "text-blue-400"   # simulateur (Le Mans ultimate, iRacing…)
TAG_CIRCUIT   = "text-green-400"   # circuit (Spa, Le Mans…)
TAG_CLASSES   = "text-orange-400"  # classes voiture (LMGT3, Hypercar…)
TAG_COLORS = (TAG_SIMULATOR, TAG_CIRCUIT, TAG_CLASSES)  # rétrocompat

# Mapping classe discord → nom de rôle (pour ping à l'annonce)
CLASS_ROLE_MAP: dict[str, str] = {
    "lmgt3":    "gt3",
    "hypercar": "hypercar",
    "lmp2":     "lmp2",
    "lmp3":     "lmp3",
    "gte":      "gte",
}

# Jours et mois en français (indépendant de la locale système)
FR_DAYS = ["lundi", "mardi", "mercredi", "jeudi", "vendredi", "samedi", "dimanche"]
FR_MONTHS = [
    "janvier", "février", "mars", "avril", "mai", "juin",
    "juillet", "août", "septembre", "octobre", "novembre", "décembre",
]


def _format_date_fr(dt: datetime) -> str:
    """Ex : « Samedi 12 juillet 2026 à 21:00 »."""
    day = FR_DAYS[dt.weekday()].capitalize()
    return f"{day} {dt.day} {FR_MONTHS[dt.month - 1]} {dt.year} à {dt:%H:%M}"


# Briefing d'avant-course posté automatiquement dans le channel de la course
BRIEFING_TEXT = """\
Avant de prendre la piste, petit rappel des règles d'or. On est là pour le plaisir, dans le respect de chacun. 🏁

🚦 **Départ & premier tour**

La course ne se gagne pas au premier virage, mais elle peut s'y perdre. Freinages anticipés, laissez de l'espace et gardez une marge de sécurité. Un bon départ est un départ où tout le monde passe le premier tour sans dégâts.

⚔️ **Dépassements**

Un dépassement propre se fait à deux. Une situation de dépassement est considérée comme engagée lorsque la roue avant de l'attaquant atteint au minimum le niveau de la roue arrière du défenseur avant le point de corde. À partir de ce moment, les deux pilotes doivent se laisser l'espace nécessaire. Pas de divebomb, un seul changement de trajectoire en défense.

🔵 **Trafic multiclasse & drapeaux bleus**

Voiture rapide : c'est à vous de réaliser le dépassement proprement. Voiture doublée : restez prévisible, gardez votre trajectoire et évitez tout changement brutal de ligne.

💥 **En cas de contact**

Si vous provoquez un contact qui fait perdre une ou plusieurs positions à un concurrent, attendez-le et rendez la position lorsque cela peut être fait en sécurité. Un simple « désolé » en vocal ne coûte rien et apaise souvent les tensions.

🔄 **Retour en piste**

Après un tête-à-queue ou une sortie : vérifiez toujours le trafic avant de revenir en piste. Reprenez la piste parallèlement au sens de circulation, jamais en travers.

Si votre voiture est endommagée, adaptez votre rythme jusqu'aux stands et restez particulièrement vigilant vis-à-vis des autres concurrents.

🎙️ **Comportement**

Pas de rage en vocal ou dans le chat pendant la course. Gardez votre calme même en cas d'incident. Les situations litigieuses seront analysées après la course selon les procédures prévues.

⚖️ **Commission de course & réclamations**

Les contacts simples sont analysés directement par la commission de course.

Si vous estimez avoir été victime d'un comportement non fair-play ou qu'un incident nécessite un examen particulier, utilisez le système de ticket après la course. Les commissaires se chargeront d'analyser la situation.

Pas de règlement de compte en piste, pas de débat à chaud en vocal : la commission est là pour ça.

🏁 **Bonne course à tous !**

À la FIS, la victoire est belle, mais le respect de ses concurrents l'est encore plus. 🏆

Je serais là à 20h50 pour répondre aux questions pré course.

À tout à l'heure !"""


# Mapping classe → (ButtonStyle, emoji)
# Discord n'a que 4 couleurs : success=vert, danger=rouge, primary=bleu, secondary=gris
CLASS_STYLES: dict = {
    "lmgt3":    (discord.ButtonStyle.success,   "🟢"),
    "hypercar": (discord.ButtonStyle.danger,    "🔴"),
    "lmp2":     (discord.ButtonStyle.primary,   "🔵"),
    "lmp3":     (discord.ButtonStyle.secondary, "🟣"),
    "gte":      (discord.ButtonStyle.secondary, "🟡"),
}

def _class_style(name: str):
    """Retourne (ButtonStyle, emoji) pour une classe donnée."""
    key = name.lower().replace(" ", "")
    _, emoji = CLASS_STYLES.get(key, (None, "🏎️"))
    return discord.ButtonStyle.secondary, emoji


def _slugify(text: str) -> str:
    text = unicodedata.normalize("NFD", text)
    text = text.encode("ascii", "ignore").decode("ascii")
    text = re.sub(r"[^\w\s-]", "", text.lower())
    return re.sub(r"[-\s]+", "-", text).strip("-")


def _clean_class_name(name) -> str:
    """Retire les suffixes parasites comme '(toute classe)'. Gère str ou dict."""
    if isinstance(name, dict):
        name = name.get("name", "")
    name = re.sub(r"\(.*?\)", "", str(name)).strip()
    return name


# ── Helpers standalone (pour les callbacks hors Cog) ────────────────

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


def _load_msgs() -> dict:
    try:
        with open(DATA_MESSAGES) as f:
            return json.load(f)
    except FileNotFoundError:
        return {}


_CLASS_COLORS: dict[str, int] = {
    "lmgt3":    0x57F287,  # vert
    "hypercar": 0xED4245,  # rouge
    "lmp2":     0x5865F2,  # bleu
    "lmp3":     0x99AAB5,  # gris
    "gte":      0xFEE75C,  # jaune
}


def _build_class_embeds(title: str, classes_data: dict, classes_max: dict | None = None) -> list[discord.Embed]:
    """Retourne une liste d'embeds : un header + un embed par classe (description = liste complète)."""
    total = sum(len(v) for v in classes_data.values())

    # Embed d'en-tête avec les instructions
    header = discord.Embed(
        title=f"🏁 {title}",
        description=(
            "Choisissez votre classe en cliquant sur le bouton correspondant.\n"
            "Cliquez à nouveau sur votre classe pour vous désinscrire."
        ),
        color=0xE63946,
    )
    header.set_footer(text=f"Par amour du spin · {total} pilote(s) inscrit(s)")
    embeds = [header]

    # Un embed par classe
    for class_name, members in classes_data.items():
        count = len(members)
        max_p = (classes_max or {}).get(class_name)
        count_str = f"{count}/{max_p}" if max_p else str(count)
        description = "\n".join(f"• {m['name']}" for m in members) if members else "*Aucun inscrit*"
        color = _CLASS_COLORS.get(class_name.lower().replace(" ", ""), 0xE63946)
        embed = discord.Embed(
            title=f"🏎️ {class_name} — {count_str} pilote(s)",
            description=description,
            color=color,
        )
        embeds.append(embed)

    return embeds


# ── Bouton classe ─────────────────────────────────────────────────

class ClassButton(discord.ui.Button):
    def __init__(self, class_name: str, channel_id: int):
        style, emoji = _class_style(class_name)
        super().__init__(
            label=class_name[:80],
            style=style,
            emoji=emoji,
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
                    embeds=_build_class_embeds(data["title"], data["classes"], data.get("classes_max"))
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

async def _refresh_inscrit_counts(guild: discord.Guild, role_id: int):
    """Met à jour le compteur d'inscrits sur l'annonce principale et l'embed du channel privé."""
    role = guild.get_role(role_id)
    if not role:
        return
    inscrit_count = len(role.members)
    msgs = _load_msgs()
    for msg_id_str, data in msgs.items():
        if data.get("role_id") != role_id:
            continue

        # Mise à jour dans le channel principal
        try:
            main_ch = guild.get_channel(RACES_CHANNEL_ID)
            if main_ch:
                main_msg = await main_ch.fetch_message(int(msg_id_str))
                if main_msg.embeds:
                    emb = main_msg.embeds[0].copy()
                    updated = False
                    for i, field in enumerate(emb.fields):
                        if "Inscrits" in field.name:
                            emb.set_field_at(i, name=field.name, value=str(inscrit_count), inline=field.inline)
                            updated = True
                            break
                    if not updated:
                        emb.add_field(name="👥 Inscrits", value=str(inscrit_count), inline=True)
                    view = RaceRegistrationView(data["title"], role_id)
                    await main_msg.edit(embed=emb, view=view)
        except Exception as e:
            logger.warning("Mise à jour inscrit channel principal : %s", e)

        # Mise à jour dans le channel privé de la course
        if data.get("channel_embed_msg_id") and data.get("channel_id"):
            try:
                race_ch = guild.get_channel(int(data["channel_id"]))
                if race_ch:
                    ch_msg = await race_ch.fetch_message(int(data["channel_embed_msg_id"]))
                    if ch_msg.embeds:
                        emb2 = ch_msg.embeds[0].copy()
                        updated2 = False
                        for i, field in enumerate(emb2.fields):
                            if "Inscrits" in field.name:
                                emb2.set_field_at(i, name=field.name, value=str(inscrit_count), inline=field.inline)
                                updated2 = True
                                break
                        if not updated2:
                            emb2.add_field(name="👥 Inscrits", value=str(inscrit_count), inline=True)
                        await ch_msg.edit(embed=emb2)
            except Exception as e:
                logger.warning("Mise à jour inscrit channel privé : %s", e)
        break


async def _remove_user_from_classes(guild: discord.Guild, role_id: int, uid: str) -> list[str]:
    """Retire l'utilisateur de toutes les classes de la course liée à ce rôle.

    Met à jour le message de sélection de classe et retourne les classes quittées."""
    msgs = _load_msgs()
    race_entry = next((d for d in msgs.values() if d.get("role_id") == role_id), None)
    if not race_entry or not race_entry.get("channel_id"):
        return []

    key = str(race_entry["channel_id"])
    regs = _load_registrations()
    data = regs.get(key)
    if not data:
        return []

    removed = []
    for cls, members in data.get("classes", {}).items():
        if any(m["id"] == uid for m in members):
            removed.append(cls)
            data["classes"][cls] = [m for m in members if m["id"] != uid]
    if not removed:
        return []

    _save_registrations(regs)

    try:
        channel = guild.get_channel(int(key))
        if channel and data.get("message_id"):
            msg = await channel.fetch_message(int(data["message_id"]))
            await msg.edit(
                embeds=_build_class_embeds(data["title"], data["classes"], data.get("classes_max"))
            )
    except Exception as e:
        logger.warning("Impossible de mettre à jour le message de classe : %s", e)

    return removed


class UnregisterButton(discord.ui.Button):
    def __init__(self, role_id: int):
        super().__init__(
            label="Se désinscrire",
            style=discord.ButtonStyle.danger,
            emoji="🚪",
            custom_id=f"race_unregister_{role_id}",
        )
        self.role_id = role_id

    async def callback(self, interaction: discord.Interaction):
        role = interaction.guild.get_role(self.role_id)
        if not role:
            await interaction.response.send_message("Rôle introuvable.", ephemeral=True)
            return
        if role not in interaction.user.roles:
            await interaction.response.send_message(
                "Vous n'êtes pas inscrit à cette course.", ephemeral=True
            )
            return

        await interaction.response.defer(ephemeral=True)
        await interaction.user.remove_roles(role)

        # Retirer aussi l'inscription de classe dans le channel de la course
        removed_classes = await _remove_user_from_classes(
            interaction.guild, self.role_id, str(interaction.user.id)
        )
        await _refresh_inscrit_counts(interaction.guild, self.role_id)

        text = f"❌ Vous êtes désinscrit de **{role.name}**."
        if removed_classes:
            text += " Votre inscription en **" + "**, **".join(removed_classes) + "** a été retirée."
        await interaction.followup.send(text, ephemeral=True)


class UnregisterView(discord.ui.View):
    def __init__(self, role_id: int):
        super().__init__(timeout=None)
        self.add_item(UnregisterButton(role_id))


class RaceButton(discord.ui.Button):
    def __init__(self, race_title: str, role_id: int):
        super().__init__(
            label=f"S'inscrire — {race_title}"[:80],
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
            # Déjà inscrit : proposer le bouton personnel « Se désinscrire »
            await interaction.response.send_message(
                f"Vous êtes déjà inscrit pour **{role.name}**.",
                view=UnregisterView(self.role_id),
                ephemeral=True,
            )
            return

        await interaction.response.defer(ephemeral=True)
        await interaction.user.add_roles(role)
        await _refresh_inscrit_counts(interaction.guild, self.role_id)
        await interaction.followup.send(
            f"✅ Inscrit pour **{role.name}** !",
            view=UnregisterView(self.role_id),
            ephemeral=True,
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
        self.check_race_reminders.start()

    def cog_unload(self):
        self.check_new_races.cancel()
        self.check_race_reminders.cancel()

    @commands.Cog.listener()
    async def on_ready(self):
        # Restaurer les boutons d'inscription simples
        for msg_id, data in _load_msgs().items():
            view = RaceRegistrationView(data["title"], data["role_id"])
            self.bot.add_view(view, message_id=int(msg_id))
            # Bouton « Se désinscrire » envoyé en éphémère (custom_id global)
            self.bot.add_view(UnregisterView(data["role_id"]))

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
        return _load_msgs()

    def _save_message(self, message_id: str, data: dict):
        messages = _load_msgs()
        messages[message_id] = data
        with open(DATA_MESSAGES, "w") as f:
            json.dump(messages, f)

    # ── API /api/events ───────────────────────────────────────────

    async def _fetch_races_api(self) -> list:
        """Récupère les courses depuis l'API /api/events (inclut serverName et serverPassword)."""
        try:
            async with aiohttp.ClientSession() as s:
                async with s.get(
                    f"{SITE_URL}/api/events",
                    timeout=aiohttp.ClientTimeout(total=10),
                    headers={"Accept": "application/json"},
                ) as r:
                    if r.status != 200:
                        logger.error("API /api/events — statut %s", r.status)
                        return []
                    data = await r.json()

            races = []
            for event in data:
                # cars peut être un JSON string ou une liste directe
                try:
                    cars_raw = json.loads(event.get("cars") or "[]")
                except (json.JSONDecodeError, TypeError):
                    cars_raw = event.get("cars") or []
                if not isinstance(cars_raw, list):
                    cars_raw = []
                # Gérer le cas où chaque élément est un dict {"name": "LMGT3", "max_places": 51}
                classes = []
                classes_max: dict[str, int] = {}
                for c in cars_raw:
                    if not c:
                        continue
                    name = _clean_class_name(c)
                    if not name:
                        continue
                    classes.append(name)
                    if isinstance(c, dict) and c.get("max_places"):
                        classes_max[name] = int(c["max_places"])

                image = event.get("imageUrl") or ""
                if image and not image.startswith("http"):
                    image = f"{SITE_URL}{image}"

                desc = event.get("description") or ""
                if len(desc) > 4096:
                    desc = desc[:4093] + "…"

                races.append({
                    "id":          event["date"],        # datetime comme ID (continuité)
                    "title":       event["title"],
                    "date":        event["date"],
                    "simulator":   event.get("game", "") or "",
                    "circuit":     event.get("track", "") or "",
                    "classes":     classes,
                    "classes_max": classes_max,
                    "description": desc,
                    "image":       image,
                    "server_name": event.get("serverName", "") or "",
                    "password":    event.get("serverPassword", "") or "",
                })
            logger.info("API /api/events : %d course(s) récupérée(s)", len(races))
            return races

        except Exception as e:
            logger.error("Erreur API /api/events : %s", e)
            return []

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
        # Les inscrits peuvent lire mais seul le staff peut écrire dans le channel de course
        overwrites = {
            guild.default_role: discord.PermissionOverwrite(view_channel=False, send_messages=False),
            role: discord.PermissionOverwrite(
                view_channel=True, send_messages=False, read_message_history=True
            ),
            guild.me: discord.PermissionOverwrite(
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
        self.bot.add_view(UnregisterView(role.id))
        msg = await channel.send(embed=self._build_embed(race, race_channel, inscrit_count=0), view=view)

        # Ping @Pilote uniquement
        notify_role = guild.get_role(RACES_NOTIFY_ROLE_ID)
        if notify_role:
            await channel.send(notify_role.mention)

        # Premier message du channel privé : infos de la course (sans bouton d'inscription)
        race_ch_msg = await race_channel.send(embed=self._build_embed(race, inscrit_count=0))

        self._save_message(str(msg.id), {
            "role_id": role.id,
            "channel_id": race_channel.id,
            "title": race["title"],
            "date": race["date"],
            "server_name": race.get("server_name", ""),
            "password": race.get("password", ""),
            "notified_1h": False,
            "channel_embed_msg_id": str(race_ch_msg.id),
        })

        # Sélection de classe dans le channel privé (si multiclasse)
        classes = race.get("classes", [])
        if len(classes) >= 2:
            await self._post_class_selection(race_channel, race, classes)

        # Briefing d'avant-course
        try:
            await self._post_briefing(race_channel)
        except Exception as e:
            logger.error("Impossible de poster le briefing dans %s : %s", race_channel.id, e)

    async def _post_briefing(self, channel: discord.TextChannel):
        """Poste le briefing d'avant-course dans le channel privé de la course."""
        notify_role = channel.guild.get_role(RACES_NOTIFY_ROLE_ID)
        mention = notify_role.mention if notify_role else "@pilote"
        embed = discord.Embed(description=BRIEFING_TEXT, color=0xE63946)
        embed.set_footer(text="Par amour du spin")
        await channel.send(
            content=f"📋 **BRIEFING D'AVANT-COURSE** {mention}",
            embed=embed,
        )

    async def _post_class_selection(
        self,
        channel: discord.TextChannel,
        race: dict,
        classes: list,
    ):
        """Poste le message de sélection de classe dans le channel privé de la course."""
        classes = [c for c in classes if c][:5]
        classes_data = {c: [] for c in classes}
        classes_max = race.get("classes_max", {})
        view = ClassRegistrationView(classes, channel.id)
        msg = await channel.send(
            embeds=_build_class_embeds(race["title"], classes_data, classes_max),
            view=view,
        )
        regs = _load_registrations()
        regs[str(channel.id)] = {
            "title": race["title"],
            "message_id": str(msg.id),
            "classes": classes_data,
            "classes_max": classes_max,
        }
        _save_registrations(regs)

    # ── Tâche planifiée ───────────────────────────────────────────

    @tasks.loop(minutes=5)
    async def check_new_races(self):
        if not RACES_CHANNEL_ID:
            return

        races = await self._fetch_races_api()
        if not races:
            return

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

    # ── Rappel 5 min avant la course ─────────────────────────────

    @tasks.loop(minutes=1)
    async def check_race_reminders(self):
        """Purge le channel privé et envoie les infos serveur/MDP 5 min avant chaque course."""
        now = datetime.now(PARIS)
        messages = _load_msgs()
        updated = False

        # Charger les données API une seule fois pour enrichir les entrées manquantes
        api_races = None

        for msg_id, data in messages.items():
            if data.get("notified_1h"):
                continue
            if not data.get("date") or not data.get("channel_id"):
                continue

            # Si server_name/password manquent, tenter de les récupérer depuis l'API
            if not data.get("server_name") and not data.get("password"):
                if api_races is None:
                    api_races = await self._fetch_races_api()
                match = next((r for r in api_races if r["id"] == data.get("date")), None)
                if match:
                    data["server_name"] = match.get("server_name", "")
                    data["password"]    = match.get("password", "")
                    updated = True

            # Toujours passer si aucune info serveur disponible
            if not data.get("server_name") and not data.get("password"):
                continue

            try:
                race_dt = datetime.fromisoformat(
                    data["date"].replace("Z", "+00:00")
                ).astimezone(PARIS)
            except ValueError:
                continue

            delta = race_dt - now
            # Fenêtre : entre 4 et 6 minutes avant le départ
            if not (timedelta(minutes=4) <= delta <= timedelta(minutes=6)):
                continue

            try:
                channel = await self.bot.fetch_channel(int(data["channel_id"]))
            except Exception as e:
                logger.warning("Rappel 5min — channel introuvable (%s) : %s", data["channel_id"], e)
                data["notified_1h"] = True   # éviter de réessayer indéfiniment
                updated = True
                continue

            # Purger les messages non-bot pour ne garder que les messages du bot
            try:
                def is_not_bot(m: discord.Message) -> bool:
                    return m.author.id != self.bot.user.id

                deleted = await channel.purge(limit=200, check=is_not_bot)
                logger.info("Purge avant course '%s' : %d message(s) supprimé(s)", data["title"], len(deleted))
            except Exception as e:
                logger.warning("Purge channel %s impossible : %s", data["channel_id"], e)

            embed = discord.Embed(
                title=f"🚦 Départ dans 5 minutes — {data['title']}",
                color=0xE63946,
            )
            if data.get("server_name"):
                embed.add_field(name="🖥️ Nom du serveur", value=data["server_name"], inline=False)
            if data.get("password"):
                embed.add_field(name="🔒 Mot de passe", value=data["password"], inline=False)
            embed.set_footer(text="Par amour du spin · Bonne course ! 🏎️")

            try:
                await channel.send(embed=embed)
                logger.info("Rappel 5min envoyé pour '%s'", data["title"])
            except Exception as e:
                logger.error("Rappel 5min — impossible d'envoyer dans %s : %s", data["channel_id"], e)

            data["notified_1h"] = True
            updated = True

        if updated:
            with open(DATA_MESSAGES, "w") as f:
                json.dump(messages, f, ensure_ascii=False, indent=2)

    @check_race_reminders.before_loop
    async def before_reminders(self):
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

        lines.append(f"\n**API** : `{SITE_URL}/api/events`")
        try:
            races = await self._fetch_races_api()
            if races:
                lines.append(f"API accessible — {len(races)} course(s) trouvée(s)")
                known = self._load_known() or set()
                new = [r for r in races if r["id"] not in known]
                lines.append(f"Courses connues : {len(known)} | Nouvelles : **{len(new)}**")
                for r in races:
                    status = "✅ connue" if r["id"] in known else "🆕 nouvelle"
                    lines.append(f"  • **{r['title']}** — {status}")
                    lines.append(f"    🎮 {r.get('simulator') or '—'}  🏟️ {r.get('circuit') or '—'}")
                    classes_str = ", ".join(r["classes"]) if r["classes"] else "*aucune*"
                    lines.append(f"    🏎️ Classes : {classes_str}")
                    if r.get("server_name"):
                        lines.append(f"    🖥️ Serveur : {r['server_name']}")
            else:
                lines.append("API **inaccessible** ou aucune course")
        except Exception as e:
            lines.append(f"Erreur : {e}")

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
        races = await self._fetch_races_api()
        if not races:
            await interaction.followup.send("API inaccessible ou aucune course.", ephemeral=True)
            return

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

    @discord.app_commands.command(
        name="coursemdp",
        description="Envoie immédiatement les infos serveur/MDP dans le channel privé d'une course",
    )
    async def course_mdp(self, interaction: discord.Interaction):
        if not self._is_admin(interaction.user):
            await interaction.response.send_message(
                "Commande réservée aux administrateurs.", ephemeral=True
            )
            return
        await interaction.response.defer(ephemeral=True)

        races_api = await self._fetch_races_api()
        api_by_date = {r["id"]: r for r in races_api}

        messages = _load_msgs()
        sent = 0
        skipped = 0

        for msg_id, data in messages.items():
            if data.get("notified_1h") or not data.get("channel_id"):
                continue

            # Enrichir depuis l'API si besoin
            date_key = data.get("date", "")
            if (not data.get("server_name") and not data.get("password")) and date_key in api_by_date:
                api_r = api_by_date[date_key]
                data["server_name"] = api_r.get("server_name", "")
                data["password"]    = api_r.get("password", "")

            if not data.get("server_name") and not data.get("password"):
                skipped += 1
                continue

            try:
                channel = await self.bot.fetch_channel(int(data["channel_id"]))
                # Purger les messages non-bot
                try:
                    deleted = await channel.purge(
                        limit=200,
                        check=lambda m: m.author.id != self.bot.user.id,
                    )
                    logger.info("coursemdp purge '%s' : %d message(s)", data.get("title"), len(deleted))
                except Exception as pe:
                    logger.warning("coursemdp — purge impossible : %s", pe)
                embed = discord.Embed(
                    title=f"🚦 Départ imminent — {data['title']}",
                    color=0xE63946,
                )
                if data.get("server_name"):
                    embed.add_field(name="🖥️ Nom du serveur", value=data["server_name"], inline=False)
                if data.get("password"):
                    embed.add_field(name="🔒 Mot de passe", value=data["password"], inline=False)
                embed.set_footer(text="Par amour du spin · Bonne course ! 🏎️")
                await channel.send(embed=embed)
                data["notified_1h"] = True
                sent += 1
            except Exception as e:
                logger.error("coursemdp — erreur channel %s : %s", data["channel_id"], e)
                skipped += 1

        with open(DATA_MESSAGES, "w") as f:
            json.dump(messages, f, ensure_ascii=False, indent=2)

        await interaction.followup.send(
            f"✅ {sent} message(s) envoyé(s){f', {skipped} ignoré(s) (pas de données)' if skipped else ''}.",
            ephemeral=True,
        )

    @discord.app_commands.command(
        name="courserestaurer",
        description="Reposte les messages de sélection de classe manquants dans les channels de course",
    )
    async def course_restaurer(self, interaction: discord.Interaction):
        if not self._is_admin(interaction.user):
            await interaction.response.send_message(
                "Commande réservée aux administrateurs.", ephemeral=True
            )
            return
        await interaction.response.defer(ephemeral=True)

        messages = _load_msgs()
        regs = _load_registrations()
        races_api = await self._fetch_races_api()
        api_by_date = {r["id"]: r for r in races_api}
        count = 0

        for msg_id, data in messages.items():
            if not data.get("channel_id"):
                continue
            channel_id = str(data["channel_id"])
            if channel_id in regs:
                continue  # Déjà un message de sélection de classe

            date_key = data.get("date", "")
            race = api_by_date.get(date_key)
            if not race or not race.get("classes") or len(race["classes"]) < 2:
                continue

            try:
                ch = await self.bot.fetch_channel(int(data["channel_id"]))
                await self._post_class_selection(ch, race, race["classes"])
                count += 1
                logger.info("courserestaurer — sélection restaurée pour '%s'", data.get("title"))
            except Exception as e:
                logger.error("courserestaurer — erreur '%s' : %s", data.get("title"), e)

        await interaction.followup.send(
            f"✅ {count} message(s) de sélection de classe restauré(s).",
            ephemeral=True,
        )

    # ── Embed annonce principale ──────────────────────────────────

    def _build_embed(self, race: dict, race_channel=None, inscrit_count: int | None = None) -> discord.Embed:
        dt = datetime.fromisoformat(race["date"].replace("Z", "+00:00")).astimezone(PARIS)
        date_str = _format_date_fr(dt)
        description = race.get("description") or ""
        # Discord limite les descriptions d'embed à 4096 caractères
        if len(description) > 4096:
            description = description[:4093] + "…"
        embed = discord.Embed(
            title=f"🏁 Nouvelle course : {race['title']}",
            description=description or None,
            color=0xE63946,
            url=race.get("url") or SITE_URL,
        )
        embed.add_field(name="📅 Date", value=date_str, inline=False)
        if race.get("simulator"):
            embed.add_field(name="🎮 Simulateur", value=race["simulator"], inline=True)
        if race.get("circuit"):
            embed.add_field(name="🏟️ Circuit", value=race["circuit"], inline=True)
        if race.get("classes"):
            embed.add_field(
                name="🏎️ Classes",
                value=" · ".join(race["classes"]),
                inline=False,
            )
        if inscrit_count is not None:
            embed.add_field(name="👥 Inscrits", value=str(inscrit_count), inline=True)
        if race_channel:
            embed.add_field(name="💬 Salon", value=race_channel.mention, inline=False)
        if race.get("image"):
            embed.set_image(url=race["image"])
        embed.set_footer(text="Par amour du spin")
        return embed


async def setup(bot):
    await bot.add_cog(Calendar(bot))
