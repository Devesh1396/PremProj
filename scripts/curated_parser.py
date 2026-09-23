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
    # GATE 4. Both are registry columns (migration `041`), not parser
    # branches, because both decide how far a rule reaches and a branch
    # here would be a second definition of the grammar.
    field_name_source: str = "FIXED"
    owner_kinds: tuple[str, ...] | None = None
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
        # Heading CAPITALISATION carries no meaning in this document, and a
        # practitioner writing the next section will not be consistent about
        # it: `Client decision logic` and `Client Decision Logic` are one
        # label. This is a property of heading grammars, not a patch for one
        # fixture, which is why it is applied to every rule at compile time
        # rather than as a capitalisation variant inside one pattern.
        #
        # Case-insensitivity makes two CASINGS one label. It does NOT make two
        # different LABELS one construct. This comment used to say `Decision
        # logic`, `Client decision logic` and `Decision intelligence` were
        # one construct -- Video 14 refuted that (050, D56): `Decision
        # intelligence` there is prognosis, in Video 1 it is selection, and
        # what it means is the practitioner's decision (Q1). The two
        # `decision logic` forms are SUB_DECISION_LOGIC; `Decision
        # intelligence` is SUB_DECISION, owned by strategy and principle
        # containers only.
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
    # Every rule whose pattern matches, in priority order. `rule` is the
    # one SELECTED. Keeping the others is what lets a rule that cannot
    # apply hand over instead of ending the chain -- see `attach()`.
    candidates: list[Rule] = field(default_factory=list)
    status: str = "REVIEW_REQUIRED"
    failure_reason: str | None = None
    parent_ordinal: int | None = None
    # The kind of container that was OPEN when attach() reached this block,
    # or None. Recorded from state attach() already holds, so a survey
    # asking "which labels recur across container kinds" reads the
    # production decision instead of re-implementing it (V2).
    context_kind: str | None = None
    # D58. The ordinal of the FIELD-BEARING block (the open container itself,
    # or a subsection it owns) whose field text absorbed this block, or None.
    # Set only for a block that could not change ownership: its text becomes
    # body of that field -- span and characters preserved -- and the block
    # itself stays REVIEW_REQUIRED, so the absorption is on the record
    # rather than silent.
    absorbed_into: int | None = None
    # Why a block is not recognised structure, when it is not:
    # NO_RULE, REGISTERED_NO_CONTAINER, REGISTERED_NOT_OWNABLE or
    # REGISTERED_DUPLICATE_FIELD. "Matches no rule" and "matches a registered
    # label whose container was not there" are different findings, and the
    # survey used to report both as unrecognised.
    review_class: str | None = None

    @property
    def block_kind(self) -> str | None:
        return self.rule.block_kind if self.rule else None


def load_rules(conn) -> list[Rule]:
    rows = conn.execute(
        """select rule_id, construct, pattern, heading_level, block_kind,
                  field_name, priority, field_name_source, owner_kinds
             from curated_grammar_rules where active
            order by priority, rule_id""").fetchall()
    if not rows:
        raise RuntimeError(
            "curated_grammar_rules is empty. The grammar is registry data "
            "(migration 033); a parser with no rules would mark the whole "
            "document REVIEW_REQUIRED and look like a parsing failure.")
    return [Rule(*r[:8], tuple(r[8]) if r[8] else None) for r in rows]


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
    """Every heading block in the document, with real offsets.

    NO SEMANTIC PATH IS BUILT HERE (D57). This used to push and pop a
    stack on Markdown `#` depth to produce `A > B > C`, and that path was
    persisted into blocks, cards, objects and fields and returned by
    retrieval. The canonical source states no level anywhere, so the depth
    it was built from was assigned by a model during conversion: measured,
    flattening the markers changed 41 of Video 1's 42 paths and 60 of
    Video 14's 61. Recognition had been made level-independent and the
    STORED STRUCTURE had not.

    Each block's `heading_path` starts as its own heading and nothing more.
    `derive_paths()` rebuilds it after classification from what the parser
    actually KNOWS -- which container is open -- never from depth.

    `level` survives only as SOURCE-MARKUP METADATA: the number of `#`
    characters the converter emitted. It is persisted for forensic audit
    as `curated_blocks.source_markup_depth` (051), and nothing in
    recognition, containment, paths or retrieval reads it.
    """
    heads = list(HEADING.finditer(text))
    blocks: list[Block] = []
    for i, m in enumerate(heads):
        raw = m.group("text").strip()
        blocks.append(Block(
            ordinal=i,
            level=len(m.group("hashes")),        # markup metadata only
            raw_heading=raw,
            heading_path=raw,                    # provisional; see derive_paths
            heading_start=m.start(),
            body_start=m.end(),
            body_end=heads[i + 1].start() if i + 1 < len(heads) else len(text),
        ))
    return blocks


PATH_SEPARATOR = " > "


def derive_paths(blocks: list[Block]) -> None:
    """Heading paths from PARSER STATE, after classification.

    Three cases and no others:

      * a recognised CONTAINER      -> its own heading
      * a subsection OWNED by one   -> container heading > its heading
      * anything else               -> its own heading, no parent

    The third case is deliberate. An unrecognised block has no owner the
    parser can name, and giving it the path of whatever came before would
    be inferring a hierarchy -- exactly what a converted `#` depth used to
    do silently. So the path it gets states no more than the parser knows.
    """
    by_ordinal = {b.ordinal: b for b in blocks}
    for b in blocks:
        if b.parent_ordinal is not None and b.parent_ordinal in by_ordinal:
            parent = by_ordinal[b.parent_ordinal]
            b.heading_path = parent.raw_heading + PATH_SEPARATOR + b.raw_heading
        else:
            b.heading_path = b.raw_heading


def classify(blocks: list[Block], rules: list[Rule]) -> None:
    """Attach a rule to each block, or a reason why none applies."""
    for b in blocks:
        # RECOGNITION READS THE LABEL AND NOTHING ELSE (D56, D57). The old
        # `heading_level` filter is gone rather than left inert: a filter
        # that happens to do nothing today is one migration away from
        # gating recognition on a depth the author never wrote again, and
        # `test_curated_flat` asserts no active rule carries a level.
        b.candidates = [r for r in rules                  # priority-ordered
                        if r.regex.match(b.raw_heading)]
        if b.candidates:
            b.rule = b.candidates[0]
            b.status = "PARSED"
        else:
            b.failure_reason = (
                # No depth in this message: it is PERSISTED, and a failure
                # reason that changes with the converter's `#` count would
                # make the stored structure depend on markup after all.
                f"no rule in curated_grammar_rules matches the heading "
                f"{b.raw_heading!r}. Adding one is an "
                "INSERT, and it must state why the construct is reusable "
                "rather than needed for this document.")


# Which enclosing kinds may own a subsection when the rule does not say.
# `033`'s rules predate `owner_kinds` and mean exactly this.
DEFAULT_OWNER_KINDS = ("STRATEGY", "PRINCIPLE")

# The kinds that OPEN a container. Anything else closes the one that is open.
CONTAINER_KINDS = ("STRATEGY", "PRINCIPLE", "CURATED_OBJECT")


def field_name_for(rule: Rule, block: Block) -> str:
    """The field a subsection rule would store its block under."""
    if rule.field_name_source == "HEADING":
        return slug_field_name(block.raw_heading)
    return rule.field_name


def attach(blocks: list[Block]) -> None:
    """Bind subsections to containers, and body to fields, by parser STATE.

    D58 -- THE RULE CHANGED, BECAUSE THE CANONICAL SOURCE REFUTED THE OLD ONE.

    `0df47bf` closed the open container on ANY unrecognised block. That was
    validated on the Markdown fixtures, where it held: zero recognised
    subsections followed an unrecognised block inside the same container.
    On the canonical .docx it is catastrophic. There, an emphasised BODY
    sentence is a bold paragraph exactly like a label, so

        Strategy 1 — ...            registered container  -> opens
        What the strategy means     registered            -> attaches
        <emphasised body sentence>  unrecognised          -> CLOSED IT
        Why this can be useful      orphaned
        Client decision logic       orphaned

    Independent review measured it on the real document: 21 STRATEGY
    containers attached nothing, and NONE kept `client_decision_logic` --
    the field GATE 1 exists to protect. The Markdown hid it because the
    model that produced the fixtures rendered those sentences as inline
    bold inside a paragraph rather than as boundaries.

    So ONLY REGISTERED STRUCTURE MAY CHANGE OWNERSHIP:

      * a registered CONTAINER opens one (closing any previous);
      * a registered SUBSECTION ownable by the open container attaches to it
        and becomes the field that subsequent body text belongs to;
      * a registered block that is neither (a strategy FAMILY heading)
        closes the container -- it is a stated boundary, not emphasis;
      * EVERYTHING ELSE inside an open container is ABSORBED as body of the
        current field. Its characters and span stay exactly where they are;
        the block stays REVIEW_REQUIRED with `absorbed_into` set, so an
        audit can list every unowned bold paragraph that now sits inside a
        field instead of it disappearing into one.

    What this deliberately does NOT do: tell a label from emphasis by
    length, punctuation, a trailing colon or capitalisation. Those are the
    heuristics Option 2 forbids, and nothing else in a flat document can
    tell them apart. The cost is stated rather than hidden: an unregistered
    SECTION heading is absorbed into the field before it just as an
    emphasised sentence is. That over-absorption is visible in the audit;
    the under-attachment it replaces was silent.

    A registered subsection that cannot be owned here -- a rule not
    permitted for this container kind, or a second occurrence of a field
    the container already holds -- does not change ownership either. It is
    absorbed and recorded, never attached.

    A RULE THAT CANNOT APPLY MUST NOT END THE CHAIN: every matching
    candidate is tried before a subsection is refused (D51's shape).
    """
    open_container: Block | None = None
    current: Block | None = None             # whose field body is growing
    taken: dict[int, set[str]] = {}

    def absorb(b: Block, why: str, klass: str) -> None:
        b.status = "REVIEW_REQUIRED"
        b.rule = None
        b.review_class = klass
        if current is not None:
            b.absorbed_into = current.ordinal
            b.failure_reason = (
                f"{why} It changes no ownership, so its text is kept as body "
                f"of the field it follows (block {current.ordinal}, "
                f"{current.raw_heading!r}), span and characters unchanged.")
        else:
            b.failure_reason = why

    for b in blocks:
        kind = b.block_kind
        b.context_kind = open_container.block_kind if open_container else None

        if b.status == "PARSED" and kind in CONTAINER_KINDS:
            open_container, current = b, b
            taken[b.ordinal] = {OPENING_FIELD}
            continue

        if b.status == "PARSED" and kind == "SUBSECTION":
            if open_container is None:
                b.status, b.rule = "REVIEW_REQUIRED", None
                b.review_class = "REGISTERED_NO_CONTAINER"
                b.failure_reason = (
                    f"{b.raw_heading!r} matches a REGISTERED subsection label, "
                    "but no container was open when it appeared, so it has "
                    "no owner. The label is known; its container is missing.")
                continue

            chosen, wanted = None, []
            for rule in b.candidates:
                allowed = rule.owner_kinds or DEFAULT_OWNER_KINDS
                wanted.append(allowed)
                if open_container.block_kind in allowed:
                    chosen = rule
                    break

            if chosen is None:
                need = sorted({k for a in wanted for k in a})
                absorb(b, f"{b.raw_heading!r} matches a registered subsection "
                          f"label that may be owned by {', '.join(need)}, and the "
                          f"open container is a {open_container.block_kind}.",
                       "REGISTERED_NOT_OWNABLE")
                continue

            name = field_name_for(chosen, b)
            if name in taken[open_container.ordinal]:
                absorb(b, f"{b.raw_heading!r} would be a second {name!r} field "
                          f"in {open_container.raw_heading!r}, which already "
                          "holds one. The parser will not overwrite either.",
                       "REGISTERED_DUPLICATE_FIELD")
                continue

            taken[open_container.ordinal].add(name)
            b.rule = chosen
            b.parent_ordinal = open_container.ordinal
            current = b
            continue

        if b.status == "PARSED":
            # Registered, but neither a container nor a subsection: a stated
            # boundary (a strategy FAMILY heading). It closes the container.
            open_container, current = None, None
            continue

        # Matches no rule.
        if open_container is not None:
            absorb(b, f"no rule in curated_grammar_rules matches {b.raw_heading!r}.",
                   "NO_RULE")
        else:
            b.review_class = "NO_RULE"


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
    # Where the field's NAME came from: RULE (a grammar rule recognised the
    # construct), HEADING (the AUTHOR named it and the grammar does not
    # know what it holds), BODY (the block's own opening text).
    #
    # Carried on the row rather than derived from the name, because an
    # author heading `Monitoring` slugifies onto `monitoring`, which IS a
    # registered role name. Classifying by string would report that field
    # as understood on a coincidence of spelling (migration 046).
    name_source: str = "RULE"


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


@dataclass
class ParsedObject:
    """A curated block whose primary unit is a curation DIRECTIVE.

    GATE 4. `ADD — …`, `MERGE — …`, `SKIP — …`. The disposition is the
    literal word the practitioner wrote, and `directive_start/end` point
    at those characters, so "this is a SKIP" is traceable to the source
    rather than asserted by the parser. Nothing here decides what a block
    MEANS; it records what the author already declared about it.
    """
    disposition: str
    ordinal: int
    name: str
    heading_path: str
    source_start: int
    source_end: int
    fields: list["ParsedField"]
    directive_start: int
    directive_end: int
    name_start: int
    name_end: int

    @property
    def content_hash(self) -> str:
        body = "\n".join(f"{f.field_name}={f.text_value}" for f in self.fields)
        return hashlib.sha256(
            f"{self.disposition}\n{self.name}\n{body}".encode("utf-8")).hexdigest()


@dataclass
class ParsedVerification:
    """A verification the PRACTITIONER stated, with the span that says so."""
    rule_id: str
    verification_actor: str
    verification_status: str
    statement_text: str
    source_start: int
    source_end: int


def normalize_disposition(directive: str) -> str:
    """`ADD / UPGRADE` -> `ADD_UPGRADE`. Mechanical, not interpretive.

    Upper-case, collapse whitespace, and turn the separators the author
    uses into underscores. The VERBATIM directive keeps its own span on
    the row, so the enum is a classification of text that is still
    pointed at rather than a replacement for it.
    """
    out = re.sub(r"\s*/\s*", "_", directive.strip().upper())
    return re.sub(r"\s+", "_", out)


def slug_field_name(heading: str) -> str:
    """The author's own heading, as a field name. Deterministic.

    Lower-case, non-alphanumerics to underscore, collapsed and trimmed.
    The heading itself is preserved verbatim as the field's
    `heading_path`, and the field text keeps its own span, so nothing
    about the original wording is lost by naming it this way.
    """
    slug = re.sub(r"[^a-z0-9]+", "_", heading.strip().lower()).strip("_")
    return slug or "unnamed"


def field_end(blocks: list[Block], field_block: Block) -> int:
    """Where a field's text ends: its own body, plus everything absorbed.

    D58. A block absorbed into a field (see `attach`) extends that field to
    the end of the absorbed block. Absorbed blocks always follow their field
    block directly -- any registered structure resets the field that grows --
    so the resulting span is one contiguous slice of the source and the
    stored text is still exactly that slice.
    """
    ends = [b.body_end for b in blocks if b.absorbed_into == field_block.ordinal]
    return max([field_block.body_end] + ends)


def _owned_fields(text: str, blocks: list[Block], owner: Block) -> list["ParsedField"]:
    """The owner's own body, then every subsection bound to it.

    Field-name uniqueness is decided ONCE, in `attach()`: a second occurrence
    of a field the container already holds is absorbed there, with a reason,
    rather than being attached and then dropped here. The check below is a
    guard that the two stayed in agreement, and it raises instead of
    silently refusing.
    """
    fields: list[ParsedField] = []
    taken: set[str] = set()

    s, e = strip_span(text, owner.body_start, field_end(blocks, owner))
    if e > s:
        fields.append(ParsedField(
            OPENING_FIELD, text[s:e], s, e, owner.heading_path, owner.ordinal,
            name_source="BODY"))
        taken.add(OPENING_FIELD)

    for sub in blocks:
        if sub.parent_ordinal != owner.ordinal:
            continue
        ss, se = strip_span(text, sub.body_start, field_end(blocks, sub))
        if se <= ss:
            continue
        name = field_name_for(sub.rule, sub)
        name_source = "HEADING" if sub.rule.field_name_source == "HEADING" else "RULE"
        if name in taken:
            raise RuntimeError(
                f"attach() let a second {name!r} field into "
                f"{owner.raw_heading!r}; field uniqueness is decided there and "
                "the two have disagreed.")
        taken.add(name)
        fields.append(ParsedField(
            name, text[ss:se], ss, se, sub.heading_path, sub.ordinal,
            name_source=name_source))
    return fields


def find_verifications(text: str, rules: list[tuple]) -> list[ParsedVerification]:
    """Authored verification statements, from the registry (migration 041).

    `rules` is rows of (rule_id, pattern, actor, status). The pattern is
    registry data for the same reason the heading grammar is: recognising
    a new authored construct is an INSERT, not an edit here (hard rule 13).

    The span is the matched line, stripped, and the stored text IS that
    slice — `ck_verification_span_is_statement` checks the length and the
    importer re-reads the characters. D48: a location field that is
    populated is not provenance.
    """
    found: list[ParsedVerification] = []
    for rule_id, pattern, actor, status in rules:
        for m in re.finditer(pattern, text, re.IGNORECASE):
            s, e = strip_span(text, m.start(), m.end())
            if e <= s:
                continue
            found.append(ParsedVerification(
                rule_id, actor, status, text[s:e], s, e))
    return sorted(found, key=lambda v: v.source_start)


def parse(text: str, rules: list[Rule]) \
        -> tuple[list[Block], list[ParsedCard], list[ParsedObject]]:
    blocks = segment(text)
    classify(blocks, rules)
    attach(blocks)
    derive_paths(blocks)

    by_ordinal = {b.ordinal: b for b in blocks}
    cards: list[ParsedCard] = []

    objects: list[ParsedObject] = []

    def extent(owner: Block) -> int:
        """Where the block ends: after its last owned or absorbed text (D58)."""
        owned = [by_ordinal[o.ordinal] for o in blocks
                 if o.parent_ordinal == owner.ordinal]
        return max([field_end(blocks, owner)]
                   + [field_end(blocks, o) for o in owned])

    for b in blocks:
        if b.status != "PARSED":
            continue

        if b.block_kind in ("STRATEGY", "PRINCIPLE"):
            name, n_start, n_end = name_span(text, b)
            fields = _owned_fields(text, blocks, b)
            cards.append(ParsedCard(
                kind=b.block_kind, ordinal=b.ordinal, name=name,
                heading_path=b.heading_path,
                source_start=b.heading_start, source_end=extent(b),
                fields=fields, name_start=n_start, name_end=n_end))

        elif b.block_kind == "CURATED_OBJECT":
            m = b.rule.regex.match(b.raw_heading)
            groups = m.groupdict() or {}
            head_at = text.index(b.raw_heading, b.heading_start)
            directive = groups.get("directive")
            if not directive:
                # A CURATED_OBJECT rule with no `directive` group cannot
                # say what disposition it read, and a disposition the
                # parser picked rather than read is exactly what this
                # construct exists to avoid.
                b.status = "REVIEW_REQUIRED"
                b.rule = None
                b.failure_reason = (
                    f"{b.raw_heading!r} matched a CURATED_OBJECT rule that "
                    "captures no `directive` group, so the disposition would "
                    "have to be guessed. The parser will not guess it.")
                continue
            d_at = head_at + b.raw_heading.index(directive)
            name = groups.get("name") or b.raw_heading
            n_at = head_at + b.raw_heading.index(name)
            fields = _owned_fields(text, blocks, b)
            objects.append(ParsedObject(
                disposition=normalize_disposition(directive),
                ordinal=b.ordinal, name=name, heading_path=b.heading_path,
                source_start=b.heading_start, source_end=extent(b),
                fields=fields,
                directive_start=d_at, directive_end=d_at + len(directive),
                name_start=n_at, name_end=n_at + len(name)))

    return blocks, cards, objects


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
