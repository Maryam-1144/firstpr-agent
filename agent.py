"""The FirstPR agent loop, independent of the UI so it can be tested."""
from __future__ import annotations

import json
import re
import time
from typing import Callable, Iterator

from github_tools import GitHub, GitHubError

SYSTEM = """You are FirstPR, an agent that helps a student make their first open-source contribution.
You can use these tools. The repo argument is filled in for you.
- list_issues()                 -> open issues (prefers 'good first issue', then 'help wanted')
- read_issue(number)            -> title, labels, assignment and body of one issue
- read_readme()
- read_contributing()           -> the repo's CONTRIBUTING guide, if any
- list_files(path)              -> files in a folder ("" for the root)
- read_file(path)               -> first 3000 characters of a file

Rules:
- Start with list_issues. Match the issue to the student's skills and experience level.
- Prefer issues labeled 'good first issue', 'documentation', 'help wanted' or small UI/text fixes.
- Skip issues that are already assigned, have many comments, or need architecture changes.
- Call read_contributing once and follow the repo's own rules in your plan.
- Use at most 5 tool calls AFTER choosing the issue, then give the final answer.
- Never call the same tool with the same arguments twice.
- Do not open huge core files. Prefer docs, tests, examples and small modules.
- If a screenshot description is given, prefer issues related to it.
- If the repo has no open issues, say so honestly and suggest the most useful first contribution.
- If you cannot find the exact file, say so honestly and name the most likely folder.

Each turn reply with ONLY one JSON object, nothing else, no code fences.
To use a tool: {"thought": "short reason", "tool": "tool_name", "args": {...}}
When done: {"final": "<markdown>"} where the markdown has these sections:
## Top 3 Candidate Issues
(a markdown table with columns: Issue | Skill match (1-5) | Difficulty (Easy/Medium/Hard) | Why)
## Chosen Issue
(number, title, link, why it fits the student)
## Repo's Contribution Rules
## Files to Change
## Step-by-Step Plan
## Git Commands
## Draft PR Description
Never invent files or facts. Only use what the tools returned."""

FORCE_FINAL = '\nSYSTEM: You are out of steps. Give the final answer NOW as {"final": "<markdown>"}.\n'
RESULT_CHARS = 3500
MAX_HISTORY_CHARS = 60_000


# ---------- Parsing ----------
def extract_json(text: str | None) -> dict | None:
    """Find the first JSON object in a model reply that looks like a tool call or a final answer."""
    if not text:
        return None
    t = text.strip()
    fence = re.search(r"```(?:json)?\s*(\{.*\})\s*```", t, re.S)
    candidates = [fence.group(1)] if fence else []
    candidates.append(t)
    dec = json.JSONDecoder(strict=False)
    for c in candidates:
        for m in re.finditer(r"\{", c):
            try:
                obj, _ = dec.raw_decode(c, m.start())
            except ValueError:
                continue
            if isinstance(obj, dict) and ("tool" in obj or "final" in obj):
                return obj
    return None


def clean_final(value) -> str:
    """Turn whatever the model put in 'final' into displayable markdown."""
    if isinstance(value, (dict, list)):
        value = json.dumps(value, indent=2)
    t = str(value or "").strip()
    # Model sometimes returns the JSON wrapper as plain text that failed to parse.
    m = re.match(r'^\{\s*"final"\s*:\s*"(.*?)"?\s*\}?\s*$', t, re.S)
    if m:
        t = m.group(1).replace("\\n", "\n").replace('\\"', '"').replace("\\t", "\t")
    # Strip an outer ```markdown fence wrapping the whole answer.
    m = re.match(r"^```(?:markdown|md)?\s*\n(.*)\n```$", t, re.S)
    if m:
        t = m.group(1)
    if t.count("```") % 2 == 1:
        t += "\n```"
    return t.strip()


def looks_final(text: str | None) -> bool:
    return bool(text) and "## Chosen Issue" in text


# ---------- Model ----------
def with_retries(fn: Callable[[], str], attempts: int = 3, backoff: float = 2.0) -> str:
    last = None
    for i in range(attempts):
        try:
            return fn()
        except Exception as e:  # SDK raises many types
            last = e
            msg = str(e).lower()
            if any(k in msg for k in ("api key", "permission", "not found", "invalid argument", "400", "401", "403", "404")):
                break  # not worth retrying
            if i < attempts - 1:
                time.sleep(backoff * (2 ** i))
    raise last


# ---------- Agent ----------
def run_agent(generate: Callable[[str], str], gh: GitHub, repo: str, skills: str, level: str,
              screenshot_desc: str | None = None, max_steps: int = 10) -> Iterator[dict]:
    """Yield events: tool | notice | final | error."""
    goal = (f"USER GOAL: Find the best issue in https://github.com/{repo} for a {level.lower()} "
            f"student skilled in {skills or 'general programming'}, and prepare a full contribution plan.\n")
    if screenshot_desc:
        goal += f"\nSCREENSHOT DESCRIPTION: {screenshot_desc}\n"
    turns: list[str] = []
    cache: dict[str, str] = {}
    invalid = 0

    for step in range(1, max_steps + 1):
        history = "".join(turns)
        if len(history) > MAX_HISTORY_CHARS:
            history = "\n[earlier steps trimmed]\n" + history[-MAX_HISTORY_CHARS:]
        prompt = SYSTEM + "\n\n" + goal + history
        if step >= max_steps - 1:
            prompt += FORCE_FINAL

        try:
            out = generate(prompt)
        except Exception as e:
            yield {"type": "error", "message": f"The model request failed: {e}"}
            return

        d = extract_json(out)
        if d is None:
            if looks_final(out) or (step >= max_steps - 1 and out and len(out) > 200):
                yield {"type": "final", "markdown": clean_final(out), "steps": step}
                return
            invalid += 1
            yield {"type": "notice", "step": step, "message": "Model reply was not valid JSON — asking it to retry."}
            turns.append("\nSYSTEM: Invalid reply. Reply with ONE JSON object only.\n")
            if invalid >= 3:
                turns.append("\nSYSTEM: Use exactly this shape: "
                             '{"thought": "...", "tool": "list_issues", "args": {}}\n')
            continue

        if "final" in d:
            md = clean_final(d["final"])
            if md:
                yield {"type": "final", "markdown": md, "steps": step}
                return
            turns.append("\nSYSTEM: Your final answer was empty. Write the full markdown plan.\n")
            continue

        tool = str(d.get("tool") or "")
        args = d.get("args") if isinstance(d.get("args"), dict) else {}
        args = {k: v for k, v in args.items() if k != "repo"}
        key = f"{tool}:{json.dumps(args, sort_keys=True, default=str)}"
        started = time.time()
        ok = True
        if key in cache:
            result = "NOTE: You already called this tool with these arguments. Result:\n" + cache[key]
        else:
            try:
                result = gh.run_tool(tool, args, repo)
                cache[key] = result
            except GitHubError as e:
                ok, result = False, f"ERROR: {e}"
            except Exception as e:  # never crash the run because of one tool call
                ok, result = False, f"ERROR: {type(e).__name__}: {e}"
        yield {"type": "tool", "step": step, "tool": tool or "(none)", "thought": str(d.get("thought", "")),
               "args": args, "result": result, "ok": ok, "seconds": round(time.time() - started, 2)}
        call = json.dumps({"thought": d.get("thought", ""), "tool": tool, "args": args})
        turns.append(f"\nASSISTANT: {call}\nTOOL RESULT: {result[:RESULT_CHARS]}\n")

    yield {"type": "error", "message": f"The agent used all {max_steps} steps without producing a plan. "
                                       "Try again, or raise the step limit in the sidebar."}
