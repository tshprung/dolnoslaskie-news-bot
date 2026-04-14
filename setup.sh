#!/bin/bash
set -e

REPO_URL="$1"
INSTALL_DIR="/opt/german_news"

echo "=== Installing dependencies ==="
sudo apt-get update -q
sudo apt-get install -y python3 python3-venv python3-pip git

echo "=== Cloning repo ==="
sudo mkdir -p "$INSTALL_DIR"
sudo chown "$USER":"$USER" "$INSTALL_DIR"
if [ ! -d "$INSTALL_DIR/.git" ]; then
  git clone "$REPO_URL" "$INSTALL_DIR"
else
  echo "Directory already exists — pull manually: cd $INSTALL_DIR && git pull"
fi

echo "=== Creating virtualenv ==="
python3 -m venv "$INSTALL_DIR/venv"
"$INSTALL_DIR/venv/bin/pip" install -q -r "$INSTALL_DIR/requirements.txt"

echo "=== Copy .env ==="
if [ ! -f "$INSTALL_DIR/.env" ]; then
  cp "$INSTALL_DIR/.env.example" "$INSTALL_DIR/.env"
fi
echo ""
echo ">>> Edit $INSTALL_DIR/.env with your Telegram + OpenAI secrets, then:"
echo "    chmod +x $INSTALL_DIR/run.sh"
echo "    crontab -e"
echo "    20,50 * * * * $INSTALL_DIR/run.sh"
