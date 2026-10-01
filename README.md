# semi-auto-memory

Semi-automatic memory for coding agents: **the agent offers, you decide, a
writer stores.**

Most agent memory is either manual (you have to say "remember this") or fully
automatic (the agent writes whatever it judges worth keeping, and you find out
later). Manual memory misses most of what is worth keeping. Automatic memory
fills up with things that were true once, said once, or never quite right, and
review-after-the-fact rarely happens.

This project sits in between:

- Agents **must offer** candidates that pass a write policy. Whether to ask is
  not left to the model: models are known to under-ask (see Research).
- You answer in one batch, `1 y, 2 n, 3 edit: ...`, at the end of a task. The
  agent never stops work to ask.
- Approved candidates are written by a **writer**: a command, a builtin, or
  a background agent the main session forks off, so writing never competes
  with the task at hand.
- Sessions with nobody to ask (scheduled jobs, background workers) queue
  their candidates instead. The next interactive session surfaces the queue.
- Approval is refused if the target changed after the candidate was proposed.

It is storage-agnostic. A repository says where memory goes in
`.semimem.toml`; the protocol, queue, review flow and hooks are the same
everywhere.

## Pieces

| Path | What |
| --- | --- |
| `skill/SKILL.md` | The protocol agents follow (Claude Code / Codex skill format) |
| `skill/bin/semimem` | Dependency-free Python 3.11+ CLI: queue, review, writers, hooks |
| `examples/` | Sample configs |
| `evals/` | Does an agent surface the right candidates from a transcript? |
| `tests/` | `python3 -m unittest discover -s tests` |

## The queue

`semimem` keeps an append-only JSONL event log (`propose`, `edit`, `approve`,
`applied`, `reject`, `failed`, `stale`). A record's state is the fold of its
events. Append-only means several agents can write at once (`flock`), and a
queue committed to git merges cleanly with `merge=union` in
`.gitattributes`.

Every record stands alone: title, text, kind, target, optional ref, evidence,
proposing agent and session. A writer never needs the conversation that
produced it, so forking for context is an optimization, not a requirement.

## Configuration

```toml
queue = ".semimem/queue.jsonl"
mode = "interactive"          # or "unattended"; SEMIMEM_MODE overrides per session
default_target = "notes"

[stop_hook]
min_tool_calls = 15           # new tool calls before the Stop hook asks again
min_stops = 4                 # fallback when the transcript can't be read

# Builtin: a bullet list in a markdown file. Good default for any repo.
[targets.notes]
description = "Durable notes for future agent sessions"
builtin = "markdown"
path = "MEMORY.md"
heading = "## Memory"

# Command writer: approved text arrives on stdin. {id} {title} {ref} {kind}
# {agent} {target} {session} are substituted shell-quoted; {ref} defaults to
# the title.
[targets.wiki]
description = "Team wiki page"
write = "./scripts/wiki-append {ref}"
fingerprint = "./scripts/wiki-show {ref}"   # content whose change makes a proposal stale
discard = "./scripts/wiki-delete {ref}"     # optional: run on reject

# Agent writer: approval prints a self-contained brief for a forked or
# background agent, which finishes with `semimem done <id>`.
[targets.docs]
description = "Architecture docs"
writer = "agent"
fingerprint = "cat docs/architecture.md"
instructions = "Add it to the relevant section of docs/architecture.md."

# Importers bring candidates in from elsewhere: a command that prints JSONL
# {"key", "title", "text", ...}. Run by `semimem sync` and at session start.
[[importers]]
name = "legacy"
target = "wiki"
command = "./scripts/unreviewed-notes --jsonl"
```

## Install

Put the skill where your agent finds skills (e.g. `.claude/skills/` or
`.agents/skills/`), add a `.semimem.toml` (`semimem init` writes a sample),
then install the hooks:

```sh
semimem install-hooks claude --script .claude/skills/semi-auto-memory/bin/semimem
semimem install-hooks codex  --script .agents/skills/semi-auto-memory/bin/semimem
```

- **SessionStart** runs importers and tells the agent the protocol is
  active, the session id, the targets, and what's waiting for review.
- **Stop** asks once the session has done real work (`min_tool_calls` new
  tool calls since the last ask): list candidates, propose them, end the reply
  with the rendered batch. It does nothing on the continuation it causes.

Claude Code and Codex use the same hook JSON, so the same commands serve
both. Codex loads project hooks only once the project's `.codex/` layer is
trusted (`/hooks`). Hooks degrade to nothing if the script is missing.

With Nix, the flake exposes the skill as `packages.<system>.skill` and the CLI
as `packages.<system>.default`.

## Evals

`python3 evals/run.py --model haiku` runs each fixture transcript through
`claude -p` (isolated from your own CLAUDE.md) under two prompts: this
skill's write policy, and a typical "save what's worth remembering"
instruction. It scores recall of candidates that should be offered and
violations (one-off instructions, secrets, things already documented).

First run (Haiku, 4 fixtures, one sample each, so treat it as a smoke test):

| Condition | Recall | Violations | Candidates |
| --- | --- | --- | --- |
| baseline | 4/5 | 2 | 6 |
| skill policy | 5/5 | 0 | 6 |

## Prior art

- **Hermes Agent** (Nous Research): `memory.write_approval` prompts inline in
  the CLI and queues writes from messaging and background runs
  (`/memory pending`); the refuse-if-target-changed rule comes from here.
  Off by default.
- **Claude-User-Memory-Plugin** (Daniel Rosehill): a `commit-learnings` skill
  proposes facts at session end and saves the approved ones.
- **Panella**: MCP memory server where agent writes become durable only after
  human approval.
- Automatic-by-default systems for contrast: ChatGPT memory, claude-mem,
  Mem0, Letta/MemGPT's self-editing memory, LangMem's background writer.

## Research

- *Remember, Verify, or Ask?* (arXiv 2608.19564, 2026): treats each candidate
  as persist / use-in-context / re-verify / ask. Models almost never choose
  to ask, even when clarification is needed. Hence: offering is mandatory.
- ChatGPT memory studies (CHI 2026): users were often unpleasantly surprised
  by what had been remembered and wanted visibility and control. Related work
  on *memory misalignment* finds AI memory too detailed and too permanent.
- *Memory Sandbox* (arXiv 2308.01542): early HCI prototype for user-managed
  conversational agent memory.
- Supermemory, *agent memory write policies*: writes should serve a defined
  future need; a one-off statement shouldn't become a standing preference.

## License

MIT
