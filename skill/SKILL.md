---
name: semi-auto-memory
description: Use in any repository with a .semimem.toml. Agents never write memory on their own; they propose candidates and the user approves, edits, or rejects them. Use when you learn something a future session would otherwise rediscover, when the user asks you to remember or correct something, when a hook asks for memory candidates, and when reviewing the pending queue.
---

# Semi-automatic memory

You **offer** memories; the user **decides**; a writer **stores** the approved
ones. You never write memory without approval, and you never let memory work
pull you off the user's task.

`semimem` is the CLI (`bin/semimem` next to this file; the SessionStart hook
tells you the exact invocation). The repository's `.semimem.toml` names the
queue and the *targets*: the places memory can go, each with its own writer.
Run `semimem targets` to see them.

## What deserves a proposal

Propose a candidate when all of these hold:

- a future session would waste real time rediscovering it;
- it will stay true for weeks or longer;
- it is not already recorded: in the target (search it first), or in the
  repository's README, AGENTS.md, CLAUDE.md, docs, or a skill.

Good candidates: how to get something done here, tool quirks and workarounds,
corrections to existing memory, preferences the user stated as standing
preferences. Not candidates: instructions scoped to the current task ("this time", "for
now", "skip X today"), anything said once in passing, task progress,
narration of what you did, anything in git history, secrets (name where a
secret lives instead).

**Offer every candidate that passes the bar.** Do not filter by whether you
think the user would want to be asked; that judgment is theirs, and models
are known to under-ask. Uncertain whether something is still true? Propose it
and say so in the evidence.

## Proposing

```sh
semimem propose --session <id> --target <target> [--ref <where>] --kind <kind> \
  --title "Short stable name" --text - --evidence "What happened that shows it" <<'EOF'
The lesson, written for a reader with no access to this conversation.
EOF
```

- The record must stand alone: whoever writes it may be a different agent, a
  script, or the user reading the queue next week. Spell out names, paths and
  commands; never say "as above" or "this repo's thing".
- `--kind` is one of `fact`, `preference`, `procedure`, `correction`, `other`.
- `--ref` says where inside the target it goes (an existing note name, a node
  id, a file). Omit it to let the writer choose. Proposing against an existing
  entry records a fingerprint of it; if the entry changes before approval, the
  approval is refused and the candidate must be re-proposed.
- Proposing the same text twice is a no-op.

## Asking

**Interactive sessions** (`mode = interactive`, the default):

- Don't stop to ask. Mid-task, at most add one line at the end of a reply:
  `Memory candidate: <title>. Save?`
- At the end of the task, or when the Stop hook asks, append the output of
  `semimem render --session <id>` to your final message. One batch, once.
- The user answers per item, e.g. `1 y, 2 n, 3 edit: <new text>`, or ignores
  it. Unanswered candidates stay pending; don't re-ask in the same session.

**Unattended sessions** (`mode = unattended`, or `SEMIMEM_MODE=unattended`
for scheduled and background agents): propose and move on. Nobody is asked;
the next interactive session surfaces the queue.

## Acting on answers

| Answer | Command |
| --- | --- |
| yes | `semimem approve <id>` |
| no | `semimem reject <id> --reason "..."` |
| edit | `semimem approve <id> --text -` (also `--title`, `--target`, `--ref`) |
| later / no answer | nothing |

A direct request ("remember that ...", "fix that note") is itself approval:
propose and approve in one go without asking again.

`approve` on a **command** or **builtin** target writes immediately; that is
fast enough to do inline. On an **agent** target it records the approval and
prints a self-contained brief. Hand that brief to someone else so the main
task keeps moving:

1. Claude Code: start a background fork (Agent tool, `subagent_type: "fork"`,
   `run_in_background: true`) whose prompt is the brief. A fork already has
   the conversation, so it can resolve anything the brief leaves open.
2. Elsewhere, with Paseo available: `create_agent` with the brief as the
   initial prompt. The brief is self-contained by design.
3. Otherwise, write it yourself after the user's task is finished.

The writer ends with `semimem done <id> --detail "<where it went>"`, or
`semimem fail <id> --error "<why>"` (a failed record can be approved again).

If `approve` reports the target changed since the proposal, don't force it:
read the current entry, re-propose a merged version, and offer that.

## Reviewing the queue

The SessionStart hook reports open records. In an interactive session, when
the user is not in the middle of something, offer once to review them. Show
`semimem render` (all pending), take answers the same way, and leave the
rest. `semimem list --status all` and `semimem show <id>` give the history.

## Never

- Write to a memory target directly, bypassing the queue, unless the user
  asked for that specific edit.
- Re-ask about a candidate the user already answered or skipped this session.
- Interrupt the user's task to resolve memory.
