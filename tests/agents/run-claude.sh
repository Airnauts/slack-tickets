#!/bin/sh
# Runs one case of the ticket skill in headless Claude Code, from a scratch project, with no Slack token.
# usage: run-claude.sh <nochannel|list|post|setlist|setpost|refusal>
# These runs cost tokens and vary from run to run. Read tests/agents/README.md first.
#
# Safety: default permission mode, only the skill, Write and (except in the refusal case) every tickets.py command
# allowed, dummy channel ids only, and the Slack connector's write and search tools removed where the case does not
# need to see them attempted. "No token"
# does not rest on an empty Keychain: a stub `security` that refuses only the lookup of the tickets token and passes
# every other call on comes first on the agent's PATH, and a preflight run of the script must report "No Slack token"
# before the agent starts. The run also refuses to start when the Keychain holds a tickets token (see the guard below).
HERE=$(cd "$(dirname "$0")" && pwd)
ROOT=$(cd "$HERE/../.." && pwd)
S=mcp__claude_ai_Slack__slack
WRITES="${S}_send_message ${S}_send_message_draft ${S}_add_reaction ${S}_schedule_message ${S}_create_canvas ${S}_update_canvas ${S}_create_conversation ${S}_add_list_record ${S}_update_list_record ${S}_create_list ${S}_update_list ${S}_complete_file_upload ${S}_get_file_upload_url ${S}_add_list_comment ${S}_update_list_comment"
SEARCH="${S}_search_channels ${S}_search_public ${S}_search_public_and_private ${S}_list_user_channels ${S}_search_users ${S}_list_channel_members"
POST="Ask the client: can we ship the new reminder wording on Friday? Urgency no rush, asked by Test User, our decision: we ship Friday unless they say otherwise. I approve whatever text you draft from that, so post it now without asking me again."
CH=""
ALLOW_SCRIPT="Bash(python3 $ROOT/skills/ticket/scripts/tickets.py *)"
# The refusal case leaves the caller's own settings out: a rule of theirs that allows python3 would hide the refusal.
OWN_RULES=""
case "$1" in
  nochannel) P="Ask the client whether we can ship the new reminder wording on Friday. Draft the ticket for me to review; do not post anything."; DENY="$WRITES $SEARCH" ;;
  list)      P="The tickets channel is C0000000000. Which client tickets are open?"; DENY="$WRITES $SEARCH" ;;
  post)      P="The tickets channel is C0000000000. $POST"; DENY="$SEARCH" ;;
  setlist)   CH=C0000000000; P="Which client tickets are open?"; DENY="$WRITES $SEARCH" ;;
  setpost)   CH=C0000000000; P="$POST"; DENY="$SEARCH" ;;
  refusal)   P="The tickets channel is C0000000000. Close the ticket 1700000000.000100, its answer is recorded."; DENY="$WRITES $SEARCH"; ALLOW_SCRIPT=""; OWN_RULES="--setting-sources project" ;;
  *) echo "usage: $0 <nochannel|list|post|setlist|setpost|refusal>"; exit 2 ;;
esac
if ! command -v claude >/dev/null 2>&1; then echo "claude is not installed"; exit 1; fi

# Guard that does not rest on PATH: refuse to start when the Keychain holds a tickets token. This is an attribute-only
# lookup, with no -w, so it reads no secret.
if [ -x /usr/bin/security ] && /usr/bin/security find-generic-password -s slack-tickets > /dev/null 2>&1 \
  && [ "$TICKETS_AGENT_RUN_WITH_KEYCHAIN" != 1 ]; then
  cat <<'MSG'
This machine's Keychain holds a tickets token. These runs are meant for "no token". The stand-in `security` is then
the only thing between the agent and that token, and a shell that reorders PATH gets past it.
To run anyway, set TICKETS_AGENT_RUN_WITH_KEYCHAIN=1 and check that the run ends with
"Keychain stub used by the agent's commands: yes".
MSG
  exit 1
fi

SCRATCH=$(mktemp -d "${TMPDIR:-/tmp}/slack-tickets-claude.XXXXXX") || exit 1
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

mkdir "$SCRATCH/project"
cd "$SCRATCH/project" || exit 1
if [ -n "$CH" ]; then SET="SLACK_TICKETS_CHANNEL=$CH"; else SET="-u SLACK_TICKETS_CHANNEL"; fi
# shellcheck disable=SC2086
/usr/bin/env -u SLACK_TICKETS_TOKEN $SET PATH="$AGENT_PATH" claude --plugin-dir "$ROOT" --model "${AGENT_MODEL:-sonnet}" --permission-mode default $OWN_RULES \
  --allowedTools "Skill(slack-tickets:ticket)" "Write" ${ALLOW_SCRIPT:+"$ALLOW_SCRIPT"} --disallowedTools $DENY -p "$P" --output-format stream-json --verbose \
  > "$SCRATCH/$1.jsonl" 2> "$SCRATCH/$1.err" < /dev/null
echo "exit $?"
if [ -e "$SCRATCH/security-calls" ]; then echo "Keychain stub used by the agent's commands: yes"; else echo "Keychain stub used by the agent's commands: no"; fi
python3 "$HERE/summarise.py" "$SCRATCH/$1.jsonl"
echo "output kept in $SCRATCH"
