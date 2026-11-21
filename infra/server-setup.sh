#!/bin/bash
# Toolbox Vault — one-time server setup.
#
# Run ONCE on the Hetzner server as root (paste into the web console).
# It does two things:
#   1. Authorizes the GitHub Actions deploy key for root SSH.
#   2. Creates /opt/toolbox-vault/app/.env with secrets GENERATED ON THE
#      SERVER (openssl) — no secret ever travels through chat or git.
#
# Safe to re-run: an existing .env is never overwritten, and the key is
# only added once. It prints NO secret values.
set -eu

APP_DIR=/opt/toolbox-vault/app
DEPLOY_PUBKEY="ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAIIm+3EMNxWyE/Hz4z0kmAbhe/9kzx5CIOf4WA7V+z4iE github-deploy-toolbox-vault"

mkdir -p "$APP_DIR" /root/.ssh
chmod 700 /root/.ssh
touch /root/.ssh/authorized_keys
chmod 600 /root/.ssh/authorized_keys
if grep -qF "$DEPLOY_PUBKEY" /root/.ssh/authorized_keys; then
  echo "deploy key: already authorized, skipping"
else
  echo "$DEPLOY_PUBKEY" >> /root/.ssh/authorized_keys
  echo "deploy key: authorized"
fi

if [ -f "$APP_DIR/.env" ]; then
  echo ".env: already exists at $APP_DIR/.env — NOT overwriting. Setup already done?"
  exit 0
fi

POSTGRES_PASSWORD="$(openssl rand -hex 24)"
JWT_SECRET="$(openssl rand -hex 64)"
MINIO_ROOT_PASSWORD="$(openssl rand -hex 24)"
MINIO_APP_PASSWORD="$(openssl rand -hex 24)"

umask 077
cat > "$APP_DIR/.env" <<EOF
# Toolbox Vault Website — production environment. Generated on-server
# by infra/server-setup.sh. NEVER commit this file.
APP_DOMAIN=toolboxvault.com
FILES_DOMAIN=files.toolboxvault.com

POSTGRES_USER=toolbox
POSTGRES_PASSWORD=$POSTGRES_PASSWORD
POSTGRES_DB=toolbox_vault
DATABASE_URL=postgresql+psycopg://toolbox:$POSTGRES_PASSWORD@postgres:5432/toolbox_vault

MINIO_ROOT_USER=minioadmin
MINIO_ROOT_PASSWORD=$MINIO_ROOT_PASSWORD
MINIO_APP_USER=toolbox-app
MINIO_APP_PASSWORD=$MINIO_APP_PASSWORD
MINIO_ENDPOINT=http://minio:9000
MINIO_BUCKET=toolbox-vault
S3_PUBLIC_ENDPOINT=https://files.toolboxvault.com

JWT_SECRET=$JWT_SECRET
JWT_ALGORITHM=HS256
ACCESS_TOKEN_EXPIRE_MINUTES=30
REFRESH_TOKEN_EXPIRE_DAYS=30
APP_BASE_URL=https://toolboxvault.com

VITE_API_URL=/api
EOF
chmod 600 "$APP_DIR/.env"
echo ".env: created at $APP_DIR/.env ($(wc -l < "$APP_DIR/.env") lines, secrets generated on this server)"
echo "Setup complete. Next: add the GitHub repo secrets (DEPLOY_HOST, DEPLOY_SSH_KEY), then push to main."
