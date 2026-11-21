#!/usr/bin/env bash
set -euo pipefail

APP_DIR="/opt/activity_board_web"
SERVICE_FILE="/etc/systemd/system/activity-board.service"
NGINX_SITE="/etc/nginx/sites-available/activity-board"

sudo apt-get update
sudo apt-get install -y python3 python3-venv python3-pip nginx

sudo mkdir -p "$APP_DIR"
sudo chown -R "$USER":"$USER" "$APP_DIR"

cd "$APP_DIR"
python3 -m venv .venv
source .venv/bin/activate
pip install --upgrade pip
pip install -r requirements.txt

sudo cp deploy/systemd/activity-board.service "$SERVICE_FILE"
sudo systemctl daemon-reload
sudo systemctl enable activity-board.service
sudo systemctl restart activity-board.service

sudo cp deploy/nginx/activity-board.conf "$NGINX_SITE"
sudo ln -sf "$NGINX_SITE" /etc/nginx/sites-enabled/activity-board
sudo rm -f /etc/nginx/sites-enabled/default
sudo nginx -t
sudo systemctl restart nginx

echo "bootstrap complete"
