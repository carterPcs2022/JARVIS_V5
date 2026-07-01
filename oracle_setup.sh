#!/bin/bash
# oracle_setup.sh — First-time Oracle Cloud Always Free instance setup
# Run this ONCE on a fresh Ubuntu 22.04 instance.
# Usage: ssh ubuntu@YOUR_IP "bash -s" < oracle_setup.sh

set -e

echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "  Oracle Cloud — JARVIS Setup"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"

echo "[1/5] System update..."
sudo apt-get update -qq && sudo apt-get upgrade -y -qq

echo "[2/5] Installing Docker..."
curl -fsSL https://get.docker.com | sudo sh
sudo usermod -aG docker "$USER"
sudo systemctl enable docker
sudo systemctl start docker

echo "[3/5] Opening firewall ports (8000 + 8080)..."
# Oracle Cloud requires iptables rules (Security List rules set via console)
sudo iptables -I INPUT 6 -m state --state NEW -p tcp --dport 8000 -j ACCEPT
sudo iptables -I INPUT 6 -m state --state NEW -p tcp --dport 8080 -j ACCEPT
sudo netfilter-persistent save 2>/dev/null || \
    sudo sh -c "iptables-save > /etc/iptables/rules.v4" 2>/dev/null || true

echo "[4/5] Creating project directory..."
mkdir -p ~/jarvis/{JARVIS_V5,FRIDAY}

echo "[5/5] Installing Tailscale (private network access)..."
curl -fsSL https://tailscale.com/install.sh | sh
sudo tailscale up --authkey "${TAILSCALE_AUTHKEY:-}" || echo "(Set TAILSCALE_AUTHKEY env var to auto-auth)"

echo ""
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "  Setup complete. Next steps:"
echo "  1. Add ports 8000 + 8080 to Oracle Security List"
echo "  2. Run ./deploy.sh YOUR_ORACLE_IP from your Mac"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
