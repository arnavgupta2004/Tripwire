#!/bin/sh
# Attacked runs for every condition (resumable: completed pairs are skipped).
set -u
cd "$(dirname "$0")/../.."
R="uv run --group eval python evals/agentdojo/run.py --mode attack --workers 10"
for suite in slack banking; do
  for c in none spotlighting tripwire_gw tripwire_full; do
    $R --suite $suite --condition $c 2>&1 | grep -E "^done|runs to do|ERR"
  done
done
# Strict trust domain only changes Slack destinations.
$R --suite slack --condition tripwire_full --trust strict 2>&1 | grep -E "^done|runs to do|ERR"
echo ALL_DONE
