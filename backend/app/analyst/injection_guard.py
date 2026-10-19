"""
Prompt-injection gate for every place a user's own text reaches an AI
model: the analyst chat and the screener's "ask in English" box.

The detection is the team's prompt_injection_sdk (vendored in
backend/prompt_injection_sdk, unedited): 11 rules for jailbreaks,
instruction overrides and chat-template tampering, each matched against the
raw text and against rebuilt forms of it, so leetspeak ("1gn0re"),
look-alike letters, invisible characters, spaced-out letters and base64
are caught by the same rule. A blocked message gets the SDK's formal
refusal and goes no further: not to the model and not into the history the
analyst replays. Nothing is recorded (the owner's choice: just block).

Ledgerline's tuning, through the SDK's public API only:

- act_as_role is narrowed. The SDK blocks any "act as a <role>", which
  stopped "act as a financial advisor and tell me which stock to buy".
  Here it blocks only hostile roles ("act as an unrestricted assistant",
  "pretend you have no rules").
- leak_system_prompt is added: asking the model to print its instructions.

Documents and web results are a different case: a filing that discusses
jailbreaks would trip the user rules. They get a second scanner that never
blocks and only flags (see analyst._guard_untrusted).
"""

from prompt_injection_sdk.injection.scanner import (
    PromptInjectionScanner, ScanResult)

_HOSTILE = (r"(?:unrestricted|uncensored|unfiltered|unbound|unlimited|"
            r"jail[-\s]?broken|evil|rogue|malicious|amoral|unethical|"
            r"dan\b|do\s+anything\s+now|developer\s+mode|god\s+mode|"
            r"different\s+(?:ai|assistant|model|bot)|"
            r"another\s+(?:ai|assistant|model|bot)|not\s+an?\s+ai)")
_NO_RULES = (r"no\s+(?:rules|restrictions|limits|limitations|guidelines|"
             r"filters|boundaries|policies)")
_VERBS = (r"(?:act|acting|behave|respond|reply|answer|roleplay|"
          r"role[-\s]?play|simulate)")

ACT_AS_HOSTILE = (
    # act / respond / roleplay as (a|an|the) [up to two words] <hostile role>
    rf"\b{_VERBS}\s+as\s+(?:if\s+)?(?:(?:a|an|the|my)\s+)?"
    rf"(?:[\w\-]+\s+){{0,2}}?{_HOSTILE}"
    # act as if you have no rules / as though there were no limits
    rf"|\b{_VERBS}\s+(?:as\s+if|as\s+though|like)\s+"
    rf"(?:you\s+(?:have|had)|there\s+(?:are|were))\s+{_NO_RULES}"
    # pretend to be an unrestricted AI / pretend you are not an AI
    r"|\bpretend\s+(?:to\s+be|that\s+you(?:\s+are|'re)|you(?:\s+are|'re))\s+"
    rf"(?:(?:a|an|the)\s+)?(?:[\w\-]+\s+){{0,2}}?{_HOSTILE}"
    # pretend you have no rules
    rf"|\bpretend\s+(?:that\s+)?(?:you\s+(?:have|had)|there\s+(?:are|were))\s+"
    rf"{_NO_RULES}"
)
# the same, for the prompt with every space removed ("a c t a s ...")
ACT_AS_HOSTILE_COMPACT = (
    r"(?<![A-Za-z])(?:act|acting|behave|respond|reply|answer|roleplay|"
    r"role-?play|simulate)as(?:if)?(?:an|a|the|my)?[\w\-]{0,30}?"
    r"(?:unrestricted|uncensored|unfiltered|jailbroken|jailbroke|evil|rogue|"
    r"amoral|developermode|godmode|doanythingnow|differentai|anotherai)"
    r"|(?<![A-Za-z])(?:act|behave|respond|answer)(?:asif|asthough|like)"
    r"(?:youhave|youhad|thereare|therewere)no(?:rules|restrictions|limits|"
    r"limitations|guidelines|filters|boundaries)"
    r"|(?<![A-Za-z])pretend(?:tobe|thatyou(?:are|'re)|you(?:are|'re))"
    r"(?:an|a|the)?[\w\-]{0,30}?(?:unrestricted|uncensored|unfiltered|"
    r"jailbroken|evil|rogue|differentai|anotherai|notanai)"
    r"|(?<![A-Za-z])pretend(?:that)?(?:youhave|youhad|thereare)no(?:rules|"
    r"restrictions|limits|guidelines|filters)"
)

LEAK_SYSTEM_PROMPT = (
    r"\b(?:print|repeat|show|reveal|display|output|dump|tell\s+me|give\s+me)"
    r"\s+(?:me\s+)?(?:your|the)\s+(?:full\s+|exact\s+|original\s+|hidden\s+|"
    r"secret\s+|initial\s+)?(?:system\s+prompt|system\s+message|"
    r"initial\s+instructions|hidden\s+instructions|original\s+instructions|"
    r"instructions\s+you\s+were\s+given)"
)
LEAK_SYSTEM_PROMPT_COMPACT = (
    r"(?:print|repeat|show|reveal|display|output|dump|tellme|giveme)(?:me)?"
    r"(?:your|the)(?:full|exact|original|hidden|secret|initial)?"
    r"(?:systemprompt|systemmessage|initialinstructions|hiddeninstructions|"
    r"originalinstructions)"
)


def _tune(scanner):
    scanner.add_pattern(
        "act_as_role", ACT_AS_HOSTILE, category="Jailbreak",
        severity="CRITICAL", compact=ACT_AS_HOSTILE_COMPACT, replace=True,
        description="asks the model to take on an unrestricted or hostile "
                    "role (narrowed by Ledgerline: 'act as a financial "
                    "advisor' is a normal question here)")
    scanner.add_pattern(
        "leak_system_prompt", LEAK_SYSTEM_PROMPT, category="Override",
        severity="CRITICAL", compact=LEAK_SYSTEM_PROMPT_COMPACT,
        description="asks the model to print its own instructions")
    return scanner


# One of each for the life of the process: the SDK compiles its rules once.
_user = _tune(PromptInjectionScanner())                 # SDK refusal text
_documents = _tune(PromptInjectionScanner(block_severities=()))


def check(text) -> ScanResult:
    """Verdict on text a USER typed. result.blocked -> reply with
    result.block_message and send nothing on."""
    return _user.scan(text or "")


def flag_document(text) -> ScanResult:
    """Never blocks: for third-party text (filings, web pages). A hit means
    the text carries instructions aimed at an AI."""
    return _documents.scan(text or "")
