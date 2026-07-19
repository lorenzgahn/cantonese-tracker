"""Phase 0.5 spike: confirm the Anthropic SDK can authenticate via the
user's claude.ai OAuth login (`ant auth login`) rather than a metered
ANTHROPIC_API_KEY, per SPEC.md §9.

Run with no ANTHROPIC_API_KEY set:

    backend/.venv/bin/python backend/scripts/llm_auth_spike.py

Prerequisite (one-time, on the user's machine, requires an interactive
browser login — cannot be done by an agent on the user's behalf):

    ant auth login
"""

import os
import sys

import anthropic


def main() -> None:
    if os.environ.get("ANTHROPIC_API_KEY"):
        print(
            "ANTHROPIC_API_KEY is set — this spike is meant to test the "
            "OAuth-only path. Unset it to actually test `ant auth login` "
            "pickup.",
            file=sys.stderr,
        )

    client = anthropic.Anthropic()
    response = client.messages.create(
        model="claude-opus-4-8",
        max_tokens=32,
        messages=[{"role": "user", "content": "Reply with exactly: auth ok"}],
    )
    text = next((b.text for b in response.content if b.type == "text"), "")
    print(f"Response: {text!r}")
    print("OAuth pickup via `ant auth login` confirmed working." if "auth ok" in text.lower() else "Got a response, but unexpected content — inspect above.")


if __name__ == "__main__":
    main()
