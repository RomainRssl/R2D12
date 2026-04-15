#!/bin/bash
# ============================================================
#  R2D12 — Script de mise à jour
# ============================================================
set -e

GREEN='\033[0;32m'
NC='\033[0m'
info() { echo -e "${GREEN}[✓]${NC} $1"; }

INSTALL_DIR="/opt/r2d12"

echo ""
echo "╔══════════════════════════════════════╗"
echo "║       Mise à jour de R2D12           ║"
echo "╚══════════════════════════════════════╝"
echo ""

if [ "$EUID" -ne 0 ]; then
    echo "Lancez ce script en tant que root : sudo bash update.sh"
    exit 1
fi

info "Arrêt du bot..."
systemctl stop r2d12

info "Récupération des dernières modifications..."
cd "$INSTALL_DIR"
sudo -u r2d12 git pull origin main

info "Mise à jour des dépendances..."
sudo -u r2d12 "$INSTALL_DIR/venv/bin/pip" install -r requirements.txt -q

info "Redémarrage du bot..."
systemctl start r2d12

sleep 2

if systemctl is-active --quiet r2d12; then
    echo -e "\n  ${GREEN}✓ R2D12 mis à jour et redémarré avec succès !${NC}\n"
else
    echo -e "\n  Erreur au démarrage. Consultez : sudo journalctl -u r2d12 -f\n"
fi
