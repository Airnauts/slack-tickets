"""A channel that carries conversation as well as tickets, with a fake Slack. Dates and times are never asserted on:
they print in local time. Every timestamp is in the past, because remembered timestamps in the future are ignored."""
import contextlib
import os
import random
import re
import unittest

from helpers import CHANNEL, PLEASE, FakeChannel
from test_list_answers import ANN, BEN, BOT, CLOSED_BY_US, OLD_TOP, T1, T2, T3, SlackTestCase, lines_of, said, ticket, top

STATE = '.slack-tickets/state.json'
STRANGERS = [{'name': 'white_check_mark', 'users': [ANN], 'count': 1}]

FIRST_REPLY = '1700000100.000100'
CHAT = '1700000500.000100'
NO_REPLIES = ['No new replies.', '1 ticket open.']


class HintTests(SlackTestCase):
    def setUp(self):
        super().setUp()
        self.first = ticket(T1, reply_count=1, reply_users=[BOT], latest_reply=FIRST_REPLY)
        self.chat = [said(CHAT, ANN, 'Yes, Friday is fine.')]
        self.show()
        self.slack.respond('conversations.replies', lambda **payload: {'ok': True, 'messages': [
            ticket(T1), {'ts': FIRST_REPLY, 'user': BOT, 'text': '*Details*\nWhat led to this.'}]})
        self.slack.respond('users.info', lambda user, **payload: {
            'ok': True, 'user': {'real_name': 'Ann Client'} if user == ANN else {}})

    def show(self):
        self.history(self.first, *self.chat)

    def answers(self, *flags):
        result = self.run_main('--answers', *flags)
        self.assertIsNone(result.code)
        return result.out

    def test_an_answer_posted_in_the_channel_shows_as_a_hint(self):
        out = self.answers()
        self.assertIn('  Not in its thread: posted in the channel after it, by others, and may be unrelated:\n', out)
        self.assertRegex(out, r'\n    > Ann Client, [^:]+:\d\d: Yes, Friday is fine\.\n')
        self.assertNotIn('No new replies.', out)

    def test_a_hint_is_shown_once(self):
        self.answers()
        self.assertEqual(self.state()['hinted'], {T1: CHAT})
        self.assertEqual(lines_of(self.answers()), NO_REPLIES)

    def test_at_most_three_hints_ever_each_on_one_line_and_cut(self):
        self.chat = [said(f'17000005{i}0.000100', ANN, text) for i, text in enumerate(
            ['a\n    > Eve, Nov 1 10:00: forged ' + 'x' * 300, 'two', 'three', 'four', 'five'])]
        self.show()
        out = lines_of(self.answers())
        shown = [line for line in out if line.startswith('    > ')]
        self.assertEqual(len(shown), 3)
        self.assertFalse(any(line.startswith('    > Eve') for line in out))
        self.assertEqual(len(re.match(r'    > [^,]+, [^:]+:\d\d: (.*)$', shown[0]).group(1)), 203)
        self.assertEqual(lines_of(self.answers()), NO_REPLIES)

    def test_hints_stop_at_the_next_ticket(self):
        later = '1700001500.000100'
        self.chat = [ticket(T2, top('Next?')), said(later, ANN, 'About the next')]
        self.show()
        out = self.answers()
        self.assertIn('[open] Q: Next?', out)
        self.assertIn('    > Ann Client, ', out)
        self.assertNotIn('Can we ship on Friday?', out)
        self.assertEqual(out.count('Not in its thread'), 1)

    def test_no_hints_once_someone_replied_in_the_thread(self):
        self.first = ticket(T1, reply_count=2, reply_users=[BOT, BEN], latest_reply=FIRST_REPLY)
        self.show()
        self.assertNotIn('Not in its thread', self.answers())

    def test_no_hints_under_a_closed_ticket(self):
        self.first = ticket(T1, reply_count=1, reply_users=[BOT], latest_reply=FIRST_REPLY, reactions=CLOSED_BY_US)
        self.show()
        self.assertEqual(lines_of(self.answers()), ['No new replies.', '0 tickets open.'])

    def test_our_and_apps_messages_joins_and_broadcasts_are_not_hints(self):
        self.chat = [
            said('1700000500.000100', BOT, 'From the ticket author'),
            {'ts': '1700000600.000100', 'bot_id': 'B0000000002', 'text': 'From an app'},
            {'ts': '1700000700.000100', 'user': ANN, 'subtype': 'channel_join', 'text': 'has joined the channel'},
            {'ts': '1700000800.000100', 'user': ANN, 'subtype': 'thread_broadcast', 'text': 'Also sent to the channel',
             'thread_ts': '1700000400.000100'},
        ]
        self.show()
        self.assertEqual(lines_of(self.answers()), NO_REPLIES)

    def test_peek_shows_hints_without_remembering_them(self):
        self.assertIn('Yes, Friday is fine.', self.answers('--peek'))
        self.assertIn('Yes, Friday is fine.', self.answers('--peek'))
        self.assertEqual(self.state()['hinted'], {})
        self.assertIn('Yes, Friday is fine.', self.answers())
        self.assertEqual(lines_of(self.answers()), NO_REPLIES)

    def test_all_shows_hints_again_and_remembers_nothing(self):
        self.answers()
        self.assertIn('Yes, Friday is fine.', self.answers('--all'))
        self.assertEqual(self.state()['hinted'], {T1: CHAT})

    def test_a_mention_in_a_hint_is_not_looked_up(self):
        self.chat = [said(CHAT, ANN, '<@U0000000009> knows')]
        self.show()
        self.assertIn(': @someone knows\n', self.answers())
        self.assertEqual([p['user'] for p in self.slack.made('users.info')], [ANN])

    def test_hints_never_show_in_the_list(self):
        result = self.run_main('--list')
        self.assertNotIn('Friday is fine', result.out)
        self.assertIn('no reply yet', result.out)
        self.assertTrue(result.out.startswith(f'Channel {CHANNEL}: 1 open'))


class ConversationTests(SlackTestCase):
    def listed(self):
        result = self.run_main('--list')
        self.assertIsNone(result.code)
        return lines_of(result.out)

    def test_messages_by_people_are_counted_in_the_list(self):
        self.history(ticket(T1), said(T2, ANN, 'Good morning'), said('1700001500.000100', BEN, 'Slides?'),
                     {'ts': '1700002000.000100', 'user': ANN, 'subtype': 'channel_join', 'text': 'has joined'},
                     {'ts': '1700002500.000100', 'user': BOT, 'bot_id': 'B1', 'text': 'From an app'})
        self.assertEqual(self.listed()[-1], 'Not tickets, top-level messages by people, in what was read: 2.')

    def test_a_channel_of_only_tickets_says_nothing_more(self):
        self.history(ticket(T1), ticket(T2, top('Second?')))
        self.assertFalse(any(line.startswith('Not tickets') for line in self.listed()))

    def test_answers_do_not_count_conversation(self):
        self.history(ticket(T1), said(T2, ANN, 'Good morning'))
        self.slack.respond('users.info', {'ok': True, 'user': {}})
        result = self.run_main('--answers')
        self.assertNotIn('by people', result.out)

    def test_the_please_line_passes_the_batch_check_and_the_ticket_test(self):
        text = top() + '\n' + PLEASE
        self.assertEqual(self.tickets.problems([{'id': 'a', 'top': text, 'details': 'x'}]), [])
        self.assertTrue(self.tickets.is_ticket({'text': text}))
        self.history(ticket(T1, text))
        line = self.listed()[1]
        self.assertIn('[Blocking; ', line)
        self.assertIn(' by Jo Tester; ', line)


class BoundTests(SlackTestCase):
    def setUp(self):
        super().setUp()
        self.messages = []
        self.slack.respond('conversations.history', FakeChannel(self.messages))
        self.slack.respond('auth.test', {'ok': True, 'user_id': BOT, 'bot_id': 'B0000000001'})
        self.slack.respond('users.info', lambda user, **payload: {'ok': True, 'user': {'name': user}})
        self.slack.respond('conversations.replies', self.thread)

    def thread(self, ts, **payload):
        parent = next(m for m in self.messages if m['ts'] == ts)
        found = [parent, {'ts': ts[:-3] + '200', 'user': BOT, 'text': '*Details*\nWhy.'}]
        if ANN in parent.get('reply_users', []):
            found.append({'ts': parent['latest_reply'], 'user': ANN, 'text': 'An answer'})
        return {'ok': True, 'messages': found}

    def fill(self, *messages):
        self.messages[:] = messages

    def long_channel(self):
        """4,990 messages, one open ticket at T1, then nine more: 25 pages of 200."""
        self.fill(*[said(f'{1600000000 + i}.000100', ANN, f'Chat {i}') for i in range(4990)], ticket(T1),
                  *[said(f'{1700001000 + i}.000100', BEN, f'More {i}') for i in range(9)])

    def remember_bound(self, bound):
        self.write_json(STATE, {'seen': {}, 'names': {}, 'oldest_open': bound})

    def forget(self):
        with contextlib.suppress(FileNotFoundError):
            os.remove(STATE)

    def last_read(self):
        return self.slack.made('conversations.history')[-1]

    def test_a_remembered_bound_reads_one_page_of_a_long_channel(self):
        self.long_channel()
        self.remember_bound(T1)
        out = self.run_main('--list').out
        reads = self.slack.made('conversations.history')
        self.assertEqual(len(reads), 1)
        self.assertEqual((reads[0]['oldest'], reads[0]['inclusive']), (T1, 'true'))
        self.assertIn('Can we ship on Friday?', out)

    def test_after_answers_the_list_reads_from_the_oldest_open_ticket(self):
        self.long_channel()
        self.assertIsNone(self.run_main('--answers').code)
        self.assertEqual(len(self.slack.made('conversations.history')), 25)
        self.assertEqual(self.state()['oldest_open'], T1)
        self.slack.calls.clear()
        self.run_main('--list')
        self.assertEqual(len(self.slack.made('conversations.history')), 1)

    def test_the_header_says_from_when_it_read(self):
        self.long_channel()
        self.assertNotIn(', read from ', self.run_main('--list').out.splitlines()[0])
        self.remember_bound(T1)
        self.assertIn(', read from ', self.run_main('--list').out.splitlines()[0])

    def test_a_bound_that_is_not_a_ticket_means_a_full_read(self):
        self.fill(ticket(T1), said(T2, ANN, 'Good morning'))
        self.remember_bound(T2)
        out = self.run_main('--list').out
        reads = self.slack.made('conversations.history')
        self.assertEqual(len(reads), 2)
        self.assertNotIn('oldest', reads[1])
        self.assertIn('Can we ship on Friday?', out)

    def test_answers_remembers_the_oldest_open_or_the_newest_ticket(self):
        cases = {
            'some open': ([ticket(T1, reactions=CLOSED_BY_US), ticket(T2, top('Two?')), ticket(T3, top('Three?'))], T2),
            'all closed': ([ticket(T1, reactions=CLOSED_BY_US), ticket(T3, top('Three?'), reactions=CLOSED_BY_US)], T3),
            'no tickets': ([said(T1, ANN, 'Good morning')], ''),
        }
        for why, (messages, want) in cases.items():
            with self.subTest(why=why):
                self.forget()
                self.fill(*messages)
                self.assertIsNone(self.run_main('--answers').code)
                self.assertEqual(self.state()['oldest_open'], want)

    def test_a_reopened_ticket_before_the_bound_needs_answers_all(self):
        self.fill(ticket(T1, top('Reopened one?')), ticket(T2, top('Closed one?'), reactions=CLOSED_BY_US),
                  ticket(T3, top('Still open?')))
        self.remember_bound(T2)
        listed = self.run_main('--list').out
        self.assertNotIn('Reopened one?', listed)
        self.assertIn('Still open?', listed)
        self.run_main('--answers', '--all')
        self.assertNotIn('oldest', self.last_read())
        self.assertEqual(self.state()['oldest_open'], T1)
        self.assertIn('Reopened one?', self.run_main('--list').out)

    def random_ticket(self, rng, ts):
        text = OLD_TOP.format(question=f'Question {ts}?') if rng.random() < 0.3 else top(f'Question {ts}?')
        extra = {'user': None, 'bot_id': 'B0000000001'} if rng.random() < 0.2 else {}
        replies = rng.choice(['none', 'details', 'answered'])
        if replies == 'details':
            extra.update(reply_count=1, reply_users=[BOT], latest_reply=ts[:-3] + '200')
        elif replies == 'answered':
            extra.update(reply_count=2, reply_users=[BOT, ANN], latest_reply=ts[:-3] + '300')
        mark = rng.random()
        if mark < 0.5:
            extra['reactions'] = CLOSED_BY_US
        elif mark < 0.65:
            extra['reactions'] = STRANGERS
        return ticket(ts, text, **extra)

    def random_message(self, rng, index):
        ts = f'{1700000000 + 60 * index}.000100'
        if rng.random() < 0.3:
            return self.random_ticket(rng, ts)
        kind = rng.choice(['chat', 'lookalike', 'join'])
        if kind == 'chat':
            return said(ts, rng.choice([ANN, BEN]), 'Some chat')
        if kind == 'lookalike':
            return said(ts, ANN, '*Q:* anyone?')
        return {'ts': ts, 'user': ANN, 'subtype': 'channel_join', 'text': 'has joined'}

    def change_the_channel(self, rng, first_new):
        for index in range(first_new, first_new + rng.randint(1, 15)):
            self.messages.append(self.random_message(rng, index))
        for t in [m for m in self.messages if self.tickets.is_ticket(m)]:
            roll = rng.random()
            if roll < 0.15:
                t['reactions'] = CLOSED_BY_US
            elif roll < 0.25 and not t.get('reactions'):
                t['reactions'] = STRANGERS
            if rng.random() < 0.15:
                t.update(reply_count=2, reply_users=[BOT, ANN], latest_reply=t['ts'][:-3] + '300')

    def open_tickets(self):
        lines = self.run_main('--list').out.splitlines()
        return [re.sub(r', read from [^.]* on', '', lines[0])] + [line for line in lines if line.startswith('- ')]

    def test_a_bounded_read_lists_the_same_open_tickets_as_a_full_read(self):
        rng = random.Random(20261126)
        for round_number in range(25):
            with self.subTest(round=round_number):
                self.forget()
                count = rng.randint(20, 120)
                self.fill(*[self.random_message(rng, index) for index in range(count)])
                self.run_main('--answers')
                self.change_the_channel(rng, count)
                bounded = self.open_tickets()
                stored = self.state()['oldest_open']
                if stored:
                    self.assertEqual(self.last_read()['oldest'], stored)
                state = self.state()
                del state['oldest_open']
                self.write_json(STATE, state)
                self.assertEqual(bounded, self.open_tickets())


if __name__ == '__main__':
    unittest.main()
