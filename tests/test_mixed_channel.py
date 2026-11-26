"""A channel that carries conversation as well as tickets, with a fake Slack. Dates and times are never asserted on:
they print in local time. Every timestamp is in the past, because remembered timestamps in the future are ignored."""
import re
import unittest

from helpers import CHANNEL, PLEASE
from test_list_answers import ANN, BEN, BOT, CLOSED_BY_US, T1, T2, SlackTestCase, lines_of, said, ticket, top

FIRST_REPLY = '1700000100.000100'
CHAT = '1700000500.000100'
NO_REPLIES = ['No new replies.', '1 ticket, 1 open.']


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
        self.assertEqual(lines_of(self.answers()), ['No new replies.', '1 ticket, 0 open.'])

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


if __name__ == '__main__':
    unittest.main()
