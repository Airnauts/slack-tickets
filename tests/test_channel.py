"""--channel=<id> and the channel rules, checked through the command line.

Each run has an empty PATH and no token, so the script stops before it could call Slack."""
import os
import unittest

from helpers import CHANNEL, OTHER_CHANNEL, THIRD_CHANNEL, TicketsTestCase, run_cli

TOP = '*Q: Test?*\n*Urgency:* No rush · *Asked by:* Test'


class ChannelTestCase(TicketsTestCase):
    def batch(self, **extra):
        return self.write_json('batch.json', {**extra, 'tickets': [{'id': 't', 'top': TOP, 'details': '*Details*\nx'}]})


class ChannelFlagTests(ChannelTestCase):
    def test_a_flag_is_accepted_when_the_project_has_no_channel(self):
        code, out = run_cli(['--list', f'--channel={CHANNEL}'])
        self.assertIn('could not be read: No Slack token', out)
        self.assertNotIn('channel id', out)

    def test_a_flag_that_is_not_an_id_is_refused(self):
        code, out = run_cli(['--list', '--channel=general'])
        self.assertIn('is not set to a channel id', out)
        self.assertNotIn('No Slack token', out)

    def test_another_flag_is_refused_when_the_project_has_a_channel(self):
        code, out = run_cli(['--list', f'--channel={CHANNEL}'], channel=OTHER_CHANNEL)
        self.assertIn('--channel names one channel, and only for a project that has none set.', out)

    def test_the_same_flag_is_accepted_when_the_project_has_that_channel(self):
        code, out = run_cli(['--list', f'--channel={OTHER_CHANNEL}'], channel=OTHER_CHANNEL)
        self.assertIn('could not be read: No Slack token', out)
        self.assertNotIn('--channel names one channel', out)

    def test_the_message_without_a_channel_names_the_flag(self):
        code, out = run_cli(['--list'])
        self.assertIn('or name the channel for one run with --channel=<id>.', out)

    def test_a_dry_run_with_the_flag_names_that_channel(self):
        code, out = run_cli([self.batch(), f'--channel={CHANNEL}'])
        self.assertEqual(code, 0)
        self.assertEqual(out.splitlines()[-1], f'Dry run: 1 ticket for {CHANNEL}, nothing posted. Add --post to post.')
        self.assertFalse(os.path.exists(os.path.join(self.tmp, 'batch.result.json')))

    def test_a_variable_that_is_not_an_id_is_never_printed(self):
        secret = 'xoxb-dummy-secret'
        code, out = run_cli(['--list', f'--channel={CHANNEL}'], channel=secret)
        self.assertIn('is set, but not to a channel id', out)
        self.assertNotIn(secret, out)

    def test_two_different_flags_are_refused(self):
        code, out = run_cli(['--list', f'--channel={CHANNEL}', f'--channel={OTHER_CHANNEL}'])
        self.assertIn('--channel names one channel', out)

    def test_the_project_channel_and_two_flags_are_refused(self):
        code, out = run_cli(['--list', f'--channel={OTHER_CHANNEL}', f'--channel={CHANNEL}'], channel=OTHER_CHANNEL)
        self.assertIn('--channel names one channel', out)

    def test_a_batch_that_names_another_channel_is_refused(self):
        code, out = run_cli([self.batch(channel=THIRD_CHANNEL)], channel=OTHER_CHANNEL)
        self.assertNotEqual(code, 0)
        self.assertEqual(out.splitlines()[-1],
                         'Not posted: the batch names another channel. Take "channel" out of the batch.')

    def test_check_names_the_channel_before_the_token_error(self):
        code, out = run_cli(['--check'], channel=OTHER_CHANNEL)
        self.assertNotEqual(code, 0)
        self.assertTrue(out.startswith(f'Channel {OTHER_CHANNEL}.\n'), out)
        self.assertIn('No Slack token', out)


class BatchChannelFieldTests(ChannelTestCase):
    """The batch's own "channel" field, in a dry run with the project's channel set."""

    def dry_run(self, batch):
        return run_cli([self.batch(**batch)], channel=OTHER_CHANNEL)

    def test_an_empty_null_same_or_zero_channel_is_accepted(self):
        for value in ('', None, OTHER_CHANNEL, 0):
            with self.subTest(channel=value):
                code, out = self.dry_run({'channel': value})
                self.assertEqual(code, 0, out)
                self.assertIn(f'Dry run: 1 ticket for {OTHER_CHANNEL}, nothing posted.', out)

    def test_another_channel_is_refused(self):
        code, out = self.dry_run({'channel': THIRD_CHANNEL})
        self.assertNotEqual(code, 0)
        self.assertIn('Not posted: the batch names another channel.', out)
        self.assertNotIn('Dry run', out)


if __name__ == '__main__':
    unittest.main()
