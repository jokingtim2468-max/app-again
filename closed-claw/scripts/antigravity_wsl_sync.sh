#!/usr/bin/env bash
# Run INSIDE WSL: clone/pull the shared repo into Antigravity's workspace and bootstrap.
#   bash antigravity_wsl_sync.sh [branch] [path]
set -euo pipefail
REPO="${REPO:-https://github.com/jokingtim2468-max/app-again.git}"
BRANCH="${1:-main}"; DEST="${2:-$HOME/antigravity/app-again}"
if [ -d "$DEST/.git" ]; then
  git -C "$DEST" fetch origin "$BRANCH" && git -C "$DEST" checkout "$BRANCH" && git -C "$DEST" pull --ff-only origin "$BRANCH"
else
  mkdir -p "$(dirname "$DEST")" && git clone --branch "$BRANCH" "$REPO" "$DEST"
fi
bash "$DEST/closed-claw/scripts/setup_dev.sh"
echo "READY: $DEST  (Windows path: \\\\wsl\$\\${WSL_DISTRO_NAME:-Ubuntu}${DEST})"
