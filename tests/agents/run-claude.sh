#!/bin/sh
# Runs one case of the ticket skill in headless Claude Code, from a scratch project, with no Slack token.
# usage: run-claude.sh <nochannel|list|post|setlist|setpost>
# These runs cost tokens and vary from run to run. Read tests/agents/README.md first.
#
# Safety: default permission mode (nothing that needs approval can run), only the skill and Write allowed,
# dummy channel ids only, and the Slack connector's write and search tools removed where the case does not
# need to see them attempted.
HERE=$(cd "$(dirname "$0")" && pwd)
ROOT=$(cd "$HERE/../.." && pwd)
S=mcp__claude_ai_Slack__slack
WRITES="${S}_send_message ${S}_send_message_draft ${S}_add_reaction ${S}_schedule_message ${S}_create_canvas ${S}_update_canvas ${S}_create_conversation ${S}_add_list_record ${S}_update_list_record ${S}_create_list ${S}_update_list ${S}_complete_file_upload ${S}_get_file_upload_url"
SEARCH="${S}_search_channels ${S}_search_public ${S}_search_public_and_private ${S}_list_user_channels"
POST="Ask the client: can we ship the new reminder wording on Friday? Urgency no rush, asked by Test User, our decision: we ship Friday unless they say otherwise. I approve whatever text you draft from that, so post it now without asking me again."
CH=""
case "$1" in
  nochannel) P="Ask the client whether we can ship the new reminder wording on Friday. Draft the ticket for me to review; do not post anything."; DENY="$WRITES" ;;
  list)      P="The tickets channel is C0000000000. Which client tickets are open?"; DENY="$WRITES $SEARCH" ;;
  post)      P="The tickets channel is C0000000000. $POST"; DENY="$SEARCH" ;;
  setlist)   CH=C0000000000; P="Which client tickets are open?"; DENY="$WRITES $SEARCH" ;;
  setpost)   CH=C0000000000; P="$POST"; DENY="$SEARCH" ;;
  *) echo "usage: $0 <nochannel|list|post|setlist|setpost>"; exit 2 ;;
esac
if ! command -v claude >/dev/null 2>&1; then echo "claude is not installed"; exit 1; fi

SCRATCH=$(mktemp -d "${TMPDIR:-/tmp}/slack-tickets-claude.XXXXXX") || exit 1
mkdir "$SCRATCH/project"
cd "$SCRATCH/project" || exit 1
if [ -n "$CH" ]; then SET="SLACK_TICKETS_CHANNEL=$CH"; else SET="-u SLACK_TICKETS_CHANNEL"; fi
# shellcheck disable=SC2086
/usr/bin/env -u SLACK_TICKETS_TOKEN $SET claude --plugin-dir "$ROOT" --model "${AGENT_MODEL:-sonnet}" --permission-mode default \
  --allowedTools "Skill(slack-tickets:ticket)" "Write" --disallowedTools $DENY -p "$P" --output-format stream-json --verbose \
  > "$SCRATCH/$1.jsonl" 2> "$SCRATCH/$1.err" < /dev/null
echo "exit $?"
python3 "$HERE/summarise.py" "$SCRATCH/$1.jsonl"
echo "output kept in $SCRATCH"
