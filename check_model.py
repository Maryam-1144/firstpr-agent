"""Quick check that your Gemini key and model work.

Usage:  GEMINI_API_KEY=... python check_model.py
"""
import os
import sys

from google import genai

key = os.environ.get("GEMINI_API_KEY")
if not key:
    sys.exit("Set the GEMINI_API_KEY environment variable first.")

model = os.environ.get("MODEL", "gemma-4-26b-a4b-it")
client = genai.Client(api_key=key)
r = client.models.generate_content(
    model=model,
    contents='Reply with ONLY this JSON: {"tool": "list_issues", "args": {}}',
)
print(f"{model} replied:\n{r.text}")
