"""Styling and small HTML render helpers for the Streamlit UI."""
from __future__ import annotations

import json
from html import escape

import streamlit as st

CSS = """
<style>
@import url('https://fonts.googleapis.com/css2?family=Bricolage+Grotesque:opsz,wght@12..96,500;12..96,700&family=Schibsted+Grotesk:wght@400;500;600&display=swap');

:root {
  --ink: #1B2330;
  --ink-soft: #5A6474;
  --paper: #F6F7F9;
  --panel: #FFFFFF;
  --line: #DCE1E8;
  --merge: #16775A;
  --merge-tint: #E3F1EB;
  --warn: #9A5B12;
  --warn-tint: #FBF0E1;
  --fail: #A23B3B;
}

html, body, .stMarkdown, .stMarkdown p, label, input, textarea {
  font-family: 'Schibsted Grotesk', system-ui, sans-serif;
}
h1, h2, h3, h4, .fp-title { font-family: 'Bricolage Grotesque', 'Schibsted Grotesk', sans-serif !important; letter-spacing: -0.01em; }
.block-container { padding-top: 2.2rem; max-width: 1120px; }
#MainMenu, footer { visibility: hidden; }

/* ---------- Hero ---------- */
.fp-hero { display: flex; gap: 2.5rem; align-items: center; justify-content: space-between;
  padding: 0.5rem 0 1.75rem; border-bottom: 1px solid var(--line); margin-bottom: 1.75rem; }
.fp-hero-text { max-width: 620px; }
.fp-title { font-size: clamp(2.1rem, 4.2vw, 3.1rem); font-weight: 700; line-height: 1.05;
  color: var(--ink); margin: 0 0 0.75rem; }
.fp-lede { font-size: 1.08rem; line-height: 1.55; color: var(--ink-soft); margin: 0; }
.fp-branch { flex: 0 0 auto; }
.fp-branch svg { display: block; }
@media (max-width: 760px) { .fp-branch { display: none; } }

/* ---------- Repo card ---------- */
.fp-repo { background: var(--panel); border: 1px solid var(--line); border-radius: 10px;
  padding: 1rem 1.2rem; margin: 0.25rem 0 1rem; }
.fp-repo a { color: var(--ink); font-weight: 600; font-size: 1.08rem; text-decoration: none; }
.fp-repo a:hover { color: var(--merge); text-decoration: underline; }
.fp-repo p { color: var(--ink-soft); margin: 0.3rem 0 0.7rem; font-size: 0.95rem; }
.fp-facts { display: flex; flex-wrap: wrap; gap: 0.4rem 1.2rem; font-size: 0.88rem; color: var(--ink-soft); }
.fp-facts b { color: var(--ink); font-weight: 600; }
.fp-flag { display: inline-block; background: var(--warn-tint); color: var(--warn);
  border-radius: 4px; padding: 0.05rem 0.45rem; font-weight: 600; }

/* ---------- Timeline (agent steps) ---------- */
.fp-step { position: relative; padding: 0 0 0.7rem 1.9rem; }
.fp-step::before { content: ""; position: absolute; left: 0.42rem; top: 1.1rem; bottom: -0.6rem;
  width: 2px; background: var(--line); }
.fp-dot { position: absolute; left: 0; top: 0.28rem; width: 0.95rem; height: 0.95rem; border-radius: 50%;
  background: var(--panel); border: 3px solid var(--merge); }
.fp-step.fail .fp-dot { border-color: var(--fail); }
.fp-step.note .fp-dot { border-color: var(--warn); }
.fp-step-head { display: flex; flex-wrap: wrap; align-items: baseline; gap: 0.5rem; }
.fp-step-n { color: var(--ink-soft); font-size: 0.85rem; }
.fp-tool { font-weight: 600; color: var(--ink); }
.fp-args { font-family: ui-monospace, SFMono-Regular, Menlo, monospace; font-size: 0.82rem;
  color: var(--ink-soft); background: #EEF1F5; border-radius: 4px; padding: 0.05rem 0.4rem; }
.fp-thought { color: var(--ink-soft); font-size: 0.93rem; margin: 0.15rem 0 0.1rem; }
.fp-err { color: var(--fail); font-size: 0.9rem; }

/* ---------- Plan output ---------- */
.fp-plan h2 { font-size: 1.35rem; margin-top: 1.6rem; padding-top: 1.1rem; border-top: 1px solid var(--line); }
[data-testid="stMarkdownContainer"] table { font-size: 0.93rem; }

/* ---------- Sidebar ---------- */
.fp-status { display: flex; align-items: center; gap: 0.55rem; font-size: 0.92rem; margin: 0.25rem 0; }
.fp-led { width: 0.6rem; height: 0.6rem; border-radius: 50%; background: var(--merge); flex: 0 0 auto; }
.fp-led.off { background: #C3CAD4; }
.fp-led.bad { background: var(--fail); }
.fp-howto { padding-left: 1.1rem; color: var(--ink-soft); font-size: 0.9rem; line-height: 1.5; }

/* ---------- Controls ---------- */
.stButton button[kind="primary"], .stFormSubmitButton button[kind="primaryFormSubmit"] {
  font-weight: 600; padding: 0.55rem 1.4rem; }
:focus-visible { outline: 2px solid var(--merge) !important; outline-offset: 2px; }
</style>
"""

BRANCH_SVG = """
<svg width="230" height="120" viewBox="0 0 230 120" role="img" aria-label="A feature branch splitting from main and merging back">
  <path d="M10 88 H220" stroke="#B9C2CE" stroke-width="3" fill="none" stroke-linecap="round"/>
  <path d="M55 88 C80 88 78 34 104 34 H146 C172 34 170 88 195 88" stroke="#16775A" stroke-width="3"
        fill="none" stroke-linecap="round"/>
  <circle cx="30" cy="88" r="7" fill="#fff" stroke="#B9C2CE" stroke-width="3"/>
  <circle cx="55" cy="88" r="7" fill="#fff" stroke="#B9C2CE" stroke-width="3"/>
  <circle cx="104" cy="34" r="7" fill="#fff" stroke="#16775A" stroke-width="3"/>
  <circle cx="146" cy="34" r="7" fill="#fff" stroke="#16775A" stroke-width="3"/>
  <circle cx="195" cy="88" r="9" fill="#16775A"/>
  <text x="125" y="20" text-anchor="middle" font-size="12" fill="#5A6474"
        font-family="Schibsted Grotesk, sans-serif">your-first-fix</text>
  <text x="20" y="112" font-size="12" fill="#5A6474" font-family="Schibsted Grotesk, sans-serif">main</text>
</svg>
"""


def inject_css() -> None:
    st.markdown(CSS, unsafe_allow_html=True)


def hero() -> None:
    st.markdown(f"""
<div class="fp-hero">
  <div class="fp-hero-text">
    <h1 class="fp-title">Find your first pull request</h1>
    <p class="fp-lede">Give FirstPR a GitHub repository and tell it what you know. It reads the open
    issues, the README and the contribution guide, picks an issue you can realistically finish,
    and writes the plan: files to change, git commands and a draft PR description.</p>
  </div>
  <div class="fp-branch">{BRANCH_SVG}</div>
</div>""", unsafe_allow_html=True)


def status_line(label: str, state: str) -> str:
    cls = {"on": "", "off": " off", "bad": " bad"}[state]
    return f'<div class="fp-status"><span class="fp-led{cls}"></span>{escape(label)}</div>'


def repo_card(meta: dict) -> None:
    facts = [
        f"<span><b>{meta['stars']:,}</b> stars</span>",
        f"<span><b>{meta['forks']:,}</b> forks</span>",
        f"<span><b>{meta['open_issues']:,}</b> open issues and PRs</span>",
        f"<span>Main language <b>{escape(str(meta['language']))}</b></span>",
        f"<span>Default branch <b>{escape(meta['default_branch'])}</b></span>",
    ]
    if meta.get("archived"):
        facts.append('<span class="fp-flag">Archived: read-only, no new PRs accepted</span>')
    desc = escape(meta["description"]) if meta["description"] else "No description."
    st.markdown(f"""
<div class="fp-repo">
  <a href="{escape(meta['url'])}" target="_blank" rel="noopener">{escape(meta['full_name'])}</a>
  <p>{desc}</p>
  <div class="fp-facts">{''.join(facts)}</div>
</div>""", unsafe_allow_html=True)


def _short_args(args: dict) -> str:
    if not args:
        return ""
    s = ", ".join(f"{k}={json.dumps(v) if not isinstance(v, str) else repr(v)}" for k, v in args.items())
    return s if len(s) <= 80 else s[:77] + "..."


def step_row(ev: dict) -> None:
    """Render one agent event as a timeline row, with the raw result in an expander."""
    if ev["type"] == "notice":
        st.markdown(f"""
<div class="fp-step note"><span class="fp-dot"></span>
  <div class="fp-step-head"><span class="fp-step-n">Step {ev['step']}</span>
  <span class="fp-thought">{escape(ev['message'])}</span></div>
</div>""", unsafe_allow_html=True)
        return

    args = _short_args(ev.get("args") or {})
    args_html = f'<span class="fp-args">{escape(args)}</span>' if args else ""
    thought = f'<div class="fp-thought">{escape(ev["thought"])}</div>' if ev.get("thought") else ""
    err = ""
    if not ev["ok"]:
        err = f'<div class="fp-err">{escape(ev["result"][:300])}</div>'
    st.markdown(f"""
<div class="fp-step{'' if ev['ok'] else ' fail'}"><span class="fp-dot"></span>
  <div class="fp-step-head"><span class="fp-step-n">Step {ev['step']}</span>
  <span class="fp-tool">{escape(ev['tool'])}</span>{args_html}</div>
  {thought}{err}
</div>""", unsafe_allow_html=True)
    if ev["ok"]:
        with st.expander(f"What GitHub returned ({len(ev['result']):,} characters)"):
            st.code(_pretty(ev["result"])[:4000], language=None, wrap_lines=True)


def _pretty(text: str) -> str:
    try:
        return json.dumps(json.loads(text), indent=2)
    except (ValueError, TypeError):
        return text
