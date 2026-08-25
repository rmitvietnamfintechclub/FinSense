# AI Confidence Rubric

## Why this document exists

`ai_confidence` is written on every extraction and gates every one of them, and
until now it had no written criteria at all. An undefined number in `[0.0, 1.0]`
invites the same drift the sentiment rubric was written to stop: the model settles
on a house average, or moves the number in response to prompt wording rather than
anything about the article.

Embedding this rubric into the prompt template is a **later** step of the parent
ticket. This document does not modify any prompt.

## Source of truth

`PipelineSettings.AI_CONFIDENCE_THRESHOLD` in
[`backend/core/config.py`](../../backend/core/config.py) is the **code-side source
of truth** for the inclusion cut. This document and that value are a **matched
pair** and **must change together** — moving the band edges here without moving the
threshold, or vice versa, is a defect, not a drift to reconcile later.

**No band-edge constants module exists for confidence**, deliberately. The sentiment
rubric has [`backend/core/buckets.py`](../../backend/core/buckets.py) because its
bands are consumed at read time to label scores. Confidence bands are not: the only
thing code ever does with a confidence value is compare it to the single threshold
scalar. The band edges below are a labelling aid, and adding a constants module for
them would create a second source of truth for no consumer. This asymmetry with
`SENTIMENT.md` is intentional — please don't "fix" it.

---

## Confidence measures observable article properties, not the model's certainty

**Do not ask the model how sure it is.** Self-reported LLM confidence is
well-documented as poorly calibrated and prompt-sensitive — it tracks the phrasing
of the question more than the difficulty of the task. This is a settled finding, not
a house preference, and it is the reason every criterion in this document is written
against something a second reader can check by looking at the article.

Each criterion asks about a property of the text:

- **Identification** — is the entity named explicitly (ticker code, unambiguous
  legal name), or by a bare brand name, or only implied?
- **Centrality** — is the entity a subject the article makes claims about, or a name
  in a list?
- **Attribution** — are material claims sourced to a filing, a named official, a
  regulator, a named analyst? Or are they unattributed?
- **Text integrity** — is the scraped body complete and prose-bearing, or truncated,
  paywalled, or mostly navigation and price tables?
- **Determinability** — is there evaluative framing that can actually be read?

- Valid: *"The company is named only inside a 12-ticker market roundup, with no
  claim specific to it."*
- Invalid: *"The model was not very sure about this one."*

A labeler and the model should be able to reach the same band from the same article.
That is the whole test.

---

## Confidence Rubric

Four bands, contiguous, non-overlapping, jointly covering the full `[0.0, 1.0]`
domain. Four rather than five because the observable properties above yield four
genuinely distinguishable states; a fifth would ask labelers to split a distinction
the text does not carry.

| Range | Label | Aggregation |
|---|---|---|
| `[0.0, 0.2)` | `unusable` | **excluded** |
| `[0.2, 0.5)` | `weak` | **excluded** |
| `[0.5, 0.8)` | `solid` | included |
| `[0.8, 1.0]` | `high` | included |

**Inclusivity convention.** Every band is closed at its lower bound and open at its
upper bound, except the top band, which is closed at `1.0`. Unlike the sentiment
scale there is no meaningful centre to be symmetric about, so the simple rule
applies throughout. This convention is chosen to agree with the code: a value
exactly at the threshold is **included**, which is what `confidence >= threshold`
already does (see [Excluded bands](#excluded-bands-and-why)).

The two outer bands are deliberately narrow. `unusable` and `high` are both strong
claims that require clear evidence in the text; the middle two bands are where
ordinary articles are expected to land.

---

### `[0.0, 0.2)` — `unusable`

The content is not a usable article. Scrape failure, paywall stub, near-empty body,
navigation and boilerplate only, or a pure price/ticker table carrying no prose. Also
lands here when the text is a genuine article but concerns no `Ticker` or `Concept`
member at all, so there is nothing in the closed vocabulary for it to be about.

No entity can be identified as a subject, so there is no extraction to have
confidence in.

**Example:** `[example pending real data]`

---

### `[0.2, 0.5)` — `weak`

The article is readable, but the extraction rests on inference rather than on what
the text states. Any one of these is sufficient:

- The entity appears only inside a list or market roundup, with no claim specific to
  it.
- The entity name maps ambiguously to more than one `Ticker` member and the text does
  not disambiguate (see [Ticker disambiguation](#ticker-disambiguation)).
- The material claims are unattributed rumour or speculation.
- The body is substantially truncated, so the framing may reverse in the part that
  was not scraped.

The article is real; the *reading of it* is a guess.

**Example:** `[example pending real data]`

---

### `[0.5, 0.8)` — `solid`

A complete, prose-bearing news report. The entity is identified unambiguously, is a
genuine subject of at least one specific claim, and the material claims are either
attributed or reported as plain fact rather than speculation. Residual imprecision
is fine here — a report that is clearly about the entity but hedges on magnitude, or
covers it as one of two or three co-subjects, belongs in this band.

This is the default landing place for ordinary, competent financial reporting.

**Example:** `[example pending real data]`

---

### `[0.8, 1.0]` — `high`

Everything required for `solid`, plus all three of:

- The entity is the article's **primary** subject, not one of several.
- Identification is explicit — ticker code, or a full legal name with no other
  `Ticker` member it could denote.
- The material claims carry **named** attribution: a company filing or board
  resolution, a named executive, a regulator, an exchange notice, or a named analyst
  or institution.

Reserve this band. An article being clear is not enough; the sourcing has to be
checkable.

**Example:** `[example pending real data]`

---

## Ticker disambiguation

Vietnamese financial coverage routinely refers to companies by group or brand name
where the group has more than one listed member in our closed vocabulary. The
extraction output is schema-constrained to `Ticker`
([`backend/core/enums.py`](../../backend/core/enums.py)), so **the model cannot emit
"ambiguous"** — it is forced to pick one member, and a wrong pick is downstream
indistinguishable from a right one. Confidence is the only channel that can carry
this doubt. **Unresolved identity lowers the band.**

Two real cases, both verified against the current 30-member enum:

- **"Masan"** — could denote `MSN` (Masan Group) or `MCH` (Masan Consumer). Both are
  live enum members, so a bare "Masan" with no further qualification is genuinely
  undecidable.
- **The Vin- family** — `VIC` (Vingroup), `VHM` (Vinhomes), `VRE` (Vincom Retail) and
  `VPL` (Vinpearl) are all live enum members. Coverage that says only "Vingroup" while
  describing a residential property development does not settle whether the subject is
  the parent or the subsidiary.

**Rule.** If the entity string could map to more than one `Ticker` member and the
article does not resolve it — by ticker code, full legal name, or an unmistakable
description of the specific business — cap the band at `weak` `[0.2, 0.5)`, which
excludes it from aggregation.

**One important limit on that rule.** Because confidence is a single float per source
(see [The single article-level value](#the-single-article-level-value)), capping for
one ambiguous entity also suppresses every other, correctly identified entity in the
same response. So apply the cap only when the ambiguous entity is the article's
**primary subject**. When the ambiguity attaches to an incidental mention, leave the
band where the primary subject puts it and let the audit panel handle the incidental
row — suppressing a whole good extraction to flag one marginal name costs more signal
than it saves.

---

## Sector articles: the concept/ticker asymmetry

A sector-wide article — banking credit growth, steel export tariffs, a property-market
regulation — is *strong* evidence about a `Concept` and *weak* evidence about any
individual member ticker it happens to name.

This is a real asymmetry, and the schema cannot express it: `ai_confidence` is one
float per source, shared across that source's entire `ticker_sentiments[]` and
`concept_sentiments[]`. **This document does not propose changing that.** What
follows is a reading convention for humans, not a specification for code.

**Guidance for scoring.** Score the float on the extraction the article actually
supports — for a sector piece, that is the concept extraction. A well-sourced,
clearly-framed sector article should reach `solid` or `high` on the strength of its
concept reading, and it should not be marked down merely because the tickers it lists
in passing are weakly evidenced.

**Guidance for the audit panel.** The consequence is that a sector article's
per-ticker rows carry a confidence number that was earned by the concept reading, not
by them. A reviewer looking at those rows should treat them as **less reliable than
the stored number implies**, and should expect that a ticker appearing only in a
sector piece's enumeration is a weaker signal than the same number attached to a
company-specific article. When correcting such an event, the per-ticker rows are the
ones to scrutinise first.

This is exactly the kind of judgement the audit panel exists to apply, which is why
it is written here as guidance to a reader rather than pushed into the pipeline.

---

## The single article-level value

`ai_confidence` is **one float per source**, covering that source's whole response.
It is not per entity and this document does not propose making it so.

**Rule: judge the article on its primary subject.** Identify what the article is
principally about and score the confidence of *that* extraction. Secondary entities
inherit the number whether or not they individually deserve it — that is a known and
accepted consequence of the schema, not an oversight to work around.

The two sections above are the two places this rule bites, and each states how to
resolve it: cap for ambiguity only when the ambiguous entity is primary; for sector
articles, score the concept and let the audit panel discount the incidental tickers.

**No counterexample has been checked against real data.** The parent ticket asks that
a case where the primary-subject rule produces a clearly wrong result be flagged here
rather than quietly replaced with a different rule. `event_clusters` was empty when
this was written, so no such case could be looked for. **This rule is provisional
until it has been run against real extractions** — the most likely failure shape to
watch for is an article with two genuinely co-equal subjects, where "primary" is not
a well-defined question and whichever answer is picked mislabels the other.

---

## Excluded bands, and why

`unusable` `[0.0, 0.2)` and `weak` `[0.2, 0.5)` are excluded from aggregation.
`AI_CONFIDENCE_THRESHOLD = 0.5` is the lower bound of `solid`, the lowest included
band.

The reasoning turns on the fact that confidence does **two** jobs in
[`confidence_weighted_avg`](../../backend/core/formulas.py):

```python
if confidence < threshold:      # (1) a gate
    continue
weighted_sum += score * confidence   # (2) and the weight itself
```

Because of job (2), a merely *imprecise* source does not need to be excluded — it
already contributes proportionally little, and the average handles it gracefully.
That is what makes the gate's purpose specific: it is not there to downweight weak
evidence, it is there to reject input that **is not evidence about the entity at
all**.

- `unusable` fails because there is no article-shaped content to read. Including it
  at any weight injects a reading of nothing.
- `weak` fails for a subtler and more important reason: an inference-based extraction
  is not a low-precision measurement of the right quantity, it is potentially a
  measurement of the **wrong entity** — the wrong half of the Masan group, or a
  company that was only listed in a roundup. Averaging that in does not add noise that
  cancels; it adds a confident-looking number about something else. No weight is small
  enough to make that safe.

`solid` is included because, by construction, its criteria establish that the article
does make a checkable claim about the identified entity. From there, precision is a
matter of degree, and the weighting handles degree.

**When everything is excluded.** If no source for an entity reaches the threshold,
`confidence_weighted_avg` returns `None` and the entity's aggregated score is stored
as `null` — "no confident read", which is a distinct state from a confident `0.0`.
`SENTIMENT.md` documents that distinction and it is not repeated here.

**Effect of this rubric on the existing default.** The threshold was previously
`0.4`, a value with no written justification. Setting it to `0.5` makes it slightly
stricter and, more importantly, gives it a meaning: it is now exactly the
`weak`/`solid` boundary, so it moves only when that boundary moves.

---

## Examples (pending real data)

Every example slot in this document is empty and marked `[example pending real
data]`. This is intentional and is a **blocking gap for sign-off**.

Rubric examples must be real scraped article text drawn from
`event_clusters.source_breakdown.representative_article.content_fed_to_ai`, and each
must be cited with its `cluster_id` and source (CafeF / VnExpress) so it stays
traceable. At the time of writing, `event_clusters` contained **0 documents**, as did
`articles` — there was no real text to draw on anywhere in the
database.

No example has been invented, paraphrased, or approximated to fill the gap, and none
has been borrowed from `SENTIMENT.md` — those were selected to illustrate tone, which
is a different question from the one this document asks. Once the pipeline has
populated `event_clusters`, fill each slot from real content and cite it.

The ticker-disambiguation cases (`MSN`/`MCH`, the Vin- family) are **not** examples in
this sense — they are statements about the contents of the `Ticker` enum, verified
against [`backend/core/enums.py`](../../backend/core/enums.py) at the time of writing,
and need no article to support them. Real article examples for those cases are still
pending like every other slot.
