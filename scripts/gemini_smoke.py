"""
Manual check that the Gemini key and model name work.

    python scripts/gemini_smoke.py

Deliberately not under tests/: it makes a real API call, so it must not run
as part of the test suite.
"""

import os
from dotenv import load_dotenv
from google import genai

load_dotenv()

client = genai.Client(api_key=os.getenv("GEMINI_API_KEY"))

response = client.models.generate_content(
    model="gemini-3.5-flash",
    contents="Say hello in one short sentence."
)

print(response.text)