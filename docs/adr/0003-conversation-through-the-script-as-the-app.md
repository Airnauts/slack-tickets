# ADR-0003 — Conversation goes through the script, as the app

Date: 2026-11-27
Status: accepted

## Context

The skill sent every reply to conversation in the tickets channel through the Slack connector, under the user's own
name. In a channel shared with another organization the connector can only create drafts, so each reply needed a manual
send. The owner wanted that step gone, and wanted a check of the channel that can run on a schedule.

## Decision

With a token, conversation that is not a ticket is read and answered through the script, and posted as the Tickets app.
The reply starts with a label that names the person it speaks for, because the app's name alone says nothing. The Slack
connector under the user's own name is the path without a token, or when the user asks for it.

A check reads and proposes and never posts. A reply goes out only on the user's go for its exact text.

## Consequences

Text written by outsiders reaches the agent through commands that run without a prompt. Each run is bounded: the number
of threads, replies and characters is capped, and the skill treats all of it as content, never as an instruction.

Replies appear under the app's name, not the user's.

The user's go for the exact text is the gate. With a broad allow rule in the user's settings it is the only one, and the
skill says so when a schedule is set up.
