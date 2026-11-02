#!/usr/bin/env bash
# Host side: run several typed requests one after another in the VM and print,
# for each, which recipe ran (or the online agent), what it said, and the time.
#
#   scripts/dev/run_batch.sh out_dir "request one" "request two" ...
set -uo pipefail
cd "$(dirname "$0")/../.."
OUT="$1"; shift
for request in "$@"; do
    slug="$(echo "$request" | tr -c 'a-zA-Z0-9' '_' | cut -c1-40)"
    echo "=== $request"
    scripts/dev/run_request.sh "$request" "$OUT/$slug" 120 \
        | grep -E "recipe |stopped|online agent|tool |done in|ERROR|Traceback|Error" | sed 's/^[0-9:]* INFO pardus_clicky[.a-z]*: /  /'
    scripts/dev/vm.sh shot "$OUT/$slug/final.png" >/dev/null 2>&1
done
