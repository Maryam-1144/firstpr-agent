"""FirstPR Agent: Streamlit app."""
from __future__ import annotations

import os
import time

import streamlit as st

import ui
from agent import run_agent, with_retries
from github_tools import GitHub, GitHubError, normalize_repo

DEFAULT_MODEL = "gemma-4-26b-a4b-it"
MAX_UPLOAD_MB = 7
EXAMPLES = ["firstcontributions/first-contributions", "freeCodeCamp/freeCodeCamp", "streamlit/streamlit"]

st.set_page_config(page_title="FirstPR Agent", page_icon="🔀", layout="wide",
                   initial_sidebar_state="expanded")
ui.inject_css()


# ---------- Config ----------
def secret(name: str) -> str | None:
    """Read from .streamlit/secrets.toml, falling back to environment variables."""
    try:
        if name in st.secrets:
            return str(st.secrets[name]).strip() or None
    except Exception:  # no secrets file at all
        pass
    return os.environ.get(name) or None


GEMINI_KEY = secret("GEMINI_API_KEY")
GITHUB_TOKEN = secret("GITHUB_TOKEN")


@st.cache_resource(show_spinner=False)
def get_client(api_key: str):
    from google import genai
    return genai.Client(api_key=api_key)


def describe_screenshot(client, model: str, data: bytes, mime: str) -> str:
    from google.genai import types
    prompt = ("Describe the bug, error message or UI problem in this screenshot in 3 short sentences. "
              "Mention any visible error text or product name.")
    return with_retries(lambda: (client.models.generate_content(
        model=model, contents=[types.Part.from_bytes(data=data, mime_type=mime), prompt]).text or "").strip())


ss = st.session_state
ss.setdefault("result", None)
ss.setdefault("repo_input", "")


def use_example(repo: str) -> None:
    ss.repo_input = repo


def reset() -> None:
    ss.result = None
    ss.repo_input = ""


# ---------- Sidebar ----------
with st.sidebar:
    st.markdown("### Setup")
    st.markdown(ui.status_line("Gemini API key found" if GEMINI_KEY else "Gemini API key missing",
                               "on" if GEMINI_KEY else "bad"), unsafe_allow_html=True)
    st.markdown(ui.status_line("GitHub token set: 5,000 requests/hour" if GITHUB_TOKEN
                               else "No GitHub token: 60 requests/hour", "on" if GITHUB_TOKEN else "off"),
                unsafe_allow_html=True)
    if not GITHUB_TOKEN:
        st.caption("A run uses roughly 8–15 GitHub requests. Add `GITHUB_TOKEN` to secrets for heavier use.")

    st.markdown("### Agent")
    model = st.text_input("Model", secret("MODEL") or DEFAULT_MODEL,
                          help="Any model available through the Gemini API.")
    max_steps = st.slider("Step limit", 4, 16, 10,
                          help="How many tool calls the agent may make before it must answer.")

    st.markdown("### How it works")
    st.markdown("""<ol class="fp-howto">
<li>Lists open issues, preferring ones labeled for newcomers.</li>
<li>Reads the README and contribution guide.</li>
<li>Picks the issue that best fits your skills.</li>
<li>Looks at the relevant files and writes your plan.</li>
</ol>""", unsafe_allow_html=True)
    st.button("Start over", on_click=reset, width="stretch")


# ---------- Header & form ----------
ui.hero()

if not GEMINI_KEY:
    st.error("FirstPR can't run without a Gemini API key. Add `GEMINI_API_KEY = \"...\"` to "
             "`.streamlit/secrets.toml` (or set it as an environment variable) and reload the page.")

with st.form("run"):
    c1, c2 = st.columns([1, 1])
    repo_raw = c1.text_input("GitHub repository", key="repo_input",
                             placeholder="owner/repo or https://github.com/owner/repo")
    skills = c2.text_input("What you know", "Python, HTML/CSS, JavaScript",
                           placeholder="Languages, frameworks, tools")
    c3, c4 = st.columns([1, 1])
    level = c3.selectbox("Experience", ["Beginner", "Intermediate"],
                         help="Beginner favours docs, typos and small isolated fixes.")
    screenshot = c4.file_uploader("Bug screenshot (optional)", type=["png", "jpg", "jpeg", "webp"],
                                  help="If you've hit a bug in this project, the agent will look for a matching issue.")
    submitted = st.form_submit_button("Find my first issue", type="primary", disabled=not GEMINI_KEY)

ex_cols = st.columns([0.9] + [1.6] * len(EXAMPLES) + [2])
ex_cols[0].caption("Try one:")
for col, ex in zip(ex_cols[1:], EXAMPLES):
    col.button(ex, key=f"ex_{ex}", on_click=use_example, args=(ex,), type="tertiary")


# ---------- Run ----------
def run() -> None:
    repo = normalize_repo(repo_raw)
    if not repo:
        st.error("That doesn't look like a GitHub repository. Use the form `owner/repo`, "
                 "for example `firstcontributions/first-contributions`.")
        return
    if screenshot is not None and screenshot.size > MAX_UPLOAD_MB * 1024 * 1024:
        st.error(f"The screenshot is larger than {MAX_UPLOAD_MB} MB. Crop it or save it as JPEG and try again.")
        return

    gh = GitHub(GITHUB_TOKEN)
    client = get_client(GEMINI_KEY)
    started = time.time()

    try:
        meta = gh.repo_info(repo)
    except GitHubError as e:
        st.error(f"Couldn't open `{repo}`: {e}")
        return
    ui.repo_card(meta)
    if meta["archived"]:
        st.warning("This repository is archived, so it won't accept pull requests. Pick an active project.")
        return
    if not meta["has_issues"]:
        st.warning("Issues are turned off for this repository, so there's nothing for the agent to choose from.")
        return

    result = {"repo": repo, "meta": meta, "trace": [], "plan": None, "error": None, "screenshot": None}

    with st.status("Working through the repository…", expanded=True) as status:
        if screenshot is not None:
            status.update(label="Reading your screenshot…")
            mime = "image/jpeg" if screenshot.type in ("image/jpg", "image/pjpeg") else screenshot.type
            try:
                result["screenshot"] = describe_screenshot(client, model, screenshot.getvalue(), mime)
                st.info(f"From your screenshot: {result['screenshot']}")
            except Exception as e:
                st.warning(f"Couldn't read the screenshot ({e}). Continuing without it.")

        def generate(prompt: str) -> str:
            return with_retries(lambda: client.models.generate_content(model=model, contents=prompt).text or "")

        for ev in run_agent(generate, gh, repo, skills.strip(), level, result["screenshot"], max_steps):
            if ev["type"] in ("tool", "notice"):
                result["trace"].append(ev)
                ui.step_row(ev)
                label = ev.get("tool", "retrying")
                status.update(label=f"Step {ev['step']} of up to {max_steps}: {label}")
            elif ev["type"] == "final":
                result["plan"] = ev["markdown"]
            elif ev["type"] == "error":
                result["error"] = ev["message"]

        result["seconds"] = round(time.time() - started)
        result["gh_calls"] = gh.calls
        result["rate_remaining"] = gh.rate_remaining
        if result["plan"]:
            status.update(label=f"Plan ready after {len(result['trace'])} steps", state="complete", expanded=False)
        else:
            status.update(label="The agent stopped before finishing", state="error", expanded=True)

    ss.result = result


if submitted:
    ss.result = None
    run()
    if ss.result:
        st.rerun()  # redraw from session state so the result survives later clicks


# ---------- Results (kept in session state so downloads don't wipe them) ----------
res = ss.result
if res:
    ui.repo_card(res["meta"])
    if res.get("screenshot"):
        st.info(f"From your screenshot: {res['screenshot']}")
    if res["error"]:
        st.error(res["error"])

    m1, m2, m3 = st.columns(3)
    m1.metric("Agent steps", len(res["trace"]))
    m2.metric("GitHub requests", res.get("gh_calls", 0),
              help=f"Remaining this hour: {res['rate_remaining']}" if res.get("rate_remaining") else None)
    m3.metric("Time", f"{res.get('seconds', 0)} s")

    tab_plan, tab_trace = st.tabs(["Contribution plan", f"Agent steps ({len(res['trace'])})"])
    with tab_plan:
        if res["plan"]:
            with st.container(border=True):
                st.markdown(res["plan"])
            d1, d2, _ = st.columns([1, 1, 2])
            d1.download_button("Download plan (.md)", res["plan"],
                               file_name=f"firstpr-{res['repo'].replace('/', '-')}.md",
                               mime="text/markdown", type="primary", width="stretch")
            d2.link_button("Open issues on GitHub", f"{res['meta']['url']}/issues", width="stretch")
        else:
            st.caption("No plan this time. Check the agent steps to see where it stopped, then run it again.")
    with tab_trace:
        if res["trace"]:
            for ev in res["trace"]:
                ui.step_row(ev)
        else:
            st.caption("The agent didn't call any tools.")
elif not submitted:
    st.caption("Results appear here: the repository summary, the agent's steps and your contribution plan.")
