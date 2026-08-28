# Sentiment Scoring — Instructions

You are reading a Vietnamese financial news article. For each entity you extract — each
`Ticker` and each `Concept` — you must output a sentiment score, a float in the range
`[-1.0, 1.0]`. These instructions tell you how to choose that number.

---

## Rule 1 — Score coverage tone, and nothing else

Every criterion below describes **how the coverage frames the entity**. Not price, not
returns, not what an investor should do.

- Valid: *"Coverage frames the company as the subject of a regulatory penalty."*
- Invalid: *"The stock is likely to decline."*

A story about a company whose share price fell is **not** automatically negative
coverage. A story reporting a fine **is** negative coverage regardless of what the price
did. Score the framing in front of you.

---

## Rule 2 — Primary subject vs. secondary party changes the band

Whether the entity is the article's main subject or a party named in passing shifts the
score by one band toward zero. A severe event where the entity is only a secondary party
is `negative`, not `strongly_negative`. The same applies on the positive side.

---

## The five bands

Bands are contiguous, non-overlapping, and cover the full `[-1.0, 1.0]` range.

| Range | Label |
|---|---|
| `[-1.0, -0.6)` | `strongly_negative` |
| `[-0.6, -0.2)` | `negative` |
| `[-0.2, 0.2]` | `neutral` |
| `(0.2, 0.6]` | `positive` |
| `(0.6, 1.0]` | `strongly_positive` |

**Boundary convention.** The neutral band owns both of its endpoints. Every other band is
open on the edge facing zero and closed on the edge facing the extreme. This is symmetric
about zero and leaves no value unassigned. So `-0.2` and `0.2` are neutral; `-0.6` is
`strongly_negative`; `0.6` is `positive`.

---

### `[-1.0, -0.6)` — `strongly_negative`

Use this band when coverage frames the entity as the subject of a **severe adverse
event**: regulatory penalty, criminal investigation or prosecution, licence revocation or
suspension, executive arrest, default, or an allegation of accounting fraud.

Both conditions must hold: the framing is unambiguous, **and** the entity is the
**primary** subject, not a party named in passing.

Reserve this band for institutional failure or misconduct. A bad quarter, however bad, is
not this.

*Cue terms:* `bị xử phạt`, `khởi tố`, `đình chỉ hoạt động`, `thao túng`, `vỡ nợ`.

---

### `[-0.6, -0.2)` — `negative`

Use this band when coverage frames the entity as facing **adverse developments in the
ordinary course of business**: earnings decline, missed targets, project delay, lost
contract, cut guidance, credit-rating pressure, or a sector headwind the entity is
exposed to. The tone is clearly unfavourable, but the subject is routine business
difficulty rather than institutional failure.

Also use this band when a **severe** event is reported but the entity is a **secondary**
party — a supplier to a company under investigation, rather than the company itself.

*Cue terms:* `giảm`, `sụt giảm`, `chậm tiến độ`, `không đạt kế hoạch`, `áp lực`.

---

### `[-0.2, 0.2]` — `neutral`

This band carries the most articles and is where errors do the most damage. It has
**three distinct cases, and they do not all resolve to `0.0`**. Decide which case you are
in before picking a number.

#### (a) Factually balanced coverage → a small non-zero value

Coverage carries real evaluative weight in **both** directions, and the two largely
offset: revenue up but margin compressed, a contract won while a project slips.

**Score the residual lean** somewhere inside `[-0.2, 0.2]` rather than forcing `0.0`.
There genuinely is tone here — it is opposed, not absent — and the offset is rarely
exact. Hard-zeroing every balanced article throws away real signal.

#### (b) Purely factual coverage, no tone → exactly `0.0`

Announcements, filings, schedule notices, index-composition mechanics, AGM dates.
Coverage that reports an occurrence without any evaluative framing.

There is no tone to measure. `0.0` is not a hedge here, it is the correct reading. Any
non-zero value would be invention.

#### (c) Genuinely ambiguous tone → exactly `0.0`, and lower your confidence

Coverage clearly carries evaluative weight, but its **direction cannot be determined** —
heavy hedging, unattributed claims, or a frame that cuts both ways depending on context
the article never supplies.

Do not split the difference at ±0.1. That is indistinguishable downstream from case (a)'s
real measured lean, and the two must not collide. Ambiguity is a statement about **how
well the coverage can be read**, not about where it sits on the scale, so it belongs in
the confidence channel. Score `0.0` and express the uncertainty as a low `ai_confidence`
(see the confidence scoring instructions).

#### `0.0` means a confident read of "neutral"

`0.0` is a positive claim that the coverage is neutral. It is **not** a placeholder for
"I could not tell" — case (c) covers that, and the way to express it is a low confidence
value alongside the `0.0`, never the score alone.

---

### `(0.2, 0.6]` — `positive`

Use this band when coverage frames the entity as the subject of **favourable
ordinary-course developments**: earnings growth, a new contract or partnership, capacity
expansion, a completed capital raise, or a favourable assessment attributed to a named
analyst or institution. The framing is clearly favourable at routine scale — good news,
not a milestone.

Symmetric to `negative`: a *strongly* favourable event in which the entity is only a
**secondary** party lands here.

*Cue terms:* `tăng trưởng`, `ký kết`, `mở rộng`, `khả quan`, `vượt kế hoạch`.

---

### `(0.6, 1.0]` — `strongly_positive`

Use this band when coverage frames the entity as the subject of an **exceptional
favourable event**: record results, transformative M&A, a major regulatory approval or
licence award, a landmark foreign investment, or index inclusion. The framing is
superlative or milestone-grade **and** the entity is the **primary** subject.

Reserve this band the same way `strongly_negative` is reserved. A good quarter is
`positive`, not this.

*Cue terms:* `kỷ lục`, `cao nhất lịch sử`, `đột phá`, `chấp thuận`.

---

## Decision procedure

For each entity, work through these in order:

1. **Does the coverage carry any evaluative framing about this entity?** If no →
   `0.0` (neutral case b). Stop.
2. **Can you determine the direction of that framing?** If no → `0.0` and lower
   `ai_confidence` (neutral case c). Stop.
3. **Does the framing point in both directions and largely offset?** If yes → score the
   residual lean inside `[-0.2, 0.2]` (neutral case a). Stop.
4. **Which direction?** Negative → step 5. Positive → step 6.
5. **Is this a severe adverse event (penalty, prosecution, default, fraud allegation,
   licence loss) with the entity as the primary subject?** If yes → `[-1.0, -0.6)`.
   Otherwise → `[-0.6, -0.2)`.
6. **Is this an exceptional favourable event (record, transformative M&A, major approval,
   index inclusion) with the entity as the primary subject?** If yes → `(0.6, 1.0]`.
   Otherwise → `(0.2, 0.6]`.

Cue terms are hints, not triggers. A cue term appearing in an article does not by itself
place the score — read what the article claims about the entity.

---

## Examples

<!-- MAINTAINER NOTE: fill each slot with real scraped text from
event_clusters.source_breakdown.representative_article.content_fed_to_ai, cited by
cluster_id and source (CafeF / VnExpress). Do not invent, paraphrase, or approximate.
A fabricated example becomes the de-facto specification the moment someone reads past
the caveat. Remove this section from the rendered prompt until it is populated. -->

- `strongly_negative` — `[example pending real data]`
- `negative` — `[example pending real data]`
- `neutral` (balanced) — `[example pending real data]`
- `neutral` (purely factual) — `[example pending real data]`
- `neutral` (ambiguous) — `[example pending real data]`
- `positive` — `[example pending real data]`
- `strongly_positive` — `[example pending real data]`