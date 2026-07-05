#!/bin/bash
# Add a device to STARK-NET. Usage: sudo bash add_device.sh iphone
set -e

DEVICE_NAME=$1
if [ -z "$DEVICE_NAME" ]; then
    echo "Usage: $0 <device_name>"
    echo "Known names: macbook, iphone, ipad, raybans, friday (anything else gets .99)"
    exit 1
fi

STARK_NET_IP="10.13.37"

declare -A DEVICE_IPS=(
    ["macbook"]="2"
    ["iphone"]="3"
    ["ipad"]="4"
    ["raybans"]="5"
    ["friday"]="10"
)

DEVICE_IP="${STARK_NET_IP}.${DEVICE_IPS[$DEVICE_NAME]:-99}"

DEVICE_PRIVATE=$(wg genkey)
DEVICE_PUBLIC=$(echo "$DEVICE_PRIVATE" | wg pubkey)

cat >> /etc/wireguard/stark0.conf << EOF

[Peer]
# ${DEVICE_NAME}
PublicKey = ${DEVICE_PUBLIC}
AllowedIPs = ${DEVICE_IP}/32
EOF

JARVIS_PUBLIC=$(cat /etc/wireguard/server_public.key)
SERVER_ENDPOINT="${SERVER_IP:-YOUR_SERVER_IP}:51820"

cat > "${DEVICE_NAME}_stark_net.conf" << EOF
[Interface]
PrivateKey = ${DEVICE_PRIVATE}
Address = ${DEVICE_IP}/24
DNS = 1.1.1.1

[Peer]
PublicKey = ${JARVIS_PUBLIC}
Endpoint = ${SERVER_ENDPOINT}
AllowedIPs = 10.13.37.0/24
PersistentKeepalive = 25
EOF

wg addconf stark0 <(wg-quick strip stark0) 2>/dev/null || systemctl restart wg-quick@stark0

echo "Device '${DEVICE_NAME}' added to STARK-NET"
echo "IP: ${DEVICE_IP}"
echo "Config saved to: ${DEVICE_NAME}_stark_net.conf"
if [ "$SERVER_ENDPOINT" = "YOUR_SERVER_IP:51820" ]; then
    echo "NOTE: set SERVER_IP=<your server's public IP> before running this script for a usable config."
fi

if command -v qrencode >/dev/null; then
    qrencode -t ansiutf8 < "${DEVICE_NAME}_stark_net.conf"
fi
