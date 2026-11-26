#!/bin/sh
# Runs the ticket skill in Codex from a scratch project, with no channel variable and no token.
# usage: run-codex.sh
# These runs cost tokens and vary from run to run. Read tests/agents/README.md first.
#
# Safety: the default write sandbox (workspace-write), no Slack variables, and the skill is only linked into
# the scratch project, so nothing is written into this repository.
HERE=$(cd "$(dirname "$0")" && pwd)
ROOT=$(cd "$HERE/../.." && pwd)
if ! command -v codex >/dev/null 2>&1; then echo "codex is not installed"; exit 1; fi

SCRATCH=$(mktemp -d "${TMPDIR:-/tmp}/slack-tickets-codex.XXXXXX") || exit 1
mkdir -p "$SCRATCH/project/.agents/skills"
ln -s "$ROOT/skills/ticket" "$SCRATCH/project/.agents/skills/ticket"
env -u SLACK_TICKETS_CHANNEL -u SLACK_TICKETS_TOKEN codex exec -C "$SCRATCH/project" --skip-git-repo-check -s workspace-write --json \
  "Ask the client whether we can ship the new reminder wording on Friday. Draft the ticket for me to review; do not post anything." \
  > "$SCRATCH/nochannel.jsonl" 2> "$SCRATCH/nochannel.err" < /dev/null
echo "exit $?"
python3 "$HERE/summarise.py" "$SCRATCH/nochannel.jsonl"
echo "output kept in $SCRATCH"
