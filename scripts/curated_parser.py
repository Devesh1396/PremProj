#!/usr/bin/env python3
"""Deterministic structural parser for curated practitioner documents.

D49. NO MODEL CALL. Not one, anywhere in this file.

### Why this exists

K09 asks a model to find the checkable assertions buried in prose. On a
hand-curated document that operation has already been performed, by a
human with clinical judgement, and running it again does not improve the
result — measured, it lost Strategy 6 entirely, dropped every
`Client decision logic` block, and fabricated all seven `mechanism`
fields from model knowledge.

So a curated source is parsed, not extracted. The structure the
practitioner wrote — `Strategy N — Name` and its fixed subsections — is
already machine-readable, and reading it is a job for a grammar.

### The grammar is a REGISTRY, not regexes buried here

`curated_grammar_rules` (migration `033`). Every rule states the construct
it recognises, an example, why the construct is REUSABLE across sections,
and which other section families are expected to use it. Adding a rule is
an INSERT (hard rule 13), and `ck_rule_justified` refuses one with an
empty justification.

**The fixture tests the parser. The parser is not fitted to the fixture.**
A construct that appears in one section and is not on the practitioner's
list of expected constructs does NOT get a rule — it becomes
`REVIEW_REQUIRED`, which reports the gap with the heading, the text and
the byte range needed to close it.

### Unknown structure fails loudly

There is no "best guess" branch. A heading no rule matches, and a
subsection whose enclosing block is not a strategy or a principle, are
both recorded with their full text and their exact span. Nothing is
skipped: a silently dropped block is precisely how Strategy 6 vanished
with nothing in the output saying so.

### Every field carries its own span

`(source_start, source_end)` are offsets into the ORIGINAL document, and
the stored text is the exact slice. That is what makes "no invented
mechanism" a test rather than an opinion: the verifier re-reads the
preserved raw file and compares. A field that cannot be found at the range
it names is a failure, and no model is asked whether it means the same
thing.

A field the source did not supply is ABSENT. It is never filled from
anywhere else.
"""
from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass, field

# One heading regex, matched over the whole document so offsets are real.
HEADING = re.compile(r'^(?P<hashes>#{1,6})[ \t]+(?P<text>.*\S)[ \t]*$', re.M)

# The strategy/principle body that precedes its first subsection. Not a
# heading, so it has no grammar rule: it is inherent to the card
# construct. Strategies 5 and 6 of the acceptance document carry their
# whole definition here, so dropping it would lose the strategy.
OPENING_FIELD = "opening_statement"


@dataclass
class Rule:
    rule_id: str
    construct: str
    pattern: str
    heading_level: int | None
    block_kind: str
    field_name: str | None
    priority: int
    regex: re.Pattern = field(init=False)

    def __post_init__(self):
        # CASE-INSENSITIVE, for every rule, deliberately.
        #
        # The acceptance run caught this: `Client decision logic` has a
        # lowercase `d` and did not match a pattern written `Decision`, so
        # Strategies 1 and 4 lost their decision logic silently -- the exact
        # failure this parser exists to prevent, reproduced by the parser.
        # `Future alternatives` was lost the same way.
        #
        # Heading capitalisation carries no meaning in this document:
        # `Decision logic`, `Client decision logic` and `Decision
        # intelligence` are one construct however they are cased, and a
        # practitioner writing the next section will not be consistent about
        # it. This is a property of heading grammars, not a patch for one
        # fixture, which is why it is applied to every rule at compile time
        # rather than as a capitalisation variant inside one pattern.
        self.regex = re.compile(self.pattern, re.IGNORECASE)


@dataclass
class Block:
    ordinal: int
    level: int
    raw_heading: str
    heading_path: str
    heading_start: int          # offset of the '#' character
    body_start: int             # first char after the heading line
    body_end: int               # start of the next heading, or EOF
    rule: Rule | None = None
    status: str = "REVIEW_REQUIRED"
    failure_reason: str | None = None
    parent_ordinal: int | None = None

    @property
    def block_kind(self) -> str | None:
        return self.rule.block_kind if self.rule else None


def load_rules(conn) -> list[Rule]:
    rows = conn.execute(
        """select rule_id, construct, pattern, heading_level, block_kind,
                  field_name, priority
             from curated_grammar_rules where active
            order by priority, rule_id""").fetchall()
    if not rows:
        raise RuntimeError(
            "curated_grammar_rules is empty. The grammar is registry data "
            "(migration 033); a parser with no rules would mark the whole "
            "document REVIEW_REQUIRED and look like a parsing failure.")
    return [Rule(*r) for r in rows]


def strip_span(text: str, start: int, end: int) -> tuple[int, int]:
    """Tighten a span onto non-whitespace so the slice IS the stored text.

    Stripping without moving the offsets is how a 'verbatim' field stops
    matching the range it claims.
    """
    while start < end and text[start].isspace():
        start += 1
    while end > start and text[end - 1].isspace():
        end -= 1
    return start, end


def segment(text: str) -> list[Block]:
    """Every heading block in the document, with real offsets."""
    heads = list(HEADING.finditer(text))
    blocks: list[Block] = []
    stack: list[tuple[int, str]] = []          # (level, heading text)

    for i, m in enumerate(heads):
        level = len(m.group("hashes"))
        raw = m.group("text").strip()
        while stack and stack[-1][0] >= level:
            stack.pop()
        stack.append((level, raw))
        blocks.append(Block(
            ordinal=i,
            level=level,
            raw_heading=raw,
            heading_path=" > ".join(h for _, h in stack),
            heading_start=m.start(),
            body_start=m.end(),
            body_end=heads[i + 1].start() if i + 1 < len(heads) else len(text),
        ))
    return blocks


def classify(blocks: list[Block], rules: list[Rule]) -> None:
    """Attach a rule to each block, or a reason why none applies."""
    for b in blocks:
        for rule in rules:                       # already priority-ordered
            if rule.heading_level and rule.heading_level != b.level:
                continue
            if rule.regex.match(b.raw_heading):
                b.rule = rule
                b.status = "PARSED"
                break
        else:
            b.failure_reason = (
                f"no rule in curated_grammar_rules matches the heading "
                f"{b.raw_heading!r} at level {b.level}. Adding one is an "
                "INSERT, and it must state why the construct is reusable "
                "rather than needed for this document.")


def attach(blocks: list[Block]) -> None:
    """Bind each subsection to the strategy or principle that owns it.

    A subsection whose enclosing block is not one of those has nowhere to
    be stored, so it is REVIEW_REQUIRED rather than attached to whatever
    came before it. Video 1's `Final Engine 7 intelligence` section
    contains a `Decision intelligence` heading that matches the decision
    rule but belongs to no strategy — guessing an owner for it is exactly
    the kind of inference this parser exists to avoid.
    """
    for i, b in enumerate(blocks):
        if b.status != "PARSED" or b.block_kind != "SUBSECTION":
            continue
        owner = None
        for prev in reversed(blocks[:i]):
            if prev.level < b.level and prev.status == "PARSED" \
                    and prev.block_kind in ("STRATEGY", "PRINCIPLE"):
                owner = prev
                break
            if prev.level < b.level:
                break                    # a nearer enclosing block, not a card
        if owner is None:
            b.status = "REVIEW_REQUIRED"
            b.rule = None
            b.failure_reason = (
                f"{b.raw_heading!r} matched a subsection rule but its "
                "enclosing block is not a strategy or a principle, so it has "
                "no owner. The parser will not infer one.")
        else:
            b.parent_ordinal = owner.ordinal


def name_span(text: str, block: Block) -> tuple[str, int, int]:
    """The strategy/principle name, as a VERBATIM slice of the heading.

    Taken from the rule's own `name` group where it has one, so the number
    and the dash are dropped by the grammar rather than by string surgery
    here — and the span still points at the real characters.
    """
    m = block.rule.regex.match(block.raw_heading)
    if m and "name" in (m.groupdict() or {}) and m.group("name"):
        inner = m.group("name")
        # Offset of the heading text within the document, plus the offset
        # of the name within the heading text.
        head_at = text.index(block.raw_heading, block.heading_start)
        at = head_at + block.raw_heading.index(inner)
        return inner, at, at + len(inner)
    head_at = text.index(block.raw_heading, block.heading_start)
    return block.raw_heading, head_at, head_at + len(block.raw_heading)


@dataclass
class ParsedField:
    field_name: str
    text_value: str
    source_start: int
    source_end: int
    heading_path: str
    block_ordinal: int | None
    provenance: str = "VERBATIM_SOURCE"
    transformation_type: str | None = None
    transformation_rule: str | None = None


@dataclass
class ParsedCard:
    kind: str                      # STRATEGY | PRINCIPLE
    ordinal: int
    name: str
    heading_path: str
    source_start: int
    source_end: int
    fields: list[ParsedField]
    family: str | None = None
    # The NAME's own span, which `name_span()` already computes and
    # `parse()` used to discard. GATE 3 offers the card name to the
    # concept resolver (D52) and a link without a byte range is not
    # provenance (D48), so the offsets are kept rather than re-derived by
    # searching the document for the string -- a name that occurs twice
    # would make that search point at the wrong occurrence.
    name_start: int | None = None
    name_end: int | None = None

    @property
    def content_hash(self) -> str:
        body = "\n".join(f"{f.field_name}={f.text_value}" for f in self.fields)
        return hashlib.sha256(
            f"{self.name}\n{body}".encode("utf-8")).hexdigest()


def parse(text: str, rules: list[Rule]) -> tuple[list[Block], list[ParsedCard]]:
    blocks = segment(text)
    classify(blocks, rules)
    attach(blocks)

    by_ordinal = {b.ordinal: b for b in blocks}
    cards: list[ParsedCard] = []

    for b in blocks:
        if b.status != "PARSED" or b.block_kind not in ("STRATEGY", "PRINCIPLE"):
            continue
        name, n_start, n_end = name_span(text, b)
        fields: list[ParsedField] = []

        # The card's own body, before its first subsection.
        s, e = strip_span(text, b.body_start, b.body_end)
        if e > s:
            fields.append(ParsedField(
                OPENING_FIELD, text[s:e], s, e, b.heading_path, b.ordinal))

        for sub in blocks:
            if sub.parent_ordinal != b.ordinal:
                continue
            ss, se = strip_span(text, sub.body_start, sub.body_end)
            if se <= ss:
                continue
            fields.append(ParsedField(
                sub.rule.field_name, text[ss:se], ss, se,
                sub.heading_path, sub.ordinal))

        # The card ends where its last owned block ends.
        owned = [by_ordinal[o.ordinal] for o in blocks
                 if o.parent_ordinal == b.ordinal]
        card_end = max([b.body_end] + [o.body_end for o in owned])
        cards.append(ParsedCard(
            kind=b.block_kind, ordinal=b.ordinal, name=name,
            heading_path=b.heading_path,
            source_start=b.heading_start, source_end=card_end,
            fields=fields, name_start=n_start, name_end=n_end))
    return blocks, cards


def verify(text: str, fields: list[ParsedField]) -> list[str]:
    """Mechanical check: every VERBATIM field IS its claimed slice.

    No normalization is applied and none is needed — the spans were
    tightened onto the text rather than the text being tidied after the
    fact. A mismatch is returned, never repaired.
    """
    problems: list[str] = []
    for f in fields:
        if f.provenance != "VERBATIM_SOURCE":
            continue
        if text[f.source_start:f.source_end] != f.text_value:
            problems.append(
                f"{f.heading_path} :: {f.field_name} does not match "
                f"source[{f.source_start}:{f.source_end}]")
    return problems
