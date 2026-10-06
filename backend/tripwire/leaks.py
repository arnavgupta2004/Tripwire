"""Deterministic detection of private specifics in outbound text."""

import re

# Tokens specific enough to identify someone: anything with a digit (IDs,
# amounts, account numbers), and canary markers.
_SPECIFIC = re.compile(r"[A-Za-z0-9][A-Za-z0-9\-_/.]*\d[A-Za-z0-9\-_/.]*|CANARY-[A-Za-z0-9]+")


def private_specifics(texts: list[str]) -> set[str]:
    return {t.lower() for text in texts for t in _SPECIFIC.findall(text) if len(t) >= 4}
