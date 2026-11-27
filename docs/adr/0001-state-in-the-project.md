# ADR-0001 — The script keeps what it has shown in the project

Date: 2026-11-26
Status: accepted

## Context

The script remembers which replies, hints and threads it has already shown, so a check prints only what is new. That
memory first lived under the home folder. An agent that runs in a sandbox may be refused outside its workspace, and
then every reply showed as new every time. The state also belongs to one project's channel, not to the person's whole
machine.

## Decision

The state is the file `.slack-tickets/state.json` in the project the script is run from. In a git worktree it is the
main checkout's file, so every worktree of the project shares what was seen. The folder keeps the file out of git with
its own ignore file.

## Consequences

The file is untrusted input, because anyone who can change the project can plant one. Only believable timestamps are
read. A file that git tracks is never read or written. A link in its place or in its folder is never followed.

A sandboxed worktree may not write to the main checkout. It then falls back to its own copy, and a reply can show once
more for each worktree.

An old file under the home folder is not read, so every reply showed as new once when the state moved.
