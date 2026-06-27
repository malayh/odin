#!/usr/bin/env bash
set -euo pipefail

NAMESPACE="malayh"
REPO="$NAMESPACE/odin"
BACKEND_IMAGE="$NAMESPACE/odin-backend"
POSTGRES_IMAGE="$NAMESPACE/odin-postgres"
ROOT="$(cd "$(dirname "$0")" && pwd)"
OUT="$ROOT/.release"
COMPOSE="$ROOT/docker-compose.prod.yaml"

die() { printf 'error: %s\n' "$*" >&2; exit 1; }

usage() {
  cat >&2 <<EOF
usage: ./release.sh <target> vX.Y.Z

targets:
  cli        build + publish the CLI binary (rolling 'cli' GitHub release)
  backend    build + push $BACKEND_IMAGE, pin it in $COMPOSE
  postgres   build + push $POSTGRES_IMAGE, pin it in $COMPOSE
  all        cli + backend + postgres at the same version
EOF
  exit 2
}

[ "$#" -eq 2 ] || usage
TARGET="$1"
VER="${2#v}"
[ -n "$VER" ] || usage
case "$TARGET" in cli|backend|postgres|all) ;; *) usage ;; esac

command -v docker >/dev/null || die "docker is required"
command -v git >/dev/null || die "git is required"
case "$TARGET" in
  cli|all) command -v gh >/dev/null || die "gh (GitHub CLI) is required for the cli binary" ;;
esac
git diff --quiet && git diff --cached --quiet || die "working tree is dirty; commit or stash first"

PUSH_REFS=""
COMPOSE_CHANGED=0

pin_compose() {
  _img="$1"
  sed -i "s#${_img}:[^[:space:]\"]*#${_img}:${VER}#g" "$COMPOSE"
  COMPOSE_CHANGED=1
}

build_image() {
  local image="$1" context="$2" dockerfile="${3:-}"
  local -a df=()
  [ -n "$dockerfile" ] && df=(-f "$dockerfile")
  printf '==> Building and pushing %s:%s\n' "$image" "$VER"
  docker build --platform linux/amd64 "${df[@]}" -t "$image:$VER" -t "$image:latest" "$context"
  docker push "$image:$VER"
  docker push "$image:latest"
}

release_backend() {
  build_image "$BACKEND_IMAGE" "$ROOT" "$ROOT/backend/Dockerfile"
  pin_compose "$BACKEND_IMAGE"
  PUSH_REFS="$PUSH_REFS backend-v$VER"
  git tag "backend-v$VER"
}

release_postgres() {
  build_image "$POSTGRES_IMAGE" "$ROOT/docker/postgres"
  pin_compose "$POSTGRES_IMAGE"
  PUSH_REFS="$PUSH_REFS postgres-v$VER"
  git tag "postgres-v$VER"
}

release_cli() {
  printf '==> Building odin-linux-x86_64 (PyInstaller, linux/amd64)\n'
  rm -rf "$OUT"
  mkdir -p "$OUT"
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

  printf '==> Publishing CLI binary to the rolling cli release\n'
  if ! gh release view cli >/dev/null 2>&1; then
    gh release create cli --title "Odin CLI (latest)" \
      --notes "Rolling release — always holds the newest odin CLI binary."
  fi
  gh release upload cli "$OUT/odin-linux-x86_64" --clobber
  PUSH_REFS="$PUSH_REFS cli-v$VER"
  git tag "cli-v$VER"
}

case "$TARGET" in
  backend)  release_backend ;;
  postgres) release_postgres ;;
  cli)      release_cli ;;
  all)      release_postgres; release_backend; release_cli ;;
esac

if [ "$COMPOSE_CHANGED" -eq 1 ] && ! git diff --quiet -- "$COMPOSE"; then
  printf '==> Committing pinned compose\n'
  git add "$COMPOSE"
  git commit -m "release($TARGET): pin to $VER"
  PUSH_REFS="$PUSH_REFS HEAD"
fi

printf '==> Pushing %s\n' "$PUSH_REFS"
# shellcheck disable=SC2086
git push origin $PUSH_REFS

printf 'Done: %s %s\n' "$TARGET" "$VER"
