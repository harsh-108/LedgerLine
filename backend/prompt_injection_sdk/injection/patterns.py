r"""
patterns — what counts as a prompt injection
=============================================
The detection rules behind ``PATTERN_MATCHED`` in
``tbl_prompt_injection_scanner``. Each rule is a :class:`Pattern`: a name,
a compiled regex, the **category** written to the table and the
**severity** written to the audit ``ALERT_CATEGORY``.

Categories (exactly the four values the table allows)
-----------------------------------------------------
    Jailbreak   make the model drop its persona / safety role
    Override    make the model discard the instructions it was given
    Tampering   smuggle in chat-template / control markup
    NA          nothing matched (clean prompt)

Severity (existing audit alert levels — no new enums)
------------------------------------------------------
    CRITICAL    built-ins 1-5   direct override attempts
    HIGH        built-ins 6-11  structural / template injections
    NA          nothing matched

Built-in patterns (11)
----------------------
     #  name                            category    severity
     1  ignore_previous_instructions    Override    CRITICAL
     2  disregard_system_prompt         Override    CRITICAL
     3  you_are_now_role                Jailbreak   CRITICAL
     4  act_as_role                     Jailbreak   CRITICAL
     5  jailbreak_keyword               Jailbreak   CRITICAL
     6  chat_role_xml_tags              Tampering   HIGH
     7  inst_template_markers           Tampering   HIGH
     8  anthropic_turn_separator        Tampering   HIGH
     9  system_override_directive       Override    HIGH
    10  chatml_markers                  Tampering   HIGH
    11  template_placeholder_injection  Tampering   HIGH

Two regexes per rule
--------------------
Every rule carries a main ``regex`` and a whitespace-free ``compact``
regex. :mod:`normalize` rebuilds the prompt into several forms and each
rule is tried against all of them, so one rule catches every spelling of
the same attack:

    regex    matched against the raw prompt, the de-obfuscated prompt
             (leetspeak undone, look-alike letters folded, invisible
             characters stripped, spelled-o-u-t words rejoined) and
             anything decoded out of base64
    compact  matched against the prompt with all whitespace removed, so
             "Ig nore", "<sys tem>" and "< | im_start | >" are caught

``compact`` is optional — pattern 8 has none, because it is *defined* by
its newlines and removing them would destroy it.

Custom patterns
---------------
A developer adds their own rules without touching this file::

    scanner = PromptInjectionScanner()
    scanner.add_pattern(
        "leak_system_prompt",
        r"\b(?:print|repeat|show|reveal)\s+(?:your|the)\s+system\s+prompt\b",
        category="Override", severity="CRITICAL",
        compact=r"(?:print|repeat|show|reveal)(?:your|the)systemprompt",
    )

or from a YAML file (also via ``PROMPT_INJECTION_CUSTOM_PATTERNS=<path>``)::

    patterns:
      - name: leak_system_prompt
        regex: '\b(?:print|repeat|show)\s+your\s+system\s+prompt\b'
        compact: '(?:print|repeat|show)yoursystemprompt'
        category: Override
        severity: CRITICAL
        description: asks the model to echo its own instructions

``compact`` may be left out; the rule then only matches the spaced forms.

Custom rules may only use the four categories and the two severities
above: the table's CHECK constraint and the audit enums accept nothing
else.
"""

from __future__ import annotations

import os
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Iterator, Optional, Union

from .normalize import COMPACT, DECODED, NORMALIZED, RAW, SQUASHED, ScanText

# ── PATTERN_MATCHED values (tbl_prompt_injection_scanner) ───────────────
JAILBREAK = "Jailbreak"
OVERRIDE = "Override"
TAMPERING = "Tampering"
CLEAN = "NA"
CATEGORIES = (JAILBREAK, OVERRIDE, TAMPERING)

# ── severity == audit ALERT_CATEGORY values (existing enums only) ───────
CRITICAL = "CRITICAL"
HIGH = "HIGH"
NA = "NA"
SEVERITIES = (CRITICAL, HIGH)

# NA ranks lowest so the most dangerous match always wins when several hit.
SEVERITY_RANK = {CRITICAL: 2, HIGH: 1, NA: 0}

CUSTOM_PATTERNS_ENV = "PROMPT_INJECTION_CUSTOM_PATTERNS"


class PatternError(ValueError):
    """Invalid pattern definition (bad regex, category or severity)."""


@dataclass(frozen=True)
class Pattern:
    """One detection rule."""

    name: str
    regex: re.Pattern
    category: str          # Jailbreak | Override | Tampering
    severity: str          # CRITICAL | HIGH
    description: str = ""
    builtin: bool = False
    compact: Optional[re.Pattern] = None   # whitespace-free variant

    @property
    def rank(self) -> int:
        return SEVERITY_RANK[self.severity]

    def search(self, text: Union[str, ScanText]) -> Optional[str]:
        """
        The name of the first form of `text` this rule matches — "raw",
        "normalized", "compact", "squashed" or "decoded" — or None. A
        plain string is treated as raw text only.
        """
        if isinstance(text, str):
            return RAW if self.regex.search(text) else None
        if self.regex.search(text.raw):
            return RAW
        if text.normalized and self.regex.search(text.normalized):
            return NORMALIZED
        if self.compact is not None:
            if text.compact and self.compact.search(text.compact):
                return COMPACT
            # Punctuation gone too, so "previous, instructions" reads as
            # one phrase. Rules built out of punctuation (<|im_start|>,
            # [INST]) simply never match here, which is harmless.
            if text.squashed and self.compact.search(text.squashed):
                return SQUASHED
        if text.decoded and self.regex.search(text.decoded):
            return DECODED
        return None

    def __str__(self) -> str:  # never includes the scanned prompt
        return f"{self.name}({self.category}/{self.severity})"


def compile_pattern(
    name: str,
    regex: Union[str, re.Pattern],
    *,
    category: str,
    severity: str = HIGH,
    description: str = "",
    flags: int = re.IGNORECASE,
    builtin: bool = False,
    compact: Union[str, re.Pattern, None] = None,
) -> Pattern:
    """Validate and compile one rule. Raises PatternError on bad input."""
    if not name or not str(name).strip():
        raise PatternError("pattern name is required")
    if category not in CATEGORIES:
        raise PatternError(
            f"category must be one of {CATEGORIES}, got {category!r} — the "
            f"PATTERN_MATCHED column accepts nothing else"
        )
    if severity not in SEVERITIES:
        raise PatternError(f"severity must be one of {SEVERITIES}, got {severity!r}")

    def _compile(source, label):
        if source is None or isinstance(source, re.Pattern):
            return source
        try:
            return re.compile(source, flags)
        except re.error as exc:
            raise PatternError(f"pattern {name!r} has an invalid {label}: {exc}") from exc

    compiled = _compile(regex, "regex")
    compiled_compact = _compile(compact, "compact regex")
    if compiled_compact is not None and r"\s" in compiled_compact.pattern:
        raise PatternError(
            f"pattern {name!r}: the compact regex is matched against text with "
            f"all whitespace removed, so it must not contain \\s"
        )
    return Pattern(
        name=str(name).strip(),
        regex=compiled,
        category=category,
        severity=severity,
        description=description,
        builtin=builtin,
        compact=compiled_compact,
    )


def _builtin(name, regex, category, severity, description, compact=None) -> Pattern:
    return compile_pattern(
        name, regex, category=category, severity=severity,
        description=description, builtin=True, compact=compact,
    )


# ─────────────────────────────────────────────────────────────────────────
# The 11 built-ins, in the documented order
# ─────────────────────────────────────────────────────────────────────────

BUILTIN_PATTERNS: tuple[Pattern, ...] = (
    # 1 — "ignore all previous instructions", "forget everything above"
    _builtin(
        "ignore_previous_instructions",
        r"\b(?:ignore|forget|disregard)\s+"
        r"(?:all\s+|any\s+|of\s+|the\s+|your\s+|these\s+|those\s+)*"
        r"(?:previous|prior|preceding|earlier|above|initial|original|former)\s+"
        r"(?:instruction|prompt|direction|rule|command|message|guideline|context)s?\b"
        r"|\b(?:ignore|forget|disregard)\s+everything\s+(?:above|before|you\s+were\s+told)\b",
        OVERRIDE, CRITICAL,
        "discards the instructions the model was given",
        compact=r"(?:ignore|forget|disregard)(?:all|any|of|the|your|these|those)*"
                r"(?:previous|prior|preceding|earlier|above|initial|original|former)"
                r"(?:instruction|prompt|direction|rule|command|message|guideline|context)s?"
                r"|(?:ignore|forget|disregard)everything(?:above|before|youweretold)",
    ),
    # 2 — "disregard the system prompt"
    _builtin(
        "disregard_system_prompt",
        r"\b(?:disregard|ignore|forget|bypass|override|violate)\s+"
        r"(?:the\s+|your\s+|all\s+|any\s+|its\s+|his\s+|her\s+|their\s+)*"
        r"system\s+(?:prompt|message|instruction|rule|role|persona|directive)s?\b",
        OVERRIDE, CRITICAL,
        "targets the system prompt itself",
        compact=r"(?:disregard|ignore|forget|bypass|override|violate)"
                r"(?:the|your|all|any|its|his|her|their)*"
                r"system(?:prompt|message|instruction|rule|role|persona|directive)s?",
    ),
    # 3 — "you are now a/an <role>", "from now on you are DAN"
    _builtin(
        "you_are_now_role",
        r"\byou(?:\s+are|'re|’re)\s+(?:now|hereby|henceforth|from\s+now\s+on)\s+"
        r"(?:a|an|the)?\s*[A-Za-z][\w\-]{1,40}"
        r"|\bfrom\s+now\s+on,?\s+you(?:\s+are|'re|’re)\s+(?:a|an|the)?\s*[A-Za-z][\w\-]{1,40}",
        JAILBREAK, CRITICAL,
        "reassigns the model's identity",
        # (?!here) keeps "you are nowhere near done" from matching.
        compact=r"you(?:are|'re|’re)(?:now(?!here)|hereby|henceforth|fromnowon)"
                r"(?:a|an|the)?[A-Za-z][\w\-]{1,40}"
                r"|fromnowon,?you(?:are|'re|’re)(?:a|an|the)?[A-Za-z][\w\-]{1,40}",
    ),
    # 4 — "act as a/an <role>", "pretend to be a <role>"
    _builtin(
        "act_as_role",
        r"\b(?:act|acting|behave|respond|reply|answer|roleplay|role[-\s]?play|simulate)\s+as\s+"
        r"(?:a|an|the)\s+[A-Za-z][\w\-]{1,40}"
        r"|\bpretend\s+(?:to\s+be|that\s+you(?:\s+are|'re)|you(?:\s+are|'re))\s+"
        r"(?:a|an|the)\s+[A-Za-z][\w\-]{1,40}",
        JAILBREAK, CRITICAL,
        "asks the model to play another role",
        # (?<![A-Za-z]) stops "contact as a specialist" matching on "...act as a...".
        compact=r"(?<![A-Za-z])(?:act|acting|behave|respond|reply|answer|roleplay|role-?play|simulate)"
                r"as(?:an|a|the)[A-Za-z][\w\-]{2,40}"
                r"|(?<![A-Za-z])pretend(?:tobe|thatyou(?:are|'re)|you(?:are|'re))"
                r"(?:an|a|the)[A-Za-z][\w\-]{2,40}",
    ),
    # 5 — the word itself
    _builtin(
        "jailbreak_keyword",
        r"\bjail\s*[-_]?\s*break(?:s|ed|ing|er)?\b",
        JAILBREAK, CRITICAL,
        "explicit jailbreak wording",
        # No letter guard here: compacting "the jail bre ak" glues the
        # word to the one before it, and "jailbreak" cannot appear inside
        # an ordinary English word by accident.
        compact=r"jail-?_?break(?:s|ed|ing|er)?",
    ),
    # 6 — <system> / <user> / <assistant> chat-role tags
    _builtin(
        "chat_role_xml_tags",
        r"<\s*/?\s*(?:system|user|assistant|human)\s*>",
        TAMPERING, HIGH,
        "fake chat-role XML tags",
        compact=r"<\/?(?:system|user|assistant|human)>",
    ),
    # 7 — [INST] / [/INST] / [SYS] / <<SYS>> template markers
    _builtin(
        "inst_template_markers",
        r"\[\s*/?\s*(?:INST|SYS|INSTRUCTIONS?)\s*\]|<<\s*/?\s*SYS\s*>>",
        TAMPERING, HIGH,
        "Llama-style instruction template markers",
        compact=r"\[\/?(?:INST|SYS|INSTRUCTIONS?)\]|<<\/?SYS>>",
    ),
    # 8 — \n\nHuman: / \n\nAssistant: (real newlines or the literal escape).
    #     No compact form: this pattern IS its newlines.
    _builtin(
        "anthropic_turn_separator",
        r"(?:\r?\n|\\n){2}\s*(?:Human|Assistant)\s*:",
        TAMPERING, HIGH,
        "Anthropic turn separators forging a new conversation turn",
    ),
    # 9 — "system override:"
    _builtin(
        "system_override_directive",
        r"\b(?:system|admin(?:istrator)?|developer|root)\s+override\s*:",
        OVERRIDE, HIGH,
        "fake privileged override directive",
        # Same reasoning as pattern 5, and the trailing colon makes an
        # accidental hit vanishingly unlikely.
        compact=r"(?:system|admin(?:istrator)?|developer|root)override:",
    ),
    # 10 — ChatML <|im_start|> / <|im_end|>
    _builtin(
        "chatml_markers",
        r"<\|\s*im_(?:start|end)\s*\|>",
        TAMPERING, HIGH,
        "ChatML conversation markers",
        compact=r"<\|im_(?:start|end)\|>",
    ),
    # 11 — {{ ... }} template injection: one placeholder, no nested braces,
    #      bounded length, never spanning a line — so ordinary prose with
    #      stray braces does not trip it.
    #
    #      No compact form on purpose. This rule is about a placeholder a
    #      template engine would expand downstream, and "{ { x } }" is not
    #      one — Jinja and str.format need the braces adjacent, so padding
    #      defeats the attack rather than hiding it. Compacting here only
    #      invented false positives ("uses { { and } } as delimiters").
    _builtin(
        "template_placeholder_injection",
        r"\{\{\s*[^{}\r\n]{1,200}?\s*\}\}",
        TAMPERING, HIGH,
        "template placeholder that would be expanded downstream",
    ),
)

BUILTIN_NAMES: tuple[str, ...] = tuple(p.name for p in BUILTIN_PATTERNS)


# ─────────────────────────────────────────────────────────────────────────
# PatternSet — built-ins + a developer's own rules
# ─────────────────────────────────────────────────────────────────────────

class PatternSet:
    """
    An ordered, name-keyed collection of :class:`Pattern`.

    Built-ins come first and keep their documented order; custom rules are
    appended in the order they were added. A custom rule may not silently
    shadow an existing name — pass ``replace=True`` to overwrite one on
    purpose (that is also how a built-in is tuned).
    """

    def __init__(
        self,
        patterns: Optional[Iterable[Pattern]] = None,
        *,
        include_builtins: bool = True,
    ) -> None:
        self._patterns: dict[str, Pattern] = {}
        if include_builtins:
            self.extend(BUILTIN_PATTERNS)
        if patterns:
            self.extend(patterns)

    # ── contents ────────────────────────────────────────────────────

    def __len__(self) -> int:
        return len(self._patterns)

    def __iter__(self) -> Iterator[Pattern]:
        return iter(self._patterns.values())

    def __contains__(self, name: object) -> bool:
        return name in self._patterns

    def __getitem__(self, name: str) -> Pattern:
        return self._patterns[name]

    @property
    def names(self) -> tuple[str, ...]:
        return tuple(self._patterns)

    @property
    def custom(self) -> tuple[Pattern, ...]:
        return tuple(p for p in self if not p.builtin)

    # ── building ────────────────────────────────────────────────────

    def add(
        self,
        name: str,
        regex: Union[str, re.Pattern],
        *,
        category: str,
        severity: str = HIGH,
        description: str = "",
        flags: int = re.IGNORECASE,
        compact: Union[str, re.Pattern, None] = None,
        replace: bool = False,
    ) -> Pattern:
        """Add one custom rule and return it."""
        pattern = compile_pattern(
            name, regex, category=category, severity=severity,
            description=description, flags=flags, compact=compact,
        )
        return self._put(pattern, replace=replace)

    def extend(self, patterns: Iterable[Pattern], *, replace: bool = False) -> None:
        for pattern in patterns:
            self._put(pattern, replace=replace)

    def remove(self, name: str) -> None:
        """Drop a rule (a built-in your product produces false hits on)."""
        self._patterns.pop(name, None)

    def _put(self, pattern: Pattern, *, replace: bool = False) -> Pattern:
        if not isinstance(pattern, Pattern):
            raise PatternError(f"expected a Pattern, got {type(pattern).__name__}")
        if pattern.name in self._patterns and not replace:
            raise PatternError(
                f"pattern {pattern.name!r} already exists — pass replace=True to "
                f"override it on purpose"
            )
        self._patterns[pattern.name] = pattern
        return pattern

    # ── YAML ────────────────────────────────────────────────────────

    def load_yaml(self, path: Union[str, Path], *, replace: bool = False) -> int:
        """
        Add every rule from a YAML file. Returns how many were added.

        Accepts either ``{patterns: [...]}`` or a bare list; each entry needs
        ``name``, ``regex`` and ``category``, and may set ``severity``,
        ``description`` and ``compact``.
        """
        try:
            import yaml
        except ImportError as exc:  # pragma: no cover
            raise PatternError(
                "loading custom patterns from YAML needs PyYAML: pip install pyyaml"
            ) from exc

        path = Path(path)
        if not path.is_file():
            raise PatternError(f"custom pattern file not found: {path}")
        data = yaml.safe_load(path.read_text(encoding="utf-8")) or []
        entries = data.get("patterns", []) if isinstance(data, dict) else data
        if not isinstance(entries, list):
            raise PatternError(f"{path}: expected a list of patterns")

        added = 0
        for index, entry in enumerate(entries, 1):
            if not isinstance(entry, dict):
                raise PatternError(f"{path}: pattern #{index} is not a mapping")
            try:
                name, regex = entry["name"], entry["regex"]
                category = entry["category"]
            except KeyError as exc:
                raise PatternError(
                    f"{path}: pattern #{index} is missing {exc.args[0]!r}"
                ) from exc
            self.add(
                name, regex, category=category,
                severity=entry.get("severity", HIGH),
                description=entry.get("description", ""),
                compact=entry.get("compact"),
                replace=replace,
            )
            added += 1
        return added

    def load_env(self, env_var: str = CUSTOM_PATTERNS_ENV, *, replace: bool = False) -> int:
        """Load the YAML file named by `env_var`, if that variable is set."""
        path = os.getenv(env_var)
        return self.load_yaml(path, replace=replace) if path else 0

    @classmethod
    def from_yaml(
        cls, path: Union[str, Path], *, include_builtins: bool = True
    ) -> "PatternSet":
        patterns = cls(include_builtins=include_builtins)
        patterns.load_yaml(path, replace=True)
        return patterns

    # ── matching ────────────────────────────────────────────────────

    def match_with_variants(
        self, text: Union[str, ScanText], *, deobfuscate: bool = True
    ) -> list[tuple[Pattern, str]]:
        """
        Every rule that fires, paired with the form of the text it fired
        on ("raw", "normalized", "compact" or "decoded"), in this set's
        order.
        """
        if not text:
            return []
        if isinstance(text, str):
            text = ScanText.build(text, deobfuscate=deobfuscate)
        hits = []
        for pattern in self:
            variant = pattern.search(text)
            if variant is not None:
                hits.append((pattern, variant))
        return hits

    def match(
        self, text: Union[str, ScanText], *, deobfuscate: bool = True
    ) -> list[Pattern]:
        """Every rule that fires on `text`, in this set's order."""
        return [p for p, _ in self.match_with_variants(text, deobfuscate=deobfuscate)]

    @staticmethod
    def worst(matches: Iterable[Pattern]) -> Optional[Pattern]:
        """
        The match that decides PATTERN_MATCHED and the severity: highest
        severity first, ties broken by the order the rules were declared.
        """
        best: Optional[Pattern] = None
        for pattern in matches:
            if best is None or pattern.rank > best.rank:
                best = pattern
        return best

    def describe(self) -> str:
        """Configuration summary for the audit config row (no prompt text)."""
        custom = self.custom
        summary = f"patterns={len(self)} (builtin={len(self) - len(custom)}, custom={len(custom)})"
        if custom:
            summary += ": " + ", ".join(p.name for p in custom)
        return summary
