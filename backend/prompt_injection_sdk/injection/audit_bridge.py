"""
audit_bridge — prompt-injection watchpoints in the audit_client_sdk tables
===========================================================================
Every row written to ``tbl_prompt_injection_scanner`` is mirrored into
**both** audit watchpoint tables at the same time, through
``audit_client_sdk`` (an optional dependency):

  PRODUCT watchpoint  (tbl_audit_clnt_products_watchpoint)
      What happened inside one end user's request — it carries the
      product_id, user_id and session_id.

      kind    event type               raised by
      ------  -----------------------  --------------------------------
      scan    PROMPT_INJECTION_CHECK   scan_prompt() / record_scan()

  TOOL watchpoint  (tbl_audit_clnt_tool_watchpoint)
      Whether the SDK itself did its job on that scan, plus its
      configuration and maintenance.

      config  PROMPT_INJECTION_CONFIG  every scan (health), scanner
                                       loaded, scanner DB connected /
                                       failed

So one scan == one PRODUCT row + one TOOL row, written concurrently.

TOOL_ID is T010 (``PROMPT_INJECTION_AUDIT_TOOL_ID`` to override).

What goes in which column
-------------------------
    TOKEN_IN / TOKEN_OUT        left blank.
    PROMPT_ENC / RESPONSE_ENC   left blank. This SDK scans prompts only
                                and keeps no prompt content anywhere: a
                                blocked prompt never reaches the LLM, so
                                there is nothing to retain. (``record()``
                                still accepts all four, so they can be
                                filled later without reshaping anything.)
    ALERT_CATEGORY              the severity of the worst pattern that
                                matched: CRITICAL (built-ins 1-5), HIGH
                                (built-ins 6-11), NA when nothing matched.
    EVENT_STATUS (product)      ALERT when a pattern matched, SUCCESS when
                                clean, ERROR when the SDK failed.
    EVENT_STATUS (tool)         SUCCESS when the SDK did its job, ERROR
                                when it did not: the scan crashed, or the
                                insert into the scanner table failed.
    MESSAGE                     the names of the patterns that matched and
                                nothing else — never the prompt.

Switching it on/off
-------------------
  PROMPT_INJECTION_AUDIT=auto (default)  on when audit_client_sdk is installed
  PROMPT_INJECTION_AUDIT=on              on; warns if audit_client_sdk is missing
  PROMPT_INJECTION_AUDIT=off             off
  per call:                              scan_prompt(..., audit=False),
                                         ScannerClient(..., audit=False)

audit_client_sdk itself needs AUDIT_DB_DSN (insert-only login) in the
environment / .env. If it is missing, or the audit tables / INSERT grant
are missing, auditing is disabled for the process with ONE warning — an
audit problem never breaks scanning.
"""

from __future__ import annotations

import asyncio
import logging
import os
import socket
import uuid
from typing import Any, Optional, Union

from .patterns import HIGH, NA
from .scanner import ScanResult

logger = logging.getLogger(__name__)

PRODUCT = "product"
TOOL = "tool"

# kind -> (watchpoint, event type name in audit_client_sdk)
ROUTES: dict[str, tuple[str, str]] = {
    "scan": (PRODUCT, "PROMPT_INJECTION_CHECK"),
    "config": (TOOL, "PROMPT_INJECTION_CONFIG"),
}

# status -> (product event category, default alert level)
_PRODUCT_STATUS = {
    "SUCCESS": ("OPERATIONAL", NA),
    "ALERT": ("ALERT", HIGH),
    "ERROR": ("EXCEPTION", HIGH),
}

DEFAULT_TOOL_ID = "T010"
SYSTEM_USER = "SYSTEM"
UNKNOWN_USER = "UNKNOWN"
# Tool events have no user session; one id per running process groups them.
PROCESS_SESSION_ID = f"{socket.gethostname()}-{os.getpid()}-{uuid.uuid4().hex[:6]}"

_OFF = {"off", "false", "0", "no", "disabled"}
_ON = {"on", "true", "1", "yes", "enabled"}


class PromptInjectionAudit:
    """
    Records prompt-injection watchpoints. One shared instance
    (``default_audit``) is used unless a caller passes its own.

    Parameters
    ----------
    enabled : True / False to force on/off; None (default) follows
              PROMPT_INJECTION_AUDIT.
    client  : an audit_client_sdk AuditClient; defaults to its shared ``audit``.
    tool_id : TOOL_ID written on every row (product rows carry it too).
    """

    def __init__(
        self,
        *,
        enabled: Optional[bool] = None,
        client: Any = None,
        tool_id: Optional[str] = None,
    ) -> None:
        self._enabled = enabled
        self._client = client
        self._sdk: Any = None
        self._disabled_reason: Optional[str] = None
        self.tool_id = (
            tool_id or os.getenv("PROMPT_INJECTION_AUDIT_TOOL_ID") or DEFAULT_TOOL_ID
        )
        self._described: set[int] = set()

    # ── on/off ──────────────────────────────────────────────────────

    def _wanted(self) -> Optional[bool]:
        """True = required on, None = on if available, False = off."""
        if self._enabled is not None:
            return self._enabled
        mode = os.getenv("PROMPT_INJECTION_AUDIT", "auto").strip().lower()
        if mode in _OFF:
            return False
        return True if mode in _ON else None

    def _resolve(self):
        """(client, sdk module) when auditing is active, else (None, None)."""
        wanted = self._wanted()
        if wanted is False or self._disabled_reason:
            return None, None
        if self._sdk is None:
            try:
                import audit_client_sdk as sdk
            except ImportError:
                self._disabled_reason = "audit_client_sdk is not installed"
                (logger.warning if wanted else logger.info)(
                    "Prompt injection audit watchpoints disabled: %s", self._disabled_reason
                )
                return None, None
            self._sdk = sdk
            if self._client is None:
                self._client = sdk.audit
        return self._client, self._sdk

    @property
    def active(self) -> bool:
        return self._resolve()[0] is not None

    # ── core router ─────────────────────────────────────────────────

    async def record(
        self,
        kind: str,
        *,
        status: str = "SUCCESS",
        message: str,
        product_id: Optional[str] = None,
        user_id: Optional[str] = None,
        session_id: Optional[str] = None,
        alert: Optional[str] = None,
        token_in: Optional[int] = None,
        token_out: Optional[int] = None,
        prompt_enc: Optional[str] = None,
        response_enc: Optional[str] = None,
    ) -> Optional[str]:
        """
        Write one watchpoint row, choosing the table from `kind` (see
        ROUTES). Returns the audit EVENT_ID, or None when auditing is off
        or the event could not be recorded. Never raises.

        token_in / token_out / prompt_enc / response_enc are accepted so
        those columns can be filled later; record_scan leaves them unset.
        """
        if kind not in ROUTES:
            raise ValueError(f"unknown audit kind {kind!r}; expected one of {sorted(ROUTES)}")
        client, sdk = self._resolve()
        if client is None:
            return None

        watchpoint, event_type = ROUTES[kind]
        if watchpoint == PRODUCT and not product_id:
            # No product context -> it can only be an SDK/admin action.
            watchpoint, event_type = ROUTES["config"]
            message = f"[{kind}] {message}"

        try:
            if watchpoint == PRODUCT:
                category, default_alert = _PRODUCT_STATUS[status]
                return await client.log_product_event(
                    sdk.ProductEventType[event_type],
                    product_id=product_id,
                    user_id=user_id or UNKNOWN_USER,
                    tool_id=self.tool_id,
                    session_id=session_id or UNKNOWN_USER,
                    status=sdk.ProductEventStatus[status],
                    category=sdk.ProductEventCategory[category],
                    alert_category=sdk.ProductAlertCategory[alert or default_alert],
                    token_in=token_in,
                    token_out=token_out,
                    prompt_enc=prompt_enc,
                    response_enc=response_enc,
                    message=message,
                )
            tool_status = "ERROR" if status == "ERROR" else "SUCCESS"
            return await client.log_tool_event(
                sdk.ToolEventType[event_type],
                tool_id=self.tool_id,
                user_id=user_id or SYSTEM_USER,
                session_id=session_id or PROCESS_SESSION_ID,
                status=sdk.ToolEventStatus[tool_status],
                alert_category=sdk.ToolAlertCategory[
                    alert or (HIGH if status == "ERROR" else NA)
                ],
                message=message,
            )
        except Exception as exc:
            if isinstance(exc, getattr(sdk, "AuditConfigError", ())):
                # Missing AUDIT_DB_DSN / tables / INSERT grant: permanent for
                # this process — warn once, stop trying.
                self._disabled_reason = str(exc)
                logger.warning("Prompt injection audit watchpoints disabled: %s", exc)
            else:
                logger.warning("Prompt injection audit event %r not recorded: %s", kind, exc)
            return None

    # ── the one call scan_prompt makes ──────────────────────────────

    async def record_scan(
        self,
        result: Optional[ScanResult],
        *,
        product_id: str,
        user_id: str,
        session_id: str,
        error: Optional[BaseException] = None,
    ) -> tuple[Optional[str], Optional[str]]:
        """
        Mirror one scanner-table row into BOTH watchpoint tables at once.

        `result` is None when the scan never produced a verdict (it
        crashed); `error` is the exception that stopped the SDK doing its
        job — a crashed scan, or a failed insert into the scanner table.
        Either way the tool row is ERROR.

        Returns (product EVENT_ID, tool EVENT_ID); either may be None.
        """
        if error is not None:
            status, alert = "ERROR", HIGH
            message = f"Prompt injection scan failed: {type(error).__name__}"
        else:
            status = "ALERT" if result.is_injection else "SUCCESS"
            alert = result.severity
            message = result.summary()
            if result.scan_id is not None:
                message += f" [scan_id={result.scan_id}]"

        ids = dict(product_id=product_id, user_id=user_id, session_id=session_id)
        # TOKEN_IN / TOKEN_OUT / PROMPT_ENC / RESPONSE_ENC deliberately unset.
        product_row = self.record("scan", status=status, alert=alert, message=message, **ids)
        # The tool row says whether the SDK worked, never what the prompt
        # said beyond the pattern names.
        tool_row = self.record(
            "config", status="ERROR" if error is not None else "SUCCESS",
            alert=alert, message=message, **ids,
        )
        return tuple(await asyncio.gather(product_row, tool_row))  # type: ignore[return-value]

    # ── tool watchpoint helpers ─────────────────────────────────────

    async def config(
        self, message: str, *, status: str = "SUCCESS", actor: Optional[str] = None
    ) -> Optional[str]:
        return await self.record("config", status=status, message=message, user_id=actor)

    async def describe_scanner_once(self, scanner: Any) -> None:
        """Record the scanner's configuration the first time it is used."""
        key = id(scanner)
        if key in self._described or not self.active:
            return
        self._described.add(key)
        await self.config(f"Scanner loaded: {scanner.describe()}")


default_audit = PromptInjectionAudit()

AuditArg = Union[PromptInjectionAudit, bool, None]


def resolve_audit(audit: AuditArg) -> PromptInjectionAudit:
    """None -> shared default, False/True -> forced off/on, instance -> as is."""
    if audit is None:
        return default_audit
    if isinstance(audit, PromptInjectionAudit):
        return audit
    if audit is False:
        return _DISABLED
    return _FORCED_ON


_DISABLED = PromptInjectionAudit(enabled=False)
_FORCED_ON = PromptInjectionAudit(enabled=True)
