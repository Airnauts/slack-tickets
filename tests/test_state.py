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

from helpers import ARABIC_INDIC_TS, CHANNEL, OTHER_CHANNEL, TicketsTestCase, clean_git_environment

EMPTY = {'names': {}, 'seen': {}, 'hinted': {}, 'waiting': {}, 'oldest_open': {}}
needs_git = unittest.skipUnless(shutil.which('git'), 'git is not installed')
needs_links = unittest.skipUnless(hasattr(os, 'symlink'), 'no symbolic links on this system')


def git(*args, cwd):
    subprocess.run(['git', *args], cwd=cwd, check=True, capture_output=True)


def make_repo(path):
    """A git repository at path with one empty commit."""
    git('init', '-q', cwd=path)
    git('-c', 'user.name=t', '-c', 'user.email=t@example.com', '-c', 'commit.gpgsign=false',
        'commit', '-q', '--allow-empty', '-m', 'first', cwd=path)


def commit(message, cwd):
    git('-c', 'user.name=t', '-c', 'user.email=t@example.com', '-c', 'commit.gpgsign=false',
        'commit', '-q', '-m', message, cwd=cwd)


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

    def put_in(self, folder, text):
        os.makedirs(os.path.join(folder, '.slack-tickets'), exist_ok=True)
        with open(self.state_file(folder), 'w', encoding='utf-8') as out:
            out.write(text)

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
        make_repo(self.repo)
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
        deep = os.path.join(self.repo, 'src', 'deep')
        os.chdir(deep)
        with mock.patch.dict(os.environ, {'PATH': os.path.join(self.tmp, 'nothing-here')}):
            self.assert_path(self.tickets.state_path(), self.state_file(deep))

    def test_a_separate_git_dir_keeps_the_state_at_the_top_folder_from_any_subfolder(self):
        project, elsewhere = os.path.join(self.tmp, 'project'), os.path.join(self.tmp, 'elsewhere')
        os.makedirs(os.path.join(project, 'src'))
        git('init', '-q', '--separate-git-dir', elsewhere, project, cwd=self.tmp)
        os.chdir(os.path.join(project, 'src'))
        self.assertEqual([os.path.realpath(p) for p in self.tickets.state_paths()],
                         [os.path.realpath(self.state_file(project))])

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


needs_permissions = unittest.skipIf(hasattr(os, 'geteuid') and os.geteuid() == 0, 'root can write anywhere')


@needs_git
class WorktreeStateTests(StateTestCase):
    """A sandboxed agent may not write to the main checkout: the worktree then keeps its own copy."""

    def setUp(self):
        super().setUp()
        self.repo, self.tree = os.path.join(self.tmp, 'repo'), os.path.join(self.tmp, 'tree')
        os.makedirs(self.repo)
        make_repo(self.repo)
        git('worktree', 'add', '-q', self.tree, cwd=self.repo)

    def make_main_read_only(self):
        os.chmod(self.repo, 0o555)
        self.addCleanup(os.chmod, self.repo, 0o755)

    def test_one_place_in_the_main_checkout_two_in_a_worktree(self):
        os.chdir(self.repo)
        self.assertEqual([os.path.realpath(p) for p in self.tickets.state_paths()],
                         [os.path.realpath(self.state_file(self.repo))])
        os.chdir(self.tree)
        self.assertEqual([os.path.realpath(p) for p in self.tickets.state_paths()],
                         [os.path.realpath(self.state_file(self.repo)), os.path.realpath(self.state_file(self.tree))])

    @needs_permissions
    def test_a_main_checkout_that_cannot_be_written_leaves_the_state_in_the_worktree(self):
        self.make_main_read_only()
        os.chdir(self.tree)
        out = self.remember_quietly({'seen': {'1.000001': '2.000002'}, 'names': {'U1': 'Ann'}})
        self.assertIn('Remembered in this checkout only', out)
        self.assertIn('The shared file could not be used', out)
        self.assertNotIn('could not be remembered', out)
        self.assertEqual(sorted(os.listdir(os.path.join(self.tree, '.slack-tickets'))), ['.gitignore', 'state.json'])
        status = subprocess.run(['git', 'status', '--porcelain'], cwd=self.tree, capture_output=True, text=True)
        self.assertEqual(status.stdout, '')
        self.assertEqual(self.tickets.recall()['seen'], {'1.000001': '2.000002'})
        os.chdir(self.repo)
        self.assertEqual(self.tickets.recall(), EMPTY)

    @needs_links
    @needs_permissions
    def test_when_both_places_fail_both_are_named_with_their_reasons(self):
        self.make_main_read_only()
        os.makedirs(os.path.join(self.tree, '.slack-tickets'))
        os.symlink(self.write('victim.txt', 'keep me'), self.state_file(self.tree))
        os.chdir(self.tree)
        out = self.remember_quietly({'seen': {}, 'names': {}})
        self.assertIn('could not be remembered', out)
        self.assertIn(f'{self.state_file(self.repo)}: Permission denied', out)
        self.assertIn(f'{self.state_file(self.tree)}: a link stands in its place', out)

    def test_the_later_reply_wins_whichever_place_holds_it(self):
        os.chdir(self.tree)
        for main_last, tree_last in (('2.000002', '3.000003'), ('3.000003', '2.000002')):
            with self.subTest(main=main_last):
                self.put_in(self.repo, json.dumps({'seen': {'1.0': main_last}}))
                self.put_in(self.tree, json.dumps({'seen': {'1.0': tree_last}}))
                self.assertEqual(self.tickets.recall()['seen'], {'1.0': '3.000003'})

    def test_the_later_hint_wins_whichever_place_holds_it(self):
        os.chdir(self.tree)
        for main_last, tree_last in (('2.000002', '3.000003'), ('3.000003', '2.000002')):
            with self.subTest(main=main_last):
                self.put_in(self.repo, json.dumps({'hinted': {'1.0': main_last}}))
                self.put_in(self.tree, json.dumps({'hinted': {'1.0': tree_last}}))
                self.assertEqual(self.tickets.recall()['hinted'], {'1.0': '3.000003'})

    def test_the_later_waiting_wins_whichever_place_holds_it(self):
        os.chdir(self.tree)
        for main_last, tree_last in (('2.000002', '3.000003'), ('3.000003', '2.000002')):
            with self.subTest(main=main_last):
                self.put_in(self.repo, json.dumps({'waiting': {'1.0': main_last}}))
                self.put_in(self.tree, json.dumps({'waiting': {'1.0': tree_last}}))
                self.assertEqual(self.tickets.recall()['waiting'], {'1.0': '3.000003'})

    def test_the_earlier_bound_wins_whichever_place_holds_it(self):
        os.chdir(self.tree)
        for main_ts, tree_ts in (('1700000000.000100', '1700001000.000100'), ('1700001000.000100', '1700000000.000100')):
            with self.subTest(main=main_ts):
                self.put_in(self.repo, json.dumps({'oldest_open': {CHANNEL: main_ts}}))
                self.put_in(self.tree, json.dumps({'oldest_open': {CHANNEL: tree_ts}}))
                self.assertEqual(self.tickets.recall()['oldest_open'], {CHANNEL: '1700000000.000100'})

    def test_an_odd_bound_in_either_place_means_a_full_read(self):
        os.chdir(self.tree)
        for odd_here, odd_there in ((self.repo, self.tree), (self.tree, self.repo)):
            with self.subTest(odd=odd_here):
                self.put_in(odd_here, json.dumps({'oldest_open': {CHANNEL: 'abc'}}))
                self.put_in(odd_there, json.dumps({'oldest_open': {CHANNEL: '1700000000.000100'}}))
                self.assertEqual(self.tickets.recall()['oldest_open'], {CHANNEL: ''})

    def test_bounds_of_different_channels_are_merged_each_on_its_own(self):
        os.chdir(self.tree)
        self.put_in(self.repo, json.dumps({'oldest_open': {CHANNEL: '1700000000.000100', OTHER_CHANNEL: '1700002000.000100'}}))
        self.put_in(self.tree, json.dumps({'oldest_open': {CHANNEL: '1700001000.000100', OTHER_CHANNEL: 'abc'}}))
        self.assertEqual(self.tickets.recall()['oldest_open'], {CHANNEL: '1700000000.000100', OTHER_CHANNEL: ''})

    def test_a_file_without_a_bound_leaves_the_others(self):
        os.chdir(self.tree)
        self.put_in(self.repo, json.dumps({'seen': {'1.0': '2.000002'}}))
        self.put_in(self.tree, json.dumps({'oldest_open': {CHANNEL: '1700000000.000100'}}))
        self.assertEqual(self.tickets.recall()['oldest_open'], {CHANNEL: '1700000000.000100'})

    def test_a_broken_file_in_one_place_does_not_hide_the_other(self):
        os.chdir(self.tree)
        for broken, good in ((self.repo, self.tree), (self.tree, self.repo)):
            with self.subTest(broken=broken):
                self.put_in(broken, '{not json')
                self.put_in(good, json.dumps({'seen': {'1.0': '2.000002'}, 'names': {'U1': 'Ann'}}))
                self.assertEqual(self.tickets.recall(), {'names': {'U1': 'Ann'}, 'seen': {'1.0': '2.000002'}, 'hinted': {}, 'waiting': {}, 'oldest_open': {}})

    @needs_links
    @needs_permissions
    def test_a_link_in_place_of_the_worktrees_state_is_not_written_through(self):
        self.make_main_read_only()
        victim = self.write('victim.txt', 'keep me')
        os.makedirs(os.path.join(self.tree, '.slack-tickets'))
        os.symlink(victim, self.state_file(self.tree))
        os.chdir(self.tree)
        self.assertIn('could not be remembered', self.remember_quietly({'seen': {}, 'names': {}}))
        with open(victim, encoding='utf-8') as source:
            self.assertEqual(source.read(), 'keep me')


@needs_git
class InheritedGitVariablesTests(StateTestCase):
    """git exports GIT_DIR to a hook run from a linked worktree. The tests must not act on that repository."""

    def heads(self, repo):
        found = {}
        for folder, _, names in os.walk(os.path.join(repo, '.git', 'refs', 'heads')):
            for name in names:
                with open(os.path.join(folder, name), encoding='utf-8') as source:
                    found[os.path.join(folder, name)] = source.read()
        return found

    def test_the_state_stays_out_of_a_repository_named_by_git_variables(self):
        repo, plain = os.path.join(self.tmp, 'real-repo'), os.path.join(self.tmp, 'plain')
        os.makedirs(repo)
        os.makedirs(plain)
        make_repo(repo)
        before = self.heads(repo)
        self.assertTrue(before)
        os.environ['GIT_DIR'] = os.path.join(repo, '.git')
        os.environ['GIT_WORK_TREE'] = repo
        clean_git_environment(self.git_ceiling)
        self.assertEqual(sorted(n for n in os.environ if n.startswith('GIT_')),
                         ['GIT_CEILING_DIRECTORIES', 'GIT_CONFIG_COUNT', 'GIT_CONFIG_GLOBAL', 'GIT_CONFIG_KEY_0',
                          'GIT_CONFIG_NOSYSTEM', 'GIT_CONFIG_VALUE_0'])
        os.chdir(plain)
        self.assert_path(self.tickets.state_path(), self.state_file(plain))
        self.tickets.remember({'seen': {'1.000001': '2.000002'}, 'names': {}})
        self.assertFalse(os.path.exists(os.path.join(repo, '.slack-tickets')))
        self.assertEqual(self.heads(repo), before)


@needs_git
class TrackedStateTests(StateTestCase):
    """A file that arrives through a branch is tracked by git. The script's own file never is."""
    PLANTED = {'seen': {'1.0': '2.000002'}, 'names': {'U1': 'Eve'}}
    FRESH = {'seen': {'3.0': '4.000004'}, 'names': {'U2': 'Ann'}, 'hinted': {}, 'waiting': {}, 'oldest_open': {}}

    def commit_state(self, folder, text):
        self.put_in(folder, text)
        git('add', '-f', os.path.join('.slack-tickets', 'state.json'), cwd=folder)
        commit('plant', folder)

    def read(self, folder):
        with open(self.state_file(folder), encoding='utf-8') as source:
            return json.load(source)

    def test_a_committed_state_file_is_not_read_or_changed(self):
        repo = os.path.join(self.tmp, 'repo')
        os.makedirs(repo)
        make_repo(repo)
        self.commit_state(repo, json.dumps(self.PLANTED))
        os.chdir(repo)
        self.assertEqual(self.tickets.recall(), EMPTY)
        out = self.remember_quietly(self.FRESH)
        self.assertIn('could not be remembered', out)
        self.assertIn('git tracks it', out)
        self.assertEqual(self.read(repo), self.PLANTED)

    def test_a_branchs_committed_file_in_a_worktree_is_not_read_or_merged(self):
        repo, tree = os.path.join(self.tmp, 'repo'), os.path.join(self.tmp, 'tree')
        os.makedirs(repo)
        make_repo(repo)
        git('worktree', 'add', '-q', '-b', 'planted', tree, cwd=repo)
        self.commit_state(tree, json.dumps(self.PLANTED))
        os.chdir(tree)
        self.assertEqual(self.tickets.recall(), EMPTY)
        self.assertEqual(self.remember_quietly(self.FRESH), '')
        self.assertEqual(self.read(repo), self.FRESH)
        self.assertEqual(self.read(tree), self.PLANTED)

    def test_a_tracked_file_in_the_main_checkout_sends_the_state_to_the_worktree(self):
        repo, tree = os.path.join(self.tmp, 'repo'), os.path.join(self.tmp, 'tree')
        os.makedirs(repo)
        make_repo(repo)
        git('worktree', 'add', '-q', '-b', 'other', tree, cwd=repo)
        self.commit_state(repo, json.dumps(self.PLANTED))
        os.chdir(tree)
        out = self.remember_quietly(self.FRESH)
        self.assertIn('Remembered in this checkout only', out)
        self.assertIn('git tracks it', out)
        self.assertEqual(self.read(repo), self.PLANTED)
        self.assertEqual(self.read(tree), self.FRESH)

    def test_an_ignore_file_that_does_not_ignore_the_state_gets_no_state_written(self):
        repo = os.path.join(self.tmp, 'repo')
        os.makedirs(os.path.join(repo, '.slack-tickets'))
        make_repo(repo)
        with open(os.path.join(repo, '.slack-tickets', '.gitignore'), 'w', encoding='utf-8') as out:
            out.write('# nothing is ignored here\n')
        git('add', '-f', os.path.join('.slack-tickets', '.gitignore'), cwd=repo)
        commit('plant', repo)
        os.chdir(repo)
        out = self.remember_quietly(self.FRESH)
        self.assertIn('could not be remembered', out)
        self.assertIn('git would not ignore it', out)
        self.assertFalse(os.path.exists(self.state_file(repo)))

    def test_without_git_on_the_path_saving_and_reading_back_still_work(self):
        plain = os.path.join(self.tmp, 'plain')
        os.makedirs(plain)
        os.chdir(plain)
        with mock.patch.dict(os.environ, {'PATH': os.path.join(self.tmp, 'nothing-here')}):
            self.assertEqual(self.remember_quietly(self.FRESH), '')
            self.assertEqual(self.tickets.recall(), self.FRESH)


class StatePathOutsideGitTests(StateTestCase):
    def test_folder_outside_git(self):
        plain = os.path.join(self.tmp, 'plain')
        os.makedirs(plain)
        os.chdir(plain)
        self.assert_path(self.tickets.state_path(), self.state_file(plain))

    def test_saved_and_read_back_outside_a_repository(self):
        plain = os.path.join(self.tmp, 'plain')
        os.makedirs(plain)
        os.chdir(plain)
        self.tickets.remember({'seen': {'1.0': '2.000002'}, 'names': {'U1': 'Ann'}})
        self.assertEqual(self.tickets.recall(), {'names': {'U1': 'Ann'}, 'seen': {'1.0': '2.000002'}, 'hinted': {}, 'waiting': {}, 'oldest_open': {}})


@needs_links
class LinkedStateTests(StateTestCase):
    def test_a_linked_state_file_is_not_read(self):
        self.project('link-file')
        victim = self.write_json('link-file-outside/victim.txt', {'seen': {'1.0': '2.000002'}, 'names': {'U1': 'Eve'}})
        os.symlink(victim, os.path.join('.slack-tickets', 'state.json'))
        self.assertEqual(self.tickets.recall(), EMPTY)

    def test_a_linked_state_file_is_not_written_through(self):
        self.project('link-file')
        victim = self.write('link-file-outside/victim.txt', 'keep me')
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
        for name, text in (('a list', '[]'), ('seen as a list', '{"seen": []}'), ('names as a string', '{"names": "x"}'),
                           ('waiting as a list', '{"waiting": []}')):
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

    def test_only_believable_hint_timestamps_are_kept(self):
        self.project('hints')
        self.put(json.dumps({'hinted': {'1.0': '2.000002', '3.0': 'inf', '4.0': None}}))
        self.assertEqual(self.tickets.recall()['hinted'], {'1.0': '2.000002'})

    def test_only_believable_waiting_timestamps_are_kept(self):
        self.project('waiting')
        self.put(json.dumps({'waiting': {'1.0': '2.000002', '3.0': 'inf', '4.0': None}}))
        self.assertEqual(self.tickets.recall()['waiting'], {'1.0': '2.000002'})

    def test_a_remembered_time_that_is_not_a_string_is_dropped(self):
        self.project('numbers')
        for key in ('seen', 'hinted', 'waiting'):
            for value in (1700003000, 1700003000.5, True):
                with self.subTest(key=key, value=value):
                    self.put(json.dumps({key: {'1.0': value, '2.0': '3.000003'}}))
                    self.assertEqual(self.tickets.recall()[key], {'2.0': '3.000003'})

    def test_an_odd_bound_means_a_full_read_of_its_channel(self):
        self.project('bound')
        for odd in ('abc', '1700000000', 1700000000.5, '99999999999.000000', '', None):
            with self.subTest(odd=odd):
                self.put(json.dumps({'oldest_open': {CHANNEL: odd, OTHER_CHANNEL: '1700000000.000100'}}))
                self.assertEqual(self.tickets.recall()['oldest_open'], {CHANNEL: '', OTHER_CHANNEL: '1700000000.000100'})

    def test_a_bound_written_in_other_digits_means_a_full_read(self):
        self.project('digits')
        self.assertTrue(self.tickets.believable(ARABIC_INDIC_TS))
        self.put(json.dumps({'oldest_open': {CHANNEL: ARABIC_INDIC_TS, OTHER_CHANNEL: '1700000000.000100'}}))
        self.assertEqual(self.tickets.recall()['oldest_open'], {CHANNEL: '', OTHER_CHANNEL: '1700000000.000100'})

    def test_a_key_that_is_not_a_channel_id_is_dropped(self):
        self.project('keys')
        self.put(json.dumps({'oldest_open': {'../x': '1700000000.000100', 'c0000000000': '1700000000.000100',
                                             'C1': '1700000000.000100', CHANNEL: '1700000000.000100'}}))
        self.assertEqual(self.tickets.recall()['oldest_open'], {CHANNEL: '1700000000.000100'})

    def test_a_bound_that_is_not_an_object_has_no_say(self):
        self.project('old-shape')
        for value in ('1700000000.000100', 'abc', '', ['1700000000.000100'], 1700000000, True):
            with self.subTest(value=value):
                self.put(json.dumps({'oldest_open': value}))
                self.assertEqual(self.tickets.recall(), EMPTY)

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

    def test_a_current_folder_that_is_gone_is_not_remembered_in_and_does_not_raise(self):
        gone = os.path.join(self.tmp, 'gone')
        os.makedirs(gone)
        os.chdir(gone)
        os.rmdir(gone)
        try:
            out = self.remember_quietly({'seen': {}, 'names': {}})
        finally:
            os.chdir(self.tmp)
        self.assertIn('could not be remembered', out)

    def test_a_current_folder_that_is_gone_counts_as_nothing_remembered(self):
        gone = os.path.join(self.tmp, 'gone')
        os.makedirs(gone)
        os.chdir(gone)
        os.rmdir(gone)
        self.assertEqual(self.tickets.recall(), EMPTY)


if __name__ == '__main__':
    unittest.main()
