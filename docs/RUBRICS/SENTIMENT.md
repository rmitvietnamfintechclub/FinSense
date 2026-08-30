# Sentiment Score Rubric

## Why this document exists

The extraction prompt asks Gemini for a float in `[-1.0, 1.0]` and never says what
the numbers mean. With no defined scale the model invents one per call, so the same
article scores −0.3 on one run and −0.7 on the next. That drift is not model noise
to be tuned away — it is a missing specification. This document is that
specification.

This document is the **design rationale**. Its model-facing counterpart is
[`backend/pipeline/stages/extract/prompts/docs/SENTIMENT_v3.md`](../../backend/pipeline/stages/extract/prompts/docs/SENTIMENT_v3.md)
(and `SENTIMENT_v2.md` for the version before worked examples were added), which
`prompt_builder` substitutes into prompt `v2` and later at render time — pinned by
filename, so each prompt version keeps the rubric it shipped with. The two
are a matched pair: this one explains *why* the bands are where they are, that one
tells the model what to do. **A band edit here is not live until the counterpart is
edited too — and editing the counterpart requires cutting a new prompt version**, since
it changes what an already-stamped `prompt_version` sends.

## Source of truth

`BUCKETS` in [`backend/core/buckets.py`](../../backend/core/buckets.py) — one tuple of
`(low, high, label)` triples, not the separate `BUCKET_EDGES`/`BUCKET_LABELS` pair this
document originally assumed — is the **code-side source of truth**. This document and those constants are a
matched pair and **must change together** — a band edit in one without the
corresponding edit in the other is a defect, not a drift to reconcile later.

Two consequences worth stating plainly:

- **Bucket labels are never persisted to MongoDB.** Scores stay floats everywhere
  in the datastore. Buckets are derived at read time, by a future subtask. Nothing
  in this document authorises writing a label into a document.
- **No bucket-lookup function exists yet.** `buckets.py` is constants only. The
  inclusivity convention is documented there and here precisely because bare floats
  cannot carry it, and whoever writes the lookup needs it.

## The scale measures coverage tone, and nothing else

Every criterion below describes **how the coverage frames the entity**. Not price,
not returns, not what an investor should do. This is a hard project rule, and it is
the difference between a label a human can reproduce and a prediction nobody can.

- Valid: *"Coverage frames the company as the subject of a regulatory penalty."*
- Invalid: *"The stock is likely to decline."*

A story about a company whose share price fell is not automatically negative
coverage; a story reporting a fine is negative coverage regardless of what the
price did. Score the framing in front of you.

---

## Sentiment Score Rubric

The five bands are contiguous, non-overlapping, and jointly cover the full
`[-1.0, 1.0]` domain.

| Range | Label | Sign |
|---|---|---|
| `[-1.0, -0.6)` | `strongly_negative` | — |
| `[-0.6, -0.2)` | `negative` | — |
| `[-0.2, 0.2]` | `neutral` | 0 |
| `(0.2, 0.6]` | `positive` | + |
| `(0.6, 1.0]` | `strongly_positive` | + |

**Inclusivity convention.** The neutral band owns both of its endpoints. Every
other band is open on the edge facing zero and closed on the edge facing the
extreme. This is symmetric about zero and leaves no value unassigned.

---

### `[-1.0, -0.6)` — `strongly_negative`

Coverage frames the entity as the subject of a severe adverse event: regulatory
penalty, criminal investigation or prosecution, licence revocation or suspension,
executive arrest, default, or an allegation of accounting fraud. The framing is
unambiguous and the entity is the **primary** subject, not a party named in
passing. Reserve this band for institutional failure or misconduct — a bad quarter,
however bad, is not this.

*Cue vocabulary (needs Vietnamese-language review):* `bị xử phạt`, `khởi tố`,
`đình chỉ hoạt động`, `thao túng`, `vỡ nợ`.

**Example:** `[example pending real data]`

---

### `[-0.6, -0.2)` — `negative`

Coverage frames the entity as facing adverse developments in the ordinary course of
business: earnings decline, missed targets, project delay, lost contract, cut
guidance, credit-rating pressure, or a sector headwind the entity is exposed to.
The tone is clearly unfavourable, but the subject is routine business difficulty
rather than institutional failure. This band also takes cases where a *severe*
event is reported but the entity is a **secondary** party — a supplier to a company
under investigation, say, rather than the company itself.

*Cue vocabulary (needs Vietnamese-language review):* `giảm`, `sụt giảm`,
`chậm tiến độ`, `không đạt kế hoạch`, `áp lực`.

**Example:** `[example pending real data]`

---

### `[-0.2, 0.2]` — `neutral`

This is the widest-traffic band and the one where drift does the most damage, so
its three distinct cases are separated below rather than lumped together. **They do
not all resolve to 0.0.**

#### (a) Factually balanced coverage → may take a small non-zero value

Coverage carries real evaluative weight in both directions that largely offsets:
revenue up but margin compressed, a contract won while a project slips. **Score the
residual lean** within `[-0.2, 0.2]` rather than forcing 0.0.

*Reasoning:* there genuinely is tone here — it is opposed, not absent. The offset
is rarely exact, and downstream `S_final` is a time- and confidence-weighted
average ([`backend/core/formulas.py`](../../backend/core/formulas.py)) built to
accumulate exactly this kind of small consistent lean across many events. Hard-zeroing
every balanced article discards real signal and biases the aggregate toward neutral.
The narrow band is what keeps this honest: a lean can be recorded without letting a
balanced article masquerade as a directional one.

#### (b) Purely factual coverage, no tone → exactly `0.0`

Announcements, filings, schedule notices, index-composition mechanics, AGM dates.
Coverage that reports an occurrence without evaluative framing.

*Reasoning:* there is no tone to measure. `0.0` is not a hedge here, it is the
correct reading, and any non-zero value would be invention — precisely the failure
mode this rubric exists to stop.

#### (c) Genuinely ambiguous tone → exactly `0.0`, and lower the confidence

Coverage clearly carries evaluative weight, but its direction cannot be determined —
heavy hedging, unattributed claims, or a frame that cuts both ways depending on
context the article never supplies.

*Reasoning:* this is the case that tempts a model into splitting the difference at
±0.1, which is indistinguishable downstream from case (a)'s real measured lean. The
two must not collide. Ambiguity is a statement about **how well the coverage can be
read**, not about where it sits on the scale, so it belongs in the confidence
channel, not the score. Score `0.0` and express the uncertainty as low
`ai_confidence`.

> The `ai_confidence` rubric and its threshold are **out of scope for this
> document** and are defined by a separate subtask. Case (c) only asserts *which
> channel* carries ambiguity; it does not define that channel's scale.

#### `0.0` is not `null`, and neither is "absent"

Three distinct states that must not be conflated:

| State | Meaning |
|---|---|
| `0.0` | A confident read that the coverage is neutral. |
| `null` | No source at or above `AI_CONFIDENCE_THRESHOLD` mentioned this entity — "no confident read" (see `docs/mongodb_schema.md`). |
| absent / `is_empty` | No valid events at all. `blend_s_final()` returns `SFinalResult(score=0.0, is_empty=True)`; a `0.0` with `is_empty=True` must render differently from a genuine neutral. |

**Example (balanced):** `[example pending real data]`
**Example (purely factual):** `[example pending real data]`
**Example (ambiguous):** `[example pending real data]`

---

### `(0.2, 0.6]` — `positive`

Coverage frames the entity as the subject of favourable ordinary-course
developments: earnings growth, a new contract or partnership, capacity expansion, a
completed capital raise, or a favourable assessment attributed to a named analyst
or institution. The framing is clearly favourable at routine scale — good news, not
a milestone. Symmetric to `negative`: a *strongly* favourable event in which the
entity is only a secondary party lands here.

*Cue vocabulary (needs Vietnamese-language review):* `tăng trưởng`, `ký kết`,
`mở rộng`, `khả quan`, `vượt kế hoạch`.

**Example:** `[example pending real data]`

---

### `(0.6, 1.0]` — `strongly_positive`

Coverage frames the entity as the subject of an exceptional favourable event:
record results, transformative M&A, a major regulatory approval or licence award, a
landmark foreign investment, or index inclusion. The framing is superlative or
milestone-grade and the entity is the **primary** subject. Reserve this band the
same way `strongly_negative` is reserved — a good quarter is `positive`, not this.

*Cue vocabulary (needs Vietnamese-language review):* `kỷ lục`, `cao nhất lịch sử`,
`đột phá`, `chấp thuận`.

**Example:** `[example pending real data]`

---

## Divergence from the live 3-band path

A 3-band bucketing scheme already exists in this repo and is live in the dashboard
gauge. It is **not** modified by this subtask. The two schemes side by side:

**Live 3-band** — `bucket_sentiment(score, threshold)` at
[`backend/core/formulas.py:103`](../../backend/core/formulas.py#L103), consumed at
[`backend/api/features/dashboard/service.py:78`](../../backend/api/features/dashboard/service.py#L78),
with `APISettings.SENTIMENT_BUCKET_THRESHOLD = 0.2` at
[`backend/core/config.py:56`](../../backend/core/config.py#L56):

```python
if score > threshold:   return "positive"    # (0.2, 1.0]
if score < -threshold:  return "negative"    # [-1.0, -0.2)
return "neutral"                             # [-0.2, 0.2]
```

**Mapping between the two:**

| Score range | 3-band (live) | 5-band (this rubric) |
|---|---|---|
| `[-1.0, -0.6)` | `negative` | `strongly_negative` |
| `[-0.6, -0.2)` | `negative` | `negative` |
| `[-0.2, 0.2]` | `neutral` | `neutral` |
| `(0.2, 0.6]` | `positive` | `positive` |
| `(0.6, 1.0]` | `positive` | `strongly_positive` |

The 5-band scheme is a **strict refinement**: the neutral band is byte-identical to
the live one, and the two schemes never disagree about a score's sign. The 5-band
scheme only subdivides the outer two. Nothing needs migrating for them to coexist.

**One real hazard, flagged for review.** `SENTIMENT_BUCKET_THRESHOLD` is a
`BaseSettings` field and therefore env-overridable, while `BUCKETS` is a
hardcoded literal. Anyone who sets `SENTIMENT_BUCKET_THRESHOLD` to something other
than `0.2` silently breaks the refinement relationship above — the two schemes would
then disagree about signs with nothing to catch it. Whether to pin that setting,
derive it from `BUCKETS`, or retire the 3-band path is a decision for the
follow-up subtask that owns read-time bucketing. It is deliberately not decided here.

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

No example has been invented, paraphrased, or approximated to fill the gap. A
fabricated example in a rubric is worse than a missing one: it silently becomes the
de-facto specification the moment someone reads past the caveat. Once the pipeline
has populated `event_clusters`, fill each slot from real content and cite it.
