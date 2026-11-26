#!/usr/bin/env python3
"""Measures how often a headless Claude Code session reaches for the ticket skill, judging by its name and description.

For each prompt in trigger-evals.json it starts real sessions in a scratch project holding only a stub skill that
carries the description, and watches for the first tool call. If that call picks the stub, the description worked.
The session is stopped at its first tool call. A call to another skill or a file read is recognised a moment later than
other tools, so it may have started when the session is stopped.

Every run is a real, paid session. It uses the caller's own Claude Code settings, with their connectors, and it is
stopped at its first tool call. Do not run it casually.

Prompts must use invented names only: never a real channel, person or project. Prompts must not name files to
open: a file read is a first tool call, so it scores as a miss whatever the description says.

Results depend on the model and on the other skills and hooks the caller has installed.

Usage: python3 tests/description/run.py [--runs 3] [--workers 6] [--model M] [--json out.json]
"""
import argparse
import concurrent.futures
import json
import os
import re
import shutil
import signal
import subprocess
import sys
import tempfile
import threading
import uuid

HERE = os.path.dirname(os.path.abspath(__file__))
DEFAULT_PROMPTS = os.path.join(HERE, 'trigger-evals.json')
DEFAULT_SKILL = os.path.join(os.path.dirname(os.path.dirname(HERE)), 'skills', 'ticket', 'SKILL.md')

# Tools whose input can name the stub: the Skill tool, or a Read of the stub's command file. Each maps to the input
# key that holds the name.
WATCHED_TOOLS = {'Skill': 'skill', 'Read': 'file_path'}

# Sessions that are running now, and whether the run is being stopped.
LIVE = set()
LIVE_LOCK = threading.Lock()
STOPPING = threading.Event()
STARTED = 0

# Texts of what failed sessions wrote to stderr, in the order they were found.
ERROR_REASONS = []


def read_description(path):
    """The description value from the frontmatter of a SKILL.md. Raises ValueError if it is missing or not one line."""
    with open(path, encoding='utf-8') as f:
        lines = f.read().split('\n')
    if not lines or lines[0].strip() != '---':
        raise ValueError(f'{path} has no frontmatter')
    for line in lines[1:]:
        if line.strip() == '---':
            break
        if not line.startswith('description:'):
            continue
        value = line[len('description:'):].strip()
        if len(value) >= 2 and value[0] == value[-1] == '"':
            try:
                value = json.loads(value)
            except ValueError:
                value = value[1:-1]
        elif len(value) >= 2 and value[0] == value[-1] == "'":
            value = value[1:-1].replace("''", "'")
        if not value or value[0] in '|>':
            raise ValueError(f'{path}: the description must be one line, bare or in quotes')
        return value
    raise ValueError(f'{path} has no description in its frontmatter')


def stub_text(description):
    """The content of the stub command file: the description as frontmatter, and again in the body."""
    indented = description.replace('\n', '\n  ')
    return f'---\ndescription: |\n  {indented}\n---\n\n# ticket\n\nThis skill handles: {description}\n'


class Watcher:
    """Reads a session's events one at a time and decides at the first tool call.

    feed(event) returns True (the stub was picked), False (it was not) or None (not decided yet). Once it has
    decided, it keeps returning the same answer."""

    def __init__(self, stub):
        self.stub = stub
        self.result = None
        self.key = None
        self.text = ''

    def feed(self, event):
        if self.result is None and isinstance(event, dict):
            self.result = self._step(event)
        return self.result

    def _step(self, event):
        kind = event.get('type')
        if kind == 'stream_event':
            return self._stream(event.get('event') or {})
        if kind == 'assistant':
            content = (event.get('message') or {}).get('content')
            for item in content if isinstance(content, list) else []:
                if isinstance(item, dict) and item.get('type') == 'tool_use':
                    return self._whole_call(item)
            return None
        if kind == 'result':
            # A session that failed (bad model, not logged in, rate limit) is an error, not a miss.
            if event.get('is_error') or event.get('subtype', 'success') != 'success':
                return None
            return False
        return None

    def _value(self):
        """(value so far, closed) of the collected call's key, or (None, False) while the key has not appeared."""
        match = re.search(r'"' + self.key + r'"\s*:\s*"((?:[^"\\]|\\.)*)("?)', self.text)
        return (match.group(1), bool(match.group(2))) if match else (None, False)

    def _hit(self):
        value = self._value()[0]
        return value is not None and self.stub in value

    def _stream(self, inner):
        kind = inner.get('type')
        if kind == 'content_block_start':
            block = inner.get('content_block') or {}
            if block.get('type') != 'tool_use':
                return None
            if block.get('name') in WATCHED_TOOLS:
                self.key = WATCHED_TOOLS[block['name']]
                return None
            return False
        if kind == 'content_block_delta' and self.key:
            delta = inner.get('delta') or {}
            if delta.get('type') == 'input_json_delta':
                self.text += delta.get('partial_json') or ''
                value, closed = self._value()
                if value is not None and self.stub in value:
                    return True
                if closed:
                    return False
            return None
        if kind == 'content_block_stop' and self.key:
            return self._hit()
        if kind == 'message_stop':
            return self._hit() if self.key else False
        return None

    def _whole_call(self, item):
        name = item.get('name')
        args = item.get('input') or {}
        if name == 'Skill':
            return self.stub in str(args.get('skill', ''))
        if name == 'Read':
            return self.stub in str(args.get('file_path', ''))
        return False


def decide(events, stub):
    """True, False or None (no decision) for a finished list of parsed events."""
    watcher = Watcher(stub)
    for event in events:
        answer = watcher.feed(event)
        if answer is not None:
            return answer
    return None


def _kill(proc):
    """Stops the session and anything it started, even when the session itself has already exited."""
    try:
        os.killpg(proc.pid, signal.SIGKILL)
    except (OSError, AttributeError):
        pass
    if proc.poll() is None:
        try:
            proc.kill()
        except OSError:
            pass


def error_reason(path):
    """The last 300 characters of a stderr file on one line. Empty when there is no file or nothing in it."""
    try:
        with open(path, encoding='utf-8', errors='replace') as f:
            return ' '.join(f.read().split())[-300:]
    except OSError:
        return ''


def run_once(query, description, model, timeout, extra=()):
    """One session in its own scratch project. True if it picked the stub, False if not, None on error.

    When a session ends as an error, what it wrote to stderr is added to ERROR_REASONS."""
    global STARTED
    if STOPPING.is_set():
        return None
    stub = f'ticket-check-{uuid.uuid4().hex[:8]}'
    project = tempfile.mkdtemp()
    stderr_path = os.path.join(project, 'stderr.txt')
    proc = None
    timer = None
    answer = None
    try:
        commands = os.path.join(project, '.claude', 'commands')
        os.makedirs(commands)
        with open(os.path.join(commands, f'{stub}.md'), 'w', encoding='utf-8') as f:
            f.write(stub_text(description))
        cmd = ['claude', '-p', query, '--output-format', 'stream-json', '--verbose', '--include-partial-messages',
               '--no-session-persistence']  # hundreds of scratch sessions would otherwise fill the caller's history
        if model:
            cmd += ['--model', model]
        cmd += list(extra)
        env = {k: v for k, v in os.environ.items() if k != 'CLAUDECODE'}
        with open(stderr_path, 'wb') as stderr_file:
            proc = subprocess.Popen(cmd, cwd=project, env=env, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                                    stderr=stderr_file, text=True, start_new_session=True)
        with LIVE_LOCK:
            LIVE.add(proc)
            STARTED += 1
        if STOPPING.is_set():
            return None
        timer = threading.Timer(timeout, _kill, args=(proc,))
        timer.start()
        watcher = Watcher(stub)
        for line in proc.stdout:
            try:
                event = json.loads(line)
            except ValueError:
                continue
            answer = watcher.feed(event)
            if answer is not None:
                return answer
        return None
    except OSError:
        return None
    finally:
        if timer is not None:
            timer.cancel()
        if proc is not None:
            _kill(proc)
            try:
                proc.wait(timeout=10)
            except subprocess.TimeoutExpired:
                pass
            if proc.stdout is not None:
                proc.stdout.close()
            with LIVE_LOCK:
                LIVE.discard(proc)
        if answer is None and not STOPPING.is_set():
            reason = error_reason(stderr_path)
            if reason:
                with LIVE_LOCK:
                    ERROR_REASONS.append(reason)
        shutil.rmtree(project, ignore_errors=True)


def _interrupt(signum, frame):
    """SIGTERM handler: stop the run the way Ctrl-C does."""
    raise KeyboardInterrupt


def is_wrong(should_trigger, hits, decided):
    """True when the rate is on the wrong side of 0.5 (or no run decided)."""
    if decided == 0:
        return True
    rate = hits / decided
    return rate < 0.5 if should_trigger else rate >= 0.5


def main():
    parser = argparse.ArgumentParser(description='Measure how often a session picks the ticket skill by its name and '
                                                 'description. Every run is a real, paid Claude Code session.')
    parser.add_argument('--prompts', default=DEFAULT_PROMPTS, help='JSON list of {query, should_trigger}')
    parser.add_argument('--skill', default=DEFAULT_SKILL, help='SKILL.md whose description is scored')
    parser.add_argument('--description-file', help='score the text of this file instead of the skill description')
    parser.add_argument('--model', help='model for the sessions')
    parser.add_argument('--runs', type=int, default=3, help='sessions per prompt (default 3)')
    parser.add_argument('--workers', type=int, default=6, help='sessions at the same time (default 6)')
    parser.add_argument('--timeout', type=int, default=90, help='seconds before a session counts as an error (default 90)')
    parser.add_argument('--json', help='write the full result to this file')
    parser.add_argument('--claude-arg', action='append', default=[], metavar='ARG',
                        help='one more argument for claude, repeatable, written with "=": '
                             '--claude-arg=--setting-sources --claude-arg=project leaves your own settings, hooks '
                             'and plugins out')
    args = parser.parse_args()

    if args.description_file:
        with open(args.description_file, encoding='utf-8') as f:
            description = f.read().strip()
    else:
        description = read_description(args.skill)
    if not description:
        sys.exit('The description is empty.')
    with open(args.prompts, encoding='utf-8') as f:
        prompts = json.load(f)
    if shutil.which('claude') is None:
        sys.exit('The claude command is not on PATH.')

    results = [[] for _ in prompts]
    pool = concurrent.futures.ThreadPoolExecutor(max_workers=args.workers)
    previous = signal.signal(signal.SIGTERM, _interrupt)
    try:
        futures = [(i, pool.submit(run_once, item['query'], description, args.model, args.timeout, args.claude_arg))
                   for i, item in enumerate(prompts) for _ in range(args.runs)]
        for i, future in futures:
            results[i].append(future.result())
        pool.shutdown()
    except KeyboardInterrupt:
        STOPPING.set()
        pool.shutdown(wait=False, cancel_futures=True)
        with LIVE_LOCK:
            running = list(LIVE)
            started = STARTED
        for proc in running:
            _kill(proc)
        print(f'Stopped: {started} sessions were started, the rest were not.', file=sys.stderr)
        sys.exit(130)
    finally:
        signal.signal(signal.SIGTERM, previous)

    rows = []
    wrong_any = False
    fired = quiet = errors = should_total = should_not_total = 0
    for item, runs in zip(prompts, results):
        hits = sum(1 for r in runs if r is True)
        decided = sum(1 for r in runs if r is not None)
        failed = len(runs) - decided
        errors += failed
        wrong = is_wrong(item['should_trigger'], hits, decided)
        wrong_any = wrong_any or wrong
        if item['should_trigger']:
            should_total += 1
            fired += not wrong
        else:
            should_not_total += 1
            quiet += not wrong
        note = f' (+{failed} err)' if failed else ''
        print(f"{'WRONG' if wrong else '     '} {'+' if item['should_trigger'] else '-'} "
              f'{hits}/{decided}{note} {item["query"][:90]}')
        rows.append({'query': item['query'], 'should_trigger': item['should_trigger'], 'hits': hits,
                     'decided': decided, 'errors': failed, 'runs': runs, 'wrong': wrong})
    print(f'description: {len(description)} chars, fired {fired}/{should_total} should-trigger, '
          f'quiet {quiet}/{should_not_total} should-not, errors {errors}/{len(prompts) * args.runs} runs')
    if errors:
        print(f'First error: {ERROR_REASONS[0] if ERROR_REASONS else "no output"}')

    if args.json:
        with open(args.json, 'w', encoding='utf-8') as f:
            json.dump({'description': description, 'length': len(description), 'model': args.model,
                       'runs': args.runs, 'fired': fired, 'should_trigger': should_total, 'quiet': quiet,
                       'should_not_trigger': should_not_total, 'errors': errors, 'prompts': rows}, f, indent=2)
            f.write('\n')
    return 1 if wrong_any else 0


if __name__ == '__main__':
    sys.exit(main())
