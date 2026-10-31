#!/bin/sh
# Deploy the committed tree (HEAD) to the NAS over SSH.
#
#   scripts/deploy.sh <ssh-host> <remote-dir>
#
# Replaces src/, scripts/ and docs/ in <remote-dir>, keeping config.ini, logs/
# and work/. Records the deployed commit in DEPLOYED_COMMIT, removes the sync
# state file so the next scheduled run does a full sync with the new code, and
# checks that the package imports with the NAS's Python.
set -eu

if [ $# -ne 2 ]; then
  echo "usage: $0 <ssh-host> <remote-dir>" >&2
  exit 2
fi
HOST=$1
REMOTE_DIR=$2

cd "$(dirname -- "$0")/.."
if ! git diff --quiet HEAD --; then
  echo "Working tree has uncommitted changes; commit them first." >&2
  exit 1
fi
COMMIT=$(git rev-parse --short HEAD)

git archive --format=tar HEAD src scripts docs README.md pyproject.toml config.example.ini \
  | ssh "$HOST" "set -eu
cd '$REMOTE_DIR'
rm -rf .deploy && mkdir .deploy && tar -xf - -C .deploy
for part in src scripts docs; do
  rm -rf \"\$part.old\"
  if [ -e \"\$part\" ]; then mv \"\$part\" \"\$part.old\"; fi
  mv \".deploy/\$part\" \"\$part\"
done
cp .deploy/README.md .deploy/pyproject.toml .deploy/config.example.ini .
rm -rf .deploy src.old scripts.old docs.old
rm -f work/sync-state.json
echo '$COMMIT' > DEPLOYED_COMMIT
PYTHONPATH=src python3 -m synology_dhcp_dns_sync --help > /dev/null"

echo "Deployed $COMMIT to $HOST:$REMOTE_DIR"
