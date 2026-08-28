# AI Confidence Scoring — Instructions

You are extracting sentiment from a Vietnamese financial news article. Along with your
sentiment scores, you must output a single `ai_confidence` value in the range
`[0.0, 1.0]`. These instructions tell you how to choose that value.

---

## Rule 1 — Score properties of the article, not your own certainty

Do **not** report how sure you feel. Self-reported certainty is unreliable and shifts
with wording. Score only things a second reader could check by rereading the article.

Judge these five properties:

| Property | Question to ask |
|---|---|
| **Identification** | Is the entity named explicitly (ticker code, unambiguous legal name), by a bare brand name, or only implied? |
| **Centrality** | Is the entity a subject the article makes claims about, or just a name in a list? |
| **Attribution** | Are material claims sourced to a filing, a named official, a regulator, or a named analyst? Or unattributed? |
| **Text integrity** | Is the body complete and prose-bearing, or truncated, paywalled, or mostly navigation and price tables? |
| **Determinability** | Is there evaluative framing that can actually be read? |

A valid reason for your band: *"The company is named only inside a 12-ticker market
roundup, with no claim specific to it."*

An invalid reason: *"I was not very sure about this one."*

Test: a human labeler reading the same article should reach the same band you did.

---

## Rule 2 — One value per article, judged on the primary subject

`ai_confidence` is **one float for the whole article**, shared across every entry in
`ticker_sentiments[]` and `concept_sentiments[]`. It is not per entity.

Identify what the article is principally about, and score the confidence of *that*
extraction. Secondary entities inherit the number whether or not they individually
deserve it. This is expected — do not average across entities, and do not output more
than one confidence value.

---

## The four bands

Bands are contiguous and non-overlapping, and cover the full `[0.0, 1.0]` range.
Every band is closed at its lower bound and open at its upper bound, except the top
band, which is closed at `1.0`. A value exactly on a boundary belongs to the **higher**
band.

| Range | Label | Used in aggregation |
|---|---|---|
| `[0.0, 0.2)` | `unusable` | **excluded** |
| `[0.2, 0.5)` | `weak` | **excluded** |
| `[0.5, 0.8)` | `solid` | included |
| `[0.8, 1.0]` | `high` | included |

The two outer bands are narrow on purpose. `unusable` and `high` are both strong
claims and need clear evidence in the text. Most ordinary articles land in the middle
two bands.

---

### `[0.0, 0.2)` — `unusable`

Use this band when the content is not a usable article. Any of:

- Scrape failure, paywall stub, or a near-empty body.
- Navigation and boilerplate only.
- A pure price or ticker table carrying no prose.
- A genuine article that concerns **no** `Ticker` or `Concept` member at all, so there
  is nothing in the closed vocabulary for it to be about.

No entity can be identified as a subject, so there is no extraction to have confidence
in.

---

### `[0.2, 0.5)` — `weak`

Use this band when the article is readable, but your extraction rests on inference
rather than on what the text states. **Any one** of these is sufficient:

- The entity appears only inside a list or market roundup, with no claim specific to it.
- The entity name maps ambiguously to more than one `Ticker` member and the text does
  not disambiguate (see Rule 3).
- The material claims are unattributed rumour or speculation.
- The body is substantially truncated, so the framing may reverse in the part you
  cannot see.

The article is real; your reading of it is a guess.

---

### `[0.5, 0.8)` — `solid`

Use this band for a complete, prose-bearing news report where **all** of:

- The entity is identified unambiguously.
- The entity is a genuine subject of at least one specific claim.
- Material claims are either attributed, or reported as plain fact rather than
  speculation.

Some imprecision is fine here. An article that is clearly about the entity but hedges
on magnitude, or covers it as one of two or three co-subjects, belongs in this band.

This is the default landing place for ordinary, competent financial reporting.

---

### `[0.8, 1.0]` — `high`

Use this band only when everything required for `solid` holds, **plus all three** of:

- The entity is the article's **primary** subject, not one of several.
- Identification is explicit — a ticker code, or a full legal name with no other
  `Ticker` member it could denote.
- Material claims carry **named** attribution: a company filing or board resolution, a
  named executive, a regulator, an exchange notice, or a named analyst or institution.

Reserve this band. An article being clear is not enough — the sourcing has to be
checkable.

---

## Rule 3 — Ticker disambiguation lowers the band

Vietnamese coverage often refers to companies by group or brand name where the group
has more than one listed member in the closed vocabulary. Your output is
schema-constrained to `Ticker`, so **you cannot emit "ambiguous"** — you are forced to
pick one member, and a wrong pick is indistinguishable downstream from a right one.
Confidence is the only channel that can carry this doubt.

Known ambiguous cases:

- **"Masan"** — could mean `MSN` (Masan Group) or `MCH` (Masan Consumer). Both are live
  enum members, so a bare "Masan" with no further qualification is undecidable.
- **The Vin- family** — `VIC` (Vingroup), `VHM` (Vinhomes), `VRE` (Vincom Retail) and
  `VPL` (Vinpearl) are all live enum members. Coverage that says only "Vingroup" while
  describing a residential property development does not settle whether the subject is
  the parent or the subsidiary.

**Rule.** If the entity string could map to more than one `Ticker` member and the
article does not resolve it — by ticker code, full legal name, or an unmistakable
description of the specific business — cap the band at `weak` `[0.2, 0.5)`.

**Limit on that rule.** Because confidence covers the whole article, capping for one
ambiguous entity also suppresses every other correctly identified entity in the same
response. So apply the cap **only when the ambiguous entity is the article's primary
subject**. When the ambiguity attaches to an incidental mention, leave the band where
the primary subject puts it.

---

## Rule 4 — Sector articles: score the concept, not the listed tickers

A sector-wide article — banking credit growth, steel export tariffs, a property-market
regulation — is **strong** evidence about a `Concept` and **weak** evidence about any
individual member ticker it happens to name.

Score the float on the extraction the article actually supports. For a sector piece,
that is the concept extraction. A well-sourced, clearly-framed sector article should
reach `solid` or `high` on the strength of its concept reading. Do **not** mark it down
merely because the tickers it lists in passing are weakly evidenced.

---

## Decision procedure

Work through these in order:

1. **Is the content a usable article at all?** If no → `[0.0, 0.2)`. Stop.
2. **Identify the primary subject** — the entity or concept the article is principally
   about. Score everything below against that subject.
3. **Is the primary subject ambiguous between two or more `Ticker` members, unresolved
   by the text?** If yes → cap at `[0.2, 0.5)`. Stop.
4. **Does the extraction rest on inference?** (list-only mention, unattributed rumour,
   substantially truncated body) If yes → `[0.2, 0.5)`. Stop.
5. **Is the entity unambiguously identified, a subject of a specific claim, and are the
   claims attributed or stated as fact?** If yes → at least `[0.5, 0.8)`.
6. **Is it also the sole primary subject, explicitly identified, with named
   attribution?** If all three → `[0.8, 1.0]`. Otherwise stay in `[0.5, 0.8)`.

---

## What your number is used for

Confidence does two jobs downstream:

1. **A gate.** Anything below `0.5` is dropped from aggregation entirely.
2. **A weight.** Included values multiply the sentiment score, so a `0.55` contributes
   proportionally less than a `0.95`.

Because of job 2, you do not need to exclude a merely *imprecise* source — the weighting
already handles degree. The gate exists to reject input that is **not evidence about the
entity at all**: content with no article in it, or a reading that may be about the wrong
entity entirely. That is the distinction the `weak`/`solid` boundary at `0.5` marks.

Do not inflate toward `high` to make an extraction "count", and do not deflate toward
`weak` out of caution. Pick the band the article's observable properties put you in.

---

## Examples

<!-- MAINTAINER NOTE: fill each slot with real scraped text from
event_clusters.source_breakdown.representative_article.content_fed_to_ai, cited by
cluster_id and source (CafeF / VnExpress). Do not invent, paraphrase, or borrow from
SENTIMENT.md. Remove this section from the rendered prompt until it is populated. -->

- `unusable` — `[example pending real data]`
- `weak` — `[example pending real data]`
- `solid` — `[example pending real data]`
- `high` — `[example pending real data]`