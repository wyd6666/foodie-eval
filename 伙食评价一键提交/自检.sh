#!/usr/bin/env bash
cd "$(dirname "$0")" || exit 1
python3 scripts/selfcheck.py "$@" 2>&1 | tee /dev/tty
