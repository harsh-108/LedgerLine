"""
scanner — the verdict behind every row of tbl_prompt_injection_scanner
=======================================================================
Pure detection: a user's prompt in, a verdict out. No database, no
network — so it is cheap to call, easy to unit-test, and safe to run on
the request path before anything else happens.

**Prompts only.** This SDK guards what the user types, before it reaches
the LLM, the RAG retriever or anything else. It does not scan the model's
answer: a prompt that fails is stopped here, so there is no answer to
scan. That is why there is no ``source`` column.

    from prompt_injection_sdk.injection.scanner import PromptInjectionScanner

    scanner = PromptInjectionScanner()
    result = scanner.scan(user_query)
    if result.blocked:
        return result.block_message        # formal refusal, nothing forwarded

One :class:`ScanResult` maps 1:1 onto the columns the scanner table
records for that scan:

    PATTERN_MATCHED  result.pattern_matched   Jailbreak | Override | Tampering | NA
    RISK_SCORE       result.risk_score        1 when any pattern fired, else 0
    FLAG             result.flag              Block | Allow

plus ``result.severity`` (CRITICAL | HIGH | NA), which becomes the audit
ALERT_CATEGORY, and ``result.pattern_names`` — the only thing about the
prompt that is ever written to a log or an audit message. The prompt text
itself is never stored.

When several rules fire, the most severe one decides PATTERN_MATCHED and
the severity; every name that fired is still reported in
``pattern_names``.

Persisting the verdict is :mod:`scanner_client` (``scan_prompt``).
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Optional, Sequence, Union

from .normalize import RAW, ScanText
from .patterns import CLEAN, HIGH, NA, Pattern, PatternSet, SEVERITIES

# FLAG values, spelled exactly as the table's CHECK constraint has them.
ALLOW = "Allow"
BLOCK = "Block"

# What the user sees instead of an answer. Formal, says what happened
# without coaching anyone on how to get around it, and points at a way
# forward. Newlines become separate paragraphs in a chat UI.
BLOCKED_PROMPT_MESSAGE = (
    "I'm not able to process that request.\n\n"
    "Your message contains instructions that attempt to change how this "
    "assistant operates, which is not permitted.\n\n"
    "Please rephrase your question around the information you need, and I "
    "will be glad to help."
)


@dataclass
class ScanResult:
    """The verdict for one user prompt."""

    pattern_matched: str                     # Jailbreak | Override | Tampering | NA
    severity: str                            # CRITICAL | HIGH | NA
    risk_score: int                          # 1 | 0
    flag: str                                # Block | Allow
    matched: tuple[Pattern, ...] = ()
    text_length: int = 0
    block_message: str = ""                  # what to reply with when blocked
    variant: str = ""                        # which form of the text matched
    scan_id: Optional[int] = None            # set after the row is inserted

    @property
    def is_injection(self) -> bool:
        return bool(self.matched)

    @property
    def obfuscated(self) -> bool:
        """
        True when the match only showed up after de-obfuscation — the
        prompt was leetspoken, padded, spelled out, written with
        look-alike letters, or base64-encoded.

        Worth surfacing to whoever reviews the Block rows: a literal hit
        can be a curious employee, but nobody disguises a question by
        accident.
        """
        return bool(self.matched) and self.variant not in ("", RAW)

    @property
    def blocked(self) -> bool:
        return self.flag == BLOCK

    @property
    def pattern_names(self) -> tuple[str, ...]:
        """Names only — never the prompt that matched them."""
        return tuple(p.name for p in self.matched)

    def summary(self) -> str:
        """One safe line for an audit MESSAGE or a log record."""
        if not self.matched:
            return "No injection pattern matched"
        disguise = f", obfuscated ({self.variant})" if self.obfuscated else ""
        return (
            f"{self.pattern_matched} injection detected ({self.severity})"
            f"{disguise}, {self.flag.lower()}ed; "
            f"pattern(s): {', '.join(self.pattern_names)}"
        )


class PromptInjectionScanner:
    """
    Matches a user's prompt against the built-in patterns plus any custom
    rules.

    Parameters
    ----------
    patterns : a ready-made :class:`PatternSet`; built when omitted.
    custom_patterns : extra rules to add, as ``(name, regex, category, ...)``
        mappings or :class:`Pattern` objects.
    include_builtins : False leaves only your own rules in place.
    custom_patterns_file : YAML file of extra rules (see patterns.py).
        Defaults to ``PROMPT_INJECTION_CUSTOM_PATTERNS`` when that is set.
    block_severities : which severities set FLAG='Block'. Both by default,
        so anything that matches is blocked; pass ``("CRITICAL",)`` to
        block only direct override attempts and merely record the rest.
    blocked_message : the reply a blocked user gets, on
        ``result.block_message``. Override it to match your product's
        voice or to name your support team.
    deobfuscate : also match each rule against the de-obfuscated prompt
        (see :mod:`normalize`) — leetspeak, look-alike letters, invisible
        characters, spelled-o-u-t words, padding inside words, base64.
        On by default. False falls back to literal matching only, if a
        normalization rule ever proves too eager for your traffic.
    """

    def __init__(
        self,
        *,
        patterns: Optional[PatternSet] = None,
        custom_patterns: Optional[Iterable[Union[Pattern, dict]]] = None,
        include_builtins: bool = True,
        custom_patterns_file: Optional[Union[str, Path]] = None,
        block_severities: Sequence[str] = SEVERITIES,
        blocked_message: str = BLOCKED_PROMPT_MESSAGE,
        deobfuscate: bool = True,
    ) -> None:
        self.deobfuscate = deobfuscate
        unknown = sorted(set(block_severities) - set(SEVERITIES))
        if unknown:
            raise ValueError(f"block_severities may only contain {SEVERITIES}, got {unknown}")
        self.block_severities = tuple(block_severities)
        self.blocked_message = blocked_message

        self.patterns = patterns if patterns is not None else PatternSet(
            include_builtins=include_builtins
        )
        if custom_patterns_file:
            self.patterns.load_yaml(custom_patterns_file, replace=True)
        else:
            self.patterns.load_env(replace=True)
        for entry in custom_patterns or ():
            if isinstance(entry, Pattern):
                self.patterns.extend([entry], replace=True)
            else:
                self.patterns.add(**{**entry, "replace": True})

    # ── custom rules ────────────────────────────────────────────────

    def add_pattern(
        self,
        name: str,
        regex: str,
        *,
        category: str,
        severity: str = HIGH,
        description: str = "",
        compact: Optional[str] = None,
        replace: bool = False,
    ) -> Pattern:
        """
        Add one custom rule. `category` must be Jailbreak, Override or
        Tampering; `severity` CRITICAL or HIGH.

        `compact` is an optional second regex, matched against the prompt
        with all whitespace removed, so your rule also survives padding
        ("Ig nore"). Write it without any ``\\s``.
        """
        return self.patterns.add(
            name, regex, category=category, severity=severity,
            description=description, compact=compact, replace=replace,
        )

    def load_patterns(self, path: Union[str, Path], *, replace: bool = False) -> int:
        """Add every rule from a YAML file. Returns how many were added."""
        return self.patterns.load_yaml(path, replace=replace)

    def remove_pattern(self, name: str) -> None:
        self.patterns.remove(name)

    # ── scanning ────────────────────────────────────────────────────

    def scan(self, text: Optional[str]) -> ScanResult:
        """
        Match a user prompt and return the verdict. Never raises on content.

        The whole prompt is searched, so position makes no difference —
        an injection buried in the middle of an otherwise ordinary
        question is caught exactly like one at the start. With
        ``deobfuscate`` on, each rule is also tried against the prompt
        with leetspeak undone, look-alike letters folded, invisible
        characters stripped, spacing removed and base64 decoded.
        """
        text = text or ""
        scan_text = ScanText.build(text, deobfuscate=self.deobfuscate)
        hits = self.patterns.match_with_variants(scan_text)
        worst = PatternSet.worst(p for p, _ in hits)

        if worst is None:
            return ScanResult(
                pattern_matched=CLEAN, severity=NA, risk_score=0, flag=ALLOW,
                matched=(), text_length=len(text),
            )
        flag = BLOCK if worst.severity in self.block_severities else ALLOW
        variant = next(v for p, v in hits if p is worst)
        return ScanResult(
            pattern_matched=worst.category,
            severity=worst.severity,
            risk_score=1,
            flag=flag,
            matched=tuple(p for p, _ in hits),
            text_length=len(text),
            block_message=self.blocked_message if flag == BLOCK else "",
            variant=variant,
        )

    def describe(self) -> str:
        """Configuration summary for the audit config row (no prompt text)."""
        blocking = "+".join(self.block_severities) or "none"
        return f"{type(self).__name__}, {self.patterns.describe()}, blocks={blocking}"
