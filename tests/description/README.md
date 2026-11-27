# Does the description call the skill?

An agent decides to use a skill from its name and `description`. `trigger-evals.json` holds 36 prompts: 18 that should
call the `ticket` skill and 18 near-misses that should not. `run.py` measures, for one description, how often a
headless Claude Code session reaches for the skill on each prompt.

## How a run works

For every prompt and run, `run.py` makes a scratch project holding a stub command with the description. It starts
`claude -p` there and stops the session at its first tool call. A call to another skill or a file read is recognised a
moment later than other tools, so it may have started when the session is stopped. Calling the stub counts as a hit.
Any other first tool, or an answer with no tool, counts as a miss. A session that never decides is an error and is left
out of the rate. So is a session that fails, for example with a wrong model name or no login. It is an error, not a
miss, and the runner prints the text of the first error.

## How to run

```
python3 tests/description/run.py --model opus
python3 tests/description/run.py --model sonnet --claude-arg=--setting-sources --claude-arg=project
python3 tests/description/run.py --description-file candidate.txt --runs 3
```

- The first line tests the skill's current description on your own setup.
- The second does the same with your own settings, hooks and plugins left out. This is closer to a teammate's fresh
  install.
- The third tests another text instead of the skill's description.

It exits with 1 when any prompt lands on the wrong side.

## Before you run it

- Every run is a real, paid session in your own Claude Code, with your connectors. It is stopped at its first tool
  call. A call to another skill or a file read is recognised a moment later, so it may have started by then.
- Every session also runs your own hooks and starts your connectors' servers. The runner asks Claude Code not to keep
  the sessions, so no transcript is saved. Each run still leaves an empty folder for its scratch project under
  `~/.claude/projects`.
- `--setting-sources project` leaves out your settings, hooks and plugins. Checked once, on 26 November 2026: a
  session started that way loaded no hook, no connector and 20 skills, where the own setup loaded 74 skills and 9
  connectors.
- Ctrl-C stops the run and the sessions it started.
- Prompts use invented names only: no real channel, person or project.
- A prompt must not name a file to open. Opening a file is a first tool call, so it scores as a miss whatever the
  description says.
- Results depend on the model and on what else is installed. A hook that tells sessions to reach for skills makes every
  description look better.
- One project per run is deliberate. Runs that share a project see each other's stubs and pick the wrong one. One clear
  prompt scored 6 of 6 alone and 1 of 6 when six runs shared a project.

## Results, 26 November 2026

Three runs per prompt unless noted. "Fired" counts should-trigger prompts that called the skill. "Quiet" counts
should-not prompts that did not.

| Description | Length | Opus, own setup, the original 22 prompts | Sonnet, own setup, the original 22 prompts | Sonnet, clean settings, the first 32 |
|---|---|---|---|---|
| The one before this change | 910 | 11/11 fired, 11/11 quiet | 11/11, 11/11 | 16/16, 16/16 |
| Candidate, 636 characters | 636 | 11/11, 11/11 | 11/11, 11/11 | not run |
| Candidate, 443 characters | 443 | 11/11, 11/11 | 11/11, 11/11 | 16/16, 16/16 |
| The current one | 275 | 11/11, 11/11 | 11/11, 11/11 | 16/16, 16/16 |
| Candidate, 198 characters | 198 | 11/11, 11/11 | 11/11, 11/11 | 16/16, 16/16 |
| Control: "Tickets." (two runs) | 8 | 8/11, 9/11 | not run | 7/16, 14/16 |

The four prompts about answering conversation in the tickets channel were added on 27 November 2026 and run on their
own with Sonnet, three runs each: both that should call the skill did, 3 of 3, and both near misses stayed quiet, 3 of
3. The description was not changed for them.

- The original 22 were 11 should-trigger and 11 should-not. Ten harder ones were added afterwards, and the file lists
  should-trigger first, so they are not its first 22 lines.
- The ten harder prompts were also run on Opus with the own setup for the 910, 443, 275 and 198 character versions:
  5/5 fired and 5/5 quiet each time.
- What the control shows: with next to no description the skill is still called when a prompt says "ticket". But it
  misses the prompts where the client contradicts earlier material, where work is blocked on the client, and where
  nobody says "ticket". And it fires on a customer's support ticket. So the description is what carries those cases,
  and the test can tell. The control still fires on prompts that say "ticket" partly because the stub's name contains
  that word, as the real skill's name does.
- Why 275 and not 198: both scored the same. The 275 one still says both reasons to use the skill in words. The 198 one
  drops "work needs a decision or fact only the client has".

## What this does not show

- Only Claude Code is measured, through a stub command, not the installed plugin. Other agents read the same
  description but were not measured.
- 36 prompts are a sample.
- When the skill is missed, or called when it should not be, in real use, add that prompt here first, then change the
  description.
