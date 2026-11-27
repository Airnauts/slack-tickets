#!/usr/bin/env python3
"""Tickets in a Slack channel through Slack's own API: post a reviewed batch, and check for replies.

  tickets.py batch.json            dry run: prints what would be posted, posts nothing
  tickets.py batch.json --post     posts; safe to run again, already posted tickets are skipped
  tickets.py --list                one line per open ticket (loaded with the skill, or run first; never fails)
  tickets.py --answers             replies that arrived since the last check, and how many tickets are open
  tickets.py --answers --all       every ticket with every reply (reads the whole channel)
  tickets.py --answers --peek      as --answers, without remembering what was shown
  tickets.py --talk                threads that are not tickets, with news since the last --talk, by where their last word came from
  tickets.py --talk --all          every such thread of the last 14 days (the newest 10)
  tickets.py --talk --peek         as --talk, without remembering what was shown
  tickets.py --thread <ts>         one thread in full: any top-level message of the channel
  tickets.py --reply <ts> note.txt         dry run of a reply in a thread, a ticket's or any other: shows the message it starts with
  tickets.py --reply <ts> note.txt --post  posts it (a reply outside a ticket's thread starts with "*Reply* (<name>): ")
  tickets.py --close <ts>          marks a ticket closed with a check mark (the top-level message's timestamp)
  tickets.py --check               says which channel and whose token (never prints the token)
  tickets.py --setup               prints the setup steps and the Slack app manifest (needs nothing, calls nobody)
  tickets.py --sources-template    prints the template for the register of client documents
  tickets.py --sources             prints the register of client documents, if there is one
  tickets.py ... --channel=<id>    with any command: the channel for this run, when the project has none set

Configuration, two environment variables (in Claude Code: the project's .claude/settings.local.json, key "env"):
  SLACK_TICKETS_CHANNEL   the channel's id, for example C0123456789
  SLACK_TICKETS_TOKEN     the Slack app's bot token (xoxb-...)
Without SLACK_TICKETS_TOKEN the token is read from the macOS Keychain, service "slack-tickets"
(store it with: security add-generic-password -U -s slack-tickets -a slack -w).

batch.json: {"tickets": [{"id": "refund-wording", "top": "...", "details": "..."}]}
Texts are Slack mrkdwn: *bold* with single asterisks (the question and each label), one line per field,
nobody mentioned, and the top-level message says who asked ("*Asked by:* <name>").
Results go to batch.result.json beside the batch. What --answers and --talk already showed, and where the oldest open ticket
was, is kept in .slack-tickets/state.json in the project (the main checkout, when run in a git worktree).
"""
import datetime
import json
import os
import re
import stat
import subprocess
import sys
import time
import unicodedata
import urllib.error
import urllib.parse
import urllib.request

KEYCHAIN = 'slack-tickets'
CLOSED = 'white_check_mark'
HINTS = 3
HINT_LENGTH = 200
QUESTION_LENGTH = 300
FIELD_LENGTH = 80
WINDOW_DAYS = 14
TALK_THREADS = 10  # threads printed per run
TALK_READS = 20  # threads read per run, printed or not
TALK_REPLIES = 3  # newest replies printed per thread
TALK_LENGTH = 400  # characters per message, one line
TALK_PAGES = 3  # conversations.replies pages per thread (600 messages)
THREAD_REPLIES = 20
THREAD_LENGTH = 1500
THREAD_PAGES = 10
THIS_APP, INSIDE, OUTSIDE, UNKNOWN, AN_APP = 'this app', 'inside', 'outside', 'unknown', 'an app'
LABEL = re.compile(r'\*[^*\n]+\* \([^()\n]*[^\s()][^()\n]*\):').match
# An underscore may stand beside the word (_@here_ is italic), a letter or digit before it makes an address.
BROADCAST = re.compile(r'(?<![^\W_]|@)@(channel|here|everyone|group)(?![^\W_])', re.I).search
LINK = re.compile(r'<([a-z][a-z0-9+.-]*:[^|>\s]*)(?:\|[^>]*)?>|(https?://[^\s<>|]+)', re.I).finditer
FLAGS = frozenset(('--list', '--answers', '--all', '--peek', '--talk', '--thread', '--reply', '--close', '--post', '--check', '--setup',
                   '--sources', '--sources-template'))
CONTROLS = re.compile(r'[\x00-\x08\x0b-\x1f\x7f-\x9f]')
LINE_BREAKS = re.compile(r'[\r\x0b\x0c\x1c-\x1e\x85\u2028\u2029]')
# Not Cn (unassigned): an old Python's tables would take a new emoji for one.
HIDDEN_CATEGORIES = frozenset(('Cf', 'Cc', 'Cs', 'Co'))
EMOJI_GLUE = {0xfe0e: None, 0xfe0f: None, 0x200d: None}  # what an emoji in a reply may hold; clean() still blanks them
TIMESTAMP = re.compile(r'[0-9]{10}\.[0-9]{6}').fullmatch
CHANNEL_ID = re.compile(r'[CG][A-Z0-9]{6,}').fullmatch
# The skill's own folder. realpath, so a symlinked script or skill folder still finds the files beside it.
SKILL_DIR = os.path.dirname(os.path.dirname(os.path.realpath(__file__)))
SETUP_FILES = (('The setup steps', 'references/setup.md'), ('The Slack app manifest', 'assets/slack-app-manifest.yaml'))


def channel_id():
    """The project's channel, or the one named with --channel=<id> when the project has none."""
    value = os.environ.get('SLACK_TICKETS_CHANNEL', '').strip()
    named = {a.split('=', 1)[1] for a in sys.argv[1:] if a.startswith('--channel=')}
    if value and not CHANNEL_ID(value):  # never print it: a token put in the wrong variable would land here
        sys.exit('SLACK_TICKETS_CHANNEL is set, but not to a channel id (like C0123456789). Correct it where it is set.')
    ids = (named | {value}) - {''}
    if len(ids) > 1:
        sys.exit('--channel names one channel, and only for a project that has none set.')
    chosen = next(iter(ids), '')
    if not CHANNEL_ID(chosen):
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
        sys.exit('No Slack token: set SLACK_TICKETS_TOKEN, or store it in the Keychain under "slack-tickets". tickets.py --setup prints the steps.')
    return value


def show_file(title, name):
    """Prints one file of the skill's folder between a header and an end line. Never raises: a missing file is said."""
    try:
        with open(os.path.join(SKILL_DIR, name), encoding='utf-8') as source:
            text = source.read().strip()
    except Exception as error:  # missing, unreadable or not UTF-8
        text = f"(Missing from the skill's folder: {name} ({type(error).__name__}).)"
    try:
        print(f'===== {title}: {name} =====\n{text}\n===== End of {name} =====\n')
    except Exception:  # a terminal that cannot show a character; the files are ASCII, so only a damaged copy
        pass


def sources():
    """The register of client documents: the project's (this checkout, then the main checkout), else the one under the
    home folder. Never raises. Reads only a plain file with one name and at most 1 MB, reached through no link, so it
    cannot print another file or stall."""
    places = []
    try:  # the top folders of this checkout and of the main one, as the state files find them
        places += [(os.path.dirname(os.path.dirname(path)), ('.claude', 'slack-tickets', 'sources.md')) for path in reversed(state_paths())]
    except Exception:  # the current folder may be gone
        pass
    try:
        places.append((os.path.join(os.path.expanduser('~'), '.claude', 'slack-tickets'), (channel_id(), 'sources.md')))
    except SystemExit:  # no channel is configured, so there is no second place
        pass
    for base, names in places:
        path = os.path.join(base, *names)
        if any(os.path.islink(os.path.join(base, *names[:depth])) for depth in range(1, len(names) + 1)):
            print(f'(Not read: {path} is reached through a link.)')
            continue
        try:  # no following of a link and no waiting on a pipe; the checks and the read use one descriptor
            with open(path, 'rb', opener=lambda name, flags: os.open(name, flags | getattr(os, 'O_NOFOLLOW', 0) | getattr(os, 'O_NONBLOCK', 0))) as source:
                info = os.fstat(source.fileno())
                refusal = ('not a plain file' if not stat.S_ISREG(info.st_mode)
                           else 'it has more than one name' if info.st_nlink != 1
                           else 'over 1 MB' if info.st_size > 1_000_000 else '')
                text = '' if refusal else source.read(1_000_000).decode('utf-8')
        except FileNotFoundError:
            continue
        except Exception as error:  # unreadable or not UTF-8
            print(f'(Not read: {path} ({type(error).__name__}).)')
            continue
        if refusal:
            print(f'(Not read: {path} ({refusal}).)')
            continue
        text = CONTROLS.sub(' ', text).strip()
        if not text:
            print(f'The register is empty: {path}')
            return
        # The header's line count is what bounds the register: a line in the body can still look like the end marker.
        lines = count(text.count('\n') + 1, 'line')
        try:
            print(f'===== The register: {path} ({lines}) =====\n{text}\n===== End of the register =====')
        except Exception:  # a terminal that cannot show a character
            pass
        return
    print('No register yet. tickets.py --sources-template prints the template.')


def setup():
    """The setup steps and the Slack app manifest, from the skill's own folder, for an agent to lead someone through.
    Reads no token, checks no channel, calls nobody."""
    for title, name in SETUP_FILES:
        show_file(title, name)


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


def hidden(char):
    """A character a person cannot see or that moves the cursor: any format, control (but not a tab or a newline),
    surrogate or private-use character, and the variation selectors."""
    return char not in '\n\t' and (unicodedata.category(char) in HIDDEN_CATEGORIES
                                   or '\ufe00' <= char <= '\ufe0f' or '\U000e0100' <= char <= '\U000e01ef')


def clean(text):
    """Text from Slack that cannot draw a line of the script's own: every line break becomes a newline, every hidden
    character a space."""
    return ''.join(' ' if hidden(char) else char for char in LINE_BREAKS.sub('\n', text))


def one_line(text):
    return ' '.join(clean(text).split())


def cut(text, length):
    return text[:length] + '...' if len(text) > length else text


def count(number, noun):
    return f'{number} {noun}' + ('' if number == 1 else 's')


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


def state_paths():
    """Where the state may be kept: .slack-tickets/state.json in the main checkout, which every git worktree shares,
    then the same file in the checkout the script is run from, for a sandbox that may not write outside it."""
    try:
        found = subprocess.run(['git', 'rev-parse', '--git-common-dir', '--show-toplevel'], capture_output=True, text=True, timeout=10)
        lines = found.stdout.split('\n') if found.returncode == 0 else []
    except (OSError, subprocess.TimeoutExpired):  # no git on this machine, or it hangs
        lines = []
    common = os.path.abspath(lines[0]) if lines and lines[0] else ''
    own = os.path.abspath(lines[1]) if len(lines) > 1 and lines[1] else os.getcwd()
    # Only a plain .git folder names the project; a submodule or a separate git dir is its own project.
    main = os.path.dirname(common) if os.path.basename(common) == '.git' and os.path.isdir(common) else own
    roots = [main] if os.path.realpath(own) == os.path.realpath(main) else [main, own]
    return [os.path.join(root, '.slack-tickets', 'state.json') for root in roots]


def state_path():
    """The shared file: the first of state_paths()."""
    return state_paths()[0]


def linked(path):
    """True when the state file or its folder is a link, which could send a read or a write outside the project."""
    return os.path.islink(path) or os.path.islink(os.path.dirname(path))


def git_exit(folder, *args):
    """The exit code of one git command run in folder, or None when git is not there, hangs or the folder is not usable."""
    try:
        return subprocess.run(['git', '-C', folder, *args], capture_output=True, text=True, timeout=10).returncode
    except (OSError, subprocess.TimeoutExpired):
        return None


def tracked(path):
    """True when git tracks the state file: a file that arrives with a branch, never the script's own."""
    return git_exit(os.path.dirname(os.path.dirname(path)), 'ls-files', '--error-unmatch', '--', '.slack-tickets/state.json') == 0


def believable(last):
    """A reply's timestamp that can be true: a number, and not in the future (a day's slack for a clock that is off)."""
    try:
        return 0 < float(last) <= time.time() + 86400
    except (TypeError, ValueError, OverflowError):
        return False


def read_state(path):
    """The believable part of one state file. Raises on a file that is oddly shaped or unreadable."""
    state = {} if linked(path) or not os.path.lexists(path) or tracked(path) else load(path)
    times = {key: {ts: last for ts, last in state.get(key, {}).items() if believable(last)} for key in ('seen', 'hinted', 'waiting')}
    names = {user: one_line(str(name)) for user, name in state.get('names', {}).items()}
    found = state.get('oldest_open')
    bounds = {channel: last if isinstance(last, str) and TIMESTAMP(last) and believable(last) else ''
              for channel, last in (found.items() if isinstance(found, dict) else ()) if CHANNEL_ID(channel)}
    return dict(times, names=names, bounds=bounds)


def recall():
    """What --answers remembered, read as something a stranger could have put in the project, from every place
    state_paths() names: the later timestamp per reply, hint or waiting thread wins, the first name per user stays, the earliest
    bound of each channel wins (an odd one means reading all of that channel). A missing, unreadable, linked, tracked or oddly shaped file
    counts as nothing remembered. Never raises."""
    seen, hinted, waiting, names, bounds = {}, {}, {}, {}, {}
    try:
        paths = state_paths()
    except Exception:  # whatever the surroundings are, --list must still load with the skill
        paths = []
    for path in paths:
        try:
            part = read_state(path)
        except Exception:  # one bad file must not hide the other
            continue
        for merged, more in ((seen, part['seen']), (hinted, part['hinted']), (waiting, part['waiting'])):
            for ts, last in more.items():
                merged[ts] = max(merged.get(ts, last), last, key=float)
        for user, name in part['names'].items():
            names.setdefault(user, name)
        for channel, found in part['bounds'].items():
            bounds.setdefault(channel, []).append(found)
    return {'names': names, 'seen': seen, 'hinted': hinted, 'waiting': waiting,
            'oldest_open': {channel: '' if '' in found else min(found, key=float) for channel, found in bounds.items()}}


def write_state(path, state):
    folder = os.path.dirname(path)
    if linked(path):
        raise OSError(0, 'a link stands in its place')
    if tracked(path):
        raise OSError(0, 'git tracks it')
    os.makedirs(folder, exist_ok=True)
    try:  # before the state, so the state is never in the project without it; 'x' does not follow a link
        with open(os.path.join(folder, '.gitignore'), 'x', encoding='utf-8') as out:
            out.write('*\n')
    except FileExistsError:
        pass
    if git_exit(os.path.dirname(folder), 'check-ignore', '-q', '--', '.slack-tickets/state.json') == 1:
        raise OSError(0, 'git would not ignore it')
    save(path, state)


def remember(state):
    """Saves what was shown. A folder that cannot be written costs a repeat next time, not the answers just printed."""
    try:
        paths = state_paths()
    except OSError as error:  # the current folder may be gone
        print(f'What was shown could not be remembered ({error.strerror}). The same replies will show as new next time.')
        return
    failed = []
    for path in paths:
        try:
            write_state(path, state)
        except OSError as error:
            failed.append((path, error.strerror))
            continue
        if failed:
            print(f'Remembered in this checkout only ({path}). The shared file could not be used ({failed[0][0]}: {failed[0][1]}).')
        return
    tried = '; '.join(f'{path}: {reason}' for path, reason in failed)
    print(f'What was shown could not be remembered ({tried}). The same replies will show as new next time.')


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
        print(f'Dry run: {count(len(tickets), "ticket")} for {channel}, nothing posted. Add --post to post.')
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
    print(f'Posted {count(len(tickets), "ticket")}. Results: {result_path}')


def fields(lines):
    """A ticket's lines split into its fields, each label read with or without its bold."""
    return [re.sub(r'^\*([^*:]+:)\*', r'\1', part.strip()) for line in lines for part in line.split('\u00b7')]


def is_ticket(message):
    """A ticket's first message: top-level, starts with *Q: and has an Urgency or an Asked by field, bold or not."""
    if message.get('thread_ts', message.get('ts')) != message.get('ts'):
        return False
    lines = (message.get('text') or '').lstrip().split('\n')
    return lines[0].startswith('*Q:') and any(part.startswith(('Urgency:', 'Asked by:')) for part in fields(lines[1:]))


def looks_like_ticket(message):
    """A message that starts like a ticket but that is_ticket() left out."""
    return (message.get('text') or '').lstrip().startswith('*Q:') and not is_ticket(message)


def lookalikes(messages):
    """The line that counts messages starting like a ticket that is_ticket() left out, so a wrong rule shows."""
    found = sum(1 for m in messages if looks_like_ticket(m))
    return [f'Not tickets, though they start with *Q: (no Urgency or Asked by field), in what was read: {found}.'] if found else []


def conversation(messages):
    """The line that says the channel carries messages by people besides the tickets; none when it does not. A message
    the look-alike line already counts is not counted again."""
    found = sum(1 for m in messages if by_people(m) and not looks_like_ticket(m))
    return [f'Not tickets, top-level messages by people, in what was read: {found}.'] if found else []


def history(channel, tok, oldest=''):
    """The channel's top-level messages, oldest first: every one, or those from the one at oldest on."""
    since = {'oldest': oldest, 'inclusive': 'true'} if oldest else {}
    messages, cursor = [], None
    while True:
        page = call('conversations.history', tok, read=True, channel=channel, limit=200, **since, **({'cursor': cursor} if cursor else {}))
        messages += page.get('messages', [])
        cursor = page.get('response_metadata', {}).get('next_cursor')
        if not cursor:
            break
    return sorted(messages, key=lambda m: float(m['ts']))


def read_from(channel, tok, oldest):
    """The top-level messages from where the read starts, and that start: the earlier of the remembered bound and
    WINDOW_DAYS ago. Everything, and no start, when there is no bound or when the bound's message is not among what was
    read or is not a ticket (deleted since, or a value that was never true)."""
    if oldest:
        cutoff = time.time() - WINDOW_DAYS * 86400
        since = oldest if float(oldest) <= cutoff else f'{cutoff:.6f}'
        messages = history(channel, tok, since)
        if any(m.get('ts') == oldest and is_ticket(m) for m in messages):
            return messages, since
    return history(channel, tok), ''


def bound(tickets, is_closed):
    """Where the next read may start: the oldest open ticket, else the newest ticket; nothing when there are none."""
    return next((t['ts'] for t in tickets if not is_closed(t)), tickets[-1]['ts'] if tickets else '')


def read_thread(channel, tok, ts, pages=0, oldest=''):
    """A thread's messages over at most pages pages (0: all), only those after oldest when given, and whether more
    were left unread. Callers pick the top-level message out by its ts: Slack may leave it out after oldest."""
    since = {'oldest': oldest} if oldest else {}
    messages, cursor, read = [], None, 0
    while True:
        page = call('conversations.replies', tok, read=True, channel=channel, ts=ts, limit=200, **since, **({'cursor': cursor} if cursor else {}))
        messages += page.get('messages', [])
        cursor = page.get('response_metadata', {}).get('next_cursor')
        read += 1
        if not cursor or read == pages:
            return messages, bool(cursor)


def replies(channel, tok, ts):
    """Every message of a ticket's thread, the ticket first, over as many pages as Slack serves."""
    return read_thread(channel, tok, ts)[0]


def when(ts):
    return datetime.datetime.fromtimestamp(float(ts)).strftime('%b %d %H:%M')


def replies_count(number):
    return f'{number} repl' + ('y' if number == 1 else 'ies')


def attached(message):
    files = message.get('files')
    return f' [{len(files)} file(s) attached]' if isinstance(files, list) and files else ''


def thread_size(top, fallback):
    return top['reply_count'] if isinstance(top.get('reply_count'), int) else fallback


class People:
    """Names and sides of the people in the channel. Names are kept in the state; users.info is asked once per run."""

    def __init__(self, tok, names, own=None):
        self.tok, self.names, self.own, self.profiles = tok, names, own or {}, {}

    def profile(self, user):
        """users.info's user, or None for one Slack cannot find. Any other failure stops, so a missing scope shows."""
        if user not in self.profiles:
            try:
                self.profiles[user] = call('users.info', self.tok, read=True, user=user).get('user') or {}
            except SystemExit as stop:  # a deleted, foreign or not visible user
                if stop.code not in ('users.info: user_not_found', 'users.info: user_not_visible'):
                    raise
                self.profiles[user] = None
        return self.profiles[user]

    def name(self, user):
        if user and user not in self.names:
            found = self.profile(user)
            if found is None:
                return 'someone'
            self.names[user] = one_line(found.get('real_name') or found.get('name') or user)
        return self.names.get(user) or user or 'someone'

    def plain(self, text, look_up=True):
        text = re.sub(r'<@(\w+)(?:\|[^>]*)?>', lambda m: '@' + (self.name(m.group(1)) if look_up else self.names.get(m.group(1), 'someone')), clean(text or ''))
        text = re.sub(r'<(https?://[^|>]+)\|([^>]+)>', r'\2', text)
        return re.sub(r'<(https?://[^>]+)>', r'\1', text)

    def who(self, message):
        """The side and the name for a script line: a name cannot carry the marks of a field of the line."""
        name = ' '.join(re.sub(r'[|\[\]:]', ' ', self.name(message.get('user'))).split()) or 'someone'
        side = self.side(message)
        through = ' (through an app)' if message.get('user') and message.get('bot_id') and side not in (THIS_APP, AN_APP) else ''
        return f'{side}: {cut(name, FIELD_LENGTH)}{through}'

    def ours(self, message):
        user, bot = message.get('user'), message.get('bot_id')
        return bool((bot and bot == self.own.get('bot_id')) or (user and user == self.own.get('user_id')))

    def person(self, message):
        return self.side(message) not in (THIS_APP, AN_APP)

    def side(self, message):
        """Where a message comes from, seen from the app's own workspace. What Slack does not say is UNKNOWN, never INSIDE.
        A message with a user is the user's, also when another app posted it."""
        user = message.get('user')
        if self.ours(message):
            return THIS_APP
        if not user:
            return AN_APP
        team = self.own.get('team_id')
        if not team:
            return UNKNOWN
        posted = message.get('user_team') or message.get('team')  # the poster's workspace in a channel shared between organizations
        if posted and posted != team:
            return OUTSIDE
        found = self.profile(user)
        if not found:
            return UNKNOWN
        if found.get('is_bot'):
            return AN_APP
        if found.get('is_stranger') or found.get('is_restricted') or found.get('is_ultra_restricted'):
            return OUTSIDE
        home = found.get('team_id')
        return INSIDE if home == team else OUTSIDE if home else UNKNOWN


def listing():
    """One line per open ticket. Claude Code loads it into the skill's text, so it never exits with an error."""
    try:
        lines = list_lines()
    except SystemExit as stop:
        lines = [f'The ticket list could not be read: {stop.code}']
    except Exception as error:  # a failing command would stop the skill from loading in Claude Code
        lines = [f'The ticket list could not be read: {type(error).__name__}']
    try:
        print('\n'.join(lines))
    except Exception as error:  # a character the terminal cannot show must not stop the skill from loading
        try:
            print(f'The ticket list could not be read: {type(error).__name__}')
        except Exception:
            pass


def list_lines():
    channel, tok = channel_id(), token()
    state = recall()
    messages, since = read_from(channel, tok, state['oldest_open'].get(channel, ''))
    tickets = [m for m in messages if is_ticket(m)]
    is_closed = closer(tok)
    still_open = [t for t in tickets if not is_closed(t)]
    read = f', read from {datetime.datetime.fromtimestamp(float(since)).strftime("%b %d")} on' if since else ''
    lines = [f'Channel {channel}: {len(still_open)} open{read}. Open tickets, oldest first:']
    return lines + [ticket_line(t, state['seen']) for t in still_open] + lookalikes(messages) + conversation(messages)


def ticket_line(t, seen):
    """The --list line of one open ticket."""
    lines = re.sub(r'<[^>|]*\|([^>]*)>', r'\1', clean(t.get('text') or '')).split('\n')
    parts = fields(lines[1:])
    level = next((part[len('Urgency:'):].strip() for part in parts if part.startswith('Urgency:')), '?')
    level = cut(re.sub(r':[a-z_]+:', '', level).strip() or level, FIELD_LENGTH)
    by = cut(next((part[len('Asked by:'):].strip() for part in parts if part.startswith('Asked by:')), ''), FIELD_LENGTH)
    day = datetime.datetime.fromtimestamp(float(t['ts'])).strftime('%b %d')
    thread = t.get('reply_count', 0)
    # The ticket's own Details reply comes from its author; anyone else in the thread is an answer or a routing tag.
    others = repliers(t)
    unread = bool(others) and float(t.get('latest_reply', '0')) > float(seen.get(t['ts'], '0'))
    fresh = (', others replied' if others else ', no reply yet') + (', NEW since the last check' if unread else '')
    question = cut(lines[0].strip('* ').removeprefix('Q:').strip(), QUESTION_LENGTH)
    person = '' if t.get('bot_id') else "; posted from a person's account"
    return f'- {question} [{level}; {day}{" by " + by if by else ""}{person}; thread {thread}{fresh}; ts {t["ts"]}]'


def ticket_at(ts, tok, channel):
    """The message at ts when it is a ticket, else None."""
    parent = (call('conversations.replies', tok, read=True, channel=channel, ts=ts, limit=1).get('messages') or [{}])[0]
    return parent if parent.get('ts') == ts and is_ticket(parent) else None


def top_level_at(ts, tok, channel):
    """The top-level message at ts in channel and '', or None and why there is none."""
    try:
        found = call('conversations.replies', tok, read=True, channel=channel, ts=ts, limit=1).get('messages') or []
    except SystemExit as stop:  # a ts of another channel
        if stop.code != 'conversations.replies: thread_not_found':
            raise
        found = []
    first = found[0] if found else {}
    if not first.get('ts'):
        return None, 'that timestamp is not a message in this channel.'
    if first['ts'] == ts and first.get('thread_ts', ts) == ts:
        return first, ''
    parent = first['ts'] if first['ts'] != ts else first.get('thread_ts')
    if isinstance(parent, str) and TIMESTAMP(parent):
        return None, f"that timestamp is a reply in the thread of {parent}. Use {parent}, the thread's top-level message."
    return None, 'that timestamp is not a top-level message in this channel.'


def reply(ts, path, flags):
    with open(path, encoding='utf-8', newline='') as source:  # a lone carriage return is not turned into a newline here
        text = source.read().replace('\r\n', '\n')
    plain = text.translate(EMOJI_GLUE)
    if clean(plain) != plain:
        sys.exit('Not posted: the reply holds characters that cannot be seen. Type it again as plain text.')
    text = text.strip()
    if not text or '<@' in text or '<!' in text or BROADCAST(text) or len(text) > 3500:
        sys.exit('Not posted: a reply needs some text, mentions nobody and fits one message.')
    if not TIMESTAMP(ts):
        sys.exit("Not posted: the first argument is the thread's timestamp, as printed by --answers or --talk (like 1700000000.000100).")
    channel = channel_id()
    try:
        tok = token()
    except SystemExit:
        if '--post' in flags:
            raise
        tok = None  # the dry run still shows the text without a token
    top = None
    if tok:
        top, why = top_level_at(ts, tok, channel)
        if not top:
            sys.exit(f'Not posted: {why}')
        if not is_ticket(top) and not LABEL(text):
            sys.exit('Not posted: a reply outside a ticket\'s thread goes out under the app\'s name, so it starts with a bold '
                     'label and the name it speaks for, like "*Reply* (Jo Tester): ".')
    dry = '--post' not in flags
    if dry:
        print(f'--- reply in the thread of {ts}')
    if top:
        people = People(tok, recall()['names'], us(tok))
        print(f'It starts with: {when(ts)} | {"a ticket" if is_ticket(top) else "not a ticket"} | '
              f'thread {thread_size(top, 0)} | {people.who(top)}')
        print('  ' + cut(one_line(people.plain(top.get('text'), look_up=False)), HINT_LENGTH))
    elif dry:
        print('Not read without a token: the message the thread starts with. Whether it is a ticket was not checked.')
    if dry:
        print(f'--- the reply\n{text}')
        links = list(dict.fromkeys(found.group(1) or found.group(2) for found in LINK(text)))
        if links:
            print('Links in it: ' + ' '.join(links))
        print(f'\nDry run for {channel}, nothing posted. Add --post to post.')
        return
    sent = call('chat.postMessage', tok, channel=channel, thread_ts=ts, text=text, unfurl_links=False, unfurl_media=False)
    print(f'Replied in the thread of {ts} ({sent["ts"]}).')


def same_author(one, other):
    """Two messages from the same person or the same bot; a message with neither has no author to share."""
    return any(one.get(key) and one.get(key) == other.get(key) for key in ('user', 'bot_id'))


def us(tok):
    """The token's own user, bot and workspace ids from auth.test; none when Slack does not say."""
    try:
        who = call('auth.test', tok)
        return {key: who[key] for key in ('user_id', 'bot_id', 'team_id') if isinstance(who.get(key), str) and who[key]}
    except (SystemExit, Exception):  # call() fails through sys.exit; --list must not fail over it, and a miss leaves a ticket open
        return {}


def identity(tok):
    """The token's own user and bot ids, or none when Slack does not say, so that a check mark then reads as open."""
    own = us(tok)
    return {own[key] for key in ('user_id', 'bot_id') if key in own}


def closer(tok):
    """A test for a closed ticket: a check mark from its author or from this token, whose ids are asked for once and
    only when a check mark comes from someone else."""
    me = None

    def is_closed(ticket):
        nonlocal me
        users = {u for r in ticket.get('reactions') or [] if r.get('name') == CLOSED for u in r.get('users') or []}
        if not users or ticket.get('user') in users:
            return bool(users)
        if me is None:
            me = identity(tok)
        return bool(users & me)
    return is_closed


def repliers(ticket):
    """Who replied in a ticket's thread, its author left out."""
    return set(ticket.get('reply_users') or []) - {ticket.get('user'), ticket.get('bot_id'), None}


def by_people(message):
    """A person's own top-level message: not a ticket, not from an app, not a join or a reply also sent to the channel."""
    return bool(message.get('user')) and not message.get('bot_id') and message.get('subtype') in (None, 'file_share') and not is_ticket(message)


def hints(ticket, messages):
    """The first HINTS messages by people other than the ticket's author, posted after it and before the next ticket."""
    found = []
    for message in messages[messages.index(ticket) + 1:]:
        if is_ticket(message) or len(found) == HINTS:
            break
        if by_people(message) and not same_author(message, ticket):
            found.append(message)
    return found


def close(ts):
    if not TIMESTAMP(ts):
        sys.exit('Not closed: the argument is the ticket\'s timestamp, as printed by --answers (like 1700000000.000100).')
    channel, tok = channel_id(), token()
    ticket = ticket_at(ts, tok, channel)
    if not ticket:
        sys.exit('Not closed: that timestamp is not a ticket in this channel.')
    if closer(tok)(ticket):
        print(f'Already closed {ts}.')
        return
    try:
        call('reactions.add', tok, channel=channel, timestamp=ts, name=CLOSED)
    except SystemExit as stop:
        if stop.code != 'reactions.add: already_reacted':
            raise
        print(f'Already closed {ts}.')
        return
    print(f'Closed {ts}.')


def answers(flags):
    channel, tok = channel_id(), token()
    state = recall()
    names, seen = state.setdefault('names', {}), state.setdefault('seen', {})
    hinted = state.setdefault('hinted', {})
    people = People(tok, names)
    name, plain = people.name, people.plain
    show_all = '--all' in flags
    messages, _ = read_from(channel, tok, '' if show_all else state['oldest_open'].get(channel, ''))
    tickets = [m for m in messages if is_ticket(m)]
    is_closed = closer(tok)

    open_count, shown = 0, 0
    for ticket in tickets:
        closed = is_closed(ticket)
        open_count += 0 if closed else 1
        last_seen = '0' if show_all else seen.get(ticket['ts'], '0')
        latest = ticket.get('latest_reply', '0')
        fresh, fetched = [], False
        if ticket.get('reply_count') and (show_all or float(latest) > float(last_seen)):
            thread, fetched = replies(channel, tok, ticket['ts'])[1:], True
            # The ticket's own Details reply, from its author, is part of the ticket, not an answer (bold or not).
            fresh = [r for r in thread if float(r['ts']) > float(last_seen)
                     and not (same_author(r, ticket) and (r.get('text') or '').lstrip(' *\n').startswith('Details'))]
        offered = [] if closed or repliers(ticket) else hints(ticket, messages)
        new_hints = [m for m in offered if show_all or float(m['ts']) > float(hinted.get(ticket['ts'], '0'))]
        if not fresh and not new_hints and not show_all:
            if fetched and '--peek' not in flags:  # nothing to show, so no need to read it again until it grows
                seen[ticket['ts']] = latest
            continue
        lines = plain(ticket['text']).split('\n')
        question = cut(lines[0].strip('*').strip(), QUESTION_LENGTH)
        parts = fields(lines)
        urgency = cut(next((part for part in parts if part.startswith('Urgency:')), ''), FIELD_LENGTH)
        by = next((' by ' + cut(part[len('Asked by:'):].strip(), FIELD_LENGTH) for part in parts if part.startswith('Asked by:')), '')
        poster = '' if ticket.get('bot_id') else f" | posted from a person's account ({name(ticket.get('user'))})"
        print(f'[{"closed" if closed else "open"}] {question}\n  {urgency} | asked {when(ticket["ts"])}{by} | ts {ticket["ts"]}{poster}')
        for reply in fresh:
            body = plain(reply.get('text')).replace('\n', '\n      ')
            files = f' [{len(reply["files"])} file(s) attached]' if reply.get('files') else ''
            print(f'    {name(reply.get("user"))}, {when(reply["ts"])}: {body}{files}')
        if new_hints:
            print('  Not in its thread: posted in the channel after it, by others, and may be unrelated:')
            for m in new_hints:
                text = one_line(plain(m.get('text'), look_up=False))
                print(f'    > {name(m.get("user"))}, {when(m["ts"])}: {cut(text, HINT_LENGTH)}')
        shown += 1
        if '--peek' not in flags and not show_all:
            seen[ticket['ts']] = latest
            if new_hints:
                hinted[ticket['ts']] = new_hints[-1]['ts']
    if not shown:
        print('No new replies.')
    for line in lookalikes(messages):
        print(line)
    print(f'{count(open_count, "ticket")} open.')
    if '--peek' not in flags:
        newest, kept = bound(tickets, is_closed), state['oldest_open'].get(channel, '')
        if not show_all or not kept or (newest and float(newest) < float(kept)) or all(t['ts'] != kept for t in tickets):
            state['oldest_open'][channel] = newest
    remember(state)


def talk(flags):
    """Threads that are not tickets, started in the last WINDOW_DAYS days by a person or an app, and that hold a message by
    a person: those with news since the last --talk, oldest first, or every one with --all, the newest. At most
    TALK_THREADS are printed and TALK_READS read per run, each marked by where its last word came from."""
    channel, tok = channel_id(), token()
    state = recall()
    seen, waiting = state['seen'], state['waiting']
    show_all, keep = '--all' in flags, not ({'--all', '--peek'} & flags)
    cutoff = time.time() - WINDOW_DAYS * 86400
    messages = history(channel, tok, f'{cutoff:.6f}')
    people = People(tok, state['names'], us(tok))
    is_closed = closer(tok)
    after = {m['ts']: t['ts'] for t in messages if is_ticket(t) and not is_closed(t) and not repliers(t) for m in hints(t, messages)}

    def newest(m):
        """The channel's own newest timestamp of a thread: its latest reply, or the message itself."""
        return max(m['ts'], m.get('latest_reply') or m['ts'], key=float)

    def shown_to(m):
        """What was shown of a thread. The state is untrusted: a time after the thread's newest message is no time at all."""
        found = '0' if show_all else seen.get(m['ts'], '0')
        return found if float(found) <= float(newest(m)) else '0'

    def settle(top, upto, ended=False):
        """A thread with nothing to print is not news again: seen moves on, and the thread stays waiting unless we had the last word."""
        if keep:
            seen[top['ts']] = upto
            if ended:
                waiting.pop(top['ts'], None)
            elif top['ts'] in waiting:
                waiting[top['ts']] = upto

    threads = [m for m in messages if float(m['ts']) >= cutoff and not is_ticket(m)  # also when Slack sent older ones
               and m.get('subtype') in (None, 'file_share', 'bot_message') and (m.get('user') or m.get('bot_id'))
               and not (m.get('bot_id') and people.ours(m))]  # this app's own messages, not those of the person whose token it is
    news = sorted((m for m in threads if float(newest(m)) > float(shown_to(m))), key=lambda m: float(newest(m)), reverse=show_all)
    blocks, left, reads = [], 0, 0
    for top in news:
        replied = bool(top.get('reply_count'))
        if not replied and not top.get('user'):  # an app's message nobody replied to: nothing to read, nothing to print
            settle(top, newest(top))
            continue
        if len(blocks) == TALK_THREADS or (replied and reads == TALK_READS):
            left += 1
            continue
        last_seen = shown_to(top)
        since = last_seen if TIMESTAMP(last_seen) else ''  # state is untrusted: only a real timestamp goes to Slack
        thread, more = read_thread(channel, tok, top['ts'], TALK_PAGES, since) if replied else ([], False)
        reads += replied
        later = [r for r in thread if r.get('ts') != top['ts'] and float(r['ts']) > float(last_seen)]
        read_to = max((r['ts'] for r in later), key=float, default=top['ts'])
        upto = read_to if more else max(newest(top), read_to, key=float)  # a reply that came after the channel was read counts
        ended = not show_all and not more and bool(later) and people.side(later[-1]) == THIS_APP
        if ended or not any(people.person(m) for m in [top] + later) or (not later and float(top['ts']) <= float(last_seen)):
            settle(top, upto, ended)
            continue
        side = UNKNOWN if more else people.side((later or [top])[-1])
        side = UNKNOWN if side == AN_APP else side
        listed = later[-TALK_REPLIES:]
        total = thread_size(top, len(later))
        earlier, new_hidden = 0 if more else max(total - len(later), 0), len(later) - len(listed)
        if show_all:
            earlier, new_hidden = earlier + new_hidden, 0
        hint = f' | may answer the ticket {after[top["ts"]]}' if top['ts'] in after else ''
        lines = [f'[last word {side}] ts {top["ts"]} | thread {total}{hint} | {when(top["ts"])} | {people.who(top)}',
                 '  ' + cut(one_line(people.plain(top.get('text'), look_up=False)), TALK_LENGTH) + attached(top)]
        if earlier:
            lines.append(f'    (earlier, not shown: {replies_count(earlier)})')
        if new_hidden:
            lines.append(f'    (new, not shown: {replies_count(new_hidden)}. tickets.py --thread {top["ts"]} shows them.)')
        for r in listed:
            lines.append(f'    {when(r["ts"])} | {people.who(r)}: '
                         f'{cut(one_line(people.plain(r.get("text"), look_up=False)), TALK_LENGTH)}{attached(r)}')
        if more:
            lines.append(f'    (a long thread: {len(later)} new messages were read, not all. tickets.py --thread {top["ts"]} shows more.)')
        blocks.append((top, side, upto, lines))
    if show_all:
        blocks.reverse()
    open_ended = 0
    for top, side, upto, lines in blocks:
        print('\n'.join(lines))
        open_ended += side in (OUTSIDE, UNKNOWN)
        if keep:
            seen[top['ts']] = upto
            if side in (OUTSIDE, UNKNOWN):
                waiting[top['ts']] = upto
            else:
                waiting.pop(top['ts'], None)
    if not blocks:
        print(f'No conversation in the last {WINDOW_DAYS} days.' if show_all else 'No new conversation.')
    if left and show_all:
        print(f'Not shown: {count(left, "older thread")}.')
    elif left:
        print(f'Not read yet: {count(left, "more thread")} that may have news. They are read at the next checks, oldest first.')
    if blocks:
        print(f'Last word outside or unknown: {open_ended} of {count(len(blocks), "thread")} shown.')
    if not show_all:
        printed = {top['ts'] for top, _, _, _ in blocks}
        still = sum(1 for m in threads if m['ts'] not in printed and m['ts'] in waiting and float(waiting[m['ts']]) >= float(newest(m)))
        if still:
            print(f'Shown before, last word still outside or unknown: {count(still, "thread")}. tickets.py --talk --all shows them again.')
    if keep:
        gone = [ts for ts, last in waiting.items() if float(last) < cutoff or (TIMESTAMP(ts) and float(ts) < cutoff)]
        for ts in gone:
            del waiting[ts]
        if gone:
            print(f'Older than two weeks now, last word still outside or unknown: {count(len(gone), "thread")}. tickets.py --thread <ts> reads one.')
    remember(state)


def show_thread(ts):
    """One thread, bounded: its first message and its last THREAD_REPLIES replies, each cut to THREAD_LENGTH."""
    if not TIMESTAMP(ts):
        sys.exit("Not read: the argument is a top-level message's timestamp, as printed by --talk (like 1700000000.000100).")
    channel, tok = channel_id(), token()
    top, why = top_level_at(ts, tok, channel)
    if not top:
        sys.exit(f'Not read: {why}')
    people = People(tok, recall()['names'], us(tok))
    thread, more = read_thread(channel, tok, ts, THREAD_PAGES)
    later = [r for r in thread if r.get('ts') != ts]
    listed = later[-THREAD_REPLIES:]
    print(f'Thread {ts} in {channel}, {"a ticket" if is_ticket(top) else "not a ticket"}, '
          f'{replies_count(thread_size(top, len(later)))}:')
    for number, message in enumerate([top] + listed):
        if number == 1 and len(later) > len(listed):
            print(f'  (earlier, not shown: {replies_count(len(later) - len(listed))})')
        print(f'  {when(message["ts"])} | {people.who(message)}{attached(message)}')
        print('\n'.join('    ' + line for line in cut(people.plain(message.get('text'), look_up=False), THREAD_LENGTH).split('\n')))
    if more:
        print(f'(A long thread: only its first {THREAD_PAGES * 200} messages were read, so the newest are not shown.)')


def main():
    args = [a for a in sys.argv[1:] if not a.startswith('--')]
    flags = {a for a in sys.argv[1:] if a.startswith('--')}
    if any(flag not in FLAGS and not flag.startswith('--channel=') for flag in flags):
        sys.exit(__doc__)
    if '--setup' in flags:
        setup()
    elif '--sources-template' in flags:
        show_file('The register template', 'assets/sources-template.md')
    elif '--sources' in flags:
        sources()
    elif '--check' in flags:
        print(f'Channel {channel_id()}.')
        who = call('auth.test', token())
        print(f'Posting as {who.get("user")} in {who.get("team")}' + (' (a bot)' if who.get('bot_id') else ' (a person)'))
    elif '--list' in flags:
        listing()
    elif '--answers' in flags:
        answers(flags)
    elif '--talk' in flags:
        talk(flags)
    elif '--thread' in flags:
        if len(args) != 1:
            sys.exit(__doc__)
        show_thread(args[0])
    elif '--reply' in flags:
        if len(args) != 2:
            sys.exit(__doc__)
        reply(args[0], args[1], flags)
    elif '--close' in flags:
        if len(args) != 1:
            sys.exit(__doc__)
        close(args[0])
    elif len(args) == 1:
        post(args[0], flags)
    else:
        sys.exit(__doc__)


if __name__ == '__main__':
    main()
