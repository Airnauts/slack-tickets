"""Shared pieces for the tests. Nothing here can reach Slack.

In-process tests stub the one function that talks to Slack (tickets.call) and the token lookup (tickets.token),
and make urllib's urlopen raise, so a path that was missed fails loudly. Command line tests run the script in a
process whose PATH is an empty folder, with no token, so it stops before any network call.
"""
import contextlib
import importlib.util
import io
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
import urllib.request
from collections import namedtuple
from unittest import mock

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SCRIPT = os.path.join(ROOT, 'skills', 'ticket', 'scripts', 'tickets.py')

CHANNEL = 'C0000000000'
OTHER_CHANNEL = 'C1111111111'
THIRD_CHANNEL = 'C2222222222'

Call = namedtuple('Call', 'method tok read payload')
Result = namedtuple('Result', 'code out')


def load_script():
    """The script as a module, without leaving bytecode in the skill's folder."""
    spec = importlib.util.spec_from_file_location('tickets', SCRIPT)
    module = importlib.util.module_from_spec(spec)
    keep, sys.dont_write_bytecode = sys.dont_write_bytecode, True
    try:
        spec.loader.exec_module(module)
    finally:
        sys.dont_write_bytecode = keep
    return module


tickets = load_script()


def run_cli(args, channel=None, extra_env=None, cwd=None):
    """Runs the script as a command, with nothing on PATH and no token. Returns (exit code, output).
    Never pass --post here: with no token the script stops before it could call Slack."""
    with tempfile.TemporaryDirectory(prefix='tickets-path-') as empty:
        env = {k: v for k, v in os.environ.items() if not k.startswith('SLACK_TICKETS_')}
        env['PATH'] = empty
        if channel is not None:
            env['SLACK_TICKETS_CHANNEL'] = channel
        env.update(extra_env or {})
        env.pop('SLACK_TICKETS_TOKEN', None)
        done = subprocess.run([sys.executable, SCRIPT, *args], env=env, cwd=cwd or empty,
                              capture_output=True, text=True, timeout=60)
    return done.returncode, done.stdout + done.stderr


class FakeSlack:
    """Stands in for tickets.call. Records every call and answers with canned payloads per method name.

    respond(method, answer) takes a dict, a function of the call's arguments, or several of them in turn
    (the last one repeats). A function may raise. A method nobody gave an answer for fails the test."""

    def __init__(self):
        self.calls = []
        self.answers = {}

    def respond(self, method, *answers):
        self.answers[method] = list(answers)

    def __call__(self, method, tok, read=False, **payload):
        self.calls.append(Call(method, tok, read, payload))
        if method not in self.answers:
            raise AssertionError(f'unexpected Slack call: {method} {payload}')
        answers = self.answers[method]
        answer = answers[min(len(self.made(method)) - 1, len(answers) - 1)]
        return answer(**payload) if callable(answer) else answer

    def made(self, method):
        """The payloads of every call to one method, in order."""
        return [c.payload for c in self.calls if c.method == method]

    def methods(self):
        return [c.method for c in self.calls]


class TicketsTestCase(unittest.TestCase):
    """A scratch folder as the current folder, no Slack variables, and Slack out of reach."""

    def setUp(self):
        self.tickets = tickets
        self.start = os.getcwd()
        self.tmp = os.path.realpath(tempfile.mkdtemp(prefix='tickets-test-'))
        self.addCleanup(self.remove_tmp)
        os.chdir(self.tmp)

        env = mock.patch.dict(os.environ)
        env.start()
        self.addCleanup(env.stop)
        os.environ.pop('SLACK_TICKETS_CHANNEL', None)
        os.environ.pop('SLACK_TICKETS_TOKEN', None)
        # A scratch folder is never part of a repository that happens to hold the temporary folder.
        os.environ['GIT_CEILING_DIRECTORIES'] = os.path.dirname(self.tmp)

        self.slack = FakeSlack()
        self.patch(tickets, 'call', self.slack)
        self.patch(tickets, 'token', lambda: 'xoxb-test')
        self.patch(urllib.request, 'urlopen', side_effect=AssertionError('a test tried to reach the network'))
        self.patch(sys, 'argv', ['tickets.py'])
        self.sleeps = self.patch(tickets.time, 'sleep')

    def patch(self, target, name, *args, **kwargs):
        patcher = mock.patch.object(target, name, *args, **kwargs)
        started = patcher.start()
        self.addCleanup(patcher.stop)
        return started

    def remove_tmp(self):
        os.chdir(self.start)
        shutil.rmtree(self.tmp, ignore_errors=True)

    def set_channel(self, channel=CHANNEL):
        os.environ['SLACK_TICKETS_CHANNEL'] = channel

    def run_main(self, *argv):
        """tickets.main() with these arguments. Returns (code, output): code is None when main returned,
        otherwise what it exited with (a message, for a refusal)."""
        sys.argv = ['tickets.py', *argv]
        out = io.StringIO()
        code = None
        with contextlib.redirect_stdout(out):
            try:
                tickets.main()
            except SystemExit as stop:
                code = stop.code
        return Result(code, out.getvalue())

    def write(self, name, text):
        """A file in the scratch folder; returns its path."""
        path = os.path.join(self.tmp, name)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, 'w', encoding='utf-8') as out:
            out.write(text)
        return path

    def write_json(self, name, value):
        return self.write(name, json.dumps(value))

    def read_json(self, name):
        with open(os.path.join(self.tmp, name), encoding='utf-8') as source:
            return json.load(source)

