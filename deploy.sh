#!/bin/bash
# deploy.sh — Deploy JARVIS V5 + FRIDAY to Oracle Cloud Always Free
# Usage: ./deploy.sh [oracle-public-ip]

set -e

ORACLE_IP="${1:-YOUR_ORACLE_IP}"
ORACLE_USER="${ORACLE_USER:-ubuntu}"
SSH_KEY="${SSH_KEY:-~/.ssh/oracle_key}"
REMOTE_DIR="/home/${ORACLE_USER}/jarvis"

echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "  JARVIS V5 + FRIDAY — Oracle Deployment"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"

echo "[1/4] Syncing code to Oracle ($ORACLE_IP)..."
rsync -avz --exclude='.env' --exclude='__pycache__' --exclude='*.pyc' \
    --exclude='memory/' --exclude='backups/' --exclude='.jarvis_scatter/' \
    --exclude='config/gmail_credentials.json' --exclude='config/token.json' \
    -e "ssh -i $SSH_KEY" \
    . "${ORACLE_USER}@${ORACLE_IP}:${REMOTE_DIR}/JARVIS_V5/"

rsync -avz --exclude='.env' --exclude='__pycache__' --exclude='memory/' \
    -e "ssh -i $SSH_KEY" \
    ../FRIDAY/ "${ORACLE_USER}@${ORACLE_IP}:${REMOTE_DIR}/FRIDAY/"

echo "[2/4] Uploading .env files (never committed to git)..."
scp -i "$SSH_KEY" .env "${ORACLE_USER}@${ORACLE_IP}:${REMOTE_DIR}/JARVIS_V5/.env"
scp -i "$SSH_KEY" ../FRIDAY/.env "${ORACLE_USER}@${ORACLE_IP}:${REMOTE_DIR}/FRIDAY/.env"

echo "[3/4] Building and starting containers on Oracle..."
ssh -i "$SSH_KEY" "${ORACLE_USER}@${ORACLE_IP}" bash << EOF
  cd ${REMOTE_DIR}/JARVIS_V5
  docker compose pull --quiet || true
  docker compose build --no-cache
  docker compose up -d
  docker compose ps
EOF

echo "[4/4] Health checks..."
sleep 5
ssh -i "$SSH_KEY" "${ORACLE_USER}@${ORACLE_IP}" bash << EOF
  echo "JARVIS:" && curl -sf http://localhost:8000/health && echo " ✓" || echo " ✗"
  echo "FRIDAY:" && curl -sf http://localhost:8080/health && echo " ✓" || echo " ✗"
EOF

echo ""
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "  JARVIS: http://${ORACLE_IP}:8000"
echo "  FRIDAY: http://${ORACLE_IP}:8080"
echo "  HUD:    http://${ORACLE_IP}:8000/hud"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
