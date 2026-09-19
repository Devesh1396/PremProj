# GATE 4 — BASELINE: the current grammar against Video 14

**This file is evidence and is never replaced by an improved result.**

Run at commit `432d0c1` (fixture, answer key and prediction all already
committed), against migration `033`'s 17 rules with **nothing added or
changed**. Reproduce with `python3 testing/gate4_baseline.py`.

Every count below comes from calling `curated_parser.parse()` — the
production function — not from a second implementation of what it is
believed to do (V2).

---

## Verbatim output

```
fixture      testing/fixtures/curated/t2d_video14.md
bytes        20364
sha256       03b6577d6190dfa53f1f13ea35b0957581fed2fc5dd5764a54841948fffd6bfd
hash         MATCHES the frozen manifest
rules loaded 17 active (migration 033, unchanged)

======================================================================
COUNTS
======================================================================
structural blocks detected  61
PARSED                      1
REVIEW_REQUIRED             60
cards produced              1
fields stored               1
provider / model calls      0  (curated_parser makes none; the module imports no provider)

======================================================================
RULE USED FOR EVERY PARSED BLOCK
======================================================================
  line-ordinal   4  level 3  PRINCIPLE_NAMED      'E7 principle'

======================================================================
MATCHED A RULE, THEN REFUSED BY attach()
======================================================================
  ordinal   3  'Decision intelligence'
            'Decision intelligence' matched a subsection rule but its enclosing block is not a strategy or a principle, so it has no owner. The parser will not infer one.
  ordinal   9  'Why it attracts clients'
            'Why it attracts clients' matched a subsection rule but its enclosing block is not a strategy or a principle, so it has no owner. The parser will not infer one.

======================================================================
UNKNOWN HEADINGS / CONSTRUCT FREQUENCIES
======================================================================
    4x  L2 MERGE
    3x  L2 ADD
    2x  L2 SKIP
    2x  L3 Final E7 status
    2x  L3 Strategy tier
    1x  L1 T2D / Insulin Resistance
    1x  L2 ADD / UPGRADE
    1x  L2 Assessment Intelligence Added
    1x  L2 Claims NOT to Store as Clinical Truth
    1x  L2 Consultation Intelligence
    1x  L2 Existing Knowledge Reinforced
    1x  L2 Final Engine 7 Delta
    1x  L2 Main Practitioner Principle
    1x  L2 Market Intelligence Added
    1x  L2 One-Sentence Engine 7 Takeaway
    1x  L2 Problem-Solving Intelligence
    1x  L2 REINFORCE
    1x  L2 Video 14: *Insulin Expert: Stop Eating THIS to Fix Blood Sugar in 90 Days*
    1x  L3 ACV Does Not Replace Meal Structure
    1x  L3 ACV Protocol Guardrails
    1x  L3 ADD
    1x  L3 Activity execution
    1x  L3 Adjunct opportunity
    1x  L3 Berberine Safety / Gate
    1x  L3 Best use
    1x  L3 Claim structure:
    1x  L3 Client already exercises but remains sedentary after major meals
    1x  L3 Client asks for the fastest possible result
    1x  L3 Client cannot follow an "optimal" exercise program
    1x  L3 Client is improving faster than expected
    1x  L3 Client is not improved by 90 days
    1x  L3 Client wants ACV
    1x  L3 Client wants berberine instead of fixing diet
    1x  L3 Decision intelligence
    1x  L3 E7 reasoning
    1x  L3 Eating distribution
    1x  L3 Escalation logic
    1x  L3 Example:
    1x  L3 Important separation
    1x  L3 Intervention intensity
    1x  L3 Larger market principle
    1x  L3 MERGE
    1x  L3 Market claim observed
    1x  L3 Market expectation
    1x  L3 Our leverage
    1x  L3 PROVENANCE ONLY
    1x  L3 Post-meal opportunity
    1x  L3 Time horizon
    1x  L3 What E7 should understand
    1x  L3 When not to prioritize
    1x  L3 When potentially worth considering
    1x  L3 Why it attracts clients

======================================================================
EVERY REVIEW_REQUIRED BLOCK, WITH ITS BYTE RANGE
======================================================================
  ordinal   0  L1  [0:46]  body[46:46]  'T2D / Insulin Resistance — Engine 7 Update'
  ordinal   1  L2  [46:334]  body[125:332]  'Video 14: *Insulin Expert: Stop Eating THIS to Fix Blood Sugar in 90 Days*'
  ordinal   2  L2  [334:1318]  body[411:1316]  'ADD — Rapid Improvement Is Possible, but Timeline ≠ Biological Guarantee'
  ordinal   3  L3  [1318:1809]  body[1345:1807]  'Decision intelligence'
  ordinal   5  L2  [1924:2200]  body[1975:2198]  'ADD — Market / Client Expectation Intelligence'
  ordinal   6  L3  [2200:2227]  body[2227:2227]  'Market claim observed'
  ordinal   7  L3  [2227:2312]  body[2249:2310]  'Claim structure:'
  ordinal   8  L3  [2312:2368]  body[2326:2366]  'Example:'
  ordinal   9  L3  [2368:2562]  body[2397:2560]  'Why it attracts clients'
  ordinal  10  L3  [2562:2891]  body[2593:2889]  'What E7 should understand'
  ordinal  11  L3  [2891:3426]  body[2909:3424]  'Our leverage'
  ordinal  12  L3  [3426:3785]  body[3452:3783]  'Important separation'
  ordinal  13  L2  [3785:4565]  body[3875:4563]  'MERGE — Carbohydrate Reduction Is a Strategy Spectrum, Not One Universal Prescription'
  ordinal  14  L3  [4565:4888]  body[4587:4886]  'Escalation logic'
  ordinal  15  L2  [4888:5349]  body[4945:5347]  'SKIP — "Underground Vegetables Should Be Restricted"'
  ordinal  16  L2  [5349:5926]  body[5411:5924]  'MERGE — Do Not Fear Naturally Occurring Fat Automatically'
  ordinal  17  L2  [5926:6436]  body[5984:6434]  'REINFORCE — Earlier Energy Distribution / Late Eating'
  ordinal  18  L2  [6436:6719]  body[6512:6717]  'MERGE — Exercise Selection Must Balance Biological Value with Execution'
  ordinal  19  L3  [6719:7311]  body[6737:7309]  'E7 reasoning'
  ordinal  20  L2  [7311:7931]  body[7378:7929]  'MERGE — "Exercise Snack" as a Low-Friction Implementation Tool'
  ordinal  21  L2  [7931:8934]  body[7994:8932]  'ADD — Berberine as a Practitioner-Gated Supplement Adjunct'
  ordinal  22  L3  [8934:9126]  body[8955:9124]  'Final E7 status'
  ordinal  23  L3  [9126:9204]  body[9145:9202]  'Strategy tier'
  ordinal  24  L3  [9204:9476]  body[9244:9474]  'When potentially worth considering'
  ordinal  25  L3  [9476:9771]  body[9504:9769]  'When not to prioritize'
  ordinal  26  L3  [9771:10389]  body[9800:10387]  'Berberine Safety / Gate'
  ordinal  27  L2  [10389:11089]  body[10455:11087]  'ADD / UPGRADE — Vinegar / ACV as a Meal-Targeted Food Adjunct'
  ordinal  28  L3  [11089:11200]  body[11110:11198]  'Final E7 status'
  ordinal  29  L3  [11200:11281]  body[11219:11279]  'Strategy tier'
  ordinal  30  L3  [11281:11639]  body[11295:11637]  'Best use'
  ordinal  31  L3  [11639:11943]  body[11680:11941]  'ACV Does Not Replace Meal Structure'
  ordinal  32  L3  [11943:12741]  body[11972:12739]  'ACV Protocol Guardrails'
  ordinal  33  L2  [12741:13252]  body[12782:13250]  'SKIP — Mechanism Overload Around ACV'
  ordinal  34  L2  [13252:13335]  body[13286:13333]  'Assessment Intelligence Added'
  ordinal  35  L3  [13335:13437]  body[13353:13435]  'Time horizon'
  ordinal  36  L3  [13437:13563]  body[13465:13561]  'Intervention intensity'
  ordinal  37  L3  [13563:13659]  body[13588:13657]  'Eating distribution'
  ordinal  38  L3  [13659:13734]  body[13683:13732]  'Activity execution'
  ordinal  39  L3  [13734:13888]  body[13761:13886]  'Post-meal opportunity'
  ordinal  40  L3  [13888:14018]  body[13913:14016]  'Adjunct opportunity'
  ordinal  41  L3  [14018:14236]  body[14042:14234]  'Market expectation'
  ordinal  42  L2  [14236:14812]  body[14266:14810]  'Consultation Intelligence'
  ordinal  43  L2  [14812:14845]  body[14845:14845]  'Problem-Solving Intelligence'
  ordinal  44  L3  [14845:14998]  body[14894:14996]  'Client asks for the fastest possible result'
  ordinal  45  L3  [14998:15132]  body[15054:15130]  'Client cannot follow an "optimal" exercise program'
  ordinal  46  L3  [15132:15291]  body[15202:15289]  'Client already exercises but remains sedentary after major meals'
  ordinal  47  L3  [15291:15455]  body[15342:15453]  'Client wants berberine instead of fixing diet'
  ordinal  48  L3  [15455:15579]  body[15477:15577]  'Client wants ACV'
  ordinal  49  L3  [15579:15736]  body[15625:15734]  'Client is improving faster than expected'
  ordinal  50  L3  [15736:16073]  body[15775:16071]  'Client is not improved by 90 days'
  ordinal  51  L2  [16073:16827]  body[16103:16825]  'Market Intelligence Added'
  ordinal  52  L3  [16827:17073]  body[16856:17071]  'Larger market principle'
  ordinal  53  L2  [17073:17386]  body[17126:17384]  'Existing Knowledge Reinforced — Do Not Duplicate'
  ordinal  54  L2  [17386:17930]  body[17428:17928]  'Claims NOT to Store as Clinical Truth'
  ordinal  55  L2  [17930:17966]  body[17966:17966]  'Final Engine 7 Delta — Video 14'
  ordinal  56  L3  [17966:18762]  body[17975:18760]  'ADD'
  ordinal  57  L3  [18762:19199]  body[18773:19197]  'MERGE'
  ordinal  58  L3  [19199:19356]  body[19220:19354]  'PROVENANCE ONLY'
  ordinal  59  L2  [19356:19841]  body[19388:19839]  'Main Practitioner Principle'
  ordinal  60  L2  [19841:20298]  body[19876:20297]  'One-Sentence Engine 7 Takeaway'

======================================================================
SOURCE TEXT NOT OWNED BY ANY STORED FIELD
======================================================================
  document bytes (chars)   20298
  chars inside a stored field  95
  chars owned by NO field      20203
  Every one of those chars is inside a REVIEW_REQUIRED block listed
  above, with its heading and range. None is silently discarded.

======================================================================
AMBIGUOUS OWNERSHIP
======================================================================
  subsections attached to a card: 0

======================================================================
TRANSFORMED TEXT
======================================================================
  fields not VERBATIM_SOURCE: 0

======================================================================
PRESERVATION CHECK ON WHAT DID PARSE
======================================================================
  verify() problems: 0

======================================================================
CARDS PRODUCED
======================================================================
  PRINCIPLE 'E7 principle'  span[1809:1924]  name_span[1813:1825]
      opening_statement  [1827:1922]  VERBATIM_SOURCE
        '**Use rapid responders as evidence of possibility, not as a deadline imposed on every client.**'
```

---

## One correction to my own vocabulary, found by running this

The report prints `document bytes (chars) 20298` while the file is **20,364
bytes**. Both numbers are right and they are not the same thing: the parser's
offsets are **Python string indices — CHARACTER offsets**, and Video 14
contains multi-byte UTF-8 (`—`, `≠`, `→`, `−`, curly quotes). 66 bytes of
difference.

GATE 1 and GATE 3 describe these spans as "byte ranges" throughout, including
in `ck_link_span_is_phrase`. On Video 1 the two coincided closely enough that
nothing noticed. **They are character offsets, and every GATE 4 span in this
file is a character offset.** Nothing is broken — the spans verify, because
the same convention is used to store and to re-read them — but any future
consumer that seeks into the file with a byte offset will land in the wrong
place, and the existing documentation would have told it to.

Reported here, not fixed here: renaming the concept touches GATE 1 and GATE 3
text and constraints, and the brief scopes GATE 4 to Video 14.
