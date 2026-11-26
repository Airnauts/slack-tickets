"""Prints what a headless agent run did: tool calls, refusals, the last text. Flags any channel id that is not a dummy.

usage: python3 summarise.py <output.jsonl>
Reads the JSON lines of a Claude Code run (--output-format stream-json) or of a Codex run (exec --json).
"""
import json
import re
import sys

DUMMY = {'C0000000000', 'C0123456789', 'C1111111111', 'C2222222222'}
CHANNEL_ID = re.compile(r'\b[CG][A-Z0-9]{8,}\b')
CODEX_EVENTS = ('item.', 'thread.', 'turn.')


def claude_event(event, ids):
    """One line of a Claude Code run."""
    kind = event.get('type')
    if kind in ('assistant', 'user'):
        for part in event.get('message', {}).get('content') or []:
            if not isinstance(part, dict):
                continue
            if part.get('type') == 'tool_use':
                shown = json.dumps(part.get('input'), ensure_ascii=False)
                ids.update(CHANNEL_ID.findall(shown))
                print('TOOL_USE:', part.get('name'), shown[:330])
            elif part.get('type') == 'tool_result':
                body = part.get('content')
                if isinstance(body, list):
                    body = ' '.join(x.get('text', '') for x in body if isinstance(x, dict))
                print('  ->', ('ERR ' if part.get('is_error') else '') + str(body)[:200].replace('\n', ' / '))
            elif part.get('type') == 'text' and not part.get('text', '').startswith('Base directory'):
                print('TEXT:', part['text'][:900])
    elif kind == 'result':
        denied = [(d.get('tool_name'), json.dumps(d.get('tool_input'), ensure_ascii=False)[:200])
                  for d in event.get('permission_denials') or []]
        print('RESULT:', event.get('subtype'), '| turns', event.get('num_turns'), '| refused:', denied)


def codex_event(event, ids):
    """One line of a Codex run."""
    if event.get('type') != 'item.completed':
        return
    item = event.get('item') or {}
    kind = item.get('type') or item.get('item_type')
    if kind == 'command_execution':
        command = item.get('command', '')
        ids.update(CHANNEL_ID.findall(command))
        if 'SKILL.md' in command or 'sed -n' in command:
            shown = '<file text>'
        else:
            shown = (item.get('aggregated_output') or '')[:200].replace('\n', ' / ')
        print('CMD:', command[:210], '| exit', item.get('exit_code'), '|', shown)
    elif kind == 'agent_message':
        print('MSG:', (item.get('text') or '')[:900])
    elif kind and kind != 'reasoning':
        print('ITEM:', kind, json.dumps(item)[:200])


def main(path):
    ids = set()
    with open(path, encoding='utf-8') as source:
        for line in source:
            try:
                event = json.loads(line)
            except ValueError:
                continue
            if not isinstance(event, dict):
                continue
            if str(event.get('type', '')).startswith(CODEX_EVENTS):
                codex_event(event, ids)
            else:
                claude_event(event, ids)
    print('channel ids in tool calls:', sorted(ids), '| not dummy:', sorted(ids - DUMMY))


if __name__ == '__main__':
    main(sys.argv[1])
