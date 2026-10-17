"""Offline tests: no network, no API keys.  Run with:  python -m unittest discover tests"""
import base64
import json
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from agent import clean_final, extract_json, run_agent  # noqa: E402
from github_tools import GitHub, GitHubError, normalize_repo  # noqa: E402


class FakeResp:
    def __init__(self, status, data=None, headers=None):
        self.status_code, self._data, self.headers = status, data, headers or {}
        self.ok = 200 <= status < 300
        self.text = json.dumps(data)
        self.content = self.text.encode()

    def json(self):
        return self._data

    def raise_for_status(self):
        pass


class FakeSession:
    """Maps URL path (+ labels param) to responses."""
    def __init__(self, routes):
        self.routes, self.headers, self.log = routes, {}, []

    def get(self, url, params=None, timeout=None):
        path = url.replace("https://api.github.com", "")
        key = path + (f"?labels={params['labels']}" if params and "labels" in params else "")
        self.log.append(key)
        r = self.routes.get(key, self.routes.get(path))
        if r is None:
            return FakeResp(404, {"message": "Not Found"})
        return r() if callable(r) else r


def b64(s):
    return base64.b64encode(s.encode()).decode()


R = "/repos/o/r"
ROUTES = {
    R: FakeResp(200, {"full_name": "o/r", "stargazers_count": 5, "forks_count": 1, "open_issues_count": 2,
                      "default_branch": "main", "html_url": "https://github.com/o/r"}),
    R + "/issues?labels=good first issue": FakeResp(200, [{"number": 9, "title": "PR", "pull_request": {}}]),
    R + "/issues?labels=help wanted": FakeResp(200, [{"number": 3, "title": "Fix typo", "comments": 1,
                                                    "labels": [{"name": "help wanted"}], "assignees": []}]),
    R + "/issues/3": FakeResp(200, {"title": "Fix typo", "body": None, "state": "open", "labels": []}),
    R + "/readme": FakeResp(200, {"encoding": "base64", "content": b64("# Hello")}),
    R + "/contents/.github/CONTRIBUTING.md": FakeResp(200, {"encoding": "base64", "content": b64("Be nice")}),
    R + "/contents/": FakeResp(200, [{"type": "file", "path": "a.py"}, {"type": "dir", "path": "docs"}]),
    R + "/contents/docs": FakeResp(200, [{"type": "file", "path": "docs/x.md"}]),
    R + "/contents/a.py": FakeResp(200, {"type": "file", "path": "a.py", "encoding": "base64", "content": b64("print(1)")}),
}


def gh():
    return GitHub(session=FakeSession(dict(ROUTES)), backoff=0)


class TestRepo(unittest.TestCase):
    def test_normalize(self):
        for raw in ["o/r", " https://github.com/o/r ", "github.com/o/r/issues/4", "git@github.com:o/r.git",
                    "https://www.github.com/o/r.git?x=1", "https://github.com/o/r/"]:
            self.assertEqual(normalize_repo(raw), "o/r", raw)
        for raw in ["", None, "justone", "https://gitlab.com/o/r", "o/r r", "-bad/r"]:
            self.assertIsNone(normalize_repo(raw), raw)


class TestTools(unittest.TestCase):
    def test_list_issues_skips_prs_and_falls_back(self):
        out = json.loads(gh().list_issues("o/r"))
        self.assertEqual(out["source"], "label 'help wanted'")
        self.assertEqual([i["number"] for i in out["issues"]], [3])

    def test_read_issue_handles_null_body_and_hash(self):
        out = json.loads(gh().read_issue("o/r", "#3"))
        self.assertEqual(out["body"], "")
        with self.assertRaises(GitHubError):
            gh().read_issue("o/r", "abc")

    def test_contributing_found_in_github_dir(self):
        self.assertEqual(gh().read_contributing("o/r"), "Be nice")

    def test_list_files_on_file_and_dir(self):
        g = gh()
        self.assertEqual(json.loads(g.list_files("o/r")), ["dir: docs", "file: a.py"])
        self.assertEqual(json.loads(g.list_files("o/r", "a.py")), ["file: a.py"])

    def test_read_file_on_dir_errors_cleanly(self):
        g = gh()
        self.assertEqual(g.read_file("o/r", "/a.py"), "print(1)")
        with self.assertRaises(GitHubError):
            g.read_file("o/r", "docs")
        with self.assertRaises(GitHubError):
            g.read_file("o/r", "../../etc")

    def test_rate_limit_message(self):
        g = GitHub(session=FakeSession({R: FakeResp(403, {}, {"X-RateLimit-Remaining": "0"})}), backoff=0)
        with self.assertRaisesRegex(GitHubError, "rate limit"):
            g.repo_info("o/r")

    def test_server_error_retried(self):
        seq = iter([FakeResp(502, {}), ROUTES[R]])
        g = GitHub(session=FakeSession({R: lambda: next(seq)}), backoff=0)
        self.assertEqual(g.repo_info("o/r")["full_name"], "o/r")

    def test_run_tool_forces_repo_and_validates(self):
        g = gh()
        # model tries another repo and an unknown kwarg: both ignored
        out = g.run_tool("read_readme", {"repo": "evil/x", "junk": 1}, "o/r")
        self.assertEqual(out, "# Hello")
        with self.assertRaisesRegex(GitHubError, "Unknown tool"):
            g.run_tool("delete_repo", {}, "o/r")
        with self.assertRaisesRegex(GitHubError, "missing"):
            g.run_tool("read_issue", {}, "o/r")


class TestParsing(unittest.TestCase):
    def test_extract_json_variants(self):
        self.assertEqual(extract_json('{"tool": "list_issues", "args": {}}')["tool"], "list_issues")
        self.assertEqual(extract_json('Sure!\n```json\n{"tool": "read_readme"}\n```')["tool"], "read_readme")
        d = extract_json('{"final": "## Plan\\n```py\\nx = {1: 2}\\n```"}')
        self.assertIn("x = {1: 2}", d["final"])
        self.assertIsNone(extract_json("no json here"))
        self.assertIsNone(extract_json(None))
        self.assertIsNone(extract_json('{"foo": 1}'))

    def test_clean_final(self):
        self.assertEqual(clean_final("```markdown\n## A\n```"), "## A")
        self.assertTrue(clean_final("## A\n```bash\ngit").endswith("```"))
        self.assertIn('"a"', clean_final({"a": 1}))
        self.assertEqual(clean_final(None), "")


class TestAgentLoop(unittest.TestCase):
    def run_with(self, replies, max_steps=10):
        it = iter(replies)
        return list(run_agent(lambda p: next(it), gh(), "o/r", "Python", "Beginner", max_steps=max_steps))

    def test_happy_path(self):
        evs = self.run_with([
            '{"thought": "look", "tool": "list_issues", "args": {}}',
            'garbage',
            '{"tool": "read_issue", "args": {"number": 3}}',
            '{"tool": "read_issue", "args": {"number": 3}}',   # duplicate -> cached
            '{"tool": "nope", "args": []}',                     # bad tool + bad args type
            '{"final": "## Chosen Issue\\n#3"}',
        ])
        types = [e["type"] for e in evs]
        self.assertEqual(types, ["tool", "notice", "tool", "tool", "tool", "final"])
        self.assertIn("already called", evs[3]["result"])
        self.assertFalse(evs[4]["ok"])
        self.assertEqual(evs[-1]["markdown"], "## Chosen Issue\n#3")

    def test_plain_markdown_final(self):
        evs = self.run_with(["Here you go\n## Chosen Issue\n#3"])
        self.assertEqual(evs[-1]["type"], "final")

    def test_out_of_steps(self):
        evs = self.run_with(['{"tool": "read_readme"}'] * 5, max_steps=4)
        self.assertEqual(evs[-1]["type"], "error")

    def test_model_failure_stops(self):
        def boom(p):
            raise RuntimeError("quota")
        evs = list(run_agent(boom, gh(), "o/r", "", "Beginner"))
        self.assertEqual([e["type"] for e in evs], ["error"])


if __name__ == "__main__":
    unittest.main()
