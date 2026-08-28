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

### Determinability caps the band, wherever the other properties land

The sentiment instructions define a case — neutral (c) — where an article carries real
evaluative weight whose **direction cannot be read**. They resolve the score to `0.0` and
send the doubt here, because the score channel has no way to express it.

That doubt has to actually arrive. An article can be well-sourced, complete, and squarely
about its subject — everything `solid` or `high` asks for — and still be unreadable in
direction. Judged only on the other four properties it would score `0.65` and sail through
the `0.5` aggregation gate, recording an ambiguous article as usable evidence.

**Rule.** If the primary subject's framing is direction-undeterminable — the neutral (c)
case — cap the band at `weak` `[0.2, 0.5)`, however strong identification, centrality,
attribution and text integrity are. As with Rule 3's cap, apply it only when the
undeterminable entity is the article's **primary** subject; an unreadable incidental
mention does not pull the whole response down.

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
4b. **Is the primary subject's framing direction-undeterminable — the sentiment
   instructions' neutral (c) case, scored `0.0`?** If yes → `[0.2, 0.5)`. Stop.
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

Every excerpt below is verbatim scraped text from
`event_clusters.source_breakdown.representative_article.content_fed_to_ai`, cited by
`cluster_id` and source. Nothing is paraphrased. The four band examples are deliberately
not shared with the sentiment instructions, since confidence is judged on different
properties and reusing an article would blur which property does the work. The Rule 3
example at the end is the one exception, and reuses `evt_c970203638ed` on purpose: seeing
the same article scored on both axes shows that a high confidence and a moderate sentiment
are independent readings of it.

Each example states the value **and** the observable property that produced it. If you
cannot name such a property for your own number, you are reporting a feeling, which
Rule 1 forbids.

---

### `[0.0, 0.2)` — `unusable`

**`evt_2007dc51395a` · CafeF · "Ngày làm bù 22/8, thị trường chứng khoán có giao dịch không?"**

> Theo thông báo về lịch nghỉ giao dịch năm 2026 của Sở Giao dịch Chứng khoán TP.HCM,
> dịp nghỉ lễ Quốc khánh 2/9 năm nay kéo dài 5 ngày […] HoSE nêu rõ: "Đối với ngày làm
> bù vào thứ Bảy ngày 22/08/2026, Sở Giao dịch Chứng khoán Thành phố Hồ Chí Minh sẽ
> không tổ chức giao dịch."

**`ai_confidence`: `0.1`**

**The property.** This is a complete, well-sourced, perfectly readable article — and it
concerns no covered ticker and no covered concept. It answers a calendar question about
exchange opening hours. Nothing in the closed vocabulary is its subject, so there is no
extraction whose correctness a number could describe.

**This is the band's fourth bullet, and it is the one most often missed.** `unusable`
is not only for scrape failures and navigation boilerplate. A genuine article that is
simply *about something else* belongs here too, and pairs with empty sentiment lists.

**The trap.** `SECURITIES` is tempting — the article mentions HoSE, trading sessions and
brokerages. But the concept means the securities *sector as a subject of coverage*, not
any article in which an exchange is named. Reaching for it to avoid an empty response is
how a `0.1` article gets recorded as evidence.

---

### `[0.2, 0.5)` — `weak`

**`evt_fca2687a0f76` · CafeF · "Lý do Tổng Giám đốc PNJ mua 1 triệu cổ phiếu công ty"**

> Ông Phan Quốc Công - thành viên Hội đồng quản trị kiêm Tổng Giám đốc Công ty CP Vàng
> bạc Đá quý Phú Nhuận vừa mua 1 triệu cổ phiếu PNJ […] Tại Công ty CP Đầu tư Thế giới
> Di động (mã chứng khoán: MWG), ông Nguyễn Đức Tài - Chủ tịch MWG - đã mua 1 triệu cổ
> phiếu MWG để nâng sở hữu lên 2,26% vốn điều lệ. Trong khi đó, ông Nguyễn Hồng Nam -
> thành viên Hội đồng quản trị Công ty CP Chứng khoán (mã chứng khoán: SSI) đăng ký mua
> 5 triệu cổ phiếu […]

**`ai_confidence`: `0.35`**

**The property.** Centrality. This is a weekly roundup of insider transactions across
six unrelated issuers — PNJ, MWG, SSI, VBB, NKG, Pharbaco. `MWG` and `SSI` are named
explicitly and each carries one factual line, but neither is a subject the article makes
claims *about*. It reports a filing and moves on. That is the band's first bullet
exactly: the entity appears inside a list, with no claim specific to it.

**Identification is strong here, and it does not rescue the band.** Both tickers are
given in code form with no ambiguity — and the value is still `weak`, because the five
properties in Rule 1 are not additive. A roundup mention is a roundup mention however
precisely the entity is named.

**The failure this example exists to prevent.** The article's *headline subject* is PNJ,
which is not a covered ticker. Under an earlier prompt version the model resolved that
tension by attributing PNJ's story to the covered tickers that happened to be in the
same document. Out-of-vocabulary subjects produce empty entries and a low confidence —
never a transplanted score.

---

### `[0.5, 0.8)` — `solid`

**`evt_6d401cc4031c` · CafeF · "Làn sóng 'bán vốn' của ngân hàng trở lại, VPBank có gì khác biệt?"**

> Trước đó, kỷ lục của thị trường ngân hàng Việt Nam được xác lập khi VPBank hoàn tất
> phát hành riêng lẻ 1,19 tỷ cổ phiếu cho đối tác chiến lược Sumitomo Mitsui Banking
> Corporation (SMBC) vào năm 2023. […] Trong năm 2026, ngân hàng tiếp tục triển khai các
> kế hoạch tăng vốn tham vọng, với mục tiêu nâng vốn điều lệ từ mức hơn 79.300 tỷ đồng
> lên hơn 106.200 tỷ đồng […]

**`ai_confidence`: `0.65`**

**The properties.** Identification is unambiguous (`VPBank`, a single covered ticker).
Centrality holds — the headline poses a question about VPBank and the body answers it
with claims specific to the bank. Text integrity is fine, and the claims are concrete:
named counterparty, share counts, capital figures.

**Why not `high`.** Two of the three extra conditions fail. VPBank is not the *sole*
primary subject — the piece opens on Techcombank's Reuters-reported stake talks and uses
it as the frame. And the forward-looking capital plan is the company's own stated
ambition rather than a completed, externally attributed event. Solid reporting, one band
short of checkable sourcing on the central claim.

**Register is not a scoring property.** The piece reads promotionally in places. That is
a reason to be careful about *sentiment*, not to move confidence: the five properties in
Rule 1 ask what the text supports, not whether you trust its motives.

---

### `[0.8, 1.0]` — `high`

**`evt_b844bd1da80a` · CafeF · "Ông Đoàn Văn Hiểu Em đăng ký bán 1 triệu cổ phiếu MWG"**

> CTCP Đầu tư Thế Giới Di Động (mã: MWG, sàn HoSE) vừa công bố văn bản thông báo đăng ký
> giao dịch cổ phiếu của người nội bộ là ông Đoàn Văn Hiểu Em - Thành viên HĐQT điều
> hành. Theo đó, ông Đoàn Văn Hiểu Em đăng ký bán 1 triệu cổ phiếu MWG trong thời gian
> từ 7/9 đến 6/10/2026. Giao dịch nhằm mục đích cơ cấu lại danh mục để chuyển sang đầu
> tư cổ phiếu DMX […]

**`ai_confidence`: `0.9`**

**All three extra conditions hold.** `MWG` is the sole primary subject — every paragraph
concerns it or its subsidiary. Identification is explicit: the full legal name plus the
ticker code plus the exchange. And the material claim carries named attribution of the
strongest kind available — a disclosure the company itself published (`vừa công bố văn
bản thông báo`), naming the `HĐQT` member transacting, the share count, and the window.

**What "checkable" means.** Every load-bearing fact here could be verified against the
filing the article is reporting. Compare the `solid` example, where the central claim was
a plan the company intends to execute. That difference — a filed fact versus a stated
intention — is the `solid`/`high` boundary in practice.

**Note that `high` says nothing about the sentiment being strong.** The score for `MWG`
here is a mild one: an insider selling to fund a purchase in a listed subsidiary is
close to tone-neutral. Confidence measures how well the article can be read, not how
much it moves the needle. A `0.9` on a `0.0` is a perfectly coherent response.

---

### Rule 3 in practice — when the Masan cap does *not* apply

**`evt_c970203638ed` · CafeF · "Tổng giám đốc Masan Consumer mua vào 2,7 triệu cổ phiếu"**

> CTCP Hàng tiêu dùng Masan (Masan Consumer, mã: MCH) vừa công bố báo cáo kết quả giao
> dịch cổ phiếu của người nội bộ […]

**`ai_confidence`: `0.85` — not capped at `weak`.**

Rule 3 lists "Masan" as a known ambiguous string because `MSN` and `MCH` are both live
members. The cap applies when *the article does not resolve it*. Here it does, three
times over: the full legal name (`CTCP Hàng tiêu dùng Masan`), the English trading name
(`Masan Consumer`), and the ticker code (`mã: MCH`).

Apply the cap to unresolved ambiguity, not to the appearance of an ambiguous brand name.
Capping a resolved reference throws away a good extraction — and because confidence is
one value for the whole article, it suppresses every other entity in the response too.
