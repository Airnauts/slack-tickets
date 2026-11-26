# slack-tickets

An agent skill for asking a client questions through a Slack channel. It ships as a Claude Code plugin, and
`skills/ticket` follows the open [Agent Skills](https://agentskills.io) format, so other agents that read it can use
it too.

- One message per question: the question, an urgency, who asked, our own decision, a short context. Nobody is tagged;
  a reviewer tags the right person in the thread.
- The details go in the first reply of the thread.
- Claude drafts a batch, shows it, and posts it on one go. A script checks the channel for replies and prints only what
  is new.
- When a new document from the client contradicts an earlier one, Claude proposes a ticket for each conflict.
- A decision we make after a ticket is posted is added to that ticket's thread, so the thread stays the record.

The skill is `/slack-tickets:ticket`. Claude also uses it on its own when a question for the client comes up. Each
time the skill loads in Claude Code it reads the list of open tickets from Slack, so Claude knows what is already
asked. Another agent runs the same command as its first step.

## Install

```
/plugin marketplace add Airnauts/slack-tickets
/plugin install slack-tickets@airnauts
```

The repository is its own marketplace (named `airnauts`), so Claude Code pulls the plugin straight from it. If the
first command fails with a git error, for example because you have no SSH key for GitHub, start Claude Code with
`CLAUDE_CODE_PLUGIN_PREFER_HTTPS=1` set.

To get updates automatically, open `/plugin`, go to Marketplaces, and turn auto-update on for `airnauts`. To update by
hand: `/plugin marketplace update airnauts`, then `/reload-plugins`.

### Other agents

Copy or symlink `skills/ticket` into the agent's skills folder. For Codex that is `.agents/skills/` in the project,
or `~/.agents/skills/` for every project.

The setup steps say what such an agent needs as well: the variables in the shell it starts from, and network access
to `slack.com`.

## Set up

Ask Claude, or your agent, to "set up the tickets". It leads you through the steps one at a time, shows the Slack app
manifest for you to copy, and checks the result in the same session. It never asks for the token: you store it
yourself, from your own terminal. The steps are in [`skills/ticket/references/setup.md`](skills/ticket/references/setup.md),
and the manifest is [`skills/ticket/assets/slack-app-manifest.yaml`](skills/ticket/assets/slack-app-manifest.yaml).

In short: once per workspace, someone creates the Slack app from the manifest and shares its bot token through a
password manager. Once per person, the token goes into the macOS Keychain. The app is invited to each tickets
channel, and each project gets its channel's id, for one session or for good in `.claude/settings.local.json`.

## Without the channel id or the token

The skill still works with less set up, for a question or two:

- **No channel id.** Claude asks which channel the tickets go to, once per session, and passes it to the script with
  `--channel=<id>`. It never picks a channel itself. The flag only works in a project that has no channel set.
- **No token.** With a Slack connector in the session, Claude reads and posts through it, under your own name and one
  message at a time. In a channel shared with another organization the connector cannot send, so Claude creates one
  draft at a time and you send each from "Drafts & Sent" in Slack.
- **Neither a token nor a connector.** Claude says what is missing and offers to lead you through the setup.

For more than a couple of tickets, set the token up: the script posts a whole reviewed batch in one run and remembers
which replies it has shown.

## The register of client documents (optional)

A project with many client documents can keep a register of them, so Claude compares new material against the current
ones. Put it at `.claude/slack-tickets/sources.md` in the project, or at `~/.claude/slack-tickets/<channel id>/sources.md`
to keep it on your machine. A template is in
[`skills/ticket/assets/sources-template.md`](skills/ticket/assets/sources-template.md). Claude gets it with
`tickets.py --sources-template`. Claude reads it with `tickets.py --sources`. That command needs no go from you, also for
the register in your home folder. It prints at most 1 MB, and nothing when the register or its folder is a link. In a
git worktree it also finds a register that is only in the main checkout.

## A channel that is not only tickets

A ticket is a top-level message that starts with `*Q:` and has an `Urgency:` or an `Asked by:` field, bold or not.
Older tickets have a plain `Urgency:` line and no "Asked by", and still count. A message that only starts like a ticket
is left out, and `--list` and `--answers` say how many there were.

## The script

Claude runs it for you. By hand, with the two variables set (`--setup` needs neither):

```
python3 skills/ticket/scripts/tickets.py --check               which channel, whose token
python3 skills/ticket/scripts/tickets.py --setup               the setup steps and the Slack app manifest
python3 skills/ticket/scripts/tickets.py --sources-template    the template for the register of client documents
python3 skills/ticket/scripts/tickets.py --sources             the register of client documents, if there is one
python3 skills/ticket/scripts/tickets.py --list                one line per open ticket
python3 skills/ticket/scripts/tickets.py batch.json            dry run
python3 skills/ticket/scripts/tickets.py batch.json --post     post the batch
python3 skills/ticket/scripts/tickets.py --answers             new replies since the last check
python3 skills/ticket/scripts/tickets.py --answers --all       every ticket with every reply
python3 skills/ticket/scripts/tickets.py --reply <ts> note.txt our own update in a ticket's thread (dry run; add --post)
python3 skills/ticket/scripts/tickets.py --close <ts>          mark a ticket closed
python3 skills/ticket/scripts/tickets.py --list --channel=C0123456789   a channel for one run, when none is set
```

In Claude Code the skill lets only the commands that post nothing to Slack run without asking: `--list`,
`--answers`, `--check`, `--setup`, `--sources-template` and `--sources`. A dry run, a post, a reply, a close, and
anything with `--channel=<id>` ask you first. When Claude Code asks, answer yes for that one command. "Don't ask
again" saves a rule that covers every `tickets.py` command, a post included. Your own permission rules come before the
skill's: a rule of yours that allows every `python3` command makes all of them run without asking.

It needs Python 3 and nothing else. It remembers which replies it has shown in `.slack-tickets/state.json` in the
project, a folder it creates and keeps out of git. Git worktrees share the main checkout's file.

An agent whose sandbox may not write to the main checkout keeps its own copy in its worktree, so a reply repeats once
per worktree at most. To share it, add the main checkout's `.slack-tickets` folder to the folders the sandbox may
write.

## Developing

```
claude --plugin-dir ~/Projects/slack-tickets      load the plugin from this folder
claude plugin validate ~/Projects/slack-tickets   check the manifests
```

There is no `version` in the manifests on purpose: every commit pushed counts as an update.

Run the tests with:

```
python3 -m unittest discover -s tests
```

They never call Slack. A run that checks whether an agent follows the skill costs tokens and is run by hand, see
[`tests/agents/README.md`](tests/agents/README.md).

`tests/description/` checks whether the skill's description gets it called: a set of prompts and a runner that starts
real sessions, so it is run by hand. See `tests/description/README.md` before changing the description.

## License

MIT, see [LICENSE](LICENSE).
