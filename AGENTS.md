# AGENTS.md -- delivery contract for AI coding agents

This repository ships a gate. Read this before you write anything.

## The one rule

You may not report a task as complete until `python guard.py verify` exits 0.

## What counts as completion

Completion requires all three, and each must survive a re-run:

1. A named artifact exists at a path you state, and stating the path is not the
   same as the artifact existing.
2. Every claim you make has a command that proves it, listed in `.guard.json`
   under `claims`.
3. Your delivery text contains zero deferral markers: no "next steps", no
   "TODO", no "waiting for your confirmation".

## What does not count

- Reading files, writing docs, reformatting, restating the plan. These are
  activity. They are not progress.
- "I have fixed X" without a command whose exit code proves X.
- Listing what remains as a substitute for delivering what was asked.

## The three lies this gate exists to catch

| Lie | Sound like | Proof it is a lie |
|---|---|---|
| swallowed failure | "cleanup done" | the delete was wrapped in a silent-error flag; files remain |
| first-hop success | "endpoint is up" | the first hop was 302, the final hop is 502 |
| plan as result | "done, next steps below" | there is no artifact, only an intention |

## When blocked

Do not rephrase and retry. Fix the line the evidence points at, then run the
gate again. If the gate itself is wrong, say so with a counter-example, not with
an argument.
