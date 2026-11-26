#!/usr/bin/env python3
"""Tickets in a Slack channel through Slack's own API: post a reviewed batch, and check for replies.

  tickets.py batch.json            dry run: prints what would be posted, posts nothing
  tickets.py batch.json --post     posts; safe to run again, already posted tickets are skipped
  tickets.py --list                one line per open ticket (loaded with the skill, or run first; never fails)
  tickets.py --answers             replies that arrived since the last check, and how many tickets are open
  tickets.py --answers --all       every ticket with every reply
  tickets.py --answers --peek      as --answers, without remembering what was shown
  tickets.py --reply <ts> note.txt         dry run of a reply in a ticket's thread (our own update or decision)
  tickets.py --reply <ts> note.txt --post  posts it
  tickets.py --close <ts>          marks a ticket closed with a check mark (the top-level message's timestamp)
  tickets.py --check               says which channel and whose token (never prints the token)
  tickets.py ... --channel=<id>    with any command: the channel for this run, when the project has none set

Configuration, two environment variables (in Claude Code: the project's .claude/settings.local.json, key "env"):
  SLACK_TICKETS_CHANNEL   the channel's id, for example C0123456789
  SLACK_TICKETS_TOKEN     the Slack app's bot token (xoxb-...)
Without SLACK_TICKETS_TOKEN the token is read from the macOS Keychain, service "slack-tickets"
(store it with: security add-generic-password -U -s slack-tickets -a slack -w).

batch.json: {"tickets": [{"id": "refund-wording", "top": "...", "details": "..."}]}
Texts are Slack mrkdwn: *bold* with single asterisks (the question and each label), one line per field,
nobody mentioned, and the top-level message says who asked ("*Asked by:* <name>").
Results go to batch.result.json beside the batch. What --answers already showed is kept in
.slack-tickets/state.json in the project (the main checkout, when run in a git worktree).
"""
import datetime
import json
import os
import re
import subprocess
import sys
import time
import urllib.error
import urllib.parse
import urllib.request

KEYCHAIN = 'slack-tickets'
CLOSED = 'white_check_mark'


def channel_id():
    """The project's channel, or the one named with --channel=<id> when the project has none."""
    valid = re.compile(r'[CG][A-Z0-9]{6,}').fullmatch
    value = os.environ.get('SLACK_TICKETS_CHANNEL', '').strip()
    named = {a.split('=', 1)[1] for a in sys.argv[1:] if a.startswith('--channel=')}
    if value and not valid(value):  # never print it: a token put in the wrong variable would land here
        sys.exit('SLACK_TICKETS_CHANNEL is set, but not to a channel id (like C0123456789). Correct it where it is set.')
    ids = (named | {value}) - {''}
    if len(ids) > 1:
        sys.exit('--channel names one channel, and only for a project that has none set.')
    chosen = next(iter(ids), '')
    if not valid(chosen):
        sys.exit('SLACK_TICKETS_CHANNEL is not set to a channel id (like C0123456789). Set it in the environment (in '
                 'Claude Code: under "env" in the project\'s .claude/settings.local.json, then start a new session), '
                 'or name the channel for one run with --channel=<id>.')
    return chosen


def token():
    value = os.environ.get('SLACK_TICKETS_TOKEN', '').strip()
    if not value:
        try:
            found = subprocess.run(['security', 'find-generic-password', '-s', KEYCHAIN, '-w'], capture_output=True, text=True)
            value = found.stdout.strip() if found.returncode == 0 else ''
        except FileNotFoundError:  # no Keychain outside macOS
            pass
    if not value:
        sys.exit('No Slack token: set SLACK_TICKETS_TOKEN, or store it in the Keychain under "slack-tickets". See the README.')
    return value


def call(method, tok, read=False, **payload):
    """One Slack call. Reading methods take their arguments in the address, writing ones as JSON."""
    url = f'https://slack.com/api/{method}'
    headers = {'Authorization': f'Bearer {tok}'}
    data = None
    if read:
        url += '?' + urllib.parse.urlencode(payload)
    else:
        data = json.dumps(payload).encode('utf-8')
        headers['Content-Type'] = 'application/json; charset=utf-8'
    for _ in range(4):
        try:
            with urllib.request.urlopen(urllib.request.Request(url, data=data, headers=headers), timeout=30) as response:
                body = json.loads(response.read().decode('utf-8'))
        except urllib.error.HTTPError as error:
            if error.code == 429:
                time.sleep(int(error.headers.get('Retry-After', '5')))
                continue
            sys.exit(f'{method}: HTTP {error.code}')
        except (urllib.error.URLError, TimeoutError, ValueError) as error:
            sys.exit(f'{method}: Slack could not be reached ({type(error).__name__})')
        if not body.get('ok'):
            hint = ''
            if body.get('needed'):
                hint = f' (the app needs one of the scopes {body["needed"]}; add it and reinstall the app)'
            elif body.get('error') in ('not_in_channel', 'channel_not_found'):
                hint = ' (invite the app to the channel: /invite @<the app>)'
            sys.exit(f'{method}: {body.get("error", "unknown error")}{hint}')
        return body
    sys.exit(f'{method}: rate limited too many times')


def save(path, value):
    os.makedirs(os.path.dirname(path) or '.', exist_ok=True)
    with open(path, 'w', encoding='utf-8') as out:
        json.dump(value, out, indent=2)


def load(path):
    try:
        with open(path, encoding='utf-8') as source:
            return json.load(source)
    except FileNotFoundError:
        return {}


def state_path():
    """Where --answers remembers what it showed: .slack-tickets/state.json in the project the script is run from.
    In a git worktree that is the main checkout, so every worktree shares one file."""
    try:
        found = subprocess.run(['git', 'rev-parse', '--git-common-dir'], capture_output=True, text=True)
        common = os.path.abspath(found.stdout.strip()) if found.returncode == 0 and found.stdout.strip() else ''
    except OSError:  # no git on this machine
        common = ''
    # Only a plain .git folder names the project; a submodule or a bare repository does not.
    root = os.path.dirname(common) if os.path.basename(common) == '.git' and os.path.isdir(common) else os.getcwd()
    return os.path.join(root, '.slack-tickets', 'state.json')


def linked(path):
    """True when the state file or its folder is a link, which could send a read or a write outside the project."""
    return os.path.islink(path) or os.path.islink(os.path.dirname(path))


def believable(last):
    """A reply's timestamp that can be true: a number, and not in the future (a day's slack for a clock that is off)."""
    try:
        return 0 < float(last) <= time.time() + 86400
    except (TypeError, ValueError, OverflowError):
        return False


def recall():
    """What --answers remembered, read as something a stranger could have put in the project.
    A missing, unreadable, linked or oddly shaped file counts as nothing remembered. Never raises."""
    try:
        path = state_path()
        state = {} if linked(path) else load(path)
        seen = {ts: last for ts, last in state.get('seen', {}).items() if believable(last)}
        names = {user: ' '.join(str(name).split()) for user, name in state.get('names', {}).items()}
    except Exception:  # whatever the file holds, --list must still load with the skill
        seen, names = {}, {}
    return {'names': names, 'seen': seen}


def remember(state):
    """Saves what was shown. A folder that cannot be written costs a repeat next time, not the answers just printed."""
    path = state_path()
    folder = os.path.dirname(path)
    try:
        if linked(path):
            raise OSError(0, 'a link stands in its place')
        os.makedirs(folder, exist_ok=True)
        try:  # before the state, so the state is never in the project without it; 'x' does not follow a link
            with open(os.path.join(folder, '.gitignore'), 'x', encoding='utf-8') as out:
                out.write('*\n')
        except FileExistsError:
            pass
        save(path, state)
    except OSError as error:
        print(f'What was shown could not be remembered ({path}: {error.strerror}). The same replies will show as new next time.')


def problems(tickets):
    found = []
    ids = [t.get('id') for t in tickets]
    if len(ids) != len(set(ids)) or not all(ids):
        found.append('every ticket needs its own id')
    for t in tickets:
        top, details = t.get('top', ''), t.get('details', '')
        if not top.strip() or not details.strip():
            found.append(f'{t.get("id")}: both parts are required')
        if '<@' in top or '<@' in details or '<!' in top or '<!' in details:
            found.append(f'{t.get("id")}: nobody is mentioned in a ticket; a reviewer tags in the thread')
        if not re.search(r'Asked by:\*? *[^\s*]', top):
            found.append(f'{t.get("id")}: the top-level message says who asked ("Asked by: <name>")')
        if len(top) > 3500 or len(details) > 3500:
            found.append(f'{t.get("id")}: too long for one message')
    return found


def post(path, flags):
    batch = load(path)
    tickets = batch.get('tickets', [])
    channel = channel_id()
    if batch.get('channel') and batch['channel'] != channel:
        sys.exit('Not posted: the batch names another channel. Take "channel" out of the batch.')
    wrong = problems(tickets)
    if wrong:
        sys.exit('Not posted:\n  ' + '\n  '.join(wrong))
    result_path = path[:-5] + '.result.json' if path.endswith('.json') else path + '.result.json'
    done = load(result_path)

    if '--post' not in flags:
        for t in tickets:
            mark = 'already posted' if done.get(t['id'], {}).get('details_ts') else 'to post'
            print(f'--- {t["id"]} ({mark})\n{t["top"]}\n  [thread]\n{t["details"]}\n')
        print(f'Dry run: {len(tickets)} tickets for {channel}, nothing posted. Add --post to post.')
        return

    tok = token()
    for t in tickets:
        state = done.setdefault(t['id'], {})
        if not state.get('ts'):
            sent = call('chat.postMessage', tok, channel=channel, text=t['top'], unfurl_links=False, unfurl_media=False)
            # Slack answers with the conversation's own id, which can differ from the one asked for.
            state['ts'], state['channel'] = sent['ts'], sent['channel']
            save(result_path, done)
            time.sleep(1.2)
        where = state.get('channel', channel)
        if not state.get('details_ts'):
            reply = call('chat.postMessage', tok, channel=where, thread_ts=state['ts'], text=t['details'], unfurl_links=False, unfurl_media=False)
            state['details_ts'] = reply['ts']
            save(result_path, done)
            time.sleep(1.2)
        if not state.get('link'):
            state['link'] = call('chat.getPermalink', tok, read=True, channel=where, message_ts=state['ts']).get('permalink')
            save(result_path, done)
        print(f'{t["id"]}: {state.get("link")}')
    print(f'Posted {len(tickets)} tickets. Results: {result_path}')


def fields(lines):
    """A ticket's lines split into its fields, each label read with or without its bold."""
    return [re.sub(r'^\*([^*:]+:)\*', r'\1', part.strip()) for line in lines for part in line.split('\u00b7')]


def history(channel, tok):
    messages, cursor = [], None
    while True:
        page = call('conversations.history', tok, read=True, channel=channel, limit=200, **({'cursor': cursor} if cursor else {}))
        messages += page.get('messages', [])
        cursor = page.get('response_metadata', {}).get('next_cursor')
        if not cursor:
            break
    return sorted((m for m in messages if (m.get('text') or '').lstrip().startswith('*Q:')), key=lambda m: float(m['ts']))


def listing():
    """One line per open ticket, from one call to Slack. Claude Code loads it into the skill's text, so it never exits with an error."""
    try:
        channel, tok = channel_id(), token()
        tickets = history(channel, tok)
    except SystemExit as stop:
        print(f'The ticket list could not be read: {stop.code}')
        return
    except Exception as error:  # a failing command would stop the skill from loading in Claude Code
        print(f'The ticket list could not be read: {type(error).__name__}')
        return
    seen = recall()['seen']
    still_open = [t for t in tickets if not any(r.get('name') == CLOSED for r in t.get('reactions', []))]
    print(f'Channel {channel}: {len(still_open)} open, {len(tickets) - len(still_open)} closed. Open tickets, oldest first:')
    for t in still_open:
        lines = re.sub(r'<[^>|]*\|([^>]*)>', r'\1', t.get('text') or '').split('\n')
        parts = fields(lines[1:])
        level = next((part[len('Urgency:'):].strip() for part in parts if part.startswith('Urgency:')), '?')
        level = re.sub(r':[a-z_]+:', '', level).strip() or level
        by = next((part[len('Asked by:'):].strip() for part in parts if part.startswith('Asked by:')), '')
        day = datetime.datetime.fromtimestamp(float(t['ts'])).strftime('%b %d')
        thread = t.get('reply_count', 0)
        # The ticket's own Details reply comes from its author; anyone else in the thread is an answer or a routing tag.
        others = [u for u in t.get('reply_users', []) if u != t.get('user')]
        unread = bool(others) and float(t.get('latest_reply', '0')) > float(seen.get(t['ts'], '0'))
        fresh = (', others replied' if others else ', no reply yet') + (', NEW since the last check' if unread else '')
        question = lines[0].strip('* ').removeprefix('Q:').strip()
        print(f'- {question} [{level}; {day}{" by " + by if by else ""}; thread {thread}{fresh}; ts {t["ts"]}]')


def reply(ts, path, flags):
    with open(path, encoding='utf-8') as source:
        text = source.read().strip()
    if not text or '<@' in text or '<!' in text or len(text) > 3500:
        sys.exit('Not posted: a reply needs some text, mentions nobody and fits one message.')
    if not re.fullmatch(r'\d{10}\.\d{6}', ts):
        sys.exit('Not posted: the first argument is the ticket\'s timestamp, as printed by --answers (like 1795630143.783399).')
    channel = channel_id()
    if '--post' not in flags:
        print(f'--- reply in the thread of {ts}\n{text}\n\nDry run for {channel}, nothing posted. Add --post to post.')
        return
    tok = token()
    # Only a ticket's thread: the timestamp must be a top-level message that is a ticket.
    parent = call('conversations.replies', tok, read=True, channel=channel, ts=ts, limit=1).get('messages', [{}])[0]
    if parent.get('ts') != ts or not (parent.get('text') or '').lstrip().startswith('*Q:'):
        sys.exit('Not posted: that timestamp is not a ticket in this channel.')
    sent = call('chat.postMessage', tok, channel=channel, thread_ts=ts, text=text, unfurl_links=False, unfurl_media=False)
    print(f'Replied in the thread of {ts} ({sent["ts"]}).')


def answers(flags):
    channel, tok = channel_id(), token()
    state = recall()
    names, seen = state.setdefault('names', {}), state.setdefault('seen', {})

    def name(user):
        if user and user not in names:
            profile = call('users.info', tok, read=True, user=user).get('user', {})
            names[user] = profile.get('real_name') or profile.get('name') or user
        return names.get(user, 'someone')

    def plain(text):
        text = re.sub(r'<@(\w+)(?:\|[^>]*)?>', lambda m: '@' + name(m.group(1)), text or '')
        text = re.sub(r'<(https?://[^|>]+)\|([^>]+)>', r'\2', text)
        return re.sub(r'<(https?://[^>]+)>', r'\1', text)

    def when(ts):
        return datetime.datetime.fromtimestamp(float(ts)).strftime('%b %d %H:%M')

    tickets = history(channel, tok)

    show_all = '--all' in flags
    open_count, shown = 0, 0
    for ticket in tickets:
        closed = any(r.get('name') == CLOSED for r in ticket.get('reactions', []))
        open_count += 0 if closed else 1
        last_seen = '0' if show_all else seen.get(ticket['ts'], '0')
        latest = ticket.get('latest_reply', '0')
        fresh = []
        if ticket.get('reply_count') and (show_all or float(latest) > float(last_seen)):
            thread = call('conversations.replies', tok, read=True, channel=channel, ts=ticket['ts'], limit=200).get('messages', [])[1:]
            # The ticket's own Details reply is part of the ticket, not an answer (with or without the bold).
            fresh = [r for r in thread if float(r['ts']) > float(last_seen) and not (r.get('text') or '').lstrip(' *\n').startswith('Details')]
        if not fresh and not show_all:
            continue
        lines = plain(ticket['text']).split('\n')
        question = lines[0].strip('*').strip()
        parts = fields(lines)
        urgency = next((part for part in parts if part.startswith('Urgency:')), '')
        by = next((' by ' + part[len('Asked by:'):].strip() for part in parts if part.startswith('Asked by:')), '')
        print(f'[{"closed" if closed else "open"}] {question}\n  {urgency} | asked {when(ticket["ts"])}{by} | ts {ticket["ts"]}')
        for reply in fresh:
            body = plain(reply.get('text')).replace('\n', '\n      ')
            files = f' [{len(reply["files"])} file(s) attached]' if reply.get('files') else ''
            print(f'    {name(reply.get("user"))}, {when(reply["ts"])}: {body}{files}')
        shown += 1
        if '--peek' not in flags and not show_all:
            seen[ticket['ts']] = latest
    if not shown:
        print('No new replies.')
    print(f'{len(tickets)} tickets, {open_count} open.')
    remember(state)


def main():
    args = [a for a in sys.argv[1:] if not a.startswith('--')]
    flags = {a for a in sys.argv[1:] if a.startswith('--')}
    if '--check' in flags:
        print(f'Channel {channel_id()}.')
        who = call('auth.test', token())
        print(f'Posting as {who.get("user")} in {who.get("team")}' + (' (a bot)' if who.get('bot_id') else ' (a person)'))
    elif '--list' in flags:
        listing()
    elif '--answers' in flags:
        answers(flags)
    elif '--reply' in flags and len(args) == 2:
        reply(args[0], args[1], flags)
    elif '--close' in flags and len(args) == 1:
        call('reactions.add', token(), channel=channel_id(), timestamp=args[0], name=CLOSED)
        print(f'Closed {args[0]}.')
    elif len(args) == 1:
        post(args[0], flags)
    else:
        sys.exit(__doc__)


if __name__ == '__main__':
    main()
