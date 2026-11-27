"""--list, --answers, --reply, --post and --close, with a fake Slack. Dates and times are never asserted on:
they print in local time. Every timestamp is in the past, because remembered timestamps in the future are ignored."""
import contextlib
import io
import itertools
import os
import re
import sys
import unittest

from helpers import ARABIC_INDIC_TS, CHANNEL, OTHER_CHANNEL, TicketsTestCase

BOT = 'U0000000001'
ANN = 'U0000000002'
BEN = 'U0000000003'
APP = 'B0000000001'

T1 = '1700000000.000100'
T2 = '1700001000.000100'
T3 = '1700002000.000100'

TOP = '*Q: {question}*\n*Urgency:* :red_circle: Blocking · *Asked by:* {by}\n*Context:* Why it matters.'
CLOSED_BY_US = [{'name': 'white_check_mark', 'users': [BOT], 'count': 1}]
STRANGERS = [{'name': 'white_check_mark', 'users': [ANN], 'count': 1}]
US = {'ok': True, 'user_id': BOT, 'bot_id': APP}
OLD_TOP = '*Q: {question}*\nUrgency: 🔴 Blocking\nOur decision: We will ship.\nContext: Why it matters.'
LABEL_REFUSAL = ("Not posted: a reply outside a ticket's thread goes out under the app's name, so it starts with a bold "
                 'label and the name it speaks for, like "*Reply* (Jo Tester): ".')


def top(question='Can we ship on Friday?', by='Jo Tester'):
    return TOP.format(question=question, by=by)


def ticket(ts, text=None, **extra):
    """A ticket message as Slack returns it from the channel's history."""
    return dict({'ts': ts, 'user': BOT, 'bot_id': APP, 'text': text or top()}, **extra)


def said(ts, user, text):
    """A message by a person in the channel, as Slack returns it from the channel's history."""
    return {'ts': ts, 'user': user, 'text': text}


def lines_of(out):
    return out.splitlines()


class SlackTestCase(TicketsTestCase):
    def setUp(self):
        super().setUp()
        self.set_channel()

    def run_encoded(self, *argv, encoding='utf-8'):
        """main() with a stdout that refuses what the encoding cannot hold, as a terminal may. Returns what it wrote."""
        sys.argv = ['tickets.py', *argv]
        raw = io.BytesIO()
        out = io.TextIOWrapper(raw, encoding=encoding)
        with contextlib.redirect_stdout(out):
            self.tickets.main()
        out.flush()
        return raw.getvalue().decode(encoding)

    def history(self, *messages):
        self.slack.respond('conversations.history', {'ok': True, 'messages': list(messages)})

    def remember_seen(self, seen):
        self.write_json('.slack-tickets/state.json', {'seen': seen, 'names': {}})

    def state(self):
        return self.read_json('.slack-tickets/state.json')


class ListingTests(SlackTestCase):
    def listed(self):
        result = self.run_main('--list')
        self.assertIsNone(result.code)
        return lines_of(result.out)

    def test_the_header_counts_open_tickets(self):
        self.history(ticket(T1), ticket(T2, reactions=CLOSED_BY_US), ticket(T3))
        header = self.listed()[0]
        self.assertTrue(header.startswith(f'Channel {CHANNEL}: 2 open. Open tickets, oldest first:'), header)

    def test_an_open_ticket_has_its_question_urgency_asker_thread_and_ts(self):
        self.history(ticket(T1, reply_count=2, reply_users=[BOT, ANN], latest_reply='1700000500.000100'))
        line = self.listed()[1]
        self.assertRegex(line, r'^- Can we ship on Friday\? \[Blocking; [^;]+ by Jo Tester; thread 2, others replied')
        self.assertTrue(line.endswith(f'; ts {T1}]'), line)

    def test_emoji_shortcodes_are_stripped_from_the_urgency(self):
        self.history(ticket(T1))
        line = self.listed()[1]
        self.assertIn('[Blocking;', line)
        self.assertNotIn(':red_circle:', line)

    def test_a_ticket_nobody_replied_to_says_so(self):
        self.history(ticket(T1))
        self.assertIn('; thread 0, no reply yet; ', self.listed()[1])

    def test_the_authors_own_details_reply_is_not_an_answer(self):
        self.history(ticket(T1, reply_count=1, reply_users=[BOT], latest_reply='1700000100.000100'))
        line = self.listed()[1]
        self.assertIn('thread 1, no reply yet', line)
        self.assertNotIn('NEW', line)

    def test_a_reply_newer_than_what_was_seen_is_new(self):
        self.history(ticket(T1, reply_count=2, reply_users=[BOT, ANN], latest_reply='1700000500.000100'))
        self.remember_seen({T1: '1700000400.000100'})
        self.assertIn('others replied, NEW since the last check;', self.listed()[1])

    def test_a_reply_already_seen_is_not_new(self):
        self.history(ticket(T1, reply_count=2, reply_users=[BOT, ANN], latest_reply='1700000500.000100'))
        for seen in ('1700000500.000100', '1700000600.000100'):
            with self.subTest(seen=seen):
                self.remember_seen({T1: seen})
                line = self.listed()[1]
                self.assertIn('others replied;', line)
                self.assertNotIn('NEW', line)

    def test_a_reply_with_nothing_remembered_is_new(self):
        self.history(ticket(T1, reply_count=2, reply_users=[BOT, ANN], latest_reply='1700000500.000100'))
        self.assertIn('NEW since the last check', self.listed()[1])

    def test_a_closed_ticket_is_not_listed(self):
        self.history(ticket(T1, top('Is this closed?'), reactions=CLOSED_BY_US),
                     ticket(T2, top('Is this open?')))
        lines = self.listed()
        self.assertEqual(len(lines), 2)
        self.assertIn('Is this open?', lines[1])
        self.assertNotIn('Is this closed?', '\n'.join(lines))

    def test_a_check_mark_from_someone_else_leaves_a_ticket_open(self):
        self.history(ticket(T1, reactions=STRANGERS))
        self.slack.respond('auth.test', US)
        lines = self.listed()
        self.assertTrue(lines[0].startswith(f'Channel {CHANNEL}: 1 open'), lines[0])
        self.assertIn('Can we ship on Friday?', lines[1])
        self.assertEqual(len(self.slack.made('auth.test')), 1)

    def test_the_authors_check_mark_costs_no_extra_call(self):
        self.history(ticket(T1, reactions=CLOSED_BY_US))
        self.assertTrue(self.listed()[0].startswith(f'Channel {CHANNEL}: 0 open'))
        self.assertEqual(self.slack.methods(), ['conversations.history'])

    def test_our_check_mark_on_tickets_without_a_user_is_looked_up_once(self):
        self.history(ticket(T1, user=None, bot_id=APP, reactions=CLOSED_BY_US),
                     ticket(T2, user=None, bot_id=APP, reactions=CLOSED_BY_US))
        self.slack.respond('auth.test', US)
        self.assertTrue(self.listed()[0].startswith(f'Channel {CHANNEL}: 0 open'))
        self.assertEqual(len(self.slack.made('auth.test')), 1)

    def test_a_failed_lookup_leaves_the_ticket_open_and_the_list_readable(self):
        self.history(ticket(T1, reactions=STRANGERS))

        def refuse(**payload):
            raise SystemExit('auth.test: invalid_auth')
        self.slack.respond('auth.test', refuse)
        lines = self.listed()
        self.assertTrue(lines[0].startswith(f'Channel {CHANNEL}: 1 open'), lines[0])
        self.assertIn('Can we ship on Friday?', lines[1])

    def test_a_check_mark_without_its_users_reads_open_without_a_call(self):
        self.history(ticket(T1, reactions=[{'name': 'white_check_mark', 'count': 1}]))
        self.assertTrue(self.listed()[0].startswith(f'Channel {CHANNEL}: 1 open'))
        self.assertEqual(self.slack.methods(), ['conversations.history'])

    def test_other_reactions_do_not_close_a_ticket(self):
        self.history(ticket(T1, reactions=[{'name': 'eyes', 'count': 1}]))
        self.assertTrue(self.listed()[0].startswith(f'Channel {CHANNEL}: 1 open. Open tickets, oldest first:'))

    def test_messages_that_are_not_tickets_are_ignored(self):
        self.history(ticket(T1, 'Good morning everyone', bot_id=None), ticket(T2, '  *Q: Indented one?*\n*Urgency:* x'),
                     ticket(T3, 'Q: not bold start', bot_id=None))
        lines = self.listed()
        self.assertTrue(lines[0].startswith(f'Channel {CHANNEL}: 1 open. Open tickets, oldest first:'), lines[0])
        self.assertEqual(len(lines), 3)
        self.assertIn('Indented one?', lines[1])
        self.assertTrue(lines[2].startswith('Not tickets, top-level messages by people'), lines[2])

    def test_tickets_are_listed_oldest_first_across_pages(self):
        self.slack.respond('conversations.history',
                           {'ok': True, 'messages': [ticket(T2, top('Second?'))], 'response_metadata': {'next_cursor': 'c2'}},
                           {'ok': True, 'messages': [ticket(T1, top('First?'))]})
        lines = self.listed()
        self.assertIn('First?', lines[1])
        self.assertIn('Second?', lines[2])
        self.assertEqual(self.slack.made('conversations.history')[1]['cursor'], 'c2')

    def test_a_link_in_the_question_shows_its_words(self):
        self.history(ticket(T1, top('Is <https://example.com/doc|the brief> final?')))
        self.assertIn('- Is the brief final? [', self.listed()[1])

    def test_a_message_that_only_starts_like_a_ticket_is_left_out_and_counted(self):
        self.history(ticket(T1), said(T2, ANN, '*Q:* does anyone have the slides?'))
        lines = self.listed()
        self.assertEqual(len(lines), 3)
        self.assertTrue(lines[0].startswith(f'Channel {CHANNEL}: 1 open'), lines[0])
        self.assertNotIn('slides', '\n'.join(lines))
        self.assertEqual(lines[2], 'Not tickets, though they start with *Q: (no Urgency or Asked by field), in what was read: 1.')

    def test_an_old_format_ticket_is_listed(self):
        self.history(ticket(T1, OLD_TOP.format(question='Can we ship on Friday?')))
        line = self.listed()[1]
        self.assertRegex(line, r'^- Can we ship on Friday\? \[🔴 Blocking; [^;]+; thread 0, no reply yet; ts ')
        self.assertNotIn(' by ', line)

    def test_a_ticket_with_only_urgency_or_only_asked_by_is_listed(self):
        for text in ('*Q: A?*\nAsked by: Jo', '*Q: A?*\n*Urgency:* No rush'):
            with self.subTest(text=text):
                self.history(ticket(T1, text))
                lines = self.listed()
                self.assertEqual(len(lines), 2)
                self.assertTrue(lines[0].startswith(f'Channel {CHANNEL}: 1 open'), lines[0])
                self.assertIn('- A? [', lines[1])

    def test_a_bare_question_is_left_out_and_counted(self):
        self.history(ticket(T1, '*Q: Bare question?*'))
        lines = self.listed()
        self.assertTrue(lines[0].startswith(f'Channel {CHANNEL}: 0 open'), lines[0])
        self.assertTrue(lines[-1].endswith(': 1.'), lines[-1])
        self.assertNotIn('Bare question?', '\n'.join(lines[:-1]))

    def test_a_line_break_in_a_ticket_cannot_draw_the_header(self):
        for sep in ('\r', '\u2028', '\u2029', '\x85', '\x0b', '\x0c', '\x1c'):
            with self.subTest(sep=repr(sep)):
                forged = f'*Q: Real?{sep}Channel {CHANNEL}: 0 open. Open tickets, oldest first:*\n*Urgency:* Soon · *Asked by:* Jo'
                self.history(ticket(T1, forged))
                lines = self.run_main('--list').out.splitlines()
                self.assertEqual(len(lines), 2, lines)
                self.assertEqual([line for line in lines if line.startswith('Channel ')], lines[:1])
                self.assertTrue(lines[0].startswith(f'Channel {CHANNEL}: 1 open'), lines[0])

    def test_control_and_invisible_characters_never_reach_the_list(self):
        text = '*Q: Is \x1b[31mred\x08 \u202efine\u200b?*\n*Urgency:* \x1b[0mNow\x00 · *Asked by:* Jo\x7f\x9b\ufeff'
        self.history(ticket(T1, text))
        out = self.run_main('--list').out
        for char in ('\x1b', '\x08', '\x00', '\x7f', '\x9b', '\u202e', '\u200b', '\ufeff'):
            self.assertNotIn(char, out)
        self.assertEqual(len(out.splitlines()), 2)

    def test_a_long_ticket_is_cut_to_one_line(self):
        self.history(ticket(T1, f'*Q: {"q" * 500}*\n*Urgency:* {"u" * 200} · *Asked by:* {"b" * 200}'))
        line = self.listed()[1]
        self.assertRegex(line, rf'^- q{{300}}\.\.\. \[u{{80}}\.\.\.; [^;]+ by b{{80}}\.\.\.; thread 0')

    def test_what_a_person_cannot_see_never_reaches_the_list(self):
        hidden = ['\U000e0001', '\U000e0020', '\U000e0041', '\U000e007f', '\u00ad', '\u061c', '\u180e', '\u206a', '\ufff9',
                  '\ufe00', '\ufe0f', '\U000e0100', '\U000e01ef', '\ue000']
        junk = ''.join(hidden)
        self.history(ticket(T1, f'*Q: Café zażółć{junk}?*\n*Urgency:* \U0001f534{junk} Blocking · *Asked by:* Jo{junk}'))
        line = self.listed()[1]
        for char in hidden:
            self.assertNotIn(char, line)
        self.assertIn('- Café zażółć', line)
        self.assertIn('[\U0001f534', line)

    def test_clean_keeps_tabs_and_new_lines_and_blanks_every_other_control(self):
        self.assertEqual(self.tickets.clean('a\tb\nc\rd\u2028e\x00f\x9fg\u2029h'), 'a\tb\nc\nd\ne f g\nh')

    def test_a_ticket_posted_from_a_persons_account_says_so(self):
        self.history(ticket(T1, user=ANN, bot_id=None), ticket(T2, top('Ours?')))
        lines = self.listed()
        self.assertIn(" by Jo Tester; posted from a person's account; thread 0, no reply yet; ts " + T1, lines[1])
        self.assertNotIn('posted from', lines[2])

    def test_a_lone_surrogate_in_a_ticket_cannot_stop_the_list(self):
        self.history(ticket(T1, top('Is \ud800 fine?')))
        out = self.run_encoded('--list')
        self.assertTrue(out.startswith(f'Channel {CHANNEL}: 1 open'), out)
        self.assertIn('fine? [Blocking;', out)

    def test_a_list_that_cannot_be_printed_says_so_instead_of_raising(self):
        self.history(ticket(T1, top('Is the caf\u00e9 open?')))
        self.assertEqual(self.run_encoded('--list', encoding='ascii'), 'The ticket list could not be read: UnicodeEncodeError\n')

    def test_a_stdout_that_refuses_everything_does_not_make_the_list_raise(self):
        class Refuses:
            def write(self, text):
                raise OSError('closed')
        self.history(ticket(T1))
        with contextlib.redirect_stdout(Refuses()):
            self.tickets.listing()

    def test_a_slack_call_that_exits_prints_one_line(self):
        def refuse(**payload):
            raise SystemExit('conversations.history: not_in_channel')
        self.slack.respond('conversations.history', refuse)
        result = self.run_main('--list')
        self.assertIsNone(result.code)
        self.assertEqual(lines_of(result.out),
                         ['The ticket list could not be read: conversations.history: not_in_channel'])

    def test_a_slack_call_that_raises_prints_one_line(self):
        def fail(**payload):
            raise RuntimeError('boom')
        self.slack.respond('conversations.history', fail)
        result = self.run_main('--list')
        self.assertIsNone(result.code)
        self.assertEqual(lines_of(result.out), ['The ticket list could not be read: RuntimeError'])

    def test_no_channel_prints_one_line_and_calls_nothing(self):
        del os.environ['SLACK_TICKETS_CHANNEL']
        result = self.run_main('--list')
        self.assertIsNone(result.code)
        self.assertEqual(len(lines_of(result.out)), 1)
        self.assertTrue(result.out.startswith('The ticket list could not be read: SLACK_TICKETS_CHANNEL is not set'))
        self.assertEqual(self.slack.calls, [])

    def test_a_broken_state_file_does_not_stop_the_list(self):
        self.write('.slack-tickets/state.json', '{not json')
        self.history(ticket(T1))
        self.assertIn('Can we ship on Friday?', self.listed()[1])


class AnswersTests(SlackTestCase):
    def setUp(self):
        super().setUp()
        self.latest = '1700000300.000100'
        self.history(
            ticket(T1, reply_count=3, reply_users=[BOT, ANN, BEN], latest_reply=self.latest),
            ticket(T2, top('Is the old one closed?', 'Kim'), reactions=CLOSED_BY_US))
        self.thread = [
            ticket(T1),
            {'ts': '1700000100.000100', 'user': BOT, 'text': '*Details*\nWhat led to this.'},
            {'ts': '1700000200.000100', 'user': ANN, 'text': 'Yes, <@U0000000003> agrees. See <https://example.com/a|the doc>.'},
            {'ts': self.latest, 'user': BEN, 'text': 'Line one\nLine two', 'files': [{'id': 'F1'}, {'id': 'F2'}]},
        ]
        self.slack.respond('conversations.replies', lambda **payload: {'ok': True, 'messages': self.thread})
        people = {ANN: {'real_name': 'Ann Client'}, BEN: {'name': 'ben'}}
        self.slack.respond('users.info', lambda user, **payload: {'ok': True, 'user': people.get(user, {})})

    def answers(self, *flags):
        result = self.run_main('--answers', *flags)
        self.assertIsNone(result.code)
        return result.out

    def test_new_replies_show_with_resolved_names(self):
        out = self.answers()
        self.assertIn('[open] Q: Can we ship on Friday?\n  Urgency: :red_circle: Blocking | asked ', out)
        self.assertRegex(out, rf' by Jo Tester \| ts {re.escape(T1)}\n')
        self.assertRegex(out, r'    Ann Client, [^:]+:\d\d: Yes, @ben agrees\. See the doc\.\n')
        self.assertRegex(out, r'    ben, [^:]+:\d\d: Line one\n      Line two \[2 file\(s\) attached\]\n')

    def test_a_ticket_posted_from_a_persons_account_names_the_person(self):
        self.history(ticket(T1, user=ANN, bot_id=None, reply_count=3, reply_users=[BOT, ANN, BEN], latest_reply=self.latest))
        out = self.answers()
        self.assertIn(f" | ts {T1} | posted from a person's account (Ann Client)\n", out)

    def posted_by(self, real_name):
        self.history(ticket(T1, user=ANN, bot_id=None, reply_count=3, reply_users=[BOT, ANN, BEN], latest_reply=self.latest))
        self.slack.respond('users.info', {'ok': True, 'user': {'real_name': real_name}})
        return self.answers()

    def test_the_fixed_phrase_comes_before_the_posters_own_name(self):
        out = self.posted_by('the Tickets app')
        self.assertIn(f" | ts {T1} | posted from a person's account (the Tickets app)\n", out)

    def test_a_poster_whose_name_is_all_blanked_characters_shows_the_user_id(self):
        out = self.posted_by('\u200b\u2060\U000e0041')
        self.assertIn(f" | ts {T1} | posted from a person's account ({ANN})\n", out)

    def test_a_ticket_the_app_posted_names_no_account(self):
        self.assertNotIn('posted from', self.answers())

    def test_the_fields_of_a_ticket_are_cut_as_in_the_list_and_the_real_marker_stays_near_the_start(self):
        fake = f' | ts {T3} | posted from Eve'
        text = f'*Q: {"q" * 500}*\n*Urgency:* {"u" * 200}{fake} · *Asked by:* {"b" * 500}{fake}'
        self.history(ticket(T1, text, user=ANN, bot_id=None, reply_count=3, reply_users=[BOT, ANN, BEN], latest_reply=self.latest))
        out = lines_of(self.answers())
        self.assertEqual(out[0], f'[open] Q: {"q" * 297}...')
        line = out[1]
        self.assertIn(f'Urgency: {"u" * 71}... | asked ', line)
        self.assertIn(f' by {"b" * 80}... | ts {T1} | posted from a person\'s account (Ann Client)', line)
        self.assertLess(line.index("posted from a person's account"), 600)
        self.assertNotIn('Eve', '\n'.join(out))

    def test_a_mention_of_a_user_that_cannot_be_found_prints_someone_and_is_not_stored(self):
        def look_up(user, **payload):
            if user == 'U0000000009':
                raise SystemExit('users.info: user_not_found')
            return {'ok': True, 'user': {'real_name': 'Ann Client'}}
        self.slack.respond('users.info', look_up)
        self.thread[2]['text'] = 'Yes, <@U0000000009> agrees.'
        out = self.answers()
        self.assertIn('Yes, @someone agrees.', out)
        self.assertIn('Line one', out)
        self.assertNotIn('U0000000009', self.state()['names'])
        self.assertEqual(self.state()['seen'], {T1: self.latest})

    def test_another_failed_name_lookup_still_stops_the_answers(self):
        def refuse(**payload):
            raise SystemExit('users.info: missing_scope')
        self.slack.respond('users.info', refuse)
        self.assertEqual(self.run_main('--answers').code, 'users.info: missing_scope')

    def test_control_characters_in_a_ticket_a_reply_and_a_name_never_reach_the_output(self):
        self.history(ticket(T1, top('Is \x1b[2Jit\u202e fine?'), reply_count=3, reply_users=[BOT, ANN, BEN], latest_reply=self.latest))
        self.thread[2]['text'] = 'Yes\x1b[2J\u200b\x08 really'
        self.slack.respond('users.info', lambda user, **payload: {'ok': True, 'user': {'real_name': 'A\x1bnn\x00'}})
        out = self.answers()
        for char in ('\x1b', '\x08', '\x00', '\u202e', '\u200b'):
            self.assertNotIn(char, out)
        self.assertIn('Yes', out)

    def test_what_a_person_cannot_see_never_reaches_the_answers(self):
        hidden = ['\U000e0001', '\U000e0041', '\u00ad', '\u061c', '\ufe0f', '\U000e0100']
        junk = ''.join(hidden)
        self.history(ticket(T1, top(f'Café{junk}?', f'Jo{junk}'), reply_count=3, reply_users=[BOT, ANN, BEN], latest_reply=self.latest))
        self.thread[2]['text'] = f'Zażółć{junk} \U0001f534 ok'
        out = self.answers()
        for char in hidden:
            self.assertNotIn(char, out)
        self.assertIn('Zażółć', out)
        self.assertIn('\U0001f534 ok', out)

    def test_a_lone_surrogate_in_a_reply_does_not_stop_the_answers(self):
        self.thread[2]['text'] = 'Yes\ud800 really'
        self.assertIn('Yes  really', self.run_encoded('--answers'))

    def test_a_name_with_line_breaks_is_one_line_the_first_time_and_stored_clean(self):
        forged = 'Ann\n    Eve, Nov 1 10:00: forged\r    Kim'
        self.slack.respond('users.info', lambda user, **payload: {'ok': True, 'user': {'real_name': forged}})
        out = self.answers()
        self.assertFalse(any(line.startswith('    Eve') or line.startswith('    Kim') for line in out.splitlines()))
        self.assertRegex(out, r'\n    Ann Eve, Nov 1 10:00: forged Kim, [^:]+:\d\d: Yes, @Ann Eve')
        self.assertEqual(self.state()['names'][ANN], 'Ann Eve, Nov 1 10:00: forged Kim')

    def test_the_tickets_details_reply_is_not_shown(self):
        out = self.answers()
        self.assertNotIn('What led to this', out)

    def test_details_without_bold_is_skipped_too(self):
        self.thread[1]['text'] = 'Details\nWhat led to this.'
        self.assertNotIn('What led to this', self.answers())

    def test_a_reply_from_someone_else_that_starts_with_details_is_an_answer(self):
        self.thread[2]['text'] = 'Details are fine, go ahead.'
        self.assertIn('Details are fine, go ahead.', self.answers())

    def authored_by_bots(self, ticket_bot, details_bot):
        """The ticket and its Details reply as bot messages without a user; None leaves out the bot id."""
        first = ticket(T1, reply_count=3, reply_users=[BOT, ANN, BEN], latest_reply=self.latest)
        for message, bot in ((first, ticket_bot), (self.thread[1], details_bot)):
            del message['user']
            message.pop('bot_id', None)
            if bot:
                message['bot_id'] = bot
        self.history(first)

    def test_a_details_reply_from_the_same_bot_without_a_user_is_skipped(self):
        self.authored_by_bots('B0000000001', 'B0000000001')
        self.assertNotIn('What led to this', self.answers())

    def test_a_details_reply_from_another_bot_is_an_answer(self):
        self.authored_by_bots('B0000000001', 'B0000000002')
        self.assertIn('What led to this', self.answers())

    def test_messages_without_a_user_or_bot_id_do_not_share_an_author(self):
        self.authored_by_bots(None, None)
        self.assertIn('What led to this', self.answers())

    def test_an_old_format_ticket_and_its_plain_details(self):
        latest = '1700000200.000100'
        parent = ticket(T1, OLD_TOP.format(question='Can we ship on Friday?'), reply_count=2, reply_users=[BOT, ANN],
                        latest_reply=latest)
        self.history(parent)
        self.thread = [parent, {'ts': '1700000100.000100', 'user': BOT, 'text': 'Details\nWhat led'},
                       {'ts': latest, 'user': ANN, 'text': 'Yes'}]
        out = self.answers()
        self.assertIn('[open] Q: Can we ship on Friday?\n  Urgency: 🔴 Blocking | asked ', out)
        self.assertIn('Yes', out)
        self.assertNotIn('What led', out)

    def test_answers_count_what_only_starts_like_a_ticket(self):
        self.history(ticket(T1), said(T3, ANN, '*Q:* hi'))
        out = lines_of(self.answers())
        self.assertTrue(out[-2].endswith(': 1.'), out)

    def test_a_ticket_with_only_its_details_reply_shows_nothing(self):
        self.thread = self.thread[:2]
        out = self.answers()
        self.assertIn('No new replies.', out)
        self.assertNotIn('[open]', out)

    def only_details(self):
        self.thread = self.thread[:2]
        self.history(ticket(T1, reply_count=1, reply_users=[BOT], latest_reply='1700000100.000100'))

    def test_a_ticket_with_only_its_details_reply_is_not_read_again(self):
        self.only_details()
        self.answers()
        self.assertEqual(self.state()['seen'], {T1: '1700000100.000100'})
        self.slack.calls.clear()
        self.assertEqual(lines_of(self.answers()), ['No new replies.', '1 ticket open.'])
        self.assertEqual(self.slack.made('conversations.replies'), [])

    def test_a_thread_served_in_two_pages_is_read_to_its_end(self):
        pages = {None: {'ok': True, 'messages': self.thread[:2], 'response_metadata': {'next_cursor': 'page2'}},
                 'page2': {'ok': True, 'messages': self.thread[2:], 'response_metadata': {'next_cursor': ''}}}
        self.slack.respond('conversations.replies', lambda cursor=None, **payload: pages[cursor])
        out = self.answers()
        self.assertIn('Line two', out)
        self.assertEqual([c.get('cursor') for c in self.slack.made('conversations.replies')], [None, 'page2'])
        self.assertEqual(self.state()['seen'], {T1: self.latest})

    def test_a_thread_of_one_page_is_read_with_one_call(self):
        self.answers()
        self.assertEqual(len(self.slack.made('conversations.replies')), 1)
        self.assertNotIn('cursor', self.slack.made('conversations.replies')[0])

    def test_peek_and_all_do_not_remember_a_ticket_with_only_its_details_reply(self):
        self.only_details()
        for flag in ('--peek', '--all'):
            with self.subTest(flag=flag):
                self.answers(flag)
                self.assertEqual(self.state()['seen'], {})

    def test_the_last_line_counts_open_tickets(self):
        self.assertEqual(lines_of(self.answers())[-1], '1 ticket open.')

    def test_all_marks_a_ticket_with_a_strangers_check_mark_open(self):
        self.history(
            ticket(T1, reply_count=3, reply_users=[BOT, ANN, BEN], latest_reply=self.latest),
            ticket(T2, top('Is the old one closed?', 'Kim'), reactions=STRANGERS))
        self.slack.respond('auth.test', US)
        out = self.answers('--all')
        self.assertIn('[open] Q: Is the old one closed?', out)
        self.assertNotIn('[closed]', out)

    def test_a_closed_ticket_without_replies_is_not_shown(self):
        self.assertNotIn('Is the old one closed?', self.answers())

    def test_a_second_run_has_no_new_replies(self):
        self.answers()
        self.slack.calls.clear()
        out = self.answers()
        self.assertEqual(lines_of(out), ['No new replies.', '1 ticket open.'])
        self.assertEqual(self.slack.made('conversations.replies'), [])

    def test_what_was_shown_is_remembered_in_the_project(self):
        self.answers()
        state = self.state()
        self.assertEqual(state['seen'], {T1: self.latest})
        self.assertEqual(state['names'][ANN], 'Ann Client')
        self.assertTrue(os.path.exists(os.path.join('.slack-tickets', '.gitignore')))

    def test_only_replies_newer_than_what_was_seen_are_shown(self):
        self.remember_seen({T1: '1700000250.000100'})
        out = self.answers()
        self.assertNotIn('Ann Client', out)
        self.assertIn('Line one', out)

    def test_a_newer_reply_after_a_run_shows_on_the_next_run(self):
        self.answers()
        self.thread.append({'ts': '1700000400.000100', 'user': ANN, 'text': 'One more thing'})
        self.history(ticket(T1, reply_count=4, reply_users=[BOT, ANN, BEN], latest_reply='1700000400.000100'))
        out = self.answers()
        self.assertIn('One more thing', out)
        self.assertNotIn('Line one', out)

    def test_peek_does_not_advance_what_was_seen(self):
        first, second = self.answers('--peek'), self.answers('--peek')
        self.assertIn('Line one', first)
        self.assertIn('Line one', second)
        self.assertEqual(self.state()['seen'], {})
        self.assertIn('Line one', self.answers())
        self.assertIn('No new replies.', self.answers())

    def test_all_shows_every_ticket_marked_open_or_closed(self):
        out = self.answers('--all')
        self.assertIn('[open] Q: Can we ship on Friday?', out)
        self.assertIn('[closed] Q: Is the old one closed?', out)
        self.assertIn('Ann Client', out)
        self.assertNotIn('No new replies.', out)
        self.assertEqual(lines_of(out)[-1], '1 ticket open.')

    def test_all_shows_replies_that_were_already_seen_and_remembers_nothing(self):
        older = '1700000250.000100'
        self.remember_seen({T1: older})
        out = self.answers('--all')
        self.assertIn('Line one', out)
        self.assertIn('Ann Client', out)
        self.assertEqual(self.state()['seen'], {T1: older})

    def test_a_name_is_looked_up_once(self):
        self.answers()
        self.assertEqual(sorted(p['user'] for p in self.slack.made('users.info')), [ANN, BEN])

    def test_a_name_without_a_profile_falls_back_to_the_id(self):
        self.thread[2]['user'] = 'U0000000009'
        self.assertIn('U0000000009, ', self.answers())

    def test_a_reply_without_a_user_is_attributed_to_someone(self):
        del self.thread[2]['user']
        self.assertIn('    someone, ', self.answers())


class ReplyTests(SlackTestCase):
    def note(self, text):
        return self.write('note.txt', text)

    def test_a_dry_run_prints_the_text_and_posts_nothing(self):
        self.slack.respond('conversations.replies', {'ok': True, 'messages': [ticket(T1)]})
        self.slack.respond('auth.test', US)
        self.slack.respond('users.info', {'ok': True, 'user': {'real_name': 'Tickets'}})
        result = self.run_main('--reply', T1, self.note('  We will go ahead with the default.\n'))
        self.assertIsNone(result.code)
        lines = lines_of(result.out)
        self.assertEqual(lines[0], f'--- reply in the thread of {T1}')
        self.assertRegex(lines[1], r'^It starts with: .+ \| a ticket \| thread 0 \| this app: Tickets$')
        self.assertTrue(lines[2].startswith('  *Q: Can we ship on Friday?*'), lines[2])
        self.assertEqual(lines[3:], ['--- the reply', 'We will go ahead with the default.', '',
                                     f'Dry run for {CHANNEL}, nothing posted. Add --post to post.'])
        self.assertNotIn('chat.postMessage', self.slack.methods())

    def test_a_reply_that_is_refused(self):
        refused = {
            'a mention': '<@U0000000001> please look',
            'a broadcast': '<!here> look',
            'a broadcast word': 'Hi @here, look',
            'a broadcast word in capitals': '@Channel please',
            'an empty text': '  \n ',
            'a text that is too long': 'x' * 3501,
        }
        for why, text in refused.items():
            for flags in ((), ('--post',)):
                with self.subTest(why=why, flags=flags):
                    result = self.run_main('--reply', T1, self.note(text), *flags)
                    self.assertTrue(str(result.code).startswith('Not posted: a reply needs some text'), result)
                    self.assertEqual(self.slack.calls, [])

    def test_a_reply_with_characters_that_cannot_be_seen_is_refused(self):
        refused = {'a zero-width space': '\u200b', 'an escape': '\x1b', 'a tag character': '\U000e0041', 'a lone carriage return': '\r',
                   'a vertical tab': '\x0b', 'a line separator': '\u2028', 'a soft hyphen': '\u00ad',
                   'a right-to-left override': '\u202e'}
        for why, char in refused.items():
            for flags in ((), ('--post',)):
                with self.subTest(why=why, flags=flags):
                    result = self.run_main('--reply', T1, self.note(f'Fine{char} text'), *flags)
                    self.assertEqual(result.code, 'Not posted: the reply holds characters that cannot be seen. Type it again as plain text.')
                    self.assertEqual(self.slack.calls, [])

    def test_a_reply_may_hold_an_emoji_with_a_variation_selector_or_a_joiner(self):
        emoji = {'a check mark with a variation selector': '\u2714\ufe0f',
                 'two emoji joined by a joiner': '\U0001f469\u200d\U0001f467'}
        for why, char in emoji.items():
            text = f'*Update* (Jo, today): done {char}'
            with self.subTest(why=why, flags=()):
                self.slack.respond('conversations.replies', {'ok': True, 'messages': [ticket(T1)]})
                self.slack.respond('auth.test', US)
                self.slack.respond('users.info', {'ok': True, 'user': {'real_name': 'Tickets'}})
                result = self.run_main('--reply', T1, self.note(text))
                self.assertIsNone(result.code)
                self.assertIn(f'--- the reply\n{text}\n', result.out)
            with self.subTest(why=why, flags=('--post',)):
                self.slack.calls.clear()
                self.slack.respond('chat.postMessage', {'ok': True, 'ts': '1700000900.000100', 'channel': CHANNEL})
                result = self.run_main('--reply', T1, self.note(text), '--post')
                self.assertIsNone(result.code)
                self.assertEqual(self.slack.made('chat.postMessage')[0]['text'], text)

    def test_the_broadcast_words_are_found_whatever_stands_around_them(self):
        found = ['@here', 'Hi @Here, look', '_@here_', '*@channel*', '~@everyone~', '@group', 'to @Group: hi', '_@group', 'x _@everyone_ y']
        absent = ['ann@everyone.example', 'ann@group.example', 'ann@here', '@herex', '@@here', 'a@channel', 'at here']
        for text in found:
            with self.subTest(found=text):
                self.assertTrue(self.tickets.BROADCAST(text))
        for text in absent:
            with self.subTest(absent=text):
                self.assertFalse(self.tickets.BROADCAST(text))
        result = self.run_main('--reply', T1, self.note('Fine _@here_ text'))
        self.assertTrue(str(result.code).startswith('Not posted: a reply needs some text'), result)
        self.assertEqual(self.slack.calls, [])

    def test_a_malformed_timestamp_is_refused(self):
        for ts in ('123', '1700000000', '1700000000.1', 'abc.def', '1700000000.000100x', ARABIC_INDIC_TS):
            with self.subTest(ts=ts):
                result = self.run_main('--reply', ts, self.note('Fine text'), '--post')
                self.assertTrue(str(result.code).startswith("Not posted: the first argument is the thread's timestamp"))
                self.assertEqual(self.slack.calls, [])

    def test_a_reply_outside_a_ticket_without_whose_words_is_refused(self):
        in_thread = f"Not posted: that timestamp is a reply in the thread of {T2}. Use {T2}, the thread's top-level message."
        parents = {
            'chatter': ({'ts': T1, 'text': 'Good morning'}, LABEL_REFUSAL),
            'a reply inside a thread': ({'ts': T2, 'text': '*Q: Something?*'}, in_thread),
            'a message that only starts like one': ({'ts': T1, 'text': '*Q:* anyone?'}, LABEL_REFUSAL),
        }
        for why, (parent, refusal) in parents.items():
            with self.subTest(why=why):
                self.slack.calls.clear()
                self.slack.respond('conversations.replies', {'ok': True, 'messages': [parent]})
                result = self.run_main('--reply', T1, self.note('Fine text'), '--post')
                self.assertEqual(result.code, refusal)
                self.assertEqual(self.slack.methods(), ['conversations.replies'])

    def test_an_empty_answer_is_not_a_ticket(self):
        self.slack.respond('conversations.replies', {'ok': True, 'messages': []})
        result = self.run_main('--reply', T1, self.note('Fine text'), '--post')
        self.assertEqual(result.code, 'Not posted: that timestamp is not a message in this channel.')
        self.assertEqual(self.slack.methods(), ['conversations.replies'])

    def test_a_reply_in_a_thread_is_refused_even_when_it_reads_like_a_ticket(self):
        self.slack.respond('conversations.replies', {'ok': True, 'messages': [ticket(T1, thread_ts=T2)]})
        result = self.run_main('--reply', T1, self.note('Fine text'), '--post')
        self.assertEqual(result.code, f"Not posted: that timestamp is a reply in the thread of {T2}. Use {T2}, the thread's top-level message.")
        self.assertEqual(self.slack.methods(), ['conversations.replies'])

    def test_a_reply_to_an_old_format_ticket_is_posted(self):
        self.slack.respond('conversations.replies', {'ok': True, 'messages': [ticket(T1, OLD_TOP.format(question='Can we ship?'))]})
        self.slack.respond('chat.postMessage', {'ok': True, 'ts': '1700000900.000100', 'channel': CHANNEL})
        self.slack.respond('auth.test', US)
        self.slack.respond('users.info', {'ok': True, 'user': {'real_name': 'Tickets'}})
        result = self.run_main('--reply', T1, self.note('Fine text'), '--post')
        self.assertIn('Replied in the thread of', result.out)

    def test_a_reply_to_a_ticket_is_posted_in_its_thread(self):
        self.slack.respond('conversations.replies', {'ok': True, 'messages': [ticket(T1)]})
        self.slack.respond('chat.postMessage', {'ok': True, 'ts': '1700000900.000100', 'channel': CHANNEL})
        self.slack.respond('auth.test', US)
        self.slack.respond('users.info', {'ok': True, 'user': {'real_name': 'Tickets'}})
        result = self.run_main('--reply', T1, self.note('*Update* (Jo, today): we went ahead.\n'), '--post')
        self.assertIsNone(result.code)
        lines = lines_of(result.out)
        self.assertRegex(lines[0], r'^It starts with: .+ \| a ticket \| thread 0 \| this app: Tickets$')
        self.assertTrue(lines[1].startswith('  *Q: Can we ship on Friday?*'), lines[1])
        self.assertEqual(lines[2:], [f'Replied in the thread of {T1} (1700000900.000100).'])
        self.assertEqual(self.slack.methods(), ['conversations.replies', 'auth.test', 'users.info', 'chat.postMessage'])
        self.assertEqual(self.slack.made('conversations.replies')[0]['ts'], T1)
        self.assertEqual(self.slack.made('chat.postMessage')[0], {
            'channel': CHANNEL, 'thread_ts': T1, 'text': '*Update* (Jo, today): we went ahead.',
            'unfurl_links': False, 'unfurl_media': False})


class PostTests(SlackTestCase):
    def batch(self, tickets=None, name='batch.json', **extra):
        tickets = tickets or [
            {'id': 'ship-friday', 'top': top(), 'details': '*Details*\nWhat led to this.'},
            {'id': 'wording', 'top': top('Is the wording final?', 'Kim'), 'details': '*Details*\nThe words.'},
        ]
        return self.write_json(name, dict({'tickets': tickets}, **extra))

    def fake_post(self):
        """Slack answering each message with the next timestamp, and a link for each ticket."""
        counter = itertools.count(1)
        self.slack.respond('chat.postMessage', lambda **payload: {
            'ok': True, 'ts': f'{1700000000 + next(counter)}.000100', 'channel': OTHER_CHANNEL})
        self.slack.respond('chat.getPermalink', lambda channel, message_ts, **payload: {
            'ok': True, 'permalink': f'https://example.com/{channel}/p{message_ts}'})

    def test_a_dry_run_prints_each_ticket_and_posts_nothing(self):
        path = self.batch()
        result = self.run_main(path)
        self.assertIsNone(result.code)
        self.assertIn('--- ship-friday (to post)\n' + top() + '\n  [thread]\n*Details*\nWhat led to this.\n', result.out)
        self.assertIn('--- wording (to post)\n', result.out)
        self.assertEqual(lines_of(result.out)[-1], f'Dry run: 2 tickets for {CHANNEL}, nothing posted. Add --post to post.')
        self.assertEqual(self.slack.calls, [])
        self.assertFalse(os.path.exists(os.path.join(self.tmp, 'batch.result.json')))

    def test_one_ticket_is_not_plural(self):
        self.fake_post()
        path = self.batch([{'id': 'ship-friday', 'top': top(), 'details': 'x'}])
        self.assertEqual(lines_of(self.run_main(path).out)[-1], f'Dry run: 1 ticket for {CHANNEL}, nothing posted. Add --post to post.')
        self.assertIn('Posted 1 ticket. Results: ', lines_of(self.run_main(path, '--post').out)[-1])

    def test_a_dry_run_marks_what_is_already_posted(self):
        path = self.batch()
        self.write_json('batch.result.json', {'ship-friday': {'ts': T1, 'details_ts': T2}, 'wording': {'ts': T3}})
        out = self.run_main(path).out
        self.assertIn('--- ship-friday (already posted)', out)
        self.assertIn('--- wording (to post)', out)

    def test_problems_names_each_refusal(self):
        good = {'id': 'a', 'top': top(), 'details': 'Some details'}
        cases = {
            'a mention in the top': (dict(good, top=top() + ' <@U0000000001>'), 'nobody is mentioned'),
            'a broadcast in the details': (dict(good, details='<!here> look'), 'nobody is mentioned'),
            'no asker': (dict(good, top='*Q: Who asked?*\n*Urgency:* No rush'), 'says who asked'),
            'an empty asker': (dict(good, top='*Q: Who asked?*\n*Asked by:* \n'), 'says who asked'),
            'no details': (dict(good, details='  '), 'a: both parts are required'),
            'no top': (dict(good, top=''), 'a: both parts are required'),
            'too long': (dict(good, details='x' * 3501), 'too long for one message'),
        }
        for why, (bad, expected) in cases.items():
            with self.subTest(why=why):
                found = self.tickets.problems([bad])
                self.assertTrue(any(expected in f for f in found), found)

    def test_problems_accepts_a_good_ticket_with_or_without_bold_label(self):
        for line in ('*Asked by:* Jo', 'Asked by: Jo', '*Asked by:*Jo'):
            with self.subTest(line=line):
                found = self.tickets.problems([{'id': 'a', 'top': f'*Q: Yes?*\n{line}', 'details': 'x'}])
                self.assertEqual(found, [])

    def test_problems_refuses_duplicate_or_missing_ids(self):
        good = {'top': top(), 'details': 'x'}
        for why, ids in (('duplicates', ['a', 'a']), ('an empty id', ['a', '']), ('no id', ['a', None])):
            with self.subTest(why=why):
                found = self.tickets.problems([dict(good, id=i) for i in ids])
                self.assertIn('every ticket needs its own id', found)
        self.assertEqual(self.tickets.problems([dict(good, id='a'), dict(good, id='b')]), [])

    def test_a_refused_batch_stops_before_any_call(self):
        path = self.batch([{'id': 'a', 'top': top() + ' <@U0000000001>', 'details': 'x'}])
        for flags in ((), ('--post',)):
            with self.subTest(flags=flags):
                result = self.run_main(path, *flags)
                self.assertTrue(result.code.startswith('Not posted:\n  a: nobody is mentioned in a ticket'), result.code)
                self.assertEqual(self.slack.calls, [])

    def test_a_batch_naming_another_channel_is_refused(self):
        result = self.run_main(self.batch(channel=OTHER_CHANNEL), '--post')
        self.assertEqual(result.code, 'Not posted: the batch names another channel. Take "channel" out of the batch.')
        self.assertEqual(self.slack.calls, [])

    def test_posting_sends_each_top_then_its_details_in_its_thread(self):
        self.fake_post()
        path = self.batch()
        result = self.run_main(path, '--post')
        self.assertIsNone(result.code)
        sent = self.slack.made('chat.postMessage')
        self.assertEqual(self.slack.methods(), ['chat.postMessage', 'chat.postMessage', 'chat.getPermalink'] * 2)
        self.assertEqual(sent[0], {'channel': CHANNEL, 'text': top(), 'unfurl_links': False, 'unfurl_media': False})
        self.assertEqual(sent[1]['thread_ts'], '1700000001.000100')
        self.assertEqual(sent[1]['text'], '*Details*\nWhat led to this.')
        self.assertEqual(sent[1]['channel'], OTHER_CHANNEL)  # the conversation id Slack answered with
        self.assertNotIn('thread_ts', sent[2])
        self.assertEqual(sent[3]['thread_ts'], '1700000003.000100')
        self.assertEqual(self.sleeps.call_count, 4)

    def test_posting_writes_the_result_beside_the_batch(self):
        self.fake_post()
        path = self.batch()
        result = self.run_main(path, '--post')
        saved = self.read_json('batch.result.json')
        self.assertEqual(saved['ship-friday'], {
            'ts': '1700000001.000100', 'channel': OTHER_CHANNEL, 'details_ts': '1700000002.000100',
            'link': 'https://example.com/C1111111111/p1700000001.000100'})
        self.assertEqual(sorted(saved), ['ship-friday', 'wording'])
        self.assertIn('ship-friday: https://example.com/C1111111111/p1700000001.000100\n', result.out)
        self.assertEqual(lines_of(result.out)[-1], f'Posted 2 tickets. Results: {os.path.join(self.tmp, "batch.result.json")}')

    def test_a_second_run_posts_nothing_again(self):
        self.fake_post()
        path = self.batch()
        self.run_main(path, '--post')
        self.slack.calls.clear()
        result = self.run_main(path, '--post')
        self.assertIsNone(result.code)
        self.assertEqual(self.slack.calls, [])
        self.assertIn('Posted 2 tickets.', result.out)

    def test_a_run_that_stopped_halfway_posts_only_what_is_missing(self):
        self.fake_post()
        path = self.batch()
        self.write_json('batch.result.json', {
            'ship-friday': {'ts': T1, 'channel': OTHER_CHANNEL, 'details_ts': T2, 'link': 'https://example.com/x'},
            'wording': {'ts': T3, 'channel': OTHER_CHANNEL}})
        self.run_main(path, '--post')
        sent = self.slack.made('chat.postMessage')
        self.assertEqual(len(sent), 1)
        self.assertEqual((sent[0]['channel'], sent[0]['thread_ts'], sent[0]['text']),
                         (OTHER_CHANNEL, T3, '*Details*\nThe words.'))
        self.assertEqual([p['message_ts'] for p in self.slack.made('chat.getPermalink')], [T3])

    def test_a_batch_without_a_json_name_gets_a_result_name_appended(self):
        self.fake_post()
        path = self.batch(name='batch.txt')
        self.run_main(path, '--post')
        self.assertTrue(os.path.exists(path + '.result.json'))

    def test_a_failed_send_keeps_what_was_posted_before_it(self):
        sends = []

        def second_fails(**payload):
            sends.append(payload)
            if len(sends) == 2:
                raise SystemExit('chat.postMessage: ratelimited')
            return {'ok': True, 'ts': '1700000001.000100', 'channel': CHANNEL}
        self.slack.respond('chat.postMessage', second_fails)
        result = self.run_main(self.batch(), '--post')
        self.assertEqual(result.code, 'chat.postMessage: ratelimited')
        self.assertEqual(self.read_json('batch.result.json'), {'ship-friday': {'ts': '1700000001.000100', 'channel': CHANNEL}})


class MainTests(SlackTestCase):
    def test_close_adds_the_check_mark_reaction_to_a_ticket(self):
        self.slack.respond('conversations.replies', {'ok': True, 'messages': [ticket(T1, reactions=[{'name': 'eyes', 'count': 1}])]})
        self.slack.respond('reactions.add', {'ok': True})
        result = self.run_main('--close', T1)
        self.assertIsNone(result.code)
        self.assertEqual(result.out, f'Closed {T1}.\n')
        self.assertEqual(self.slack.methods(), ['conversations.replies', 'reactions.add'])
        self.assertEqual(self.slack.made('conversations.replies')[0]['ts'], T1)
        self.assertEqual(self.slack.made('reactions.add'), [{'channel': CHANNEL, 'timestamp': T1, 'name': 'white_check_mark'}])

    def test_close_adds_nothing_to_a_ticket_that_is_already_closed(self):
        self.slack.respond('conversations.replies', {'ok': True, 'messages': [
            ticket(T1, reactions=CLOSED_BY_US)]})
        result = self.run_main('--close', T1)
        self.assertIsNone(result.code)
        self.assertEqual(result.out, f'Already closed {T1}.\n')
        self.assertEqual(self.slack.methods(), ['conversations.replies'])

    def test_close_adds_ours_over_someone_elses_check_mark(self):
        self.slack.respond('conversations.replies', {'ok': True, 'messages': [
            ticket(T1, reactions=STRANGERS)]})
        self.slack.respond('auth.test', US)
        self.slack.respond('reactions.add', {'ok': True})
        result = self.run_main('--close', T1)
        self.assertIsNone(result.code)
        self.assertEqual(result.out, f'Closed {T1}.\n')
        self.assertEqual(self.slack.methods(), ['conversations.replies', 'auth.test', 'reactions.add'])

    def test_close_reads_already_reacted_as_closed(self):
        self.slack.respond('conversations.replies', {'ok': True, 'messages': [
            ticket(T1, reactions=[{'name': 'white_check_mark', 'count': 1}])]})

        def refuse(**payload):
            raise SystemExit('reactions.add: already_reacted')
        self.slack.respond('reactions.add', refuse)
        result = self.run_main('--close', T1)
        self.assertIsNone(result.code)
        self.assertEqual(result.out, f'Already closed {T1}.\n')

    def test_close_refuses_a_malformed_timestamp_before_any_call(self):
        for ts in ('123', '1700000000', 'abc.def', '1700000000.000100x', ARABIC_INDIC_TS):
            with self.subTest(ts=ts):
                result = self.run_main('--close', ts)
                self.assertEqual(result.code, "Not closed: the argument is the ticket's timestamp, as printed by --answers (like 1700000000.000100).")
                self.assertEqual(self.slack.calls, [])

    def test_close_refuses_a_message_that_is_not_a_ticket(self):
        parents = {
            'chatter': {'ts': T1, 'text': 'Good morning'},
            'a reply inside a thread': {'ts': T2, 'text': '*Q: Something?*'},
            'a message that only starts like one': {'ts': T1, 'text': '*Q:* anyone?'},
        }
        for why, parent in parents.items():
            with self.subTest(why=why):
                self.slack.calls.clear()
                self.slack.respond('conversations.replies', {'ok': True, 'messages': [parent]})
                result = self.run_main('--close', T1)
                self.assertEqual(result.code, 'Not closed: that timestamp is not a ticket in this channel.')
                self.assertEqual(self.slack.methods(), ['conversations.replies'])

    def test_close_refuses_an_empty_answer(self):
        self.slack.respond('conversations.replies', {'ok': True, 'messages': []})
        result = self.run_main('--close', T1)
        self.assertEqual(result.code, 'Not closed: that timestamp is not a ticket in this channel.')
        self.assertEqual(self.slack.methods(), ['conversations.replies'])

    def test_close_refuses_a_reply_in_a_thread_even_when_it_reads_like_a_ticket(self):
        self.slack.respond('conversations.replies', {'ok': True, 'messages': [ticket(T1, thread_ts=T2)]})
        result = self.run_main('--close', T1)
        self.assertEqual(result.code, 'Not closed: that timestamp is not a ticket in this channel.')
        self.assertEqual(self.slack.methods(), ['conversations.replies'])

    def test_close_accepts_a_ticket_that_is_its_own_thread_root(self):
        self.slack.respond('conversations.replies', {'ok': True, 'messages': [ticket(T1, thread_ts=T1)]})
        self.slack.respond('reactions.add', {'ok': True})
        self.assertEqual(self.run_main('--close', T1).out, f'Closed {T1}.\n')

    def test_close_needs_the_channel(self):
        del os.environ['SLACK_TICKETS_CHANNEL']
        result = self.run_main('--close', T1)
        self.assertTrue(result.code.startswith('SLACK_TICKETS_CHANNEL is not set'))
        self.assertEqual(self.slack.calls, [])

    def test_check_says_the_channel_and_whose_token_without_printing_it(self):
        self.slack.respond('auth.test', {'ok': True, 'user': 'tickets', 'team': 'Acme', 'bot_id': 'B0000000001'})
        result = self.run_main('--check')
        self.assertEqual(result.out, f'Channel {CHANNEL}.\nPosting as tickets in Acme (a bot)\n')
        self.assertNotIn('xoxb-test', result.out)
        self.assertEqual(self.slack.calls[0].tok, 'xoxb-test')

    def test_no_arguments_print_the_usage(self):
        result = self.run_main()
        self.assertIn('dry run: prints what would be posted', result.code)

    def test_a_reply_without_its_note_file_prints_the_usage(self):
        result = self.run_main('--reply', T1)
        self.assertEqual(result.code, self.tickets.__doc__)
        self.assertEqual(self.slack.calls, [])

    def test_a_reply_or_a_close_with_the_wrong_arguments_prints_the_usage(self):
        note = self.write('note.txt', 'Fine text')
        wrong = {
            'a reply with --post and no note file': ('--reply', T1, '--post'),
            'a reply with no arguments': ('--reply',),
            'a reply with too many arguments': ('--reply', T1, note, 'extra'),
            'a close with no timestamp': ('--close',),
            'a close with two timestamps': ('--close', T1, T2),
        }
        for why, argv in wrong.items():
            with self.subTest(why=why):
                result = self.run_main(*argv)
                self.assertEqual(result.code, self.tickets.__doc__)
                self.assertEqual(result.out, '')
                self.assertEqual(self.slack.calls, [])

    def test_a_flag_the_script_does_not_know_prints_the_usage_before_anything_is_read_or_posted(self):
        batch = self.write_json('batch.json', {'tickets': []})
        for argv in (('--talk=1', batch, '--post'), ('--peak',), ('--talk', '--peak'), ('--answers', '--al'), ('--list', '--bogus'),
                     ('--channel', '--list'), ('--thread', T1, '--all=1'), (batch, '--post', '--force'), ('--', '--list')):
            with self.subTest(argv=argv):
                result = self.run_main(*argv)
                self.assertEqual(result.code, self.tickets.__doc__)
                self.assertEqual(result.out, '')
                self.assertEqual(self.slack.calls, [])

    def test_every_flag_the_script_knows_is_still_accepted(self):
        for flags in (('--setup',), ('--sources-template',), ('--sources',), ('--setup', f'--channel={OTHER_CHANNEL}')):
            with self.subTest(flags=flags):
                self.assertIsNone(self.run_main(*flags).code)

    def test_the_channel_flag_works_in_process_too(self):
        del os.environ['SLACK_TICKETS_CHANNEL']
        self.slack.respond('conversations.history', {'ok': True, 'messages': []})
        result = self.run_main('--list', f'--channel={OTHER_CHANNEL}')
        self.assertTrue(result.out.startswith(f'Channel {OTHER_CHANNEL}: 0 open. Open tickets, oldest first:'))
        self.assertEqual(self.slack.made('conversations.history')[0]['channel'], OTHER_CHANNEL)


if __name__ == '__main__':
    unittest.main()
