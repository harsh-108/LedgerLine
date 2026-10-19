"""The SDK's own conftest, adapted for the vendored copy: the package is
importable from backend/ already, so no sys.path change and no .env load."""

import os

# Tests never write to the real audit watchpoint tables.
os.environ["PROMPT_INJECTION_AUDIT"] = "off"
# A stray custom-pattern file in the environment must not change what the
# built-in tests see.
os.environ.pop("PROMPT_INJECTION_CUSTOM_PATTERNS", None)

import pytest  # noqa: E402

from prompt_injection_sdk.injection.scanner import PromptInjectionScanner  # noqa: E402

IDS = dict(product_id="P02-SMART_AMS_ASST", user_id="NP", session_id="sdDs374")


@pytest.fixture
def scanner() -> PromptInjectionScanner:
    return PromptInjectionScanner()
