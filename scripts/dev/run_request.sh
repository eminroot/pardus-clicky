#!/usr/bin/env bash
# Host side: send a typed request to Clicky in the VM, take a VMware screenshot
# every few seconds while it works, and print the log of that request.
#
#   scripts/dev/run_request.sh "show me how to change the wallpaper" out_dir [max_seconds]
set -euo pipefail
cd "$(dirname "$0")/../.."
REQUEST="$1"; OUT="${2:-/tmp/clicky-run}"; MAX="${3:-90}"
mkdir -p "$OUT"
MARK="$(scripts/dev/vm.sh sh 'wc -l < ~/.cache/pardus-clicky/clicky.log' | tr -d '[:space:]')"
scripts/dev/vm.sh sh "cd ~/pardus-clicky && bin/pardus-clicky ask $(printf '%q' "$REQUEST")"
for i in $(seq 1 $((MAX / 4))); do
    sleep 4
    scripts/dev/vm.sh shot "$OUT/f$(printf '%02d' "$i").png" >/dev/null 2>&1 || true
    if scripts/dev/vm.sh sh "tail -n +$((MARK + 1)) ~/.cache/pardus-clicky/clicky.log | grep -q 'done in'"; then
        break
    fi
done
scripts/dev/vm.sh sh "tail -n +$((MARK + 1)) ~/.cache/pardus-clicky/clicky.log | grep -vE 'appindicator' | cut -c1-240"
