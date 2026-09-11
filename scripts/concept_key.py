#!/usr/bin/env python3
"""One rule for turning a phrase into a `concepts.canonical_key`.

`ck_canonical_key_shape` requires `^[A-Z][A-Z0-9_]{2,79}$`. Two places
create concepts -- `seed_ontology.py` from the curriculum and
`normalize.py` from an unmatched Engine 1 phrase -- and they were not using
the same rule. The seeder had one that satisfies the constraint; the
normalizer had `phrase_norm.upper().replace(" ", "_")`, which produced
`LARGE_POST-MEAL_GLUCOSE_EXCURSIONS` and was rejected outright by the
database.

That phrase is not an unlucky example. It is the one D2 uses to describe
what normalization is for, and the first CLIENT_NEW run hit it
immediately: C3's own suite never did, because its fixtures contain no
punctuation.
"""
from __future__ import annotations

import hashlib
import re

MAX_LEN = 80


def canonical_key(term: str) -> str:
    """A key satisfying ck_canonical_key_shape, or "" if none can be made.

    Callers that must have a key use `key_for()`; returning "" here keeps
    the seeder's existing behaviour, where an unusable term is skipped
    rather than given a made-up name.
    """
    key = re.sub(r"[^A-Za-z0-9]+", "_", term).strip("_").upper()
    key = re.sub(r"^[^A-Z]+", "", key)[:MAX_LEN]
    return key if re.fullmatch(rf"[A-Z][A-Z0-9_]{{2,{MAX_LEN - 1}}}", key) else ""


def key_for(term: str) -> str:
    """A key that always exists, deterministic for a given term.

    Used where a concept MUST be created -- an unresolved phrase has to
    land somewhere or C3 loses it. A term that yields nothing usable
    ("2026", "???") gets a hashed key rather than being dropped, and the
    hash is of the term, so the same phrase always lands on the same key
    instead of creating a new PROPOSED row on every run.
    """
    key = canonical_key(term)
    if key:
        return key
    return "PHRASE_" + hashlib.sha256(term.encode()).hexdigest()[:12].upper()


def disambiguate(key: str, term: str) -> str:
    """`key` with a deterministic suffix, for when it is taken by something else.

    Truncation at 80 characters can land two genuinely different long
    phrases on one key, and reusing a concept because its KEY matched is a
    silent merge -- exactly what CONFUSABLE_DO_NOT_MERGE exists to prevent
    (D3). Suffixing keeps them apart without inventing a human-meaningful
    name for either.
    """
    suffix = "_" + hashlib.sha256(term.encode()).hexdigest()[:6].upper()
    return key[:MAX_LEN - len(suffix)] + suffix
