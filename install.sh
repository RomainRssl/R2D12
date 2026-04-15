#!/bin/bash
# ============================================================
#  R2D12 — Script d'installation pour VPS Linux (Ubuntu/Debian)
# ============================================================
set -e

GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
NC='\033[0m'

info()    { echo -e "${GREEN}[✓]${NC} $1"; }
warning() { echo -e "${YELLOW}[!]${NC} $1"; }
error()   { echo -e "${RED}[✗]${NC} $1"; exit 1; }

echo ""
echo "╔══════════════════════════════════════╗"
echo "║     Installation de R2D12 Bot        ║"
echo "╚══════════════════════════════════════╝"
echo ""

# ── 1. Vérification des droits ────────────────────────────────
if [ "$EUID" -ne 0 ]; then
    error "Lancez ce script en tant que root : sudo bash install.sh"
fi

# ── 2. Mise à jour du système ─────────────────────────────────
info "Mise à jour des paquets..."
apt-get update -qq && apt-get upgrade -y -qq

# ── 3. Installation de Python ─────────────────────────────────
info "Installation de Python 3.11+..."
apt-get install -y -qq python3 python3-pip python3-venv git curl

PYTHON_VERSION=$(python3 --version 2>&1 | awk '{print $2}')
info "Python $PYTHON_VERSION installé."

# ── 4. Création de l'utilisateur dédié ───────────────────────
if ! id "r2d12" &>/dev/null; then
    useradd -r -m -d /opt/r2d12 -s /bin/bash r2d12
    info "Utilisateur système 'r2d12' créé."
else
    warning "L'utilisateur 'r2d12' existe déjà."
fi

# ── 5. Clone ou mise à jour du dépôt ─────────────────────────
INSTALL_DIR="/opt/r2d12"

if [ -d "$INSTALL_DIR/.git" ]; then
    warning "Dépôt existant détecté — mise à jour..."
    cd "$INSTALL_DIR"
    sudo -u r2d12 git pull origin main
else
    info "Clonage du dépôt..."
    git clone https://github.com/romainrssl/r2d12.git "$INSTALL_DIR"
    chown -R r2d12:r2d12 "$INSTALL_DIR"
fi

cd "$INSTALL_DIR"

# ── 6. Environnement virtuel Python ──────────────────────────
info "Création de l'environnement virtuel..."
sudo -u r2d12 python3 -m venv "$INSTALL_DIR/venv"
sudo -u r2d12 "$INSTALL_DIR/venv/bin/pip" install --upgrade pip -q
sudo -u r2d12 "$INSTALL_DIR/venv/bin/pip" install -r requirements.txt -q
info "Dépendances installées."

# ── 7. Création du dossier data ───────────────────────────────
sudo -u r2d12 mkdir -p "$INSTALL_DIR/data"
info "Dossier data/ prêt."

# ── 8. Configuration du fichier .env ─────────────────────────
if [ ! -f "$INSTALL_DIR/.env" ]; then
    echo ""
    echo "══════════════════════════════════════════"
    echo "  Configuration du bot"
    echo "══════════════════════════════════════════"
    read -rp "  Token Discord du bot : " DISCORD_TOKEN
    read -rp "  ID du serveur (laisser vide pour sync globale) : " GUILD_ID

    sudo -u r2d12 bash -c "cat > $INSTALL_DIR/.env" <<EOF
DISCORD_TOKEN=${DISCORD_TOKEN}
GUILD_ID=${GUILD_ID}
EOF
    chmod 600 "$INSTALL_DIR/.env"
    info "Fichier .env créé."
else
    warning "Fichier .env existant conservé."
fi

# ── 9. Service systemd ────────────────────────────────────────
info "Installation du service systemd..."

cat > /etc/systemd/system/r2d12.service <<EOF
[Unit]
Description=R2D12 Discord Bot
After=network.target
StartLimitIntervalSec=60
StartLimitBurst=5

[Service]
Type=simple
User=r2d12
WorkingDirectory=${INSTALL_DIR}
ExecStart=${INSTALL_DIR}/venv/bin/python bot.py
Restart=on-failure
RestartSec=5s
StandardOutput=journal
StandardError=journal
SyslogIdentifier=r2d12

[Install]
WantedBy=multi-user.target
EOF

systemctl daemon-reload
systemctl enable r2d12
systemctl start r2d12

sleep 2

# ── 10. Résultat final ────────────────────────────────────────
echo ""
echo "══════════════════════════════════════════"
if systemctl is-active --quiet r2d12; then
    echo -e "  ${GREEN}✓ R2D12 est en ligne !${NC}"
else
    echo -e "  ${RED}✗ Le bot n'a pas démarré — vérifiez les logs ci-dessous${NC}"
fi
echo "══════════════════════════════════════════"
echo ""
echo "  Commandes utiles :"
echo "    sudo systemctl status r2d12      → État du bot"
echo "    sudo systemctl restart r2d12     → Redémarrer"
echo "    sudo systemctl stop r2d12        → Arrêter"
echo "    sudo journalctl -u r2d12 -f      → Logs en direct"
echo ""
