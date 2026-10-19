#!/usr/bin/env python3
"""Check the AI providers the analyst uses, one by one. Run from anywhere,
on the PC or the phone:

    python scripts/check_llm.py

Reads the same .env the server does, so it tells you what the server sees:
which keys are set, the order the analyst tries them in, and whether each
provider answers a one-word test on its own (so a broken Gemini cannot hide
behind a working Groq). Keys are never printed, only whether they are set.
Each test is one tiny request against that provider's limits.
"""
import os
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))

from app.core import envutil, llm, paths  # noqa: E402

PASS, FAIL, WARN = "[ok]  ", "[FAIL]", "[warn]"
KEYS = ("GEMINI_API_KEY", "GROQ_API_KEY", "OPENROUTER_API_KEY", "LLM_API_KEY")


def main():
    print(f"env file: {paths.ENV_FILE} "
          f"({'found' if paths.ENV_FILE.exists() else 'MISSING'})")
    for key in KEYS:
        v = envutil.get(key)
        if v:
            note = ""
            if v != v.strip() or v[:1] in "\"'" or " " in v:
                note = "  <- has spaces or quotes inside; check the line"
            print(f"{PASS} {key} is set ({len(v)} characters){note}")
        else:
            print(f"       {key} not set")
    order = envutil.get("LLM_PROVIDER_ORDER")
    print(f"       LLM_PROVIDER_ORDER = {order!r}"
          + ("" if order else "  (not set: the built-in order is used)"))
    if envutil.get("GEMINI_API_KEY") and order and "gemini" not in order:
        print(f"{WARN} GEMINI_API_KEY is set but LLM_PROVIDER_ORDER leaves "
              f"gemini out, so it is never used. Add it to that line.")

    chain = [f"{p['name']} ({p['model']})" for p in llm.providers()]
    if not chain:
        print(f"{FAIL} no provider configured: add a key to {paths.ENV_FILE}")
        sys.exit(1)
    print("\nThe analyst tries, in order:")
    for i, step in enumerate(chain, 1):
        print(f"  {i}. {step}")

    # test every provider that has a key, each on its own, including any
    # the configured order leaves out
    os.environ["LLM_PROVIDER_ORDER"] = ",".join(llm.DEFAULT_ORDER)
    names = list(dict.fromkeys(p["name"] for p in llm.providers()))
    print("\nTesting each provider on its own:")
    bad = 0
    for name in names:
        os.environ["LLM_PROVIDER_ORDER"] = name
        t = time.time()
        try:
            msg, used = llm.complete(
                [{"role": "user", "content": "Reply with the single word OK."}],
                # room for reasoning models, which think before replying
                tools=None, temperature=0, max_tokens=300)
            text = (msg.get("content") or "").strip().replace("\n", " ")[:40]
            print(f"{PASS} {name}: answered {text!r} in {time.time() - t:.1f}s")
        except Exception as e:
            bad += 1
            reason = str(e).strip().splitlines()[0][:300] if str(e) else type(e).__name__
            print(f"{FAIL} {name}: {reason}")
            if name == "gemini" and ("not found" in reason.lower()
                                     or "404" in reason):
                print(f"{WARN}   the model name may be wrong for your key: set "
                      f"GEMINI_MODEL= to a model listed in Google AI Studio")
    if order is None:
        os.environ.pop("LLM_PROVIDER_ORDER", None)
    else:
        os.environ["LLM_PROVIDER_ORDER"] = order
    print("\nAfter changing .env, restart the server: it reads the file once "
          "at start.")
    sys.exit(1 if bad else 0)


if __name__ == "__main__":
    main()
