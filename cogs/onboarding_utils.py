"""Fonctions pures de l'onboarding PADS (aucune dépendance à discord.py).

Elles sont testées par tests/test_onboarding_utils.py. Les règles de
validation sont au moins aussi strictes que celles du site
(POST /api/members/onboarding, validation zod) pour éviter les 400.

Confidentialité : aucune de ces fonctions ne journalise quoi que ce soit.
"""

from __future__ import annotations

import re
import unicodedata
from datetime import datetime, timezone

NICKNAME_MAX = 32          # limite Discord
PSEUDO_MAX = 20            # limite du site
NAME_MAX = 50              # prénom / nom (limite du site)

_NAME_EXTRA_CHARS = {" ", "-", "'", "’"}  # espace, tiret, apostrophes ' et ’

# Suffixe « [X.Nom] » déjà présent en fin de pseudo (ex. « Clyde[J.Doe] »).
_SUFFIX_RE = re.compile(r"\s*\[\s*[^\W\d_]\s*\.[^\[\]]*\]\s*$")


def normalize(value: str | None) -> str:
    """Normalise en NFC (accents composés) et retire les espaces autour."""
    return unicodedata.normalize("NFC", value or "").strip()


def strip_suffix(pseudo: str) -> str:
    """Retire un éventuel suffixe « [X.Nom] » en fin de pseudo."""
    return _SUFFIX_RE.sub("", pseudo or "").strip()


def default_pseudo(display_name: str) -> str:
    """Valeur pré-remplie du champ Pseudo à partir du pseudo actuel du membre.

    Suffixe « [X.Nom] » retiré, crochets restants supprimés, 20 caractères max.
    """
    pseudo = strip_suffix(normalize(display_name))
    pseudo = pseudo.replace("[", "").replace("]", "").strip()
    return pseudo[:PSEUDO_MAX].strip()


def _is_letter(ch: str) -> bool:
    return unicodedata.category(ch).startswith("L")


def validate_pseudo(pseudo: str) -> str | None:
    """Retourne un message d'erreur, ou None si le pseudo est valide."""
    if not pseudo:
        return "Le pseudo est obligatoire."
    if len(pseudo) > PSEUDO_MAX:
        return f"Le pseudo doit faire {PSEUDO_MAX} caractères maximum."
    if "[" in pseudo or "]" in pseudo:
        return "Le pseudo ne doit pas contenir de crochets [ ]."
    if any(unicodedata.category(ch).startswith("C") for ch in pseudo):
        return "Le pseudo contient des caractères invalides."
    return None


def validate_name(value: str, label: str) -> str | None:
    """Valide un prénom ou un nom. Retourne un message d'erreur ou None.

    Autorisés : lettres (accents compris), espaces, tirets, apostrophes ' et ’.
    Doit contenir au moins une lettre.
    """
    if not value:
        return f"Le {label} est obligatoire."
    if len(value) > NAME_MAX:
        return f"Le {label} doit faire {NAME_MAX} caractères maximum."
    if not all(_is_letter(ch) or ch in _NAME_EXTRA_CHARS for ch in value):
        return (
            f"Le {label} ne peut contenir que des lettres, espaces, tirets "
            "et apostrophes."
        )
    if not any(_is_letter(ch) for ch in value):
        return f"Le {label} doit contenir au moins une lettre."
    return None


def first_initial(prenom: str) -> str:
    """Initiale du prénom en majuscule (« Jean-Pierre » → « J »)."""
    for ch in prenom:
        if _is_letter(ch):
            return ch.upper()[0]
    return ""


def build_nickname(pseudo: str, prenom: str, nom: str) -> str:
    """Construit le surnom serveur au format « Pseudo[P.Nom] » (32 car. max).

    - Un suffixe « [X.Nom] » déjà présent dans le pseudo est retiré.
    - Initiale = première lettre du prénom en majuscule.
    - Si le résultat dépasse 32 caractères : on tronque d'abord le pseudo
      (1 caractère minimum), puis le nom. Les crochets ne sont jamais cassés.
    """
    pseudo = strip_suffix(normalize(pseudo)) or normalize(pseudo)
    nom = normalize(nom)
    initial = first_initial(normalize(prenom))

    def suffix(n: str) -> str:
        return f"[{initial}.{n}]"

    if len(pseudo) + len(suffix(nom)) <= NICKNAME_MAX:
        return pseudo + suffix(nom)

    available = NICKNAME_MAX - len(suffix(nom))
    if available >= 1:
        cut = pseudo[:available].rstrip() or pseudo[:1]
        return cut + suffix(nom)

    # Le suffixe seul est trop long : pseudo réduit à 1 caractère, nom tronqué.
    pseudo = pseudo[:1]
    nom_max = NICKNAME_MAX - len(pseudo) - len(suffix(""))
    nom = nom[:nom_max].rstrip() or nom[:nom_max]
    return pseudo + suffix(nom)


def utc_now_iso(now: datetime | None = None) -> str:
    """Horodatage ISO 8601 UTC terminé par « Z » (ex. 2026-11-20T13:25:00Z)."""
    now = now or datetime.now(timezone.utc)
    return now.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
