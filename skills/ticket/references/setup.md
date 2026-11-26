# Setting up the tickets

These steps connect the `ticket` skill to Slack. Ask an agent that has the skill to "set up the tickets" and it leads
you through them, one step at a time. You can also follow them by hand.

`tickets.py` below is `scripts/tickets.py` in the skill's folder, run with `python3`. The agent runs it for you.

In the end three things are in place:

- a Slack app in the workspace, invited to the tickets channel;
- the app's bot token on your machine: in the macOS Keychain (service `slack-tickets`), or in the variable
  `SLACK_TICKETS_TOKEN`;
- the channel's id: given for one session with `--channel=<id>`, or set for good in `SLACK_TICKETS_CHANNEL`.

The token is a password. Never paste it into a chat with an agent, a Slack message, a ticket or git. An agent never
asks you for it and never stores it for you: you store it yourself, in your own terminal.

## 1. The channel

Pick the Slack channel the tickets go to. Its id is at the bottom of the channel's "About" panel in Slack (click the
channel's name at the top). It starts with C or G, like C0123456789. Give the id to the agent: it uses it for this
session with `--channel=<id>`. If the project already has `SLACK_TICKETS_CHANNEL` set, skip this step and leave
`--channel=<id>` out of every command below.

## 2. What is missing

Run `tickets.py --check --channel=<id>`.

- `No Slack token`: go on with step 3.
- `Posting as ... (a bot)`: the token is in place. Go to step 6.
- Anything else: see "If a check fails" below.

## 3. The Slack app

One app serves every tickets channel in a workspace, so the workspace may have it already. Ask whoever set up tickets
for another project, or look for "Tickets" among the apps in Slack.

- **The app exists.** Ask that person for its bot token through a password manager, never through chat. Go to step 4.
- **There is none.** Create it:
  1. Go to https://api.slack.com/apps, choose "Create New App", then "From a manifest", and pick the workspace.
  2. Paste the Slack app manifest and create the app. The agent shows the manifest; in the skill's folder it is
     `assets/slack-app-manifest.yaml`.
  3. Click "Install to Workspace". A workspace that requires approval for apps needs an admin here. This step is done
     when the app is installed.
  4. On "OAuth & Permissions", copy the "Bot User OAuth Token". It starts with `xoxb-`. Share it with teammates
     through a password manager.

## 4. Store the token

On a Mac, in your own terminal, not through the agent:

```
security add-generic-password -U -s slack-tickets -a slack -w
```

It asks for the token without showing it. Paste it and press Enter. `-U` replaces a token stored before. The script
finds it there in every project and every session, with nothing else to set.

Not on a Mac: in Claude Code, put the token in `.claude/settings.local.json` yourself (step 7 shows the file) and
start a new session. With another agent, see "Other agents" below.

## 5. Invite the app

In the tickets channel, type `/invite @Tickets` (or the app's name, if someone changed it). Do it in each tickets
channel.

## 6. Check

Run `tickets.py --check --channel=<id>`, then `tickets.py --list --channel=<id>`. Both work in the same session.
The first ends with "(a bot)". The second starts with `Channel <id>:`. Then the tickets work, and the agent keeps
`--channel=<id>` for the rest of the session.

## If a check fails

- `No Slack token`: the token is not stored, or not under `slack-tickets`. Step 4.
- `auth.test: invalid_auth`: the token is wrong or cut short. Copy it again (step 3) and store it again (step 4).
- `auth.test: token_revoked` or `account_inactive`: the app was removed or its token replaced. Get the current token
  (step 3) and store it (step 4).
- `(a person)` instead of `(a bot)`: that is a user token. Take the "Bot User OAuth Token" (step 3), then step 4.
- `not_in_channel`: the app is not in the channel. Step 5.
- `channel_not_found`: the id is wrong (step 1), or the channel is private and the app is not in it yet (step 5).
- `the app needs one of the scopes`: the app was not made from this manifest. On the app's "App Manifest" page, paste
  the manifest, save, then click "Reinstall to Workspace". Check again.
- `Slack could not be reached`: no network access to `slack.com`. See "Other agents" below.
- `SLACK_TICKETS_CHANNEL is set, but not to a channel id`: correct it where it is set (step 7).
- `--channel names one channel`: the project has a channel set already. Leave `--channel=<id>` out.

## 7. For good (optional)

The id given in step 1 lasts one session. To keep it, add it yourself to the project's `.claude/settings.local.json`
in Claude Code. Create the file if there is none; if it has an "env" already, add the line there. The file is
personal: check that git ignores it.

```json
{
  "env": {
    "SLACK_TICKETS_CHANNEL": "C0123456789"
  }
}
```

A new session picks it up. The token can go there too, as `"SLACK_TICKETS_TOKEN": "xoxb-..."`, but the Keychain
keeps it out of files.

## Other agents

An agent other than Claude Code reads the two variables from the shell it was started from. In that shell, before
starting the agent:

```
export SLACK_TICKETS_CHANNEL=C0123456789
```

On a Mac the token can stay in the Keychain (step 4). Elsewhere, set it in the same shell without showing it or
keeping it in the history: `read -rs SLACK_TICKETS_TOKEN && export SLACK_TICKETS_TOKEN`, then paste it and press
Enter. Keep the token out of your shell profile. An agent started before the variables were set does not see them:
start it again and run the check (step 6) in the new session.

The script calls `slack.com`, so the agent's sandbox has to allow network access. Codex blocks it by default, and the
script then says "Slack could not be reached". Where the agent can limit it, allow `slack.com` only.
