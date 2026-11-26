#!/bin/sh
# Runs the ticket skill in Codex from a scratch project, with no channel variable and no token.
# usage: run-codex.sh
# These runs cost tokens and vary from run to run. Read tests/agents/README.md first.
#
# Safety: the workspace-write sandbox with the network turned off by flag, no Slack variables, and the skill
# copied (not linked) into the scratch project, so nothing can be written into this repository. "No token"
# does not rest on an empty Keychain: a stub `security` that always fails comes first on the agent's PATH, and
# a preflight run of the script must report "No Slack token" before the agent starts.
HERE=$(cd "$(dirname "$0")" && pwd)
ROOT=$(cd "$HERE/../.." && pwd)
if ! command -v codex >/dev/null 2>&1; then echo "codex is not installed"; exit 1; fi

SCRATCH=$(mktemp -d "${TMPDIR:-/tmp}/slack-tickets-codex.XXXXXX") || exit 1

# A stub `security` that refuses only the lookup of the tickets token, and records it. Every other call goes to the
# real command, because the agent itself keeps its own login in the Keychain.
mkdir "$SCRATCH/bin"
cat > "$SCRATCH/bin/security" <<STUB
#!/bin/sh
case " \$* " in
  *" slack-tickets "*) echo called >> "$SCRATCH/security-calls"; exit 44 ;;
esac
exec /usr/bin/security "\$@"
STUB
chmod +x "$SCRATCH/bin/security"
AGENT_PATH="$SCRATCH/bin:$PATH"

# Preflight: the only direct run of the script, and it stops at the token, before any network access.
CHECK=$(/usr/bin/env -u SLACK_TICKETS_TOKEN -u SLACK_TICKETS_CHANNEL PYTHONDONTWRITEBYTECODE=1 PATH="$AGENT_PATH" \
  python3 "$ROOT/skills/ticket/scripts/tickets.py" --check --channel=C0000000000 2>&1 < /dev/null)
case "$CHECK" in
  *"No Slack token"*) ;;
  *) echo "The script can still find a token; not starting the agent."; exit 1 ;;
esac
rm -f "$SCRATCH/security-calls"

mkdir -p "$SCRATCH/project/.agents/skills"
cp -R "$ROOT/skills/ticket" "$SCRATCH/project/.agents/skills/ticket"
/usr/bin/env -u SLACK_TICKETS_CHANNEL -u SLACK_TICKETS_TOKEN PATH="$AGENT_PATH" codex exec -C "$SCRATCH/project" --skip-git-repo-check \
  -s workspace-write -c sandbox_workspace_write.network_access=false --json \
  "Ask the client whether we can ship the new reminder wording on Friday. Draft the ticket for me to review; do not post anything." \
  > "$SCRATCH/nochannel.jsonl" 2> "$SCRATCH/nochannel.err" < /dev/null
echo "exit $?"
if [ -e "$SCRATCH/security-calls" ]; then echo "Keychain stub used by the agent's commands: yes"; else echo "Keychain stub used by the agent's commands: no"; fi
python3 "$HERE/summarise.py" "$SCRATCH/nochannel.jsonl"
echo "output kept in $SCRATCH"
