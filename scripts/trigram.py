#!/usr/bin/env python3
"""pg_trgm's `similarity()`, in Python, for code that must not require it.

D15 says every optional extension is genuinely optional. `pg_trgm` is one
of them, and K1 broke that: `seed_ontology.py` called `similarity()` with
no capability gate and died with `UndefinedFunction` on a database without
the extension. Step 10b had proved that path worked; steps 12 and 13
regressed it and nothing noticed, because `pg_trgm` is contrib and ships
in both CI matrix images.

The obvious repair is to gate the call and generate fewer confusable pairs
when the extension is absent. This module exists so that is not necessary.
K1 seeds the SAME ontology either way, which matters more than it sounds:
a `CONFUSABLE_DO_NOT_MERGE` pair is a safety record, and an ontology whose
safety records depend on which extensions the server happened to have is
not one you can reason about.

Faithful to pg_trgm rather than merely similar. Each word is padded with
two leading blanks and one trailing blank, trigrams are the 3-character
windows of that, and similarity is the Jaccard index of the two sets:

    show_trgm('word')  ->  {"  w", " wo", "wor", "ord", "rd "}

`test_ontology_seed.py` asserts agreement with the real `similarity()`
whenever the extension IS available, over every sibling pair the seed
considers. That check is what keeps this honest; without it this file
would be a second implementation nobody compares.

NOT a replacement for the trigram TIER in normalize.py. That one searches
the whole concept table and is answered by a GIN index; pulling every
concept into Python to score it is a different operation with different
economics. It stays gated on the capability, and its absence still means
more phrases fall through to the LLM -- exactly what migration 000 says it
means.
"""
from __future__ import annotations

import re

# pg_trgm's ISWORDCHR is alphanumeric. Input reaching here has normally
# been through norm_phrase() already, which lowercases and strips
# punctuation; this does not assume that.
_WORD = re.compile(r"[0-9A-Za-z]+")


def trigrams(text: str) -> set[str]:
    """The distinct trigrams pg_trgm would extract from `text`."""
    out: set[str] = set()
    for word in _WORD.findall(text.lower()):
        padded = f"  {word} "
        out.update(padded[i:i + 3] for i in range(len(padded) - 2))
    return out


def similarity(a: str, b: str) -> float:
    """pg_trgm.similarity(a, b): |A intersect B| / |A union B|."""
    ta, tb = trigrams(a), trigrams(b)
    union = ta | tb
    if not union:
        return 0.0
    return len(ta & tb) / len(union)
