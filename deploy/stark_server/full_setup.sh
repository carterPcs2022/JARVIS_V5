#!/bin/bash
# Complete Stark Server setup on Oracle Cloud (or any Ubuntu 22.04+ box).
# Runs: JARVIS + FRIDAY + Home Assistant + Ollama + Nginx + SSL + monitoring
# + STARK-NET. Idempotent-ish — safe to re-run, but review before running on
# a machine that already has other services on ports 80/443/8000/8080/8123.
set -e

echo "╔══════════════════════════════════════════════════════╗"
echo "║           STARK SERVER — FULL INITIALIZATION        ║"
echo "╚══════════════════════════════════════════════════════╝"

if [ "$(id -u)" -ne 0 ]; then
    echo "Run this as root (sudo bash full_setup.sh)"
    exit 1
fi

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# ── System updates ────────────────────────────────────────────────────────
apt-get update -y && apt-get upgrade -y
apt-get install -y \
    python3 python3-pip python3-venv git curl wget \
    nginx certbot python3-certbot-nginx \
    ufw fail2ban net-tools htop \
    docker.io docker-compose \
    wireguard wireguard-tools \
    prometheus-node-exporter \
    qrencode

# ── Firewall (UFW) ────────────────────────────────────────────────────────
ufw default deny incoming
ufw default allow outgoing
ufw allow ssh
ufw allow 80/tcp
ufw allow 443/tcp
ufw allow 51820/udp
ufw allow from "${STARK_NET_SUBNET:-10.13.37.0/24}"
ufw --force enable

iptables -I INPUT -p tcp --dport 80 -j ACCEPT
iptables -I INPUT -p tcp --dport 443 -j ACCEPT
iptables -I INPUT -p udp --dport 51820 -j ACCEPT
netfilter-persistent save 2>/dev/null || true

# ── Fail2ban ───────────────────────────────────────────────────────────────
cat > /etc/fail2ban/jail.local << 'EOF'
[DEFAULT]
bantime  = 3600
findtime = 600
maxretry = 5

[sshd]
enabled = true

[nginx-http-auth]
enabled = true

[nginx-limit-req]
enabled = true
EOF
systemctl enable fail2ban
systemctl restart fail2ban

# ── CrowdSec (best-effort — skip on failure rather than aborting setup) ──
(curl -s https://packagecloud.io/install/repositories/crowdsec/crowdsec/script.deb.sh | bash \
    && apt-get install -y crowdsec \
    && systemctl enable crowdsec) || echo "CrowdSec install failed — skipping, continuing setup."

# ── JARVIS ─────────────────────────────────────────────────────────────────
cd /home/ubuntu
git clone https://github.com/carterPcs2022/JARVIS_V5.git 2>/dev/null || (cd JARVIS_V5 && git pull)
cd JARVIS_V5
python3 -m venv venv
source venv/bin/activate
pip install --upgrade pip
pip install -r requirements.txt
deactivate

cat > /etc/systemd/system/jarvis.service << 'EOF'
[Unit]
Description=JARVIS V5 — Just A Rather Very Intelligent System
After=network.target
Wants=network-online.target

[Service]
Type=simple
User=ubuntu
WorkingDirectory=/home/ubuntu/JARVIS_V5
Environment=PATH=/home/ubuntu/JARVIS_V5/venv/bin
EnvironmentFile=/home/ubuntu/JARVIS_V5/.env
ExecStart=/home/ubuntu/JARVIS_V5/venv/bin/uvicorn server.api:app --host 127.0.0.1 --port 8000
Restart=always
RestartSec=5
StandardOutput=journal
StandardError=journal

[Install]
WantedBy=multi-user.target
EOF

# ── FRIDAY (optional — skip cleanly if the repo doesn't exist/isn't public) ─
cd /home/ubuntu
git clone https://github.com/carterPcs2022/FRIDAY.git 2>/dev/null || true
if [ -d "FRIDAY" ]; then
    cd FRIDAY
    python3 -m venv venv
    source venv/bin/activate
    pip install -r requirements.txt
    deactivate

    cat > /etc/systemd/system/friday.service << 'EOF'
[Unit]
Description=FRIDAY — Backup AI Assistant
After=network.target jarvis.service

[Service]
Type=simple
User=ubuntu
WorkingDirectory=/home/ubuntu/FRIDAY
EnvironmentFile=/home/ubuntu/FRIDAY/.env
ExecStart=/home/ubuntu/FRIDAY/venv/bin/gunicorn server:app --bind 127.0.0.1:8080
Restart=always
RestartSec=10

[Install]
WantedBy=multi-user.target
EOF
fi

# ── Ollama (free local AI — no API costs) ─────────────────────────────────
curl -fsSL https://ollama.ai/install.sh | sh
systemctl enable ollama
systemctl start ollama
sleep 5
ollama pull llama3 || true
ollama pull nomic-embed-text || true
ollama pull mistral || true

# ── Home Assistant ─────────────────────────────────────────────────────────
mkdir -p /home/ubuntu/homeassistant
docker rm -f homeassistant 2>/dev/null || true
docker run -d \
    --name homeassistant \
    --restart unless-stopped \
    --network=host \
    -e TZ="${TIMEZONE:-America/New_York}" \
    -v /home/ubuntu/homeassistant:/config \
    ghcr.io/home-assistant/home-assistant:stable

# ── Nginx reverse proxy ────────────────────────────────────────────────────
# YOUR_DOMAIN_HERE must be replaced before this config is usable with SSL.
DOMAIN="${DOMAIN:-YOUR_DOMAIN_HERE}"
sed "s/YOUR_DOMAIN_HERE/${DOMAIN}/g" > /etc/nginx/sites-available/stark << NGINX
limit_req_zone \$binary_remote_addr zone=jarvis:10m rate=30r/m;

server {
    listen 80;
    server_name YOUR_DOMAIN_HERE;
    return 301 https://\$server_name\$request_uri;
}

server {
    listen 443 ssl http2;
    server_name YOUR_DOMAIN_HERE;

    ssl_certificate     /etc/letsencrypt/live/YOUR_DOMAIN_HERE/fullchain.pem;
    ssl_certificate_key /etc/letsencrypt/live/YOUR_DOMAIN_HERE/privkey.pem;
    ssl_protocols       TLSv1.3;
    ssl_ciphers         HIGH:!aNULL:!MD5;
    ssl_session_cache   shared:SSL:10m;

    add_header Strict-Transport-Security "max-age=31536000" always;
    add_header X-Frame-Options DENY;
    add_header X-Content-Type-Options nosniff;
    add_header X-XSS-Protection "1; mode=block";
    add_header Content-Security-Policy "default-src 'self'";

    location / {
        limit_req zone=jarvis burst=10 nodelay;
        proxy_pass         http://127.0.0.1:8000;
        proxy_http_version 1.1;
        proxy_set_header   Upgrade \$http_upgrade;
        proxy_set_header   Connection "upgrade";
        proxy_set_header   Host \$host;
        proxy_set_header   X-Real-IP \$remote_addr;
        proxy_read_timeout 300;
    }

    location /friday/ {
        proxy_pass http://127.0.0.1:8080/;
        proxy_set_header Host \$host;
    }

    location /homeassistant/ {
        proxy_pass http://127.0.0.1:8123/;
        proxy_set_header Host \$host;
        proxy_http_version 1.1;
        proxy_set_header Upgrade \$http_upgrade;
        proxy_set_header Connection "upgrade";
    }
}
NGINX

ln -sf /etc/nginx/sites-available/stark /etc/nginx/sites-enabled/
rm -f /etc/nginx/sites-enabled/default
nginx -t && systemctl restart nginx

if [ "$DOMAIN" != "YOUR_DOMAIN_HERE" ]; then
    certbot --nginx -d "$DOMAIN" --non-interactive --agree-tos -m "${CERTBOT_EMAIL:-admin@$DOMAIN}" || \
        echo "certbot failed — check DNS points at this server, then run certbot manually."
else
    echo "Set DOMAIN=yourdomain.com before running this script to get SSL configured automatically."
fi

# ── Monitoring: Prometheus + Grafana ───────────────────────────────────────
mkdir -p /etc/prometheus
cp "$SCRIPT_DIR/../monitoring/prometheus.yml" /etc/prometheus/prometheus.yml 2>/dev/null || true

docker rm -f prometheus 2>/dev/null || true
docker run -d --name prometheus --restart unless-stopped \
    -p 127.0.0.1:9090:9090 -v /etc/prometheus:/etc/prometheus prom/prometheus

docker rm -f grafana 2>/dev/null || true
docker run -d --name grafana --restart unless-stopped -p 127.0.0.1:3000:3000 grafana/grafana

echo "Grafana dashboard at http://localhost:3000 (default admin/admin — change immediately)"

# ── STARK-NET ───────────────────────────────────────────────────────────────
bash "$SCRIPT_DIR/../stark_net/setup.sh"

# ── Start everything ─────────────────────────────────────────────────────────
systemctl daemon-reload
systemctl enable jarvis
systemctl start jarvis
if [ -f /etc/systemd/system/friday.service ]; then
    systemctl enable friday
    systemctl start friday
fi

echo ""
echo "╔══════════════════════════════════════════════════════╗"
echo "║              STARK SERVER ONLINE                    ║"
echo "╠══════════════════════════════════════════════════════╣"
echo "║  JARVIS:         http://localhost:8000              ║"
echo "║  FRIDAY:         http://localhost:8080              ║"
echo "║  Home Assistant: http://localhost:8123              ║"
echo "║  Grafana:        http://localhost:3000              ║"
echo "║  STARK-NET:      10.13.37.1                          ║"
echo "╚══════════════════════════════════════════════════════╝"
