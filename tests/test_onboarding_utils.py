"""Tests des fonctions pures de l'onboarding.

Lancer depuis la racine du dépôt :
    python -m unittest discover -s tests -t .
"""

import unittest
from datetime import datetime, timedelta, timezone

from cogs.onboarding_utils import (
    NICKNAME_MAX,
    build_nickname,
    default_pseudo,
    first_initial,
    strip_suffix,
    utc_now_iso,
    validate_name,
    validate_pseudo,
)


class BuildNicknameTests(unittest.TestCase):
    def test_cas_normal(self):
        self.assertEqual(build_nickname("Clyde", "John", "Doe"), "Clyde[J.Doe]")

    def test_trim(self):
        self.assertEqual(build_nickname("  Clyde ", " john ", " Doe  "), "Clyde[J.Doe]")

    def test_accents(self):
        self.assertEqual(build_nickname("Pilote", "émilie", "Lefèvre"), "Pilote[É.Lefèvre]")

    def test_accents_decomposes_normalises(self):
        # « é » décomposé (e + accent combinant) → NFC
        self.assertEqual(build_nickname("X", "e\u0301lodie", "Re\u0301my"), "X[É.Rémy]")

    def test_prenom_compose(self):
        self.assertEqual(build_nickname("Clyde", "Jean-Pierre", "Doe"), "Clyde[J.Doe]")

    def test_prenom_avec_espace(self):
        self.assertEqual(build_nickname("Clyde", "Marie Anne", "Doe"), "Clyde[M.Doe]")

    def test_nom_tel_que_saisi(self):
        self.assertEqual(build_nickname("Clyde", "Anne", "de la Tour"), "Clyde[A.de la Tour]")

    def test_suffixe_deja_present(self):
        self.assertEqual(build_nickname("Clyde[J.Doe]", "John", "Smith"), "Clyde[J.Smith]")
        self.assertEqual(build_nickname("Clyde [X.Ancien Nom]", "John", "Doe"), "Clyde[J.Doe]")

    def test_exactement_32(self):
        nick = build_nickname("A" * 20, "Bob", "Martinez")  # 20 + len("[B.Martinez]")=12
        self.assertEqual(len(nick), 32)
        self.assertEqual(nick, "A" * 20 + "[B.Martinez]")

    def test_depassement_tronque_le_pseudo(self):
        nick = build_nickname("SuperPiloteDeLaMort", "Jean", "Dupont-Lajoie")
        self.assertLessEqual(len(nick), NICKNAME_MAX)
        self.assertTrue(nick.endswith("[J.Dupont-Lajoie]"))
        self.assertTrue(nick.startswith("SuperPilote"))

    def test_depassement_tronque_puis_le_nom(self):
        nom = "Abcdefghijklmnopqrstuvwxyzabcdefghij"  # 36 caractères
        nick = build_nickname("Clyde", "John", nom)
        self.assertEqual(len(nick), NICKNAME_MAX)
        self.assertTrue(nick.startswith("C[J."))
        self.assertTrue(nick.endswith("]"))
        self.assertEqual(nick.count("["), 1)
        self.assertEqual(nick.count("]"), 1)

    def test_nom_50_caracteres(self):
        nick = build_nickname("P" * 20, "Zoé", "N" * 50)
        self.assertEqual(len(nick), NICKNAME_MAX)
        self.assertEqual(nick, "P[Z." + "N" * 27 + "]")

    def test_troncature_sans_espace_final(self):
        nick = build_nickname("Le Grand Pilote Fou", "Ana", "Constantinopoli")
        self.assertLessEqual(len(nick), NICKNAME_MAX)
        self.assertNotIn(" [", nick)


class HelpersTests(unittest.TestCase):
    def test_strip_suffix(self):
        self.assertEqual(strip_suffix("Clyde[J.Doe]"), "Clyde")
        self.assertEqual(strip_suffix("Clyde"), "Clyde")
        self.assertEqual(strip_suffix("Clyde[PADS]"), "Clyde[PADS]")  # pas un suffixe X.Nom

    def test_default_pseudo(self):
        self.assertEqual(default_pseudo("Clyde[J.Doe]"), "Clyde")
        self.assertEqual(default_pseudo("[PADS] Clyde"), "PADS Clyde")
        self.assertEqual(len(default_pseudo("x" * 40)), 20)

    def test_first_initial(self):
        self.assertEqual(first_initial("jean-pierre"), "J")
        self.assertEqual(first_initial("'Ali"), "A")


class ValidationTests(unittest.TestCase):
    def test_pseudo(self):
        self.assertIsNone(validate_pseudo("Clyde"))
        self.assertIsNotNone(validate_pseudo(""))
        self.assertIsNotNone(validate_pseudo("x" * 21))
        self.assertIsNotNone(validate_pseudo("Cly[de]"))

    def test_noms_valides(self):
        for value in ("Doe", "Lefèvre", "Jean-Pierre", "O'Neil", "D\u2019Artagnan", "de la Tour", "Zoë"):
            self.assertIsNone(validate_name(value, "nom"), value)

    def test_noms_invalides(self):
        for value in ("", "Doe2", "Doe_", "J.", "x²", "---", "N" * 51, "Doe!"):
            self.assertIsNotNone(validate_name(value, "nom"), value)


class TimestampTests(unittest.TestCase):
    def test_format_z(self):
        dt = datetime(2026, 11, 20, 14, 25, 0, tzinfo=timezone(timedelta(hours=1)))
        self.assertEqual(utc_now_iso(dt), "2026-11-20T13:25:00Z")

    def test_maintenant(self):
        self.assertRegex(utc_now_iso(), r"^\d{4}-\d\d-\d\dT\d\d:\d\d:\d\dZ$")


if __name__ == "__main__":
    unittest.main()
