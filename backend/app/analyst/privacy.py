"""
Privacy layer for the AI analyst: what the outside AI service never sees.

Two jobs, both reversible on the server so the user still reads real
values in the answer:

1. Personal details are masked. Emails, phone numbers, PAN, Aadhaar,
   bank-account, demat and card numbers, IFSC codes, UPI ids and the
   user's own name/email are swapped for tokens like ⟦PAN_1⟧ in
   everything sent out: the user's messages and the text of documents
   and web results. The model (and the web-search provider, since queries
   are written by the model) only ever sees the token.

2. Portfolio amounts are hidden. get_portfolio gives the model weights
   and percentages; share counts and rupee amounts become placeholders
   such as ⟦URJA.NS:qty⟧. The model can quote a placeholder but cannot
   read it, and restore() puts the real number in the reply on the way
   back to the user. So the provider never learns how much money is in
   the account, and the user still sees "101 shares, -₹2,224".

One Vault lives per chat session (next to its message history), so the
same value keeps the same token across turns and the history that is
re-sent every turn stays masked.
"""

import re

OPEN, CLOSE = "\u27e6", "\u27e7"          # ⟦ ⟧: never in normal text
_TOKEN = re.compile(re.escape(OPEN) + r"([A-Za-z0-9_.:&-]{1,60})" + re.escape(CLOSE))


def _luhn(digits):
    total, alt = 0, False
    for ch in reversed(digits):
        d = int(ch)
        if alt:
            d = d * 2 - 9 if d > 4 else d * 2
        total += d
        alt = not alt
    return total % 10 == 0


def _card_ok(m):
    d = re.sub(r"\D", "", m)
    return 13 <= len(d) <= 19 and _luhn(d)


def _phone_ok(m):
    """Real numbers vary; round figures like 6000000000 (a volume) don't."""
    d = re.sub(r"\D", "", m)
    return len(set(d)) >= 4 and not re.search(r"(\d)\1{4}", d)


# (kind, pattern, validator). Order matters: long digit ids before phone
# numbers, emails before UPI ids. A named group "v" marks the sensitive
# part when keywords around it are only there for context.
_PATTERNS = [
    ("EMAIL", re.compile(r"\b[\w.+-]+@[A-Za-z0-9-]+(?:\.[A-Za-z0-9-]+)+\b"),
     None),
    ("UPI", re.compile(r"\b[\w.-]{2,}@[A-Za-z][A-Za-z0-9]{1,}\b"), None),
    ("PAN", re.compile(r"\b[A-Z]{3}[ABCFGHJLPT][A-Z]\d{4}[A-Z]\b"), None),
    ("IFSC", re.compile(r"\b[A-Z]{4}0[A-Z0-9]{6}\b"), None),
    ("DEMAT", re.compile(r"\bIN\d{6}[ -]?\d{8}\b|\b12\d{14}\b"), None),
    ("ACCOUNT", re.compile(
        r"(?i:\baccount|\ba/c|\bacct|\bacc\.?\s*no)\D{0,20}(?P<v>\b\d{9,18}\b)"),
     None),
    # cards (13-19 digits, Luhn-checked) before Aadhaar (exactly 12), or a
    # card's first 12 digits would be taken for an Aadhaar number
    ("CARD", re.compile(r"\b\d(?:[ -]?\d){12,18}\b"), _card_ok),
    ("AADHAAR", re.compile(
        r"\b[2-9]\d{3}[ -]\d{4}[ -]\d{4}\b(?![ -]?\d)"
        r"|(?i:aadhaa?r|\buid)\D{0,15}(?P<v>\b[2-9]\d{11}\b)"), None),
    # a full stop or comma may end the clause, but not continue a number
    # (98.5, 1,23,456)
    ("PHONE", re.compile(
        r"(?<![\w.,])(?:\+91[\s-]?|0)?(?P<v>[6-9]\d{4}[\s-]?\d{5})"
        r"(?!\w|[.,]\d)"), _phone_ok),
]


def _rupees(v):
    """₹ with Indian digit grouping: 104521 -> ₹1,04,521."""
    neg = v < 0
    n = f"{abs(v):.0f}"
    head, tail = n[:-3], n[-3:]
    while len(head) > 2:
        tail = head[-2:] + "," + tail
        head = head[:-2]
    s = (head + "," + tail) if head else tail
    return ("-" if neg else "") + "\u20b9" + s


def _qty(v):
    return (f"{v:,.4f}".rstrip("0").rstrip(".")) if v % 1 else f"{v:,.0f}"


class Vault:
    """Token <-> real value, for one chat session."""

    def __init__(self):
        self.real = {}          # token -> text shown to the user
        self._seen = {}         # (kind, value) -> token
        self._count = {}

    # ---------------------------------------------------- personal data
    def _token(self, kind, value):
        key = (kind, value)
        if key not in self._seen:
            n = self._count[kind] = self._count.get(kind, 0) + 1
            tok = f"{OPEN}{kind}_{n}{CLOSE}"
            self._seen[key] = tok
            self.real[tok] = value
        return self._seen[key]

    def mask_text(self, text, own=()):
        """Mask personal details in free text. own: the user's own name
        and email, masked wherever they appear."""
        if not text:
            return text
        for term, kind in own:
            if term and len(term) >= 3:
                text = re.sub(rf"(?i)(?<!\w){re.escape(term)}(?!\w)",
                              lambda m, k=kind: self._token(k, m.group(0)),
                              text)
        for kind, rx, ok in _PATTERNS:
            def sub(m, kind=kind, ok=ok):
                part = m.group("v") if "v" in m.re.groupindex and \
                    m.group("v") else m.group(0)
                if ok and not ok(part):
                    return m.group(0)
                return m.group(0).replace(part, self._token(kind, part))
            text = rx.sub(sub, text)
        return text

    # ------------------------------------------------ portfolio amounts
    def amount(self, name, value, kind="money"):
        """A named placeholder for a number the model may quote, not read."""
        if value is None:
            return None
        tok = f"{OPEN}{name}{CLOSE}"
        self.real[tok] = _rupees(value) if kind == "money" else _qty(value)
        return tok

    # ---------------------------------------------------------- restore
    def restore(self, text):
        """Real values back into a reply. A token the model invented or
        mangled becomes [hidden] rather than leaking the bracket syntax."""
        if not text:
            return text
        # a model that saw JSON escapes may echo them back
        text = text.replace("\\u27e6", OPEN).replace("\\u27e7", CLOSE)
        return _TOKEN.sub(
            lambda m: self.real.get(m.group(0), "[hidden]"), text)
