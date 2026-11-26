"""--setup, the files it prints, and the messages that point to it.

Each run has an empty PATH and no token, so the script stops before it could call Slack."""
import os
import re
import shutil
import subprocess
import sys
import tempfile
import unittest

from helpers import CHANNEL, ROOT, TicketsTestCase, run_cli

SKILL = os.path.join(ROOT, 'skills', 'ticket')
STEPS = ('The setup steps', 'references/setup.md')
MANIFEST = ('The Slack app manifest', 'assets/slack-app-manifest.yaml')
TEMPLATE = ('The register template', 'assets/sources-template.md')
NO_TOKEN = 'No Slack token: set SLACK_TICKETS_TOKEN, or store it in the Keychain under "slack-tickets". tickets.py --setup prints the steps.'


def read(folder, name):
    with open(os.path.join(folder, name), encoding='utf-8') as source:
        return source.read()


def run_script(script, args):
    """A copy or a link of the script, run as a command with nothing on PATH and no token. Returns (code, output)."""
    with tempfile.TemporaryDirectory(prefix='tickets-path-') as empty:
        env = {k: v for k, v in os.environ.items() if not k.startswith('SLACK_TICKETS_')}
        env['PATH'] = empty
        env['PYTHONDONTWRITEBYTECODE'] = '1'
        done = subprocess.run([sys.executable, script, *args], env=env, cwd=empty, capture_output=True, text=True, timeout=60)
    return done.returncode, done.stdout + done.stderr


def section(out, title, name):
    """What is printed between a file's header and its end marker."""
    match = re.search(re.escape(f'===== {title}: {name} =====\n') + r'(.*?)\n' + re.escape(f'===== End of {name} =====\n'), out, re.S)
    return match.group(1) if match else None


class SetupTests(TicketsTestCase):
    def test_setup_prints_both_files_and_nothing_about_a_channel(self):
        code, out = run_cli(['--setup'])
        self.assertEqual(code, 0)
        for title, name in (STEPS, MANIFEST):
            self.assertIn(f'===== {title}: {name} =====', out)
            self.assertIn(f'===== End of {name} =====', out)
        self.assertFalse([line for line in out.splitlines() if line.startswith(('Channel', 'Posting'))])

    def test_each_section_is_the_file_stripped(self):
        _, out = run_cli(['--setup'])
        for title, name in (STEPS, MANIFEST):
            self.assertEqual(section(out, title, name), read(SKILL, name).strip())

    def test_a_channel_variable_that_is_not_an_id_does_not_stop_it_or_show(self):
        secret = 'xoxb-not-a-channel'
        code, out = run_cli(['--setup', '--channel=bad'], channel=secret)
        self.assertEqual(code, 0)
        self.assertNotIn(secret, out)
        self.assertIn(f'===== End of {MANIFEST[1]} =====', out)

    def test_a_missing_file_is_said_and_the_other_still_prints(self):
        with tempfile.TemporaryDirectory(prefix='tickets-copy-') as scratch:
            copy = os.path.join(scratch, 'ticket')
            shutil.copytree(SKILL, copy, ignore=shutil.ignore_patterns('__pycache__'))
            os.remove(os.path.join(copy, 'references', 'setup.md'))
            code, out = run_script(os.path.join(copy, 'scripts', 'tickets.py'), ['--setup'])
        self.assertEqual(code, 0)
        self.assertIn("(Missing from the skill's folder: references/setup.md (FileNotFoundError).)", out.splitlines())
        self.assertEqual(section(out, *MANIFEST), read(SKILL, MANIFEST[1]).strip())

    def test_sources_template_prints_the_file_and_needs_no_channel_or_token(self):
        code, out = run_cli(['--sources-template'])
        self.assertEqual(code, 0)
        self.assertEqual(section(out, *TEMPLATE), read(SKILL, TEMPLATE[1]).strip())

    def test_a_missing_template_is_said_with_exit_zero(self):
        with tempfile.TemporaryDirectory(prefix='tickets-copy-') as scratch:
            copy = os.path.join(scratch, 'ticket')
            shutil.copytree(SKILL, copy, ignore=shutil.ignore_patterns('__pycache__'))
            os.remove(os.path.join(copy, TEMPLATE[1]))
            code, out = run_script(os.path.join(copy, 'scripts', 'tickets.py'), ['--sources-template'])
        self.assertEqual(code, 0)
        self.assertIn("(Missing from the skill's folder: assets/sources-template.md (FileNotFoundError).)", out.splitlines())

    def test_a_symlinked_skill_folder_finds_its_files(self):
        with tempfile.TemporaryDirectory(prefix='tickets-link-') as scratch:
            link = os.path.join(scratch, 'ticket')
            try:
                os.symlink(SKILL, link, target_is_directory=True)
            except (OSError, NotImplementedError):
                self.skipTest('symlinks are not available here')
            code, out = run_script(os.path.join(link, 'scripts', 'tickets.py'), ['--setup'])
        self.assertEqual(code, 0)
        for title, name in (STEPS, MANIFEST):
            self.assertEqual(section(out, title, name), read(SKILL, name).strip())


class SetupMessageTests(TicketsTestCase):
    def test_list_without_a_channel_still_exits_zero(self):
        code, out = run_cli(['--list'])
        self.assertEqual(code, 0)
        self.assertTrue(any(line.startswith('The ticket list could not be read: SLACK_TICKETS_CHANNEL is not set')
                            for line in out.splitlines()))

    def test_list_without_a_token_points_to_the_setup(self):
        code, out = run_cli(['--list'], channel=CHANNEL)
        self.assertEqual(code, 0)
        self.assertTrue(any(line.startswith('The ticket list could not be read: ') and line.endswith('tickets.py --setup prints the steps.')
                            for line in out.splitlines()))

    def test_check_without_a_token_names_the_channel_then_the_setup(self):
        code, out = run_cli(['--check'], channel='C0123456789')
        self.assertEqual(code, 1)
        self.assertEqual(out.splitlines(), ['Channel C0123456789.', NO_TOKEN])


class SkillFileTests(unittest.TestCase):
    def test_the_load_time_command_appears_once(self):
        pair = chr(33) + chr(96)
        self.assertEqual(read(SKILL, 'SKILL.md').count(pair), 1)

    def test_only_the_reading_commands_are_pre_approved(self):
        text = read(SKILL, 'SKILL.md')
        head, body = text.split('\n---\n', 1)
        rules = []
        listing = False
        for line in head.splitlines():
            if line.startswith('allowed-tools:'):
                listing = True
            elif listing and line.startswith('  - '):
                rules.append(line[len('  - '):].strip())
            elif listing:
                break
        prefix = 'Bash(python3 ${CLAUDE_SKILL_DIR}/scripts/tickets.py '
        self.assertTrue(rules)
        self.assertFalse([rule for rule in rules if '*' in rule])
        self.assertTrue(all(rule.startswith(prefix) and rule.endswith(')') for rule in rules))
        self.assertEqual({rule[len(prefix):-1] for rule in rules},
                         {'--list', '--answers', '--answers --all', '--answers --peek', '--check', '--setup', '--sources-template'})
        loaded = re.search(r'^' + re.escape(chr(33) + chr(96)) + r'(.*)' + chr(96) + r'$', body, re.M)
        self.assertIsNotNone(loaded)
        self.assertIn(f'Bash({loaded.group(1)})', rules)

    def test_the_description_is_under_1024_characters(self):
        text = read(SKILL, 'SKILL.md')
        match = re.search(r'^description: "(.*)"$', text, re.M)
        self.assertIsNotNone(match)
        self.assertLess(len(match.group(1)), 1024)

    def test_both_files_are_ascii_and_the_steps_wrap_at_120(self):
        for _, name in (STEPS, MANIFEST):
            read(SKILL, name).encode('ascii')
        for number, line in enumerate(read(SKILL, STEPS[1]).splitlines(), 1):
            self.assertLessEqual(len(line), 120, f'references/setup.md line {number}')

    def test_the_manifest_asks_for_exactly_the_five_permissions(self):
        scopes = set()
        in_bot = False
        for line in read(SKILL, MANIFEST[1]).splitlines():
            if line.strip() == 'bot:':
                in_bot = True
            elif in_bot and line.startswith('      - '):
                scopes.add(line[len('      - '):].strip())
            elif in_bot:
                break
        self.assertEqual(scopes, {'chat:write', 'groups:history', 'channels:history', 'users:read', 'reactions:write'})


if __name__ == '__main__':
    unittest.main()
