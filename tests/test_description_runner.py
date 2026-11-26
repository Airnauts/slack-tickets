"""The description eval runner's logic, and the shape of its prompt file. Nothing here starts claude."""
import importlib.util
import json
import os
import re
import subprocess
import sys
import tempfile
import time
import unittest
from unittest import mock

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
RUNNER = os.path.join(ROOT, 'tests', 'description', 'run.py')
PROMPTS = os.path.join(ROOT, 'tests', 'description', 'trigger-evals.json')
SKILL = os.path.join(ROOT, 'skills', 'ticket', 'SKILL.md')

STUB = 'ticket-check-1a2b3c4d'


def load_runner():
    """The runner as a module, without leaving bytecode next to it."""
    spec = importlib.util.spec_from_file_location('description_run', RUNNER)
    module = importlib.util.module_from_spec(spec)
    keep, sys.dont_write_bytecode = sys.dont_write_bytecode, True
    try:
        spec.loader.exec_module(module)
    finally:
        sys.dont_write_bytecode = keep
    return module


run = load_runner()


def start(name):
    return {'type': 'stream_event', 'event': {'type': 'content_block_start',
                                              'content_block': {'type': 'tool_use', 'name': name}}}


def delta(text):
    return {'type': 'stream_event', 'event': {'type': 'content_block_delta',
                                              'delta': {'type': 'input_json_delta', 'partial_json': text}}}


def stop():
    return {'type': 'stream_event', 'event': {'type': 'content_block_stop'}}


def message_stop():
    return {'type': 'stream_event', 'event': {'type': 'message_stop'}}


def text_start():
    return {'type': 'stream_event', 'event': {'type': 'content_block_start',
                                              'content_block': {'type': 'text', 'text': ''}}}


def assistant(name, **args):
    return {'type': 'assistant', 'message': {'content': [{'type': 'tool_use', 'name': name, 'input': args}]}}


class ReadDescriptionTests(unittest.TestCase):
    def read(self, frontmatter):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, 'SKILL.md')
            with open(path, 'w', encoding='utf-8') as f:
                f.write(frontmatter)
            return run.read_description(path)

    def test_the_real_skill_has_a_short_description_that_starts_with_a_capital(self):
        description = run.read_description(SKILL)
        self.assertTrue(description)
        self.assertLess(len(description), 1024)
        self.assertTrue(description[0].isupper())

    def test_a_double_quoted_description_is_read_without_its_quotes(self):
        self.assertEqual(self.read('---\nname: x\ndescription: "Ask a \\"client\\": now"\n---\nBody\n'),
                         'Ask a "client": now')

    def test_a_single_quoted_description_is_read_without_its_quotes(self):
        self.assertEqual(self.read("---\nname: x\ndescription: 'Ask it''s fine'\n---\n"), "Ask it's fine")

    def test_a_bare_description_is_read_as_it_is(self):
        self.assertEqual(self.read('---\nname: x\ndescription: Ask the client\n---\n'), 'Ask the client')

    def test_a_file_without_a_description_raises(self):
        with self.assertRaises(ValueError):
            self.read('---\nname: x\n---\ndescription: not in the frontmatter\n')

    def test_a_file_without_frontmatter_raises(self):
        with self.assertRaises(ValueError):
            self.read('# Just text\n')

    def test_a_multi_line_description_raises(self):
        with self.assertRaises(ValueError):
            self.read('---\nname: x\ndescription: |\n  two\n  lines\n---\n')


class StubTextTests(unittest.TestCase):
    def test_the_description_appears_in_the_frontmatter_and_in_the_body(self):
        text = run.stub_text('Ask the client')
        self.assertEqual(text.count('Ask the client'), 2)
        self.assertTrue(text.startswith('---\ndescription: |\n  Ask the client\n---\n'))
        self.assertIn('This skill handles: Ask the client', text)

    def test_line_breaks_are_indented_inside_the_block(self):
        text = run.stub_text('first line\nsecond line')
        self.assertIn('description: |\n  first line\n  second line\n---', text)


class DecisionTests(unittest.TestCase):
    def test_a_skill_call_naming_the_stub_is_a_trigger(self):
        events = [text_start(), start('Skill'), delta('{"skill": "'), delta(STUB), delta('"}'), stop()]
        self.assertIs(run.decide(events, STUB), True)

    def test_the_decision_comes_as_soon_as_the_stub_name_is_complete(self):
        watcher = run.Watcher(STUB)
        self.assertIsNone(watcher.feed(start('Skill')))
        self.assertIsNone(watcher.feed(delta('{"skill": "ticket-check-')))
        self.assertIs(watcher.feed(delta('1a2b3c4d')), True)

    def test_a_skill_call_for_another_skill_is_a_miss(self):
        events = [start('Skill'), delta('{"skill": "ticket-check-ffffffff"}'), stop()]
        self.assertIs(run.decide(events, STUB), False)

    def test_a_first_bash_call_is_a_miss_without_waiting_for_more_events(self):
        watcher = run.Watcher(STUB)
        self.assertIs(watcher.feed(start('Bash')), False)
        self.assertIs(watcher.feed(start('Skill')), False)
        self.assertIs(watcher.feed(delta(STUB)), False)

    def test_a_first_tool_search_call_is_a_miss(self):
        self.assertIs(run.decide([start('ToolSearch'), delta(STUB)], STUB), False)

    def test_a_read_of_the_stub_file_is_a_trigger(self):
        events = [start('Read'), delta('{"file_path": "/tmp/p/.claude/commands/' + STUB + '.md"}'), stop()]
        self.assertIs(run.decide(events, STUB), True)

    def test_a_read_of_another_file_is_a_miss(self):
        events = [start('Read'), delta('{"file_path": "/tmp/p/notes.md"}'), stop()]
        self.assertIs(run.decide(events, STUB), False)

    def test_text_only_then_the_end_of_the_message_is_a_miss(self):
        self.assertIs(run.decide([text_start(), message_stop()], STUB), False)

    def test_the_whole_message_fallback_triggers_on_the_stub_skill(self):
        self.assertIs(run.decide([assistant('Skill', skill=STUB)], STUB), True)

    def test_the_whole_message_fallback_triggers_on_a_read_of_the_stub_file(self):
        self.assertIs(run.decide([assistant('Read', file_path=f'/p/.claude/commands/{STUB}.md')], STUB), True)

    def test_the_whole_message_fallback_misses_another_skill_and_other_tools(self):
        self.assertIs(run.decide([assistant('Skill', skill='other')], STUB), False)
        self.assertIs(run.decide([assistant('Read', file_path='/p/notes.md')], STUB), False)
        self.assertIs(run.decide([assistant('Bash', command=STUB)], STUB), False)

    def test_an_assistant_message_with_only_text_does_not_decide(self):
        event = {'type': 'assistant', 'message': {'content': [{'type': 'text', 'text': 'Hi'}]}}
        self.assertIsNone(run.decide([event], STUB))

    def test_a_result_with_no_tool_call_is_a_miss(self):
        self.assertIs(run.decide([text_start(), {'type': 'result', 'subtype': 'success'}], STUB), False)

    def test_a_result_with_no_subtype_and_no_error_flag_is_a_miss(self):
        self.assertIs(run.decide([text_start(), {'type': 'result'}], STUB), False)

    def test_a_failed_run_is_not_a_miss(self):
        self.assertIsNone(run.decide([{'type': 'result', 'subtype': 'success', 'is_error': True}], STUB))
        self.assertIsNone(run.decide([{'type': 'result', 'subtype': 'error_during_execution'}], STUB))
        self.assertIsNone(run.decide([{'type': 'result', 'is_error': True}], STUB))

    def test_another_skill_is_a_miss_before_the_call_is_finished(self):
        watcher = run.Watcher(STUB)
        self.assertIsNone(watcher.feed(start('Skill')))
        self.assertIsNone(watcher.feed(delta('{"skill": "other')))
        self.assertIs(watcher.feed(delta('-skill", "args": "x')), False)

    def test_a_read_of_another_file_is_a_miss_before_the_call_is_finished(self):
        watcher = run.Watcher(STUB)
        self.assertIsNone(watcher.feed(start('Read')))
        self.assertIsNone(watcher.feed(delta('{"file_path": "/tmp/p/not')))
        self.assertIs(watcher.feed(delta('es.md", "limit": 5')), False)

    def test_the_stub_name_in_another_key_is_a_miss_in_both_paths(self):
        events = [start('Skill'), delta('{"args": "' + STUB + '", "skill": "other"}'), stop()]
        self.assertIs(run.decide(events, STUB), False)
        events = [start('Skill'), delta('{"skill": "other", "args": "' + STUB + '"}'), stop()]
        self.assertIs(run.decide(events, STUB), False)
        self.assertIs(run.decide([assistant('Skill', skill='other', args=STUB)], STUB), False)

    def test_a_key_named_inside_another_value_is_ignored(self):
        inner = '{"args": "say \\"skill\\": \\"x\\"", "skill": "' + STUB + '"}'
        self.assertIs(run.decide([start('Skill'), delta(inner), stop()], STUB), True)

    def test_an_empty_stream_has_no_decision(self):
        self.assertIsNone(run.decide([], STUB))

    def test_a_truncated_stream_has_no_decision(self):
        self.assertIsNone(run.decide([{'type': 'system'}, start('Skill'), delta('{"skill": "tick')], STUB))

    def test_events_that_are_not_objects_are_ignored(self):
        self.assertIsNone(run.decide(['text', None, 3], STUB))

    def test_a_miss_does_not_change_once_made(self):
        watcher = run.Watcher(STUB)
        self.assertIs(watcher.feed(start('Bash')), False)
        self.assertIs(watcher.feed(assistant('Skill', skill=STUB)), False)
        self.assertIs(watcher.feed(start('Skill')), False)
        self.assertIs(watcher.feed(delta('{"skill": "' + STUB + '"}')), False)

    def test_a_hit_does_not_change_once_made(self):
        watcher = run.Watcher(STUB)
        self.assertIs(watcher.feed(assistant('Skill', skill=STUB)), True)
        self.assertIs(watcher.feed(assistant('Bash', command='ls')), True)
        self.assertIs(watcher.feed(start('Bash')), True)


class StopTests(unittest.TestCase):
    """The pieces that stop sessions. The only process started is a sleeping python."""

    def sleeper(self):
        return subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(60)'], start_new_session=True)

    def test_kill_ends_a_running_session(self):
        proc = self.sleeper()
        self.addCleanup(proc.kill)
        run._kill(proc)
        proc.wait(timeout=10)
        self.assertLess(proc.returncode, 0)

    def test_kill_ends_what_a_run_started_even_after_it_exited(self):
        code = ('import subprocess, sys; '
                'child = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(60)"]); '
                'print(child.pid, flush=True)')
        proc = subprocess.Popen([sys.executable, '-c', code], stdout=subprocess.PIPE, text=True,
                                start_new_session=True)
        child = int(proc.stdout.readline())
        proc.stdout.close()
        proc.wait(timeout=10)
        run._kill(proc)
        deadline = time.time() + 10
        while time.time() < deadline:
            try:
                os.kill(child, 0)
            except ProcessLookupError:
                return
            time.sleep(0.05)
        os.kill(child, 9)
        self.fail('the grandchild was still running')

    def test_kill_tolerates_a_process_that_is_already_gone(self):
        proc = self.sleeper()
        proc.kill()
        proc.wait(timeout=10)
        run._kill(proc)
        run._kill(proc)

    def test_a_run_that_is_stopping_starts_nothing(self):
        run.STOPPING.set()
        self.addCleanup(run.STOPPING.clear)
        with mock.patch.object(run.subprocess, 'Popen', side_effect=AssertionError('started a process')), \
                mock.patch.object(run.tempfile, 'mkdtemp', side_effect=AssertionError('made a project')):
            self.assertIsNone(run.run_once('hello', 'desc', None, 5))


class ErrorReasonTests(unittest.TestCase):
    def reason(self, content):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, 'stderr.txt')
            with open(path, 'w', encoding='utf-8') as f:
                f.write(content)
            return run.error_reason(path)

    def test_the_text_is_stripped_and_kept_on_one_line(self):
        self.assertEqual(self.reason('\n  Error: unknown model\n  try again \n\n'), 'Error: unknown model try again')

    def test_only_the_last_300_characters_are_kept(self):
        self.assertEqual(self.reason('a' * 100 + 'b' * 300), 'b' * 300)

    def test_an_empty_or_missing_file_gives_nothing(self):
        self.assertEqual(self.reason(' \n'), '')
        self.assertEqual(run.error_reason(os.path.join(tempfile.gettempdir(), 'no-such-dir-xyz', 'stderr.txt')), '')


class RateTests(unittest.TestCase):
    def test_the_wrong_side_of_a_half_depends_on_the_kind_of_prompt(self):
        self.assertFalse(run.is_wrong(True, 2, 3))
        self.assertTrue(run.is_wrong(True, 1, 3))
        self.assertFalse(run.is_wrong(False, 1, 3))
        self.assertTrue(run.is_wrong(False, 2, 3))

    def test_a_prompt_with_no_decided_run_is_wrong(self):
        self.assertTrue(run.is_wrong(True, 0, 0))
        self.assertTrue(run.is_wrong(False, 0, 0))


class PromptFileTests(unittest.TestCase):
    def setUp(self):
        with open(PROMPTS, encoding='utf-8') as f:
            self.items = json.load(f)

    def test_it_is_a_list_of_at_least_twenty_prompts(self):
        self.assertIsInstance(self.items, list)
        self.assertGreaterEqual(len(self.items), 20)

    def test_every_prompt_has_a_query_and_a_boolean(self):
        for item in self.items:
            self.assertIsInstance(item.get('query'), str)
            self.assertTrue(item['query'].strip())
            self.assertIsInstance(item.get('should_trigger'), bool)

    def test_both_kinds_of_prompt_are_present(self):
        kinds = {item['should_trigger'] for item in self.items}
        self.assertEqual(kinds, {True, False})

    def test_no_query_appears_twice(self):
        queries = [item['query'] for item in self.items]
        self.assertEqual(len(queries), len(set(queries)))

    def test_no_query_contains_a_channel_id(self):
        pattern = re.compile(r'\b[CG](?=[A-Z0-9]*[0-9])[A-Z0-9]{8,}\b')
        for item in self.items:
            self.assertIsNone(pattern.search(item['query']), item['query'])


if __name__ == '__main__':
    unittest.main()
