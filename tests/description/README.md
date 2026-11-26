# Does the description call the skill?

An agent decides to use a skill from its `description` alone. `trigger-evals.json` holds 32 prompts: 16 that should call
the `ticket` skill and 16 near-misses that should not. `run.py` measures, for one description, how often a headless
Claude Code session reaches for the skill on each prompt.

## How a run works

For every prompt and run, `run.py` makes a scratch project holding a stub command with the description. It starts
`claude -p` there and stops the session at its first tool call. Calling the stub counts as a hit. Any other first tool,
or an answer with no tool, counts as a miss. A session that never decides is an error and is left out of the rate.

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
  call, before the tool runs.
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

| Description | Length | Opus, own setup, first 22 prompts | Sonnet, own setup, first 22 prompts | Sonnet, clean settings, all 32 |
|---|---|---|---|---|
| The one before this change | 910 | 11/11 fired, 11/11 quiet | 11/11, 11/11 | 16/16, 16/16 |
| Candidate, 636 characters | 636 | 11/11, 11/11 | 11/11, 11/11 | not run |
| Candidate, 443 characters | 443 | 11/11, 11/11 | 11/11, 11/11 | 16/16, 16/16 |
| The current one | 275 | 11/11, 11/11 | 11/11, 11/11 | 16/16, 16/16 |
| Candidate, 198 characters | 198 | 11/11, 11/11 | 11/11, 11/11 | 16/16, 16/16 |
| Control: "Tickets." (two runs) | 8 | 8/11, 9/11 | not run | 7/16, 14/16 |

- The ten harder prompts were also run on Opus with the own setup for the 910, 443, 275 and 198 character versions:
  5/5 fired and 5/5 quiet each time.
- What the control shows: with next to no description the skill is still called when a prompt says "ticket". But it
  misses the prompts where the client contradicts earlier material, where work is blocked on the client, and where
  nobody says "ticket". And it fires on a customer's support ticket. So the description is what carries those cases,
  and the test can tell.
- Why 275 and not 198: both scored the same. The 275 one still says both reasons to use the skill in words. The 198 one
  drops "work needs a decision or fact only the client has".

## What this does not show

- Only Claude Code is measured, through a stub command, not the installed plugin. Other agents read the same
  description but were not measured.
- 32 prompts are a sample.
- When the skill is missed, or called when it should not be, in real use, add that prompt here first, then change the
  description.
