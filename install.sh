#!/bin/sh
set -eu

REPO="malayh/odin"
ODIN_DIR="${ODIN_HOME:-$HOME/.odin}"
BIN_DIR="$ODIN_DIR/bin"
COMPOSE_FILE="$ODIN_DIR/docker-compose.prod.yaml"
ENV_FILE="$ODIN_DIR/.env"
CONFIG_FILE="$ODIN_DIR/config.yaml"
SERVER_URL="http://localhost:8000"
COMPOSE_URL="https://raw.githubusercontent.com/$REPO/main/docker-compose.prod.yaml"
BINARY_URL="https://github.com/$REPO/releases/download/cli/odin-linux-x86_64"

say() { printf '%s\n' "$*"; }
err() { printf 'error: %s\n' "$*" >&2; }
die() { err "$*"; exit 1; }

need() { command -v "$1" >/dev/null 2>&1 || die "missing required command: $1"; }

rand_hex() {
  n="$1"
  if command -v openssl >/dev/null 2>&1; then
    openssl rand -hex "$n"
  else
    LC_ALL=C tr -dc 'a-f0-9' < /dev/urandom | dd bs=1 count=$((n * 2)) 2>/dev/null
  fi
}

prompt() {
  _msg="$1"; _var="$2"
  printf '%s' "$_msg" > /dev/tty
  IFS= read -r "$_var" < /dev/tty
}

say "Installing Odin into $ODIN_DIR"

need docker
need curl
if docker compose version >/dev/null 2>&1; then
  DC="docker compose"
elif command -v docker-compose >/dev/null 2>&1; then
  DC="docker-compose"
else
  die "docker compose is required (Docker Compose v2 plugin or docker-compose)"
fi
docker info >/dev/null 2>&1 || die "the Docker daemon is not running"

mkdir -p "$BIN_DIR" "$ODIN_DIR/.data/postgres" "$ODIN_DIR/.data/minio"

say "Downloading docker-compose.prod.yaml"
curl -fsSL "$COMPOSE_URL" -o "$COMPOSE_FILE"

say "Downloading odin CLI binary"
curl -fsSL "$BINARY_URL" -o "$BIN_DIR/odin"
chmod +x "$BIN_DIR/odin"

if [ ! -f "$ENV_FILE" ]; then
  say ""
  say "First-time setup — provide your API keys (stored in $ENV_FILE)."
  prompt "OpenRouter API key: " OPENROUTER_API_KEY
  prompt "OpenAI API key (embeddings): " OPENAI_API_KEY

  PG_PW="$(rand_hex 32)"
  MINIO_USER="$(rand_hex 12)"
  MINIO_PW="$(rand_hex 24)"

  umask 077
  cat > "$ENV_FILE" <<EOF
DATABASE_URL=postgresql+psycopg://odin:$PG_PW@postgres:5432/odin
AGE_GRAPH=odin
S3_ENDPOINT_URL=http://minio:9000
S3_BUCKET=odin
S3_REGION=us-east-1
AWS_ACCESS_KEY_ID=$MINIO_USER
AWS_SECRET_ACCESS_KEY=$MINIO_PW
POSTGRES_PASSWORD=$PG_PW
OPENROUTER_API_KEY=$OPENROUTER_API_KEY
OPENROUTER_BASE_URL=https://openrouter.ai/api/v1
ANSWER_MODEL=z-ai/glm-5.2
OPENAI_API_KEY=$OPENAI_API_KEY
EMBEDDING_MODEL=text-embedding-3-small
EMBEDDING_DIMENSIONS=1536
EOF
  umask 022
  say "Wrote $ENV_FILE"
else
  say "Keeping existing $ENV_FILE"
fi

say "Pulling images"
$DC -f "$COMPOSE_FILE" --env-file "$ENV_FILE" pull

say "Starting Odin (Postgres -> migrations -> API + worker)"
$DC -f "$COMPOSE_FILE" --env-file "$ENV_FILE" up -d

if [ -f "$CONFIG_FILE" ] && grep -Eq '^token:[[:space:]]*[^[:space:]]' "$CONFIG_FILE"; then
  say "CLI already logged in — skipping admin bootstrap"
else
  say ""
  prompt "Admin email for the initial account: " ADMIN_EMAIL
  [ -n "$ADMIN_EMAIL" ] || die "admin email is required"
  say "Creating initial admin and minting a token"
  TOKEN="$($DC -f "$COMPOSE_FILE" --env-file "$ENV_FILE" run --rm -T api python -m odin.seed "$ADMIN_EMAIL" | tr -d '\r' | tail -n1)"
  [ -n "$TOKEN" ] || die "failed to obtain admin token from seed"
  "$BIN_DIR/odin" login --token "$TOKEN" --server "$SERVER_URL"
fi

case ":$PATH:" in
  *":$BIN_DIR:"*) ;;
  *)
    say ""
    say "The odin binary is at $BIN_DIR/odin but that directory is not on your PATH."
    LINE="export PATH=\"$BIN_DIR:\$PATH\""
    prompt "Append it to your shell rc now? [y/N] " ADD_PATH
    case "$ADD_PATH" in
      y|Y|yes|YES)
        for RC in "$HOME/.bashrc" "$HOME/.zshrc"; do
          [ -f "$RC" ] || continue
          grep -qF "$LINE" "$RC" || printf '\n%s\n' "$LINE" >> "$RC"
        done
        say "Added. Open a new shell or run: $LINE"
        ;;
      *)
        say "Add this to your shell rc to use 'odin' directly:"
        say "  $LINE"
        ;;
    esac
    ;;
esac

say ""
say "Odin is up. Try:"
say "  odin ingest --dir ./docs"
say "  odin ask \"what is in my knowledge base?\""
