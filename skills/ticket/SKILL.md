---
name: ticket
description: "Ask a client a question through the project's Slack tickets channel: one message per question with nobody tagged, an urgency, our own decision and a plain-language context, details in the thread. Posts a reviewed batch and checks for replies with a script. Use when the user says 'ticket', 'ask the client', 'post it to the tickets channel', 'what is still unanswered', 'check the tickets', 'any replies', or when work is blocked on a decision, approval or fact that only the client can give. ALSO use, without being asked, whenever a contradiction turns up: after reading a new document, brief, artifact, message or piece of feedback from the client, if it conflicts with an earlier one, with approved wording, with what is built, or with an assumption we are working on, propose a ticket for each conflict. Not for questions to our own team, and not for status updates or announcements."
allowed-tools: Bash(python3 ${CLAUDE_SKILL_DIR}/scripts/tickets.py *)
---

# Tickets

A ticket is one question to the client, posted in the project's tickets channel in Slack. The channel is a list of open
questions: each top-level message is one question, and everything else about it lives in its thread. **Nobody is tagged
in a ticket**: someone reviews each new ticket and tags the right person in its thread.

## The channel right now

Read from Slack when this skill loaded:

!`python3 ${CLAUDE_SKILL_DIR}/scripts/tickets.py --list`

Use this list to answer "what is open", to spot a duplicate before drafting, and to find a ticket's `ts`. It has
no reply texts: for those run `tickets.py --answers`. It is a snapshot; run `tickets.py --list` again when a long
session has posted or closed tickets since. If the lines above say the list could not be read, or that shell
commands are disabled, do the setup check below before anything else.

## Setup check

The script is `python3 ${CLAUDE_SKILL_DIR}/scripts/tickets.py`. It reads two environment variables, set under `env` in
the project's `.claude/settings.local.json`:

- `SLACK_TICKETS_CHANNEL`: the channel's id.
- `SLACK_TICKETS_TOKEN`: the Slack app's bot token. (Without it the script reads the macOS Keychain, service `slack-tickets`.)

When the list above could not be read, run `tickets.py --check`. It names the channel and whose token it is. If it
reports something missing, tell the user what, point them at the setup steps in `${CLAUDE_PLUGIN_ROOT}/README.md` and at the Slack app
manifest, `${CLAUDE_PLUGIN_ROOT}/slack-app-manifest.yaml`, and stop: do not set a token up for them, do not ask
them to paste one into the chat, and never print the environment (`env`, `printenv`, `echo $SLACK_TICKETS_TOKEN`).

## Where a project's data lives

**Never write anything into this skill's or the plugin's own folder.** It is an installed copy that every update
replaces, and it is shared by every project. A project's data has two homes, and nothing else:

- the tickets channel itself, which is the list of what was asked and answered (loaded at the top of this skill;
  `tickets.py --answers --all` for the full threads);
- the project's register of client documents, described under "When a contradiction is found".

Do not keep a log of posted tickets anywhere: the channel is that log. Batch files and reply notes are scratch
files, written to a temporary folder and not kept.

## A ticket's two parts

**The top-level message** stays short, so the channel reads as a list:

```
*Q: <the question, one sentence, ending with a question mark>*
*Urgency:* <level> · *Asked by:* <the reporter's name>
*Our decision:* <what we will do> | none yet, we need yours
*Context:* <one or two plain sentences>
*Source:* <the client's own document or artifact, by name and section>   (only when the question comes from one)
```

**The first reply in its thread** carries the rest, under a first line `*Details*`: what led to the question, the
options and what each one means, the exact words when the question is about wording, links.

Both are Slack mrkdwn, not Markdown: `*bold*` with single asterisks, `•` for bullets, `<https://address|words>` for a
link, a plain line break between fields.

**What is bold.** The question, whole, and every label up to and including its colon; never the text after a label.
At the top the labels are the five above. In the Details and in any reply of ours, a label is the short name that
opens a line or a bullet and says what follows: `• *Option A:* release first`, `• *Ours:* ...`, `• *Yours:* ...`,
`• *Today:* ...`. A bullet that is simply a sentence has no label and no bold.

**Pull requests and issues are links.** Wherever the Details or a reply names one of our pull requests or issues,
the words are the link: `• *Ours:* <https://github.com/acme/app/pull/882|pull request 882>.` Take the address from
`gh pr view <number> --json url` (or the issue tracker), never build it from a guess.

### The fields

- **Q.** One question that can be answered with yes or no, a choice between named options, or one fact. Two questions
  are two tickets. If the answer needs options, name them (A, B) in the question or the context.
- **No mention anywhere**, not at the top and not in the Details: a reviewer routes the ticket by tagging someone in
  the thread. To help them, the Details may say in plain words whose answer is needed ("the answer should come from
  counsel", "this is about pricing"), as a role or a subject. The script refuses a batch that mentions anyone.
- **Asked by.** The person the question comes from, as a plain name, never a mention. Tickets are posted by the
  Slack app, so without this line the client cannot tell who is asking or who to come back to. It is the user of
  this session unless they name someone else: take the name from `git config user.name`, and ask once if that is
  empty or not a person's name. The script refuses a ticket without it.
- **Urgency.** One of three, in these words:
  - `🔴 Blocking`: something cannot ship or go live until this is answered. Say what, and the date if there is one.
  - `🟠 This week`: named work is waiting on the answer this week.
  - `🟢 No rush`: we carry on without it for now.

  Pick the lower level when unsure, and never raise it to get attention. A default that lets us carry on means "No rush".
- **Our decision.** What we would do, written as a default the reader can simply accept: "We will keep the current
  wording unless you say otherwise." Add "by <date>" only when the user set that date. If we have no view, say
  `none yet, we need yours`. Never present a default as already decided by the client.
- **Context.** Written for someone who does not read code and may not know the feature: what a customer or the team
  sees today, and why the answer matters. No more than two sentences.
- **Source.** When the question comes from one of the client's own documents, artifacts or messages, name it the way
  its author would ("your Nov 20 test brief, item 2.4"). Put web addresses in the Details, not at the top.

### How to write it

- Plain words for a non-technical reader. In the top-level message: no pull request numbers, issue ids, file paths,
  setting names, code names or internal rule numbers. Our own links and ids belong in the Details, as links.
- Say what happens to a customer, not how the code works.
- Quote wording exactly, in quotation marks, when the question is about wording. Keep the client's own approved words
  word for word.
- No customer's personal data, health details, phone numbers or email addresses, and no secrets.
- No long dashes. Short sentences.
- Never post a list of ideas, a status report or internal discussion. One question per ticket.

### Example

```
*Q: May the text reminder page show a different sample message than the one registered with the carrier, for a few days?*
*Urgency:* 🟢 No rush · *Asked by:* Jane Smith
*Our decision:* We will update the registration right after the release, unless you want it done first.
*Context:* The public page that describes the text reminders shows sample messages. The next release changes one of them, so for a short time the page and the registration would not match.
```

```
*Details*
• *Today:* the page shows "<old sample>". After the release: "<new sample>".
• *Option A:* release first, then update the registration (a few days of mismatch).
• *Option B:* update the registration first and wait for it before the release.
• *Ours:* <https://github.com/acme/app/pull/882|pull request 882>.
• The answer should come from whoever looks after the registration.
```

## When a contradiction is found

A client sends many documents, and they do not always agree. A project may keep a register of them, with their dates,
links, status and who decides what. Look for it at `${CLAUDE_PROJECT_DIR}/.claude/slack-tickets/sources.md`, then at
`~/.claude/slack-tickets/<channel id>/sources.md`. If neither exists and the project has more than a couple of client
documents, offer to start one from `${CLAUDE_SKILL_DIR}/assets/sources-template.md`. Add a row for every new document
the moment it arrives. The register holds the client's documents, who decides what, and questions deliberately
held back or settled without a ticket. It does not list posted tickets.

Whenever new material from the client is read (a brief, an artifact, a document, a Slack message, feedback), compare
it with what came before: the register's current documents, earlier messages, the approved wording in use, what is
built, and the assumptions the current work rests on. Each conflict is a candidate ticket. Do not pick a side silently
and do not cite one document as the requirement.

1. List the conflicts found for the user first, one line each: what the new material says, what it collides with, and
   what depends on it. The user chooses which become tickets.
2. One ticket per conflict. The question asks which one holds: "Which is right: A (<source, date>) or B (<source, date>)?"
3. Our decision: what we do until the answer comes. The usual default is that the approved or already live version
   stays; say so. If the newer one should win in our view, say that and why in one clause.
4. Context: where each version shows up for a customer or the team.
5. Details: both passages quoted exactly, each with its source, author and date, and what changes under A and under B.

An assumption of ours that the new material contradicts is asked the same way, with our assumption named as ours.

## Posting

1. **Collect** the fields. Take what the conversation already holds; ask the user only for what is missing. The
   urgency is the user's to confirm when it was not stated.
2. **Check for a duplicate** against the list of open tickets at the top of this skill. If one already asks the same
   thing, propose a reply in its thread instead. Check the register's held-back questions too, if it has one.
3. **Write the batch** as a JSON file in a scratch folder (never in the plugin or the repo):
   `{"tickets": [{"id": "short-slug", "top": "...", "details": "..."}]}`.
4. **Dry run**: `tickets.py <batch.json>` prints every ticket as it will be posted. Show that to the user.
5. **On the user's go for the batch shown**, run `tickets.py <batch.json> --post`. One go covers the batch; a changed
   text needs a new dry run and a new go. The script writes `<batch>.result.json` with each ticket's timestamp and
   link. A second run skips what is already posted, so a failure halfway is safe to repeat.
6. **Report** each ticket's link, and note it where the open question lives (the issue, the spec, the pull request),
   so the answer can find its way back.

Post the most urgent first. Tickets appear under the Slack app's name, which is why each one says who asked.

## Checking for answers

- `tickets.py --answers`: the replies that arrived since the last check, per ticket, and how many tickets are open.
  "No new replies." means stop there. This is cheap; prefer it to reading the channel any other way.
- `tickets.py --answers --all`: every ticket with every reply.
- `tickets.py --answers --peek`: as `--answers`, without remembering what was shown.
- `tickets.py --close <ts>`: the check mark on a ticket whose answer is recorded (the `ts` is printed beside each).

It skips each ticket's own Details reply and shows names. Then:

1. Report per ticket with news: the question in a few words, who asked, who replied or was tagged, and whether it
   is answered.
   Lead with the blocking ones.
2. For an answered ticket: quote the answer, say what it changes, and propose where to record it (the issue, the doc,
   the code). Record only what the person wrote; an ambiguous answer gets a follow-up question in the same thread, on
   the user's go.
3. When the answer is recorded, close the ticket with `--close <ts>`.
4. A ticket with no answer is never nudged without the user's go. A nudge is a reply in the thread, not a new ticket.

## Our own decisions after a ticket is posted

A ticket's thread is the record of that question. **Whatever we decide about it after it was posted goes into its
thread**, so the client reads the current state there and nobody answers a question that has moved on. This covers:

- we went ahead with the default the ticket announced, or with a different one;
- we found the answer ourselves, or the question no longer matters;
- the user decided something in conversation that changes what we ask or what we will do;
- a date in the ticket passed, or its urgency changed.

Whenever such a decision is made in a session, check whether an open ticket is about it (the list at the top) and
propose the update without being asked. Write it as one short reply:

```
*Update* (<name>, <date>): <what we decided, in one or two plain sentences>.
<What it means for the question: "The question is still open." | "No answer is needed any more." | "We still need X.">
```

Put the text in a scratch file and run `tickets.py --reply <ts> <file>` for a dry run; show it to the user; on
their go, add `--post`. Mention nobody. Never rewrite the ticket itself: the top-level message stays as it was asked,
and the history lives in the thread. If the update means no answer is needed, close the ticket with `--close <ts>`
after posting it.

The same command posts any other reply of ours in a thread (a follow-up question, a nudge, a thanks), always on the
user's go for the text shown.
