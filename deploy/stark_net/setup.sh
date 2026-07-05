#!/bin/bash
# STARK-NET — private WireGuard VPN. Connects your devices through your own
# server as the hub. Run this ONCE on the server (Oracle Cloud, home
# hardware, any Ubuntu box) — not on Render, which doesn't allow raw
# WireGuard/iptables access.
set -e

echo "╔══════════════════════════════════════════╗"
echo "║        STARK-NET INITIALIZATION          ║"
echo "╚══════════════════════════════════════════╝"

if [ "$(id -u)" -ne 0 ]; then
    echo "Run this as root (sudo bash setup.sh)"
    exit 1
fi

apt-get update -y
apt-get install -y wireguard wireguard-tools openssl qrencode

mkdir -p /etc/wireguard
umask 077
wg genkey | tee /etc/wireguard/server_private.key | wg pubkey > /etc/wireguard/server_public.key

SERVER_PRIVATE=$(cat /etc/wireguard/server_private.key)
SERVER_PUBLIC=$(cat /etc/wireguard/server_public.key)

# Detect the primary outbound interface instead of hardcoding eth0 — varies
# by cloud provider (ens3, enp0s3, etc).
OUT_IFACE=$(ip route | awk '/^default/ {print $5; exit}')
OUT_IFACE="${OUT_IFACE:-eth0}"

cat > /etc/wireguard/stark0.conf << EOF
[Interface]
Address = 10.13.37.1/24
ListenPort = 51820
PrivateKey = ${SERVER_PRIVATE}
PostUp = iptables -A FORWARD -i stark0 -j ACCEPT; iptables -t nat -A POSTROUTING -o ${OUT_IFACE} -j MASQUERADE
PostDown = iptables -D FORWARD -i stark0 -j ACCEPT; iptables -t nat -D POSTROUTING -o ${OUT_IFACE} -j MASQUERADE
DNS = 1.1.1.1
EOF

echo "net.ipv4.ip_forward=1" >> /etc/sysctl.conf
sysctl -p

systemctl enable wg-quick@stark0
systemctl start wg-quick@stark0

echo ""
echo "STARK-NET online. Server public key: ${SERVER_PUBLIC}"
echo "Add devices with: bash add_device.sh <name>"
