"""The wake word as Whisper spells it — vendored from the backend's
millia_langraph.services.glasses.intent (the backend keeps the canon; the
laptop's spotter asks this per word)."""

from __future__ import annotations

import re

_WAKE_FAMILY = r"(?:[ae]?m[aiey]l+[iy]?(?:ia|ea|ie|ya)|m[ie]l+a|villia|miria)"
_WAKE = re.compile(rf"^\s*(?:hey\s+|ok\s+|okay\s+)?{_WAKE_FAMILY}\b[\s,.:;!?-]*", re.IGNORECASE)
_WAKE_WORD = re.compile(rf"{_WAKE_FAMILY}", re.IGNORECASE)


_WAKE_TARGETS = ("millia", "milia")

def _edit_distance(a: str, b: str) -> int:
    prev = list(range(len(b) + 1))
    for i, ca in enumerate(a, 1):
        cur = [i]
        for j, cb in enumerate(b, 1):
            cur.append(min(prev[j] + 1, cur[j - 1] + 1, prev[j - 1] + (ca != cb)))
        prev = cur
    return prev[-1]


_PUNCT = re.compile(r"[^\w\s]", re.UNICODE)


def is_wake_word(word: str) -> bool:
    """Whether one transcribed word is "Millia" as Whisper spells it: the regex
    family, or a word ending in "a" within two edits of millia/milia. The
    laptop's spotter asks this per word; strip_wake_word asks it for the lead."""
    w = _PUNCT.sub("", word).strip().lower()
    if not w:
        return False
    if _WAKE_WORD.fullmatch(w):
        return True
    return w.endswith("a") and any(_edit_distance(w, t) <= 2 for t in _WAKE_TARGETS)
