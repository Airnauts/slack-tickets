# ADR-0002 — Only exact commands that read run without asking

Date: 2026-11-26
Status: accepted

## Context

The skill first pre-approved every `tickets.py` command in Claude Code. A post, a reply and a close then ran with no
prompt, `--channel=` reached any channel the app is in, and the dry run of `--reply` printed any file it was pointed at.
A rule that matches a pattern also matches added flags, another channel or a post.

## Decision

The skill pre-approves only commands that post nothing to Slack, and each one as an exact rule, with the flags it may
carry written out. Everything else asks the user. The skill tells the agent to run each command alone, exactly as
written, and to stop when one is refused.

## Consequences

A command with an argument asks: `--thread <ts>`, `--channel=<id>`, a batch, a reply, a close, and a dry run too.

The user's own permission rules come before the skill's. A broader rule of theirs, such as allowing every `python3`
command, makes all of these run without asking. The skill's text is then the last gate for them.

The skill cannot ask for more than it allows. An ask rule for the posting commands is the user's to add in their own
settings, and the skill says so but never adds one.
