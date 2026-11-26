# Agent runs

These runs check whether an agent follows the skill's text. They are not part of `python3 -m unittest discover -s tests`.
Each one starts a real agent, which costs tokens, and the agent's answer differs from run to run. So run them by hand,
after you change `skills/ticket/SKILL.md`, and read the summary yourself. Nothing here passes or fails on its own.

Each run makes a scratch project with `mktemp -d`, runs the agent there, and prints a short summary of what it did
(`summarise.py`: the tool calls, what was refused, the last text, and any channel id that is not a dummy). The full
output stays in the scratch folder, whose path is printed at the end.

## Claude Code

```
tests/agents/run-claude.sh <case>
```

The plugin is loaded from this repository with `--plugin-dir`. Set `AGENT_MODEL` to use another model than `sonnet`.

| Case | Setup | What it should show |
| --- | --- | --- |
| `nochannel` | no channel variable, no token | The skill loads and its list says no channel is set. The agent asks which channel the tickets go to before it drafts, and does not pick one itself. Nothing is posted. |
| `list` | channel named in the prompt, no variable, no token | The agent passes `--channel=C0000000000` to every script command. The script stops at "No Slack token", and the agent carries on through the connector's read tools or says what is missing. It never tries a write. |
| `post` | channel named in the prompt, no variable, no token | The agent writes a batch, shows the dry run, and sends through the connector, saying it goes out under the user's own name. It never runs `--post` on the script. The send is attempted, and the dummy channel makes it fail. |
| `setlist` | channel variable set, no token | As `list`, without the `--channel` flag. |
| `setpost` | channel variable set, no token | As `post`, without the `--channel` flag. |

## Codex

```
tests/agents/run-codex.sh
```

One case, `nochannel`, as above. The skill has to be visible in the scratch project, so the script links
`skills/ticket` into `<scratch>/.agents/skills/ticket`. Codex blocks the network in its default sandbox, which is fine
here: the agent should stop at the missing channel and ask, and it should not run any command with a channel id in it.

## Safety rules

Keep these when you change a script or add a case.

- No Slack token anywhere: `SLACK_TICKETS_TOKEN` is always removed from the environment. The script falls back to the
  macOS Keychain entry `slack-tickets`, and the agent keeps your PATH, so run these on a machine with no such entry
  (or delete it first). Otherwise a real token is read and the dummy channel id is sent to Slack.
- Dummy channel ids only (`C0000000000`, `C0123456789`, `C1111111111`, `C2222222222`). `summarise.py` lists any other id
  it finds in a tool call.
- Claude Code runs in `--permission-mode default`, with only the skill and `Write` allowed, so nothing that needs
  approval can run.
- The Slack connector's write and search tools are disallowed in every case that does not need to see them attempted.
  `post` and `setpost` leave the writes open on purpose, to see whether the agent tries one. They are the only cases to
  run in a session whose connector you are content to see called, and the dummy id makes the send fail.
- The environment is passed as `/usr/bin/env -u SLACK_TICKETS_TOKEN <variable setting> claude ...`, so the setting
  applies to the agent and nothing leaks from the shell.
- Scratch projects and outputs live under `mktemp -d`. Never write into this repository, a real project or a real
  channel.
