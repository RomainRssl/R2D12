# R2D12 — Bot Discord

R2D12 est un bot Discord complet développé en Python avec la bibliothèque `discord.py` v2. Il couvre la modération, l'animation de communauté, la gestion de serveur et des fonctionnalités spécialisées pour les serveurs SimRacing.

---

## Sommaire

1. [Prérequis](#prérequis)
2. [Installation](#installation)
3. [Configuration](#configuration)
4. [Démarrage](#démarrage)
5. [Permissions Discord requises](#permissions-discord-requises)
6. [Modules et commandes](#modules-et-commandes)
   - [Général](#général)
   - [Modération](#modération)
   - [Templates & Annonces](#templates--annonces)
   - [Bienvenue](#bienvenue)
   - [Anniversaires](#anniversaires)
   - [Logs d'audit](#logs-daudit)
   - [Rôles automatiques](#rôles-automatiques)
   - [Rôles réactions — Boutons](#rôles-réactions--boutons)
   - [Rôles réactions — Emoji](#rôles-réactions--emoji)
   - [Sondages](#sondages)
   - [Suggestions](#suggestions)
   - [Niveaux & XP](#niveaux--xp)
   - [Économie](#économie)
   - [Giveaways](#giveaways)
   - [Tickets](#tickets)
   - [Messages planifiés](#messages-planifiés)
   - [Compteurs vocaux](#compteurs-vocaux)
   - [Relais de messages](#relais-de-messages)
   - [SimRacing — Temps au tour](#simracing--temps-au-tour)
   - [SimRacing — Sessions](#simracing--sessions)
   - [SimRacing — Championnats](#simracing--championnats)
7. [Structure des fichiers](#structure-des-fichiers)
8. [Données persistantes](#données-persistantes)

---

## Prérequis

- **Python 3.11 ou supérieur**
- Un compte Discord et un bot créé sur le [Portail Développeur Discord](https://discord.com/developers/applications)
- Les intentions (`Intents`) **Message Content** et **Server Members** activées sur le portail

---

## Installation

### 1. Cloner ou télécharger le projet

```bash
git clone https://github.com/romainrssl/r2d12.git
cd r2d12
```

### 2. Créer un environnement virtuel (recommandé)

```bash
python -m venv venv

# Linux / macOS
source venv/bin/activate

# Windows
venv\Scripts\activate
```

### 3. Installer les dépendances

```bash
pip install -r requirements.txt
```

---

## Configuration

### 1. Créer le fichier `.env`

Copiez le fichier d'exemple et renseignez vos valeurs :

```bash
cp .env.example .env
```

Ouvrez `.env` et remplissez :

```env
# Token du bot (obligatoire)
DISCORD_TOKEN=votre_token_ici

# ID de votre serveur de test (optionnel)
# Si renseigné, les slash commands sont synchronisées instantanément sur ce serveur.
# Laissez vide pour une synchronisation globale (peut prendre jusqu'à 1 heure).
GUILD_ID=123456789012345678
```

### 2. Récupérer le token du bot

1. Rendez-vous sur le [Portail Développeur Discord](https://discord.com/developers/applications)
2. Sélectionnez votre application → onglet **Bot**
3. Cliquez sur **Reset Token** puis copiez le token
4. Collez-le dans votre fichier `.env`

### 3. Activer les intentions (Intents)

Sur le Portail Développeur, onglet **Bot**, activez :
- **SERVER MEMBERS INTENT**
- **MESSAGE CONTENT INTENT**

### 4. Inviter le bot sur votre serveur

Sur le Portail Développeur, onglet **OAuth2 → URL Generator** :
- Cochez `bot` et `applications.commands`
- Dans les permissions bot, cochez au minimum :
  - Manage Roles
  - Kick Members / Ban Members
  - Manage Channels
  - Manage Webhooks
  - Send Messages
  - Embed Links
  - Attach Files
  - Read Message History
  - Add Reactions
  - Moderate Members (timeout)
- Copiez l'URL générée et ouvrez-la dans votre navigateur

---

## Démarrage

```bash
python bot.py
```

Le bot affiche dans la console :
```
Slash commands synchronisées sur le serveur 123456789
R2D12 est en ligne ! Connecté en tant que R2D12#0000 (ID: ...)
```

Pour l'arrêter : `Ctrl + C`

---

## Permissions Discord requises

| Permission | Modules concernés |
|---|---|
| Manage Roles | Rôles automatiques, Rôles réactions, Tickets |
| Kick / Ban Members | Modération |
| Manage Channels | Compteurs vocaux, Tickets |
| Manage Webhooks | Relais de messages |
| Moderate Members | Mute (timeout) |
| Send Messages + Embed Links | Tous les modules |
| Add Reactions | Rôles emoji |
| Read Message History | Sondages, Giveaways, Rôles réactions |

---

## Modules et commandes

> Les commandes préfixées par `/` sont des **slash commands** visibles directement dans Discord.
> Les commandes d'administration nécessitent la permission **Gérer le serveur** ou **Gérer les rôles** selon le module.

---

### Général

Commandes de base accessibles par tous les membres.

| Commande | Description |
|---|---|
| `/ping` | Affiche la latence du bot |
| `/help` | Liste toutes les commandes disponibles |
| `/serverinfo` | Informations sur le serveur |
| `/userinfo [@membre]` | Informations sur un membre (vous par défaut) |

---

### Modération

Commandes réservées aux modérateurs.

| Commande | Description |
|---|---|
| `/kick @membre [raison]` | Expulser un membre |
| `/ban @membre [raison]` | Bannir un membre |
| `/unban <user_id>` | Débannir un utilisateur par son ID |
| `/clear [nombre]` | Supprimer des messages (1–100) |
| `/warn @membre [raison]` | Émettre un avertissement |
| `/warnings @membre` | Consulter les avertissements d'un membre |
| `/clearwarnings @membre` | Effacer tous les avertissements d'un membre |
| `/mute @membre [minutes] [raison]` | Mettre en sourdine (timeout Discord natif) |
| `/unmute @membre` | Retirer la sourdine |

---

### Templates & Annonces

Créez des messages pré-remplis avec des variables personnalisées.

| Commande | Description |
|---|---|
| `/template créer <nom> <message>` | Crée un template. Utilisez `{variable}` pour des champs à remplir |
| `/template utiliser <nom> [#salon]` | Ouvre un formulaire pour remplir les variables, puis envoie le message |
| `/template liste` | Affiche tous les templates enregistrés |
| `/template supprimer <nom>` | Supprime un template |
| `/annonce #salon <titre> <message>` | Envoie une annonce formatée en embed dans le salon choisi |

**Exemple de template :**
```
/template créer rappel "Rappel : {événement} aura lieu le {date} à {heure}."
```
Lors de l'utilisation, un formulaire s'ouvre pour remplir `événement`, `date` et `heure`.

---

### Bienvenue

Message automatique envoyé dans un salon quand un nouveau membre rejoint le serveur.

| Commande | Description |
|---|---|
| `/bienvenue configurer #salon [message]` | Définit le salon et le message de bienvenue |
| `/bienvenue tester` | Prévisualise le message de bienvenue |
| `/bienvenue statut` | Affiche la configuration actuelle |
| `/bienvenue désactiver` | Désactive les messages de bienvenue |

**Variables disponibles dans le message :**
- `{mention}` — mentionne le nouveau membre
- `{username}` — pseudo du membre
- `{server}` — nom du serveur
- `{count}` — nombre de membres total

---

### Anniversaires

Le bot souhaite automatiquement un bon anniversaire aux membres enregistrés.

| Commande | Description |
|---|---|
| `/anniversaire enregistrer <jour> <mois>` | Enregistre votre date d'anniversaire |
| `/anniversaire supprimer` | Supprime votre anniversaire |
| `/anniversaire prochains` | Affiche les prochains anniversaires du serveur |
| `/anniversaire configurer #salon [message]` | Configure le salon d'annonce (admin) |
| `/anniversaire tester` | Prévisualise le message d'anniversaire (admin) |
| `/anniversaire statut` | Affiche la configuration (admin) |
| `/anniversaire mp-activer` | Active les DM automatiques aux nouveaux membres pour recueillir leur date |
| `/anniversaire mp-désactiver` | Désactive les DM automatiques |
| `/anniversaire tester-mp` | Prévisualise le DM envoyé aux nouveaux membres |
| `/anniversaire importer <fichier.csv>` | Import en masse depuis un fichier CSV |

**Format CSV pour l'import :**
```csv
user_id,jour,mois
123456789,14,7
987654321,3,12
```

**Fonctionnement automatique :**
- Chaque jour à minuit, le bot vérifie les anniversaires du jour et envoie un message dans le salon configuré.
- Si les DM automatiques sont activés, chaque nouveau membre reçoit un message privé avec un bouton pour enregistrer son anniversaire via un formulaire.

---

### Logs d'audit

Enregistre automatiquement les actions importantes dans un salon dédié.

| Commande | Description |
|---|---|
| `/logs configurer #salon` | Définit le salon de logs |
| `/logs désactiver` | Désactive les logs |
| `/logs statut` | Affiche la configuration actuelle |

**Événements journalisés :**
- Arrivée / départ d'un membre
- Bannissement / débannissement
- Suppression et modification de messages
- Changement de rôles d'un membre

---

### Rôles automatiques

Attribue automatiquement des rôles à chaque nouveau membre qui rejoint le serveur.

| Commande | Description |
|---|---|
| `/autorole ajouter @role` | Ajoute un rôle à la liste des rôles automatiques |
| `/autorole retirer @role` | Retire un rôle de la liste |
| `/autorole liste` | Affiche les rôles automatiques configurés |

---

### Rôles réactions — Boutons

Crée un panneau interactif avec des boutons. Cliquer sur un bouton attribue ou retire le rôle correspondant.

| Commande | Description |
|---|---|
| `/rolerole créer #salon <titre> <description>` | Crée un nouveau panneau dans le salon choisi |
| `/rolerole ajouter <msg_id> @role <label> [emoji]` | Ajoute un bouton au panneau |
| `/rolerole supprimer <msg_id>` | Supprime un panneau et son message |

**Comment utiliser :**
1. `/rolerole créer #rôles "Choisissez vos rôles" "Cliquez pour obtenir un rôle"`
2. Notez l'ID du message retourné
3. `/rolerole ajouter 1234567890 @Pilote "🏎️ Pilote"`
4. Les membres cliquent sur le bouton pour obtenir/retirer le rôle

---

### Rôles réactions — Emoji

Associe un emoji spécifique sur un message existant à un rôle. Réagir avec l'emoji attribue le rôle ; retirer la réaction le retire.

| Commande | Description |
|---|---|
| `/emojirole ajouter <msg_id> <emoji> @role` | Associe un emoji sur un message à un rôle |
| `/emojirole retirer <msg_id> <emoji>` | Supprime l'association |
| `/emojirole liste` | Affiche toutes les associations configurées |

**Comment utiliser :**
1. Copiez l'ID d'un message existant (clic droit → Copier l'identifiant)
2. `/emojirole ajouter 1234567890 👍 @Approuvé`
3. Le bot ajoute automatiquement la réaction 👍 sur le message
4. Les membres qui cliquent sur 👍 reçoivent le rôle @Approuvé

---

### Sondages

Crée des sondages interactifs avec suivi des votes en temps réel.

| Commande | Description |
|---|---|
| `/sondage <question> <opt1> <opt2> [opt3-5] [durée_h]` | Crée un sondage (2 à 5 options, durée en heures) |
| `/sondage-terminer <msg_id>` | Clôture un sondage manuellement |

**Fonctionnement :**
- Chaque option est représentée par un bouton
- L'embed se met à jour à chaque vote pour afficher les pourcentages
- Un membre ne peut voter qu'une fois
- Le sondage se clôture automatiquement à la fin du délai configuré

---

### Suggestions

Permet aux membres de soumettre des suggestions que les admins peuvent approuver ou refuser.

| Commande | Description |
|---|---|
| `/suggestion configurer #salon` | Définit le salon des suggestions |
| `/suggestion soumettre <texte>` | Soumet une suggestion |
| `/suggestion accepter <msg_id> [commentaire]` | Accepte une suggestion (admin) |
| `/suggestion refuser <msg_id> [commentaire]` | Refuse une suggestion (admin) |

**Fonctionnement :**
- La suggestion est postée dans le salon configuré avec des boutons 👍 👎
- Les votes s'affichent en temps réel sur l'embed
- Lors de l'acceptation/refus, l'embed change de couleur et affiche le commentaire de l'admin

---

### Niveaux & XP

Système de progression basé sur l'activité des membres.

| Commande | Description |
|---|---|
| `/niveau [@membre]` | Affiche le niveau, l'XP et la barre de progression |
| `/classement` | Affiche le top 10 des membres les plus actifs |
| `/niveau configurer #salon` | Définit le salon des annonces de level up (admin) |
| `/niveau recompense-ajouter <niveau> @role` | Attribue un rôle récompense à un palier (admin) |
| `/niveau recompense-retirer <niveau>` | Retire la récompense d'un palier (admin) |
| `/niveau recompense-liste` | Affiche toutes les récompenses configurées (admin) |

**Fonctionnement :**
- Chaque message envoyé rapporte entre 15 et 25 XP (cooldown de 60 secondes par membre)
- Formule : `XP nécessaire pour le niveau N = 100 × N²`
- Au passage de niveau, un message est envoyé dans le salon configuré
- Les rôles récompenses sont attribués automatiquement

---

### Économie

Système de monnaie virtuelle par serveur.

| Commande | Description |
|---|---|
| `/argent [@membre]` | Affiche le solde d'un membre |
| `/daily` | Réclame la récompense quotidienne (+200 coins, cooldown 24h) |
| `/donner @membre <montant>` | Transfère de l'argent à un autre membre |
| `/classement-argent` | Affiche le top 10 des membres les plus riches |
| `/inventaire [@membre]` | Affiche les articles possédés |
| `/boutique liste` | Affiche les articles disponibles à l'achat |
| `/boutique ajouter <nom> <prix> <description> [@role]` | Ajoute un article en boutique (admin) |
| `/boutique retirer <nom>` | Retire un article de la boutique (admin) |
| `/boutique acheter <nom>` | Achète un article (attribue le rôle associé si configuré) |

---

### Giveaways

Organise des tirages au sort parmi les membres participants.

| Commande | Description |
|---|---|
| `/giveaway lancer #salon <durée_h> <prix> [gagnants]` | Lance un giveaway |
| `/giveaway terminer <msg_id>` | Termine un giveaway manuellement |
| `/giveaway relancer <msg_id>` | Re-roll les gagnants |
| `/giveaway liste` | Affiche les giveaways en cours |

**Fonctionnement :**
- Un embed avec un bouton 🎉 est posté dans le salon choisi
- Les membres cliquent sur le bouton pour participer
- À la fin du délai, le bot tire au sort les gagnants et annonce les résultats

---

### Tickets

Système de tickets de support avec salons privés.

| Commande | Description |
|---|---|
| `/ticket configurer #catégorie @role_support` | Configure la catégorie et le rôle support |
| `/ticket panel #salon` | Envoie le bouton d'ouverture de ticket dans un salon |
| `/ticket fermer` | Ferme le ticket actuel |
| `/ticket ajouter @membre` | Ajoute un membre au ticket ouvert |

**Fonctionnement :**
1. Un admin envoie le panel avec `/ticket panel`
2. Un membre clique sur "📩 Ouvrir un ticket"
3. Un salon privé `ticket-pseudo` est créé dans la catégorie configurée
4. Seul le membre et le rôle support ont accès
5. `/ticket fermer` supprime le salon après confirmation

---

### Messages planifiés

Envoie automatiquement des messages récurrents dans un salon.

| Commande | Description |
|---|---|
| `/planifié créer <nom> #salon <message> <intervalle_h>` | Crée un message récurrent |
| `/planifié supprimer <nom>` | Supprime un message planifié |
| `/planifié liste` | Affiche tous les messages planifiés |

**Exemple :** Envoyer un rappel toutes les 24h dans `#annonces`.

---

### Compteurs vocaux

Crée des salons vocaux en lecture seule dont le nom affiche en temps réel des statistiques du serveur.

| Commande | Description |
|---|---|
| `/compteur créer <type>` | Crée un compteur (`membres`, `bots`, `salons`, `boosts`) |
| `/compteur supprimer <type>` | Supprime un compteur |
| `/compteur liste` | Affiche les compteurs actifs |

**Exemples de noms générés :**
- `👥 Membres: 42`
- `🤖 Bots: 5`
- `📁 Salons: 18`
- `✨ Boosts: 3`

> Les compteurs se mettent à jour toutes les 10 minutes (limite Discord).

---

### Relais de messages

Reposte automatiquement les messages d'un salon d'un autre serveur vers un salon local, en préservant le nom et l'avatar de l'auteur original via webhook.

| Commande | Description |
|---|---|
| `/relais configurer <guild_id> <channel_id> #destination [afficher_source]` | Configure un relais |
| `/relais liste` | Affiche les relais actifs |
| `/relais supprimer <numéro>` | Supprime un relais |
| `/relais tester <numéro>` | Envoie un message de test |

**Prérequis :**
- Le bot R2D12 doit être **membre des deux serveurs**
- Le bot doit avoir la permission **Gérer les webhooks** dans le salon de destination

**Comment trouver les IDs :**
- Activez le mode développeur dans Discord (Paramètres → Avancé → Mode développeur)
- Clic droit sur un serveur → Copier l'identifiant
- Clic droit sur un salon → Copier l'identifiant

---

### SimRacing — Temps au tour

Leaderboard de temps au tour par voiture et par circuit.

| Commande | Description |
|---|---|
| `/temps enregistrer <voiture> <piste> <temps>` | Enregistre un temps (format `mm:ss.mmm`) |
| `/temps classement <voiture> <piste>` | Affiche le classement pour une combinaison voiture/piste |
| `/temps personnel [@membre]` | Affiche tous les meilleurs temps d'un membre |
| `/temps supprimer <voiture> <piste>` | Supprime son propre temps |

**Format du temps :** `1:32.456` (1 minute, 32 secondes, 456 millisecondes)

---

### SimRacing — Sessions

Organisez des sessions de course et gérez les inscriptions.

| Commande | Description |
|---|---|
| `/session créer <titre> <date> <heure> <sim> <piste>` | Crée une session (date : `JJ/MM/AAAA`, heure : `HH:MM`) |
| `/session liste` | Affiche les prochaines sessions |
| `/session info <id>` | Détails complets d'une session |
| `/session annuler <id>` | Annule une session |
| `/session configurer #salon` | Définit le salon des rappels automatiques (admin) |

**Fonctionnement :**
- Un embed avec les boutons "✅ Je participe" et "❌ Je me retire" est posté
- Les membres s'inscrivent/se désinscrivent via les boutons
- Un rappel est automatiquement envoyé 1 heure avant la session dans le salon configuré

---

### SimRacing — Championnats

Gérez des championnats complets avec points, classements et gestion des incidents.

| Commande | Description |
|---|---|
| `/championnat créer <nom> <système_de_points>` | Crée un championnat |
| `/championnat résultat <nom> <manche>` | Enregistre les résultats d'une manche (formulaire) |
| `/championnat classement <nom>` | Affiche le classement général |
| `/championnat calendrier <nom>` | Affiche toutes les manches |
| `/championnat liste` | Liste tous les championnats |
| `/incident signaler @pilote <raison>` | Signale un incident |
| `/incident pénalité @pilote <type> <raison>` | Applique une pénalité à un pilote |

**Systèmes de points disponibles :**

| Système | Points (P1 → P10) |
|---|---|
| `f1` | 25, 18, 15, 12, 10, 8, 6, 4, 2, 1 |
| `f2` | 25, 18, 15, 12, 10, 8, 6, 4, 2, 1 |
| `indycar` | 50, 40, 35, 32, 30, 28, 26, 24, 22, 20 |
| `simple` | 10, 8, 6, 5, 4, 3, 2, 1 |
| `égal` | 1 point par pilote classé |

> Un bonus de **+1 point** est attribué au pilote ayant réalisé le meilleur tour en course.

---

## Structure des fichiers

```
R2D12/
├── bot.py                  # Point d'entrée principal
├── requirements.txt        # Dépendances Python
├── .env                    # Variables d'environnement (à créer)
├── .env.example            # Modèle du fichier .env
├── cogs/                   # Modules du bot
│   ├── general.py          # Commandes générales + /help
│   ├── moderation.py       # Modération
│   ├── templates.py        # Templates & annonces
│   ├── welcome.py          # Messages de bienvenue
│   ├── birthday.py         # Système d'anniversaires
│   ├── logs.py             # Logs d'audit
│   ├── autoroles.py        # Rôles automatiques
│   ├── reactionroles.py    # Rôles réactions (boutons + emoji)
│   ├── polls.py            # Sondages
│   ├── suggestions.py      # Suggestions
│   ├── levels.py           # Niveaux & XP
│   ├── economy.py          # Économie & boutique
│   ├── giveaways.py        # Giveaways
│   ├── tickets.py          # Tickets de support
│   ├── scheduled.py        # Messages planifiés
│   ├── counters.py         # Compteurs vocaux
│   ├── forwarder.py        # Relais de messages
│   ├── laptimes.py         # Temps au tour SimRacing
│   ├── sessions.py         # Sessions SimRacing
│   └── championship.py     # Championnats SimRacing
└── data/                   # Données persistantes (créé automatiquement)
    ├── warnings.json
    ├── logs.json
    ├── autoroles.json
    ├── reactionroles.json
    ├── emojiroles.json
    ├── polls.json
    ├── suggestions.json
    ├── levels.json
    ├── economy.json
    ├── giveaways.json
    ├── tickets.json
    ├── scheduled.json
    ├── counters.json
    ├── forwarder.json
    ├── laptimes.json
    ├── sessions.json
    ├── birthday.json
    ├── welcome.json
    └── championship.json
```

---

## Données persistantes

Toutes les données sont stockées dans des fichiers JSON dans le dossier `data/`, créé automatiquement au premier lancement. Chaque fichier est organisé par `guild_id` pour permettre au bot de fonctionner sur plusieurs serveurs simultanément.

> **Sauvegarde :** Pour sauvegarder la configuration de votre serveur, copiez simplement le dossier `data/`.

---

*R2D12 — Beep boop !*
