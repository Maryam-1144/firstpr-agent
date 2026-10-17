"""Read-only GitHub helpers used as agent tools."""
from __future__ import annotations

import base64
import inspect
import json
import re
import time
from urllib.parse import quote

import requests

API = "https://api.github.com"
REPO_RE = re.compile(r"^[A-Za-z0-9](?:[A-Za-z0-9-]{0,38})/[A-Za-z0-9._-]{1,100}$")

# Size limits for what we hand back to the model.
ISSUE_BODY_CHARS = 2500
DOC_CHARS = 2500
FILE_CHARS = 3000
MAX_LISTED_FILES = 60


class GitHubError(Exception):
    """A readable error that can be shown to the user or the model."""


def normalize_repo(text: str | None) -> str | None:
    """Accept 'owner/repo', a GitHub URL, or a clone URL; return 'owner/repo' or None."""
    t = (text or "").strip()
    t = re.sub(r"^git@github\.com:", "", t, flags=re.I)
    t = re.sub(r"^(https?://)?(www\.)?github\.com/", "", t, flags=re.I)
    t = t.split("?")[0].split("#")[0].strip().strip("/")
    if t.endswith(".git"):
        t = t[:-4]
    parts = [p for p in t.split("/") if p]
    if len(parts) < 2:
        return None
    t = f"{parts[0]}/{parts[1]}"
    return t if REPO_RE.match(t) else None


def _clean_path(path: str | None) -> str:
    p = (path or "").strip().strip("/")
    if p in ("", "."):
        return ""
    if any(seg == ".." for seg in p.split("/")):
        raise GitHubError("Invalid path.")
    return quote(p, safe="/")


class GitHub:
    def __init__(self, token: str | None = None, session: requests.Session | None = None,
                 retries: int = 3, backoff: float = 1.0):
        self.s = session or requests.Session()
        self.s.headers.update({
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
            "User-Agent": "firstpr-agent",
        })
        if token:
            self.s.headers["Authorization"] = f"Bearer {token}"
        self.retries = retries
        self.backoff = backoff
        self.calls = 0
        self.rate_remaining: str | None = None

    # ---------- HTTP ----------
    def get(self, path: str, **params):
        url = path if path.startswith("http") else API + path
        last: Exception = GitHubError("GitHub request failed.")
        for attempt in range(self.retries):
            if attempt:
                time.sleep(self.backoff * 2 ** (attempt - 1))
            try:
                r = self.s.get(url, params=params or None, timeout=20)
            except requests.RequestException as e:
                last = GitHubError(f"Network error while contacting GitHub: {e}")
                continue
            self.calls += 1
            self.rate_remaining = r.headers.get("X-RateLimit-Remaining", self.rate_remaining)

            if r.status_code == 404:
                raise GitHubError(f"Not found on GitHub: {path}")
            if r.status_code in (403, 429):
                if r.status_code == 429 or r.headers.get("X-RateLimit-Remaining") == "0":
                    msg = "GitHub API rate limit reached."
                    reset = r.headers.get("X-RateLimit-Reset")
                    if reset and reset.isdigit():
                        mins = max(0, int(reset) - int(time.time())) // 60 + 1
                        msg += f" It resets in about {mins} min."
                    if "Authorization" not in self.s.headers:
                        msg += " Add a GITHUB_TOKEN to secrets to raise the limit from 60 to 5,000 requests/hour."
                    raise GitHubError(msg)
                raise GitHubError(f"GitHub denied access (403) to {path}.")
            if r.status_code == 401:
                raise GitHubError("GitHub rejected the token (401). Check GITHUB_TOKEN.")
            if r.status_code >= 500:
                last = GitHubError(f"GitHub server error ({r.status_code}).")
                continue
            if not r.ok:
                raise GitHubError(f"GitHub returned {r.status_code}: {r.text[:200]}")
            try:
                return r.json()
            except ValueError:
                raise GitHubError("GitHub returned an unreadable response.")
        raise last

    def _decode(self, d: dict) -> str:
        """Decode a contents-API file object, falling back to the raw URL for big files."""
        if d.get("encoding") == "base64" and d.get("content"):
            raw = base64.b64decode(d["content"])
        elif d.get("download_url"):
            try:
                r = self.s.get(d["download_url"], timeout=20)
                r.raise_for_status()
                raw = r.content
            except requests.RequestException as e:
                raise GitHubError(f"Could not download file: {e}")
        else:
            return ""
        if b"\x00" in raw[:1024]:
            return "[binary file, not shown]"
        return raw.decode("utf-8", "ignore")

    # ---------- Tools ----------
    def repo_info(self, repo: str) -> dict:
        d = self.get(f"/repos/{repo}")
        return {
            "full_name": d.get("full_name", repo),
            "description": d.get("description") or "",
            "stars": d.get("stargazers_count", 0),
            "forks": d.get("forks_count", 0),
            "language": d.get("language") or "—",
            "open_issues": d.get("open_issues_count", 0),
            "default_branch": d.get("default_branch", "main"),
            "archived": bool(d.get("archived")),
            "url": d.get("html_url", f"https://github.com/{repo}"),
            "has_issues": d.get("has_issues", True),
        }

    def list_issues(self, repo: str) -> str:
        def fetch(**extra):
            items = self.get(f"/repos/{repo}/issues", state="open", per_page=30, **extra)
            return [i for i in items if "pull_request" not in i]

        issues, source = [], "all open issues"
        for label in ("good first issue", "help wanted"):
            issues = fetch(labels=label)
            if issues:
                source = f"label '{label}'"
                break
        if not issues:
            issues = fetch()
        if not issues:
            return json.dumps({"source": source, "issues": [],
                               "note": "This repository has no open issues."})
        return json.dumps({
            "source": source,
            "issues": [{
                "number": i["number"],
                "title": i["title"],
                "comments": i.get("comments", 0),
                "labels": [l["name"] for l in i.get("labels", []) if isinstance(l, dict)],
                "assigned": bool(i.get("assignees")),
                "updated": (i.get("updated_at") or "")[:10],
            } for i in issues[:25]],
        })

    def read_issue(self, repo: str, number) -> str:
        try:
            n = int(str(number).lstrip("#"))
        except ValueError:
            raise GitHubError(f"Issue number must be an integer, got {number!r}.")
        i = self.get(f"/repos/{repo}/issues/{n}")
        return json.dumps({
            "number": n,
            "title": i.get("title"),
            "state": i.get("state"),
            "is_pull_request": "pull_request" in i,
            "labels": [l["name"] for l in i.get("labels", []) if isinstance(l, dict)],
            "assigned": bool(i.get("assignees")),
            "comments": i.get("comments", 0),
            "body": (i.get("body") or "")[:ISSUE_BODY_CHARS],
        })

    def read_readme(self, repo: str) -> str:
        return self._decode(self.get(f"/repos/{repo}/readme"))[:DOC_CHARS] or "README is empty."

    def read_contributing(self, repo: str) -> str:
        for p in ("CONTRIBUTING.md", ".github/CONTRIBUTING.md", "docs/CONTRIBUTING.md",
                  "CONTRIBUTING.rst", "CONTRIBUTING"):
            try:
                d = self.get(f"/repos/{repo}/contents/{p}")
            except GitHubError as e:
                if str(e).startswith("Not found"):
                    continue
                raise
            if isinstance(d, dict):
                return self._decode(d)[:DOC_CHARS]
        return "No CONTRIBUTING file found."

    def list_files(self, repo: str, path: str = "") -> str:
        d = self.get(f"/repos/{repo}/contents/{_clean_path(path)}")
        if isinstance(d, dict):  # path is a single file
            return json.dumps([f"{d.get('type', 'file')}: {d.get('path', path)}"])
        entries = sorted(d, key=lambda x: (x.get("type") != "dir", x.get("path", "")))
        out = [f"{x['type']}: {x['path']}" for x in entries[:MAX_LISTED_FILES]]
        if len(entries) > MAX_LISTED_FILES:
            out.append(f"... and {len(entries) - MAX_LISTED_FILES} more")
        return json.dumps(out)

    def read_file(self, repo: str, path: str) -> str:
        if not (path or "").strip():
            raise GitHubError("read_file needs a file path.")
        d = self.get(f"/repos/{repo}/contents/{_clean_path(path)}")
        if isinstance(d, list):
            raise GitHubError(f"'{path}' is a directory. Use list_files instead.")
        text = self._decode(d)
        if len(text) > FILE_CHARS:
            return text[:FILE_CHARS] + f"\n... [truncated, {len(text)} chars total]"
        return text

    # ---------- Dispatch ----------
    TOOL_NAMES = ("list_issues", "read_issue", "read_readme",
                  "read_contributing", "list_files", "read_file")

    def run_tool(self, name: str, args: dict, repo: str) -> str:
        """Call a tool safely. The repo is always the user's repo, never the model's choice."""
        if name not in self.TOOL_NAMES:
            raise GitHubError(f"Unknown tool '{name}'. Valid tools: {', '.join(self.TOOL_NAMES)}.")
        fn = getattr(self, name)
        params = inspect.signature(fn).parameters
        call = {k: v for k, v in (args or {}).items() if k in params and k != "repo"}
        call["repo"] = repo
        missing = [p for p, spec in params.items()
                   if spec.default is inspect.Parameter.empty and p not in call]
        if missing:
            raise GitHubError(f"{name} is missing argument(s): {', '.join(missing)}.")
        return fn(**call)
