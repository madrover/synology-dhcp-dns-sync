#!/bin/sh
set -eu

SCRIPT_DIR=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
PROJECT_DIR=$(CDPATH= cd -- "$SCRIPT_DIR/.." && pwd)
CONFIG_PATH=${1:-"$PROJECT_DIR/config.ini"}

if [ $# -gt 0 ]; then
  shift
fi

export PYTHONPATH="${PROJECT_DIR}/src${PYTHONPATH:+:${PYTHONPATH}}"

exec /usr/bin/env python3 -m synology_dhcp_dns_sync sync --config "$CONFIG_PATH" "$@"
