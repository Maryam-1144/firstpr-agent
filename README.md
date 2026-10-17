# FirstPR Agent

A Streamlit app that helps students make their first open-source contribution.
Give it a GitHub repository and your skills; a Gemma 4 agent (via the Gemini API)
reads the repo's open issues, README and contribution guide, picks an issue that fits you,
and writes a plan: candidate issues, files to change, step-by-step instructions,
git commands and a draft PR description.

## Setup

```bash
python -m venv venv
venv\Scripts\activate          # Windows  (macOS/Linux: source venv/bin/activate)
pip install -r requirements.txt

copy .streamlit\secrets.toml.example .streamlit\secrets.toml   # macOS/Linux: cp
# then put your GEMINI_API_KEY (and optionally GITHUB_TOKEN) in secrets.toml

streamlit run app.py
```

Keys can also be set as environment variables (`GEMINI_API_KEY`, `GITHUB_TOKEN`, `MODEL`).

Without a `GITHUB_TOKEN`, GitHub allows 60 API requests per hour from your IP;
a run uses about 8–15. A read-only fine-grained token raises that to 5,000.

## Project layout

| File | What it does |
|---|---|
| `app.py` | Streamlit UI: inputs, live agent progress, results |
| `agent.py` | The agent loop and JSON parsing (no UI code, testable) |
| `github_tools.py` | Read-only GitHub API tools with retries and rate-limit handling |
| `ui.py` | Styles and HTML render helpers |
| `check_model.py` | Quick check that your API key and model respond |
| `tests/` | Offline tests: `python -m unittest discover tests` |

## Features

- Accepts `owner/repo`, full GitHub URLs or clone URLs
- Checks the repository exists, isn't archived and has issues before spending model calls
- Optional bug screenshot: the model reads it and prefers matching issues
- Live step-by-step timeline of what the agent is doing
- Plan stays on screen after downloading; download as Markdown
