"""Conversation that is not a ticket: --talk, --thread, and --reply in any thread, with a fake Slack. Dates and times
are never asserted on: they print in local time. The clock is fixed about a day after the newest message, so the
two-week window holds every message unless a test says otherwise."""
import os
import re
import unittest

from helpers import ARABIC_INDIC_TS, CHANNEL, OTHER_CHANNEL, FakeChannel, run_cli
from test_list_answers import ANN, APP, BEN, BOT, CLOSED_BY_US, LABEL_REFUSAL, T1, SlackTestCase, lines_of, said, ticket

KIM = 'U0000000004'  # a guest in the app's workspace
EVE = 'U0000000009'  # nobody Slack can find
OURS, THEIRS = 'T0000000001', 'T0000000002'
OWN = {'ok': True, 'user_id': BOT, 'bot_id': APP, 'team_id': OURS}
PROFILES = {
    ANN: {'real_name': 'Ann Client', 'team_id': THEIRS},
    BEN: {'real_name': 'Ben Ours', 'team_id': OURS},
    KIM: {'real_name': 'Kim Guest', 'team_id': OURS, 'is_restricted': True},
    BOT: {'real_name': 'Tickets', 'team_id': OURS, 'is_bot': True},
}
ASK = '1700003000.000100'
NOW = 1700100000.0
OLD = f'{int(NOW) - 15 * 86400}.000100'
QUIET = ['No new conversation.']
STATE = '.slack-tickets/state.json'
HIDDEN = ['\U000e0001', '\U000e0041', '\u00ad', '\u061c', '\ufe0f', '\U000e0100', '\ue000', '\u200b', '\x1b', '\x08']


def at(n):
    return f'{1700003000 + 100 * n}.000100'


def ours(ts, text='*Reply* (Jo Tester): XLSX only.'):
    return {'ts': ts, 'user': BOT, 'bot_id': APP, 'text': text}


class ConversationTestCase(SlackTestCase):
    def setUp(self):
        super().setUp()
        self.patch(self.tickets.time, 'time', lambda: NOW)
        self.messages, self.threads = [], {}
        self.slack.respond('conversations.history', FakeChannel(self.messages))
        self.slack.respond('conversations.replies', self.replies)
        self.slack.respond('auth.test', OWN)
        self.slack.respond('users.info', self.profile)

    def replies(self, ts, limit, cursor=None, oldest=None, **payload):
        if ts not in self.threads:
            raise SystemExit('conversations.replies: thread_not_found')
        found = [m for m in self.threads[ts] if not oldest or m['ts'] == ts or float(m['ts']) > float(oldest)]
        start = int(cursor or 0)
        more = start + limit < len(found)
        return {'ok': True, 'messages': found[start:start + limit], 'response_metadata': {'next_cursor': str(start + limit) if more else ''}}

    def profile(self, user, **payload):
        if user not in PROFILES:
            raise SystemExit('users.info: user_not_found')
        return {'ok': True, 'user': PROFILES[user]}

    def add(self, first, *later):
        """A top-level message and its replies, in the channel and in its thread."""
        if later:
            first.update(thread_ts=first['ts'], reply_count=len(later), latest_reply=later[-1]['ts'],
                         reply_users=sorted({r['user'] for r in later if r.get('user')}))
            for r in later:
                r['thread_ts'] = first['ts']
        self.messages.append(first)
        self.threads[first['ts']] = [first, *later]
        return first

    def reset(self):
        self.messages.clear()
        self.threads.clear()

    def talk(self, *flags):
        result = self.run_main('--talk', *flags)
        self.assertIsNone(result.code)
        return lines_of(result.out)

    def assert_header(self, line, side, ts, thread, who, hint=''):
        self.assertTrue(line.startswith(f'[last word {side}] ts {ts} | thread {thread}{hint} | '), line)
        self.assertTrue(line.endswith(f' | {who}'), line)


class TalkTests(ConversationTestCase):
    def test_a_question_from_another_workspace_with_no_reply_is_outside(self):
        self.add(said(ASK, ANN, 'Which export formats do you support?'))
        lines = self.talk()
        self.assert_header(lines[0], 'outside', ASK, 0, 'outside: Ann Client')
        self.assertEqual(lines[1], '  Which export formats do you support?')
        self.assertEqual(lines[2:], ['Last word outside or unknown: 1 of 1 thread shown.'])

    def test_a_reply_from_the_apps_workspace_is_inside(self):
        self.add(said(ASK, ANN, 'Which export formats do you support?'), said(at(1), BEN, 'XLSX only.'))
        lines = self.talk()
        self.assert_header(lines[0], 'inside', ASK, 1, 'outside: Ann Client')
        self.assertRegex(lines[2], r'^    [A-Z][a-z]{2} \d\d \d\d:\d\d \| inside: Ben Ours: XLSX only\.$')
        self.assertEqual(lines[3:], ['Last word outside or unknown: 0 of 1 thread shown.'])

    def test_a_guest_of_the_apps_workspace_is_outside(self):
        self.add(said(ASK, KIM, 'Can I get access?'))
        self.assert_header(self.talk()[0], 'outside', ASK, 0, 'outside: Kim Guest')

    def test_the_other_kinds_of_guest_and_a_bot_user_are_told_apart(self):
        kinds = {
            'a stranger': ({'real_name': 'Zed', 'team_id': OURS, 'is_stranger': True}, 'outside'),
            'a single-channel guest': ({'real_name': 'Zed', 'team_id': OURS, 'is_ultra_restricted': True}, 'outside'),
            'another workspace': ({'real_name': 'Zed', 'team_id': THEIRS}, 'outside'),
            'a member': ({'real_name': 'Zed', 'team_id': OURS}, 'inside'),
            'no workspace': ({'real_name': 'Zed'}, 'unknown'),
            'a bot user': ({'real_name': 'Zed', 'team_id': OURS, 'is_bot': True}, 'an app'),
        }
        for why, (profile, side) in kinds.items():
            with self.subTest(why=why):
                self.reset()
                self.write_json(STATE, {})
                self.slack.respond('users.info', {'ok': True, 'user': profile})
                self.add(said(ASK, EVE, 'Hello'))
                self.assertTrue(self.talk('--all')[0].endswith(f' | {side}: Zed'))

    def test_a_message_from_another_workspace_is_outside_even_when_its_user_cannot_be_found(self):
        self.add(dict(said(ASK, EVE, 'x'), user_team=THEIRS))
        self.assertTrue(self.talk()[0].endswith(' | outside: someone'))

    def test_the_workspace_the_message_names_is_used_without_asking_who_the_user_is(self):
        self.write_json(STATE, {'names': {BEN: 'Ben Ours'}})
        self.add(dict(said(ASK, BEN, 'x'), user_team=THEIRS))
        self.assertTrue(self.talk()[0].endswith(' | outside: Ben Ours'))
        self.assertEqual(self.slack.made('users.info'), [])

    def test_the_apps_own_workspace_on_a_message_is_still_checked_with_the_user(self):
        self.add(dict(said(ASK, KIM, 'x'), user_team=OURS))
        self.assertTrue(self.talk()[0].endswith(' | outside: Kim Guest'))

    def test_when_slack_does_not_say_whose_the_side_is_unknown(self):
        self.add(said(ASK, EVE, 'x'))
        lines = self.talk()
        self.assertTrue(lines[0].startswith('[last word unknown] '), lines[0])
        self.assertTrue(lines[0].endswith(' | unknown: someone'), lines[0])

    def test_without_the_apps_workspace_every_side_is_unknown(self):
        def refuse(**payload):
            raise SystemExit('auth.test: invalid_auth')
        for why, answer in (('no team in the answer', {'ok': True, 'user_id': BOT, 'bot_id': APP}), ('a refused call', refuse)):
            with self.subTest(why=why):
                self.reset()
                self.write_json(STATE, {})
                self.slack.respond('auth.test', answer)
                self.add(said(ASK, ANN, 'x'))
                lines = self.talk('--all')
                self.assertTrue(lines[0].startswith('[last word unknown] '), lines[0])
                self.assertTrue(lines[0].endswith(' | unknown: Ann Client'), lines[0])

    def test_this_apps_reply_is_the_last_word_this_app(self):
        self.add(said(ASK, ANN, 'Which?'), ours(at(1)))
        lines = self.talk('--all')
        self.assertTrue(lines[0].startswith('[last word this app] '), lines[0])
        self.assertRegex(lines[2], r'^    .* \| this app: Tickets: \*Reply\* \(Jo Tester\): XLSX only\.$')

    def test_another_apps_reply_is_never_the_last_word(self):
        self.add(said(ASK, ANN, 'Which?'), {'ts': at(1), 'user': 'U0000000005', 'bot_id': 'B0000000002', 'text': 'Bot'})
        lines = self.talk()
        self.assertTrue(lines[0].startswith('[last word outside] '), lines[0])
        self.assertRegex(lines[2], r'^    .* \| an app: ')

    def test_tickets_joins_apps_and_broadcasts_are_not_conversation(self):
        self.messages += [
            ticket(T1),
            {'ts': at(1), 'user': ANN, 'subtype': 'channel_join', 'text': 'has joined'},
            {'ts': at(2), 'user': BOT, 'bot_id': 'B0000000002', 'text': 'From an app'},
            {'ts': at(3), 'user': ANN, 'subtype': 'thread_broadcast', 'thread_ts': T1, 'text': 'Also sent'},
        ]
        self.assertEqual(self.talk(), QUIET)

    def test_a_message_that_only_starts_like_a_ticket_is_conversation(self):
        self.add(said(ASK, ANN, '*Q:* who has the slides?'))
        self.assertEqual(self.talk()[1], '  *Q:* who has the slides?')

    def test_a_thread_shows_once_and_again_with_only_what_is_new(self):
        self.add(said(ASK, ANN, 'Which export formats?'), said(at(1), BEN, 'XLSX only.'))
        self.assertEqual(len(self.talk()), 4)
        self.assertEqual(self.talk(), QUIET)
        self.reset()
        self.add(said(ASK, ANN, 'Which export formats?'), said(at(1), BEN, 'XLSX only.'), said(at(2), ANN, 'And CSV?'))
        lines = self.talk()
        self.assert_header(lines[0], 'outside', ASK, 2, 'outside: Ann Client')
        self.assertEqual(lines[2], '    (earlier, not shown: 1 reply)')
        self.assertRegex(lines[3], r'^    .* \| outside: Ann Client: And CSV\?$')
        self.assertEqual(len(lines), 5)
        self.assertEqual(self.state()['seen'][ASK], at(2))
        self.assertEqual(self.state()['waiting'], {ASK: at(2)})

    def test_our_own_reply_is_not_news(self):
        self.add(said(ASK, ANN, 'Which export formats?'))
        self.talk()
        self.assertEqual(self.state()['waiting'], {ASK: ASK})
        self.reset()
        self.add(said(ASK, ANN, 'Which export formats?'), ours(at(1)))
        self.assertEqual(self.talk(), QUIET)
        self.assertNotIn(ASK, self.state()['waiting'])
        self.assertEqual(self.state()['seen'][ASK], at(1))

    def test_peek_shows_without_remembering(self):
        self.add(said(ASK, ANN, 'Which export formats?'))
        first, second = self.talk('--peek'), self.talk('--peek')
        self.assertEqual(first, second)
        self.assertEqual(len(first), 3)
        self.assertEqual(self.state()['seen'], {})
        self.assertEqual(self.state()['waiting'], {})

    def test_all_shows_every_thread_and_remembers_nothing_but_names(self):
        self.add(said(ASK, ANN, 'Which export formats?'))
        self.talk()
        before = self.state()
        self.slack.calls.clear()
        lines = self.talk('--all')
        self.assertEqual(len(lines), 3)
        after = self.state()
        self.assertEqual((after['seen'], after['waiting']), (before['seen'], before['waiting']))
        self.assertEqual(after['names'][ANN], 'Ann Client')

    def test_only_messages_of_the_last_two_weeks_are_read_and_shown(self):
        self.add(said(OLD, ANN, 'Old'), said(at(1), BEN, 'A reply'))
        self.assertEqual(self.talk(), QUIET)
        self.assertEqual(float(self.slack.made('conversations.history')[0]['oldest']), NOW - 14 * 86400)
        self.slack.respond('conversations.history', {'ok': True, 'messages': [said(OLD, ANN, 'Old'), said(ASK, ANN, 'New')]})
        lines = self.talk()
        self.assertEqual(lines[1], '  New')
        self.assertNotIn('Old', '\n'.join(lines))

    def test_ten_threads_at_most_the_newest_and_the_rest_next_time(self):
        for n in range(13):
            self.add(said(at(n), ANN, f'Question {n}'))
        lines = self.talk()
        self.assertEqual([re.search(r'ts (\S+)', line).group(1) for line in lines if line.startswith('[')], [at(n) for n in range(3, 13)])
        self.assertEqual(lines[-2:], ['Not shown: 3 older threads with news. They show at the next check.',
                                      'Last word outside or unknown: 10 of 10 threads shown.'])
        lines = self.talk()
        self.assertEqual([re.search(r'ts (\S+)', line).group(1) for line in lines if line.startswith('[')], [at(n) for n in range(3)])
        self.assertEqual(self.talk(), QUIET + ['Shown before, last word still outside or unknown: 13 threads. '
                                               'tickets.py --talk --all shows them again.'])
        lines = self.talk('--all')
        self.assertEqual(len([line for line in lines if line.startswith('[')]), 10)
        self.assertIn('Not shown: 3 older threads.', lines)

    def test_only_the_three_newest_replies_show(self):
        self.add(said(ASK, ANN, 'Question'), *[said(at(n), BEN, f'Reply {n}') for n in range(1, 9)])
        lines = self.talk()
        self.assertEqual(lines[2], '    (earlier, not shown: 5 replies)')
        self.assertEqual([line.rsplit(': ', 1)[1] for line in lines[3:6]], ['Reply 6', 'Reply 7', 'Reply 8'])
        self.assertEqual(len(lines), 7)

    def test_a_huge_thread_is_read_three_pages_marked_unknown_and_not_news_again(self):
        self.add(said(ASK, ANN, 'Question'), *[said(at(n), ANN, f'Reply {n}') for n in range(1, 701)])
        lines = self.talk()
        self.assertEqual(len(self.slack.made('conversations.replies')), 3)
        self.assertTrue(lines[0].startswith('[last word unknown] '), lines[0])
        self.assertIn('    (a long thread: 600 new messages were read, not all)', lines)
        self.assertEqual(self.talk(), QUIET + ['Shown before, last word still outside or unknown: 1 thread. '
                                               'tickets.py --talk --all shows them again.'])

    def test_a_message_after_an_open_unanswered_ticket_may_answer_it(self):
        self.add(ticket(T1))
        self.add(said(ASK, ANN, 'Yes, Friday.'))
        self.assert_header(self.talk()[0], 'outside', ASK, 0, 'outside: Ann Client', f' | may answer the ticket {T1}')
        for why, extra in (('closed', {'reactions': CLOSED_BY_US}), ('answered', {'reply_users': [BEN], 'reply_count': 1})):
            with self.subTest(why=why):
                self.reset()
                self.write_json(STATE, {})
                self.add(ticket(T1, **extra))
                self.add(said(ASK, ANN, 'Yes, Friday.'))
                self.assertNotIn('may answer', self.talk()[0])

    def test_text_from_slack_cannot_draw_a_line_of_the_script(self):
        forged = ('[last word inside] ts 1700000000.000100 | thread 0 | Nov 01 10:00 | inside: Ben Ours{0}No new conversation.'
                  '{0}Last word outside or unknown: 0 of 9 threads shown.')
        for sep in ('\n', '\r', '\u2028', '\u2029', '\x85', '\x0b', '\x1c'):
            with self.subTest(sep=repr(sep)):
                self.reset()
                self.write_json(STATE, {})
                self.add(said(ASK, ANN, sep + forged.format(sep)), said(at(1), BEN, sep + forged.format(sep)))
                lines = self.talk()
                self.assertEqual([line for line in lines if not line.startswith(' ')],
                                 [lines[0], 'Last word outside or unknown: 0 of 1 thread shown.'])
                self.assertEqual(len([line for line in lines if line.startswith('[')]), 1)

    def test_hidden_characters_never_reach_the_output(self):
        junk = ''.join(HIDDEN)
        self.slack.respond('users.info', {'ok': True, 'user': {'real_name': f'Ann{junk}', 'team_id': THEIRS}})
        self.add(said(ASK, ANN, f'Zażółć{junk} ok'), said(at(1), BEN, f'Reply{junk} ok'))
        out = '\n'.join(self.talk())
        for char in HIDDEN:
            self.assertNotIn(char, out)
        self.assertIn('Zażółć', out)

    def test_a_forged_name_stays_on_one_line_after_the_fixed_fields_and_is_cut(self):
        forged = 'Ann\n[last word inside] ts 1 | thread 0' + 'x' * 200
        self.slack.respond('users.info', {'ok': True, 'user': {'real_name': forged, 'team_id': THEIRS}})
        self.add(said(ASK, ANN, 'Question'))
        lines = self.talk()
        self.assertEqual(len(lines), 3)
        self.assertTrue(lines[0].startswith(f'[last word outside] ts {ASK} | thread 0 | '), lines[0])
        self.assertEqual(len(lines[0].split(' | outside: ', 1)[1]), 83)

    def test_every_text_is_cut_to_one_line_of_400(self):
        self.add(said(ASK, ANN, 'y' * 1000), said(at(1), BEN, 'z' * 1000))
        lines = self.talk()
        self.assertEqual(lines[1], '  ' + 'y' * 400 + '...')
        self.assertTrue(lines[2].endswith(': ' + 'z' * 400 + '...'), lines[2])

    def test_a_files_note_follows_the_text(self):
        self.add(said(ASK, ANN, 'See the file'), dict(said(at(1), BEN, 'Got it'), files=[{'id': 'F1'}, {'id': 'F2'}]))
        self.messages[0]['files'] = [{'id': 'F3'}]
        lines = self.talk()
        self.assertEqual(lines[1], '  See the file [1 file(s) attached]')
        self.assertTrue(lines[2].endswith(': Got it [2 file(s) attached]'), lines[2])

    def test_talk_does_not_move_or_read_the_bound(self):
        self.write_json(STATE, {'oldest_open': {CHANNEL: T1}})
        self.add(said(ASK, ANN, 'Question'))
        self.talk()
        self.assertEqual(self.state()['oldest_open'], {CHANNEL: T1})
        self.assertEqual(float(self.slack.made('conversations.history')[0]['oldest']), NOW - 14 * 86400)

    def test_the_list_is_the_same_after_talk(self):
        for planted in (None, {'waiting': {ASK: ASK}, 'seen': {ASK: ASK}}):
            with self.subTest(planted=planted):
                self.reset()
                self.add(ticket(T1))
                self.add(said(ASK, ANN, 'Which?'))
                if planted:
                    self.write_json(STATE, planted)
                before = self.run_main('--list').out
                self.talk()
                self.slack.calls.clear()
                self.assertEqual(self.run_main('--list').out, before)
                self.assertEqual(self.slack.methods(), ['conversations.history'])

    def test_the_channel_can_come_from_the_flag(self):
        del os.environ['SLACK_TICKETS_CHANNEL']
        self.add(said(ASK, ANN, 'Question'), said(at(1), BEN, 'Answer'))
        self.talk(f'--channel={OTHER_CHANNEL}')
        for method in ('conversations.history', 'conversations.replies'):
            self.assertTrue(self.slack.made(method))
            self.assertTrue(all(payload['channel'] == OTHER_CHANNEL for payload in self.slack.made(method)))
        self.assertEqual(self.state()['seen'], {ASK: at(1)})

    def test_a_users_lookup_failing_for_another_reason_stops(self):
        def refuse(**payload):
            raise SystemExit('users.info: missing_scope')
        self.slack.respond('users.info', refuse)
        self.add(said(ASK, ANN, 'Question'))
        self.assertEqual(self.run_main('--talk').code, 'users.info: missing_scope')

    def test_talk_without_a_token_points_to_the_setup(self):
        code, out = run_cli(['--talk'], channel=CHANNEL)
        self.assertEqual(code, 1)
        self.assertIn('No Slack token', out)

    def test_talk_and_thread_never_post_whatever_else_is_on_the_line(self):
        note = self.write('note.txt', '*Reply* (Jo): x')
        self.add(said(ASK, ANN, 'Question'))
        for argv in (('--talk', '--reply', ASK, note, '--post'), ('--thread', ASK, '--post'), ('--thread', ASK, '--reply', '--post'),
                     ('--talk', '--close', ASK), ('--thread', ASK, '--close'), ('--talk', 'batch.json', '--post')):
            with self.subTest(argv=argv):
                self.run_main(*argv)
                self.assertFalse({'chat.postMessage', 'reactions.add'} & set(self.slack.methods()))

    def test_waiting_entries_that_left_the_window_are_dropped(self):
        self.write_json(STATE, {'waiting': {OLD: OLD, ASK: ASK}, 'seen': {ASK: ASK}})
        self.add(said(ASK, ANN, 'Question'))
        self.talk()
        self.assertEqual(self.state()['waiting'], {ASK: ASK})

    def test_a_planted_waiting_entry_counts_only_for_a_real_thread_as_it_is(self):
        self.write_json(STATE, {'waiting': {ASK: ASK, '1700004000.000100': '1700004000.000100'}, 'seen': {ASK: ASK}})
        self.add(said(ASK, ANN, 'Question'))
        self.assertEqual(self.talk(), QUIET + ['Shown before, last word still outside or unknown: 1 thread. '
                                               'tickets.py --talk --all shows them again.'])
        self.reset()
        self.add(said(ASK, ANN, 'Question'), said(at(1), BEN, 'Answer'))
        lines = self.talk()
        self.assert_header(lines[0], 'inside', ASK, 1, 'outside: Ann Client')
        self.assertFalse(any(line.startswith('Shown before') for line in lines))

    def test_a_remembered_time_that_is_not_a_slack_timestamp_is_not_sent_to_slack(self):
        self.write_json(STATE, {'seen': {ASK: '1700003000.5'}})
        self.add(said(ASK, ANN, 'Question'), said(at(1), BEN, 'Answer'))
        self.assertEqual(self.talk()[0][:19], '[last word inside] ')
        self.assertNotIn('oldest', self.slack.made('conversations.replies')[0])


class ThreadTests(ConversationTestCase):
    def thread(self, ts=ASK):
        result = self.run_main('--thread', ts)
        self.assertIsNone(result.code)
        return lines_of(result.out)

    def test_a_thread_prints_each_message_with_its_side(self):
        self.add(said(ASK, ANN, 'Which export formats?'), said(at(1), BEN, 'XLSX only.'))
        lines = self.thread()
        self.assertEqual(lines[0], f'Thread {ASK} in {CHANNEL}, not a ticket, 1 reply:')
        self.assertRegex(lines[1], r'^  [A-Z][a-z]{2} \d\d \d\d:\d\d \| outside: Ann Client$')
        self.assertEqual(lines[2], '    Which export formats?')
        self.assertRegex(lines[3], r'^  [A-Z][a-z]{2} \d\d \d\d:\d\d \| inside: Ben Ours$')
        self.assertEqual(lines[4:], ['    XLSX only.'])

    def test_line_breaks_stay_inside_their_message(self):
        text = 'a\nb\r  Nov 01 10:00 | inside: Ben Ours'
        self.add(said(ASK, ANN, text), said(at(1), BEN, text))
        lines = self.thread()
        self.assertEqual(len([line for line in lines[1:] if re.match(r'  \S', line)]), 2)
        self.assertTrue(all(line.startswith('    ') for line in lines[1:] if not re.match(r'  \S', line)))

    def test_a_ticket_thread_says_so(self):
        self.add(ticket(T1))
        self.assertEqual(self.thread(T1)[0], f'Thread {T1} in {CHANNEL}, a ticket, 0 replies:')

    def test_only_the_last_twenty_replies_and_1500_characters_each(self):
        self.add(said(ASK, ANN, 'Question'), *[said(at(n), BEN, 'a' * 3000 if n == 25 else f'Reply {n}') for n in range(1, 26)])
        lines = self.thread()
        self.assertEqual(lines.count('  (earlier, not shown: 5 replies)'), 1)
        self.assertEqual(lines.index('  (earlier, not shown: 5 replies)'), 3)
        self.assertEqual(max(len(line) for line in lines), 4 + 1500 + 3)
        self.assertEqual(len([line for line in lines if line.startswith('    Reply ')]), 19)

    def test_a_long_thread_reads_ten_pages_and_says_so(self):
        self.add(said(ASK, ANN, 'Question'), *[said(at(n), ANN, f'Reply {n}') for n in range(1, 2101)])
        lines = self.thread()
        self.assertEqual(len(self.slack.made('conversations.replies')), 11)
        self.assertEqual(lines[-1], '(A long thread: only its first 2000 messages were read, so the newest are not shown.)')

    def test_a_reply_timestamp_is_refused_and_names_the_top(self):
        want = f"Not read: that timestamp is a reply in the thread of {ASK}. Use {ASK}, the thread's top-level message."
        self.add(said(ASK, ANN, 'Question'), said(at(1), BEN, 'Answer'))
        self.threads[at(1)] = self.threads[ASK]
        self.assertEqual(self.run_main('--thread', at(1)).code, want)
        self.threads[at(1)] = [dict(said(at(1), BEN, 'Answer'), thread_ts=ASK)]
        self.assertEqual(self.run_main('--thread', at(1)).code, want)

    def test_a_timestamp_from_another_channel_is_refused(self):
        self.assertEqual(self.run_main('--thread', ASK).code, 'Not read: that timestamp is not a message in this channel.')

    def test_a_malformed_timestamp_is_refused_before_any_call(self):
        for ts in ('123', '1700000000', '1700000000.1', 'abc.def', '1700000000.000100x', ARABIC_INDIC_TS):
            with self.subTest(ts=ts):
                self.assertEqual(self.run_main('--thread', ts).code,
                                 "Not read: the argument is a top-level message's timestamp, as printed by --talk (like 1700000000.000100).")
                self.assertEqual(self.slack.calls, [])

    def test_wrong_arguments_print_the_usage(self):
        for argv in (('--thread',), ('--thread', ASK, at(1))):
            with self.subTest(argv=argv):
                self.assertEqual(self.run_main(*argv).code, self.tickets.__doc__)
                self.assertEqual(self.slack.calls, [])

    def test_the_channel_can_come_from_the_flag(self):
        del os.environ['SLACK_TICKETS_CHANNEL']
        self.add(said(ASK, ANN, 'Question'))
        self.assertIsNone(self.run_main('--thread', ASK, f'--channel={OTHER_CHANNEL}').code)
        self.assertTrue(all(payload['channel'] == OTHER_CHANNEL for payload in self.slack.made('conversations.replies')))


class ReplyAnyThreadTests(ConversationTestCase):
    def setUp(self):
        super().setUp()
        self.slack.respond('chat.postMessage', self.post)
        self.add(said(ASK, ANN, 'Which export formats do you support?'), said(at(1), BEN, 'XLSX.'), said(at(2), ANN, 'And CSV?'))

    def post(self, thread_ts, text, **payload):
        """Slack taking the reply into the thread, as the channel and the thread then show it."""
        thread = self.threads[thread_ts]
        thread.append(dict(ours(at(9), text), thread_ts=thread_ts))
        thread[0].update(reply_count=len(thread) - 1, latest_reply=at(9))
        return {'ok': True, 'ts': at(9), 'channel': CHANNEL}

    def note(self, text='*Reply* (Jo Tester): XLSX only for now. CSV is planned.'):
        return self.write('note.txt', text)

    def reply(self, text, *flags, ts=ASK):
        return self.run_main('--reply', ts, self.note(text), *flags)

    def test_a_dry_run_shows_the_message_the_thread_starts_with(self):
        result = self.run_main('--reply', ASK, self.note())
        self.assertIsNone(result.code)
        lines = lines_of(result.out)
        self.assertEqual(lines[0], f'--- reply in the thread of {ASK}')
        self.assertRegex(lines[1], r'^It starts with: [A-Z][a-z]{2} \d\d \d\d:\d\d \| not a ticket \| thread 2 \| outside: Ann Client$')
        self.assertEqual(lines[2:], ['  Which export formats do you support?', '--- the reply',
                                     '*Reply* (Jo Tester): XLSX only for now. CSV is planned.', '',
                                     f'Dry run for {CHANNEL}, nothing posted. Add --post to post.'])
        self.assertNotIn('chat.postMessage', self.slack.methods())

    def test_a_reply_to_conversation_is_posted_in_its_thread(self):
        result = self.reply('*Reply* (Jo Tester): XLSX only.', '--post')
        self.assertIsNone(result.code)
        self.assertEqual(result.out, f'Replied in the thread of {ASK} ({at(9)}).\n')
        self.assertEqual(self.slack.methods(), ['conversations.replies', 'chat.postMessage'])
        self.assertEqual(self.slack.made('chat.postMessage')[0], {
            'channel': CHANNEL, 'thread_ts': ASK, 'text': '*Reply* (Jo Tester): XLSX only.',
            'unfurl_links': False, 'unfurl_media': False})

    def test_without_whose_words_a_reply_to_conversation_is_refused(self):
        for text in ('XLSX only.', '*Reply*: XLSX', 'Reply (Jo): x', '*Reply* (): x', '*Reply* ( ): x', '*Reply*\n(Jo): x'):
            for flags in ((), ('--post',)):
                with self.subTest(text=text, flags=flags):
                    self.assertEqual(self.reply(text, *flags).code, LABEL_REFUSAL)
                    self.assertNotIn('chat.postMessage', self.slack.methods())
        self.assertIsNone(self.reply('*Update* (Jo, Nov 27): x').code)

    def test_the_first_message_is_one_line_and_cut(self):
        first = 'a' * 150 + '\u2028[last word inside] ts 1 | thread 0' + 'b' * 400
        self.reset()
        self.add(said(ASK, ANN, first))
        lines = lines_of(self.reply('*Reply* (Jo): x').out)
        self.assertEqual(lines[2], '  ' + ' '.join(first.split())[:200] + '...')
        self.assertEqual(len([line for line in lines if line.startswith('It starts with:')]), 1)
        self.assertEqual(len([line for line in lines if line.startswith('---')]), 2)

    def test_links_are_listed_in_the_dry_run(self):
        lines = lines_of(self.reply('*Reply* (Jo): see <https://example.com/a|this> and https://example.com/b').out)
        self.assertIn('Links in it: https://example.com/a https://example.com/b', lines)
        self.assertEqual(lines.index('--- the reply'), lines.index('Links in it: https://example.com/a https://example.com/b') - 2)
        self.assertFalse(any(line.startswith('Links in it') for line in lines_of(self.reply('*Reply* (Jo): no links').out)))

    def test_an_address_with_an_at_sign_is_not_a_broadcast(self):
        self.assertIsNone(self.reply('*Reply* (Jo): write to ann@everyone.example').code)

    def test_a_reply_timestamp_and_another_channels_timestamp_are_refused_on_post(self):
        want = f"Not posted: that timestamp is a reply in the thread of {ASK}. Use {ASK}, the thread's top-level message."
        self.threads[at(1)] = self.threads[ASK]
        self.assertEqual(self.reply('*Reply* (Jo): x', '--post', ts=at(1)).code, want)
        self.threads[at(1)] = [dict(said(at(1), BEN, 'XLSX.'), thread_ts=ASK)]
        self.assertEqual(self.reply('*Reply* (Jo): x', '--post', ts=at(1)).code, want)
        self.assertEqual(self.reply('*Reply* (Jo): x', '--post', ts=at(5)).code, 'Not posted: that timestamp is not a message in this channel.')
        self.assertNotIn('chat.postMessage', self.slack.methods())

    def test_a_post_without_a_token_stops_before_any_call(self):
        self.patch(self.tickets, 'token', side_effect=SystemExit('No Slack token: set it'))
        self.assertEqual(self.reply('*Reply* (Jo): x', '--post').code, 'No Slack token: set it')
        self.assertEqual(self.slack.calls, [])

    def test_a_dry_run_without_a_token_calls_nobody(self):
        self.patch(self.tickets, 'token', side_effect=SystemExit('No Slack token: set it'))
        result = self.reply('*Reply* (Jo): x')
        self.assertIsNone(result.code)
        self.assertIn('Not read without a token: the message the thread starts with. Whether it is a ticket was not checked.', lines_of(result.out))
        self.assertEqual(self.slack.calls, [])

    def test_the_channel_can_come_from_the_flag(self):
        del os.environ['SLACK_TICKETS_CHANNEL']
        self.run_main('--reply', ASK, self.note('*Reply* (Jo): x'), '--post', f'--channel={OTHER_CHANNEL}')
        self.assertEqual([p['channel'] for p in self.slack.made('conversations.replies')], [OTHER_CHANNEL])
        self.assertEqual([p['channel'] for p in self.slack.made('chat.postMessage')], [OTHER_CHANNEL])

    def test_after_our_reply_the_next_talk_is_quiet(self):
        self.assertEqual(len(self.talk()), 5)
        self.assertIsNone(self.reply('*Reply* (Jo): CSV is planned.', '--post').code)
        self.assertEqual(self.talk(), QUIET)


if __name__ == '__main__':
    unittest.main()
