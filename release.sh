#!/usr/bin/env bash
set -euo pipefail

NAMESPACE="malayh"
BACKEND_IMAGE="$NAMESPACE/odin-backend"
POSTGRES_IMAGE="$NAMESPACE/odin-postgres"
ROOT="$(cd "$(dirname "$0")" && pwd)"
OUT="$ROOT/.release"

die() { printf 'error: %s\n' "$*" >&2; exit 1; }

[ "$#" -eq 1 ] || die "usage: ./release.sh vX.Y.Z"
VER="${1#v}"
TAG_GIT="v$VER"

command -v docker >/dev/null || die "docker is required"
command -v gh >/dev/null || die "gh (GitHub CLI) is required"
command -v uv >/dev/null || die "uv is required"
git diff --quiet && git diff --cached --quiet || die "working tree is dirty; commit or stash first"

printf 'Releasing %s (images tagged %s and latest)\n' "$TAG_GIT" "$VER"
rm -rf "$OUT"
mkdir -p "$OUT"

printf '==> Building and pushing %s\n' "$POSTGRES_IMAGE"
docker build --platform linux/amd64 \
  -t "$POSTGRES_IMAGE:$VER" -t "$POSTGRES_IMAGE:latest" "$ROOT/docker/postgres"
docker push "$POSTGRES_IMAGE:$VER"
docker push "$POSTGRES_IMAGE:latest"

printf '==> Building and pushing %s\n' "$BACKEND_IMAGE"
docker build --platform linux/amd64 \
  -f "$ROOT/backend/Dockerfile" \
  -t "$BACKEND_IMAGE:$VER" -t "$BACKEND_IMAGE:latest" "$ROOT"
docker push "$BACKEND_IMAGE:$VER"
docker push "$BACKEND_IMAGE:latest"

printf '==> Building odin-linux-x86_64 (PyInstaller, linux/amd64)\n'
docker run --rm --platform linux/amd64 \
  -e HOST_UID="$(id -u)" -e HOST_GID="$(id -g)" \
  -v "$ROOT":/src -w /src python:3.12-slim sh -c '
  set -e
  apt-get update -qq && apt-get install -y -qq --no-install-recommends binutils
  pip install --quiet uv
  uv sync --frozen --no-dev --package odin-cli
  uv pip install --quiet pyinstaller
  uv run --no-sync pyinstaller --onefile --name odin \
    --collect-all typer --collect-all rich --collect-submodules odin_cli --paths cli \
    --distpath /src/.release/dist --workpath /src/.release/work --specpath /src/.release \
    cli/odin_cli/main.py
  chown -R "$HOST_UID:$HOST_GID" /src/.release
'
cp "$OUT/dist/odin" "$OUT/odin-linux-x86_64"
"$OUT/odin-linux-x86_64" --help >/dev/null || die "binary smoke test failed"

printf '==> Stamping compose with %s\n' "$VER"
sed -e "s#$BACKEND_IMAGE:latest#$BACKEND_IMAGE:$VER#g" \
    -e "s#$POSTGRES_IMAGE:latest#$POSTGRES_IMAGE:$VER#g" \
    "$ROOT/docker-compose.prod.yaml" > "$OUT/docker-compose.prod.yaml"

printf '==> Tagging and creating GitHub release\n'
git tag "$TAG_GIT"
git push origin "$TAG_GIT"
gh release create "$TAG_GIT" \
  "$OUT/odin-linux-x86_64" \
  "$OUT/docker-compose.prod.yaml" \
  "$ROOT/install.sh" \
  --title "$TAG_GIT" \
  --notes "Install: \`curl -fsSL https://raw.githubusercontent.com/$NAMESPACE/odin/main/install.sh | bash\`"

printf 'Done: %s\n' "$TAG_GIT"
