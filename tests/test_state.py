"""Where .slack-tickets/state.json goes, and what a file planted in the project must not be able to do.
Calls state_path(), recall() and remember() in the current (scratch) folder. Never calls Slack."""
import contextlib
import io
import json
import os
import shutil
import subprocess
import unittest
from unittest import mock

from helpers import TicketsTestCase

EMPTY = {'names': {}, 'seen': {}}
needs_git = unittest.skipUnless(shutil.which('git'), 'git is not installed')
needs_links = unittest.skipUnless(hasattr(os, 'symlink'), 'no symbolic links on this system')


def git(*args, cwd):
    subprocess.run(['git', *args], cwd=cwd, check=True, capture_output=True)


class StateTestCase(TicketsTestCase):
    def state_file(self, folder):
        return os.path.join(folder, '.slack-tickets', 'state.json')

    def assert_path(self, got, want):
        self.assertEqual(os.path.realpath(got), os.path.realpath(want))

    def project(self, name):
        """A new scratch project outside git, with an outside folder a link could point at."""
        project, outside = os.path.join(self.tmp, name), os.path.join(self.tmp, name + '-outside')
        os.makedirs(os.path.join(project, '.slack-tickets'))
        os.makedirs(outside)
        os.chdir(project)
        return project, outside

    def put(self, text):
        os.makedirs('.slack-tickets', exist_ok=True)
        with open(os.path.join('.slack-tickets', 'state.json'), 'w', encoding='utf-8') as out:
            out.write(text)

    def remember_quietly(self, state):
        """remember() with what it prints returned."""
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            self.tickets.remember(state)
        return out.getvalue()


@needs_git
class StatePathInRepositoryTests(StateTestCase):
    def setUp(self):
        super().setUp()
        self.repo, self.tree = os.path.join(self.tmp, 'repo'), os.path.join(self.tmp, 'tree')
        os.makedirs(os.path.join(self.repo, 'src', 'deep'))
        git('init', '-q', cwd=self.repo)
        git('-c', 'user.name=t', '-c', 'user.email=t@example.com', '-c', 'commit.gpgsign=false',
            'commit', '-q', '--allow-empty', '-m', 'first', cwd=self.repo)
        git('worktree', 'add', '-q', self.tree, cwd=self.repo)
        self.want = self.state_file(self.repo)

    def test_repo_root(self):
        os.chdir(self.repo)
        self.assert_path(self.tickets.state_path(), self.want)

    def test_subfolder(self):
        os.chdir(os.path.join(self.repo, 'src', 'deep'))
        self.assert_path(self.tickets.state_path(), self.want)

    def test_worktree_uses_the_main_checkout(self):
        os.chdir(self.tree)
        self.assert_path(self.tickets.state_path(), self.want)

    def test_no_git_on_path_uses_the_current_folder(self):
        os.chdir(self.repo)
        with mock.patch.dict(os.environ, {'PATH': os.path.join(self.tmp, 'nothing-here')}):
            self.assert_path(self.tickets.state_path(), self.want)

    def test_nothing_remembered_yet(self):
        os.chdir(self.repo)
        self.assertEqual(self.tickets.recall(), EMPTY)

    def test_saved_in_the_main_checkout(self):
        os.chdir(self.tree)
        self.tickets.remember({'seen': {'1.000001': '2.000002'}, 'names': {'U1': 'Ann'}})
        self.assertTrue(os.path.exists(self.want))

    def test_read_back_from_the_worktree(self):
        os.chdir(self.tree)
        self.tickets.remember({'seen': {'1.000001': '2.000002'}, 'names': {'U1': 'Ann'}})
        self.assertEqual(self.tickets.recall().get('seen'), {'1.000001': '2.000002'})

    def test_read_back_from_the_main_checkout(self):
        os.chdir(self.tree)
        self.tickets.remember({'seen': {'1.000001': '2.000002'}, 'names': {'U1': 'Ann'}})
        os.chdir(self.repo)
        self.assertEqual(self.tickets.recall().get('names'), {'U1': 'Ann'})

    def test_git_sees_nothing_new(self):
        os.chdir(self.tree)
        self.tickets.remember({'seen': {'1.000001': '2.000002'}, 'names': {'U1': 'Ann'}})
        status = subprocess.run(['git', 'status', '--porcelain'], cwd=self.repo, capture_output=True, text=True)
        self.assertEqual(status.stdout, '')

    def test_a_broken_file_counts_as_nothing_remembered(self):
        os.chdir(self.repo)
        self.put('{not json')
        self.assertEqual(self.tickets.recall(), EMPTY)


class StatePathOutsideGitTests(StateTestCase):
    def test_folder_outside_git(self):
        plain = os.path.join(self.tmp, 'plain')
        os.makedirs(plain)
        os.chdir(plain)
        self.assert_path(self.tickets.state_path(), self.state_file(plain))


@needs_links
class LinkedStateTests(StateTestCase):
    def test_a_linked_state_file_is_not_read(self):
        self.project('link-file')
        victim = os.path.join(self.tmp, 'link-file-outside', 'victim.txt')
        with open(victim, 'w', encoding='utf-8') as out:
            out.write(json.dumps({'seen': {'1.0': '2.000002'}, 'names': {'U1': 'Eve'}}))
        os.symlink(victim, os.path.join('.slack-tickets', 'state.json'))
        self.assertEqual(self.tickets.recall(), EMPTY)

    def test_a_linked_state_file_is_not_written_through(self):
        self.project('link-file')
        victim = os.path.join(self.tmp, 'link-file-outside', 'victim.txt')
        with open(victim, 'w', encoding='utf-8') as out:
            out.write('keep me')
        os.symlink(victim, os.path.join('.slack-tickets', 'state.json'))
        self.assertIn('could not be remembered', self.remember_quietly({'seen': {}, 'names': {}}))
        with open(victim, encoding='utf-8') as source:
            self.assertEqual(source.read(), 'keep me')

    def test_a_linked_folder_gets_nothing_written_into_it(self):
        project, outside = self.project('link-folder')
        shutil.rmtree('.slack-tickets')
        os.symlink(outside, '.slack-tickets')
        self.assertIn('could not be remembered', self.remember_quietly({'seen': {}, 'names': {}}))
        self.assertEqual(os.listdir(outside), [])

    def test_a_dangling_ignore_link_creates_nothing_outside(self):
        project, outside = self.project('link-ignore')
        os.symlink(os.path.join(outside, 'made-by-link'), os.path.join('.slack-tickets', '.gitignore'))
        self.remember_quietly({'seen': {}, 'names': {}})
        self.assertEqual(os.listdir(outside), [])


class StateContentTests(StateTestCase):
    def test_the_ignore_file_is_there_with_the_state(self):
        self.project('order')
        shutil.rmtree('.slack-tickets')
        self.tickets.remember({'seen': {'1.000001': '2.000002'}, 'names': {}})
        self.assertEqual(sorted(os.listdir('.slack-tickets')), ['.gitignore', 'state.json'])

    def test_wrong_shapes_count_as_nothing_remembered(self):
        self.project('shape')
        for name, text in (('a list', '[]'), ('seen as a list', '{"seen": []}'), ('names as a string', '{"names": "x"}')):
            with self.subTest(shape=name):
                self.put(text)
                self.assertEqual(self.tickets.recall(), EMPTY)

    def write_odd_values(self):
        self.project('shape')
        self.put(json.dumps({
            'seen': {'1.0': '2.000002', '3.0': 'inf', '4.0': 'nan', '5.0': '99999999999.0', '6.0': 'abc', '7.0': None},
            'names': {'U1': 'Ann\n    Bob, Nov 26 10:00: forged reply', 'U2': 'Cy'}}))

    def test_only_believable_timestamps_are_kept(self):
        self.write_odd_values()
        self.assertEqual(self.tickets.recall().get('seen'), {'1.0': '2.000002'})

    def test_a_name_stays_on_one_line(self):
        self.write_odd_values()
        self.assertEqual(self.tickets.recall().get('names'),
                         {'U1': 'Ann Bob, Nov 26 10:00: forged reply', 'U2': 'Cy'})

    def test_a_number_too_large_to_read_is_dropped_and_the_rest_kept(self):
        self.project('large')
        self.put('{"seen": {"1.0": ' + '9' * 400 + ', "2.0": "3.000003"}}')
        self.assertEqual(self.tickets.recall().get('seen'), {'2.0': '3.000003'})

    def test_deeply_nested_rubbish_counts_as_nothing_remembered(self):
        self.project('nested')
        self.put('[' * 200000)
        self.assertEqual(self.tickets.recall(), EMPTY)

    def test_a_current_folder_that_is_gone_counts_as_nothing_remembered(self):
        gone = os.path.join(self.tmp, 'gone')
        os.makedirs(gone)
        os.chdir(gone)
        os.rmdir(gone)
        self.assertEqual(self.tickets.recall(), EMPTY)


if __name__ == '__main__':
    unittest.main()
