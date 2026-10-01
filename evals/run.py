#!/usr/bin/env python3
"""Does an agent surface the right memory candidates from a session transcript?

Each fixture has a transcript, candidates an agent should offer (`expect`) and
things it must not offer (`avoid`), each matched by keywords. Two prompt
conditions are compared: `skill` uses this repo's write policy, `baseline` is a
typical "save what's worth remembering" instruction.

    python3 evals/run.py --model haiku
"""

import argparse
import json
import re
import subprocess
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
SKILL = (HERE.parent / "skill" / "SKILL.md").read_text()

BASELINE = (
    "You have a long-term memory. Save anything from this session that is worth remembering for future "
    "sessions. Ask the user before saving only when it seems appropriate."
)

OUTPUT = (
    "Respond with only a JSON array (possibly empty) of the memory candidates you would offer the user, "
    'each {"title": ..., "text": ...}. No prose.'
)


def policy():
    match = re.search(r"## What deserves a proposal\n(.*?)\n## ", SKILL, re.DOTALL)
    return "Memory write policy:\n" + match.group(1).strip()


def prompt(condition, fixture):
    instructions = policy() if condition == "skill" else BASELINE
    return f"{instructions}\n\nThe session just ended. Transcript:\n\n{fixture['transcript']}\n\n{OUTPUT}"


def ask(model, text):
    # No settings sources and an empty cwd, so the evaluator's own CLAUDE.md can't leak in.
    command = ["claude", "-p", "--model", model, "--output-format", "json", "--tools", ""]
    command += ["--setting-sources", "", "--no-session-persistence"]
    with tempfile.TemporaryDirectory() as cwd:
        result = subprocess.run(command, input=text, cwd=cwd, capture_output=True, text=True, check=True)
    reply = json.loads(result.stdout)["result"]
    match = re.search(r"\[.*\]", reply, re.DOTALL)
    return json.loads(match.group(0)) if match else []


def matches(candidate, rule):
    haystack = f"{candidate.get('title', '')} {candidate.get('text', '')}".lower()
    return any(word.lower() in haystack for word in rule["any"])


def score(fixture, candidates):
    found = [rule["name"] for rule in fixture["expect"] if any(matches(c, rule) for c in candidates)]
    violated = [rule["name"] for rule in fixture["avoid"] if any(matches(c, rule) for c in candidates)]
    return {"found": found, "violated": violated, "count": len(candidates)}


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--model", default="haiku")
    parser.add_argument("--conditions", default="baseline,skill")
    parser.add_argument("fixtures", nargs="*", type=Path)
    args = parser.parse_args()
    fixtures = args.fixtures or sorted((HERE / "fixtures").glob("*.json"))
    results = {}
    for condition in args.conditions.split(","):
        totals = {"expected": 0, "found": 0, "violated": 0, "count": 0}
        for path in fixtures:
            fixture = json.loads(path.read_text())
            candidates = ask(args.model, prompt(condition, fixture))
            result = score(fixture, candidates)
            results.setdefault(condition, {})[path.stem] = {**result, "candidates": candidates}
            totals["expected"] += len(fixture["expect"])
            totals["found"] += len(result["found"])
            totals["violated"] += len(result["violated"])
            totals["count"] += result["count"]
            missed = [r["name"] for r in fixture["expect"] if r["name"] not in result["found"]]
            print(
                f"{condition:<9} {path.stem:<26} offered {result['count']}  missed {missed}  violated {result['violated']}"
            )
        print(
            f"{condition:<9} TOTAL recall {totals['found']}/{totals['expected']}, "
            f"violations {totals['violated']}, candidates {totals['count']}\n"
        )
    out = HERE / "results" / f"{args.model}.json"
    out.parent.mkdir(exist_ok=True)
    out.write_text(json.dumps(results, indent=2))
    print(f"details: {out}")


if __name__ == "__main__":
    main()
