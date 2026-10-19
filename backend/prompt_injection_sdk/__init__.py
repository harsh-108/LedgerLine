"""Prompt Injection SDK.

    from prompt_injection_sdk.injection.scanner import PromptInjectionScanner
    from prompt_injection_sdk.injection.scanner_client import (
        ScannerClient, scan_prompt,
    )

    result = await scan_prompt(
        scanner, client, user_query,
        product_id="P02-SMART_AMS_ASST", user_id="NP", session_id="sdDs374",
    )
    if result.blocked:
        return result.block_message

Requires SCANNER_DATABASE_URL in your application's .env (your own
insert-only login). Call `await client.close()` when your application exits.
"""

__version__ = "0.1.0"
