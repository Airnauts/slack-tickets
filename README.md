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

The skill is `/slack-tickets:ticket`. Claude also uses it on its own when a question for the client comes up. The
first thing the skill does in a session is read the list of open tickets from Slack, so Claude knows what is already
asked.

## Install

The repository is private, so git on your machine must be able to read it (an SSH key, or `gh auth login` followed by
`gh auth setup-git`).

```
/plugin marketplace add Airnauts/slack-tickets
/plugin install slack-tickets@airnauts
```

The repository is its own marketplace (named `airnauts`), so Claude Code pulls the plugin straight from it. If the
first command fails with a git error and you use HTTPS, not SSH, for GitHub, start Claude Code with
`CLAUDE_CODE_PLUGIN_PREFER_HTTPS=1` set.

To get updates automatically, open `/plugin`, go to Marketplaces, and turn auto-update on for `airnauts`. To update by
hand: `/plugin marketplace update airnauts`, then `/reload-plugins`.

### Other agents

Copy or symlink `skills/ticket` into the agent's skills folder. For Codex that is `.agents/skills/` in the project,
or `~/.agents/skills/` for every project.

## Set up Slack (once per workspace)

1. Go to https://api.slack.com/apps, choose "Create New App", then "From a manifest", pick the workspace, and paste
   [`slack-app-manifest.yaml`](slack-app-manifest.yaml), the file at the top of this repository.
2. Click "Install to Workspace". A workspace that requires approval for apps needs an admin here.
3. Copy the "Bot User OAuth Token" (it starts with `xoxb-`) from "OAuth & Permissions". Share it with teammates
   through a password manager, never through chat or git.
4. In the tickets channel, type `/invite @Tickets`.

One app serves every tickets channel in the workspace. Invite it to each one.

## Set up a project (once per project and person)

Add two variables to the project's `.claude/settings.local.json`. That file is personal and is not committed.

```json
{
  "env": {
    "SLACK_TICKETS_CHANNEL": "C0123456789",
    "SLACK_TICKETS_TOKEN": "xoxb-..."
  }
}
```

- The channel id is at the bottom of the channel's "About" panel in Slack.
- To keep the token out of files, leave `SLACK_TICKETS_TOKEN` out and store it in the macOS Keychain:
  `security add-generic-password -U -s slack-tickets -a slack -w` (it asks for the token without showing it).

Another agent has no such file: export the same two variables in the shell it starts from.

Start a new Claude Code session and ask "check the tickets setup". Claude runs the check and says which channel and
which app it will post as.

## The register of client documents (optional)

A project with many client documents can keep a register of them, so Claude compares new material against the current
ones. Put it at `.claude/slack-tickets/sources.md` in the project, or at `~/.claude/slack-tickets/<channel id>/sources.md`
to keep it on your machine. A template is in
[`skills/ticket/assets/sources-template.md`](skills/ticket/assets/sources-template.md).

## The script

Claude runs it for you. By hand, with the two variables set:

```
python3 skills/ticket/scripts/tickets.py --check               which channel, whose token
python3 skills/ticket/scripts/tickets.py --list                one line per open ticket
python3 skills/ticket/scripts/tickets.py batch.json            dry run
python3 skills/ticket/scripts/tickets.py batch.json --post     post the batch
python3 skills/ticket/scripts/tickets.py --answers             new replies since the last check
python3 skills/ticket/scripts/tickets.py --answers --all       every ticket with every reply
python3 skills/ticket/scripts/tickets.py --reply <ts> note.txt our own update in a ticket's thread (dry run; add --post)
python3 skills/ticket/scripts/tickets.py --close <ts>          mark a ticket closed
```

It needs Python 3 and nothing else. It remembers which replies it has shown in
`~/.claude/slack-tickets/<channel id>/state.json`.

## Developing

```
claude --plugin-dir ~/Projects/slack-tickets      load the plugin from this folder
claude plugin validate ~/Projects/slack-tickets   check the manifests
```

There is no `version` in the manifests on purpose: every commit pushed counts as an update.
