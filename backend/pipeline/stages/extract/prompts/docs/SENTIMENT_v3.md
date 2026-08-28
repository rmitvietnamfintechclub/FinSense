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
`negative`; `0.6` is `positive`. Each of those three sits in the band nearer zero.

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

Every excerpt below is verbatim scraped text from
`event_clusters.source_breakdown.representative_article.content_fed_to_ai`, cited by
`cluster_id` and source. Excerpts are trimmed to the sentences that carry the framing;
nothing is paraphrased. Where an article's correct output is an empty list, that is
shown rather than hidden — an entity you cannot emit is not an entity you may
approximate.

---

### `strongly_negative` — and why it still extracts nothing

**`evt_a08ec5df53db` · CafeF · "Cổ phiếu LTG của Lộc Trời bị hủy giao dịch trên UPCoM từ ngày 25/8/2026"**

> Sở Giao dịch Chứng khoán Hà Nội (HNX) vừa có văn bản thông báo về việc hủy đăng ký
> giao dịch đối với cổ phiếu LTG của Công ty Cổ phần Tập đoàn Lộc Trời. […] Trước đó,
> Lộc Trời liên tục nhận án phạt của cơ quan quản lý liên quan việc chậm công bố thông
> tin. […] Ngoài ra, cổ phiếu LTG còn đang nằm trong diện bị hạn chế giao dịch do Lộc
> Trời chậm nộp Báo cáo tài chính (BCTC) bán niên 2024, 2025 […] còn bị đình chỉ giao
> dịch do tại thời điểm kết thúc năm tài chính 2025, doanh nghiệp không thực hiện […]

```json
{"ticker_sentiments": [], "concept_sentiments": [], "ai_confidence": 0.1}
```

**Why the band.** This is what `strongly_negative` coverage reads like: `hủy đăng ký
giao dịch` (delisting), a run of `án phạt` from the regulator, `đình chỉ giao dịch`
and `hạn chế giao dịch`. Institutional failure, not a bad quarter. Lộc Trời is the
primary subject, and the framing is unambiguous — both conditions the band requires.

**Why the output is still empty.** `LTG` is not a covered ticker. The coverage being
severe does not license moving that severity onto a listed company that happens to be
nearby, and the article makes no claim about `CONSUMER_STAPLES` as a sector — one
company's disclosure failures are not a sector story. Return empty lists.

*Do not* reach for a covered ticker to have something to say. An out-of-vocabulary
subject is the single most common way a wrong score enters the database.

<!-- MAINTAINER NOTE, stripped before the prompt is sent. No article in the corpus this
file was built from carries a severe adverse event with a *covered* entity as primary
subject, so this band has no worked in-vocabulary example. Add one when the corpus
contains one; do not synthesise it. -->

---

### `negative` — sector headwind, named attribution

**`evt_4567ad7c870d` · VnExpress · "Doanh nghiệp nguy cơ mất 100 USD mỗi tấn thép sang EU vì phát thải"**

> Doanh nghiệp Việt có thể đối diện nguy cơ phải bù đắp hơn 100 USD mỗi tấn khi xuất
> khẩu hàng phát thải lớn, như thép, sang EU, theo cơ chế CBAM. Thông tin được ông
> Hoàng Anh Dũng, Tổng giám đốc Công ty Intracom […] chia sẻ bên lề hội thảo "Áp lực
> CBAM, ESG", ngày 26/8. […] Tính riêng thép, với lượng xuất khẩu 100.000 tấn sang EU,
> doanh nghiệp mất khoảng 300 tỷ đồng thuế carbon, chiếm 20% giá trị đơn hàng.

```json
{"ticker_sentiments": [],
 "concept_sentiments": [{"concept": "MATERIALS", "score": -0.45}],
 "ai_confidence": 0.7}
```

**Why the band.** A cost shock imposed on steel exporters by an external regulation —
adverse, quantified, and squarely ordinary-course. It is a sector headwind, not
institutional failure or misconduct, so it stops at `negative`. `-0.45` sits mid-band:
the harm is concrete (20% of order value) but prospective and mitigable.

**Why no tickers.** The article names no listed company. `HPG` is the obvious steel
name a reader might supply from memory — supplying it would be inventing an entity the
article never discusses.

---

### `neutral` (a) — factually balanced, non-zero residual

**`evt_019cef138009` · CafeF · "Ngành ngân hàng nửa đầu 2026: Tăng trưởng mạnh nhưng NIM chịu sức ép"**

> […] tổng tài sản toàn hệ thống ngân hàng đạt khoảng 22,6 triệu tỷ đồng vào cuối quý
> II/2026, tăng 20% so với cùng kỳ năm trước […] Vốn chủ sở hữu đạt khoảng 1,92 triệu
> tỷ đồng, tăng 19,6% so với cùng kỳ […] Tổng tài sản của MBB, VPB và HDB tăng lần lượt
> khoảng 34%, 36% và 33% so với cùng kỳ.

```json
{"ticker_sentiments": [{"ticker": "MBB", "score": 0.35},
                       {"ticker": "VPB", "score": 0.35},
                       {"ticker": "HDB", "score": 0.35}],
 "concept_sentiments": [{"concept": "BANKING", "score": 0.15}],
 "ai_confidence": 0.65}
```

**Why `BANKING` is neutral and not positive.** The headline states both sides:
`tăng trưởng mạnh` against `NIM chịu sức ép`. Balance-sheet expansion is favourable,
margin compression is not, and the article does not resolve which dominates. That is
case (a) — real evaluative weight in both directions, largely offsetting.

**Why `0.15` and not `0.0`.** The growth figures are specific, large and repeated
across every bank group; the margin pressure is asserted without comparable
quantification. The lean is genuinely positive, just small. Forcing `0.0` here would
discard a measured signal and collide with case (b), which means something different.

**Why the tickers score higher than the concept.** `MBB`, `VPB` and `HDB` are not
carrying the sector's margin problem — each is named for growth specifically above the
average. Their individual framing is favourable at ordinary-course scale, so they land
in `positive`. An entity's score follows the claims made about *that entity*, not the
article's overall mood.

**Why all three tickers score the same.** The article gives them one identical treatment
— a growth figure in a single list, 34%/36%/33%. Those differences are not a difference
in *coverage tone*, which is what the score measures, and spreading them across 0.30 and
0.35 would encode a distinction the text does not make. Vary a score only when the
article varies its framing, not when a number in it varies.

---

### `neutral` (b) — purely factual, exactly `0.0`

**`evt_96ee1d29848f` · CafeF · "Lý do PV Gas không còn đáp ứng điều kiện công ty đại chúng"**

> Tổng Công ty Khí Việt Nam - CTCP (PV Gas, mã: GAS) vừa công bố thông tin về việc
> không còn đáp ứng điều kiện công ty đại chúng. Lý do là doanh nghiệp không đảm bảo
> có tối thiểu 10% số cổ phiếu có quyền biểu quyết do ít nhất 100 nhà đầu tư không phải
> cổ đông lớn nắm giữ. Tại ngày 14/8/2026, PV Gas có tổng cộng 24.743 cổ đông sở hữu
> 2,41 tỷ cổ phiếu.

```json
{"ticker_sentiments": [{"ticker": "GAS", "score": 0.0}],
 "concept_sentiments": [],
 "ai_confidence": 0.85}
```

**Why exactly `0.0`.** The article reports a mechanical consequence of the shareholder
register — free float below a statutory threshold — and then lists board appointments.
It explains, it does not evaluate. There is no favourable or unfavourable framing to
measure, so `0.0` is the correct reading rather than a hedge.

**The trap.** "No longer meets public-company conditions" *sounds* like a sanction. It
is not: it is an ownership-concentration fact with no wrongdoing alleged and no penalty
imposed. Scoring this negative reads the vocabulary instead of the claim.

**Why `ENERGY` is absent.** Nothing here concerns gas or energy markets — the subject is
one issuer's shareholder structure. A ticker being in a sector is not the article
discussing that sector.

---

### `neutral` (c) — direction undeterminable, `0.0` plus low confidence

**`evt_146c782cc8ee` · VnExpress · "Chứng khoán 'xanh vỏ, đỏ lòng'"**

> VN-Index vẫn giữ sắc xanh, song số lượng cổ phiếu giảm giá duy trì gần một nửa sàn
> HoSE. […] sàn HoSE ghi nhận 187 cổ phiếu giảm giá, nhiều hơn so với 116 cổ phiếu
> tăng. […] thanh khoản sụt khoảng 20% về gần 16.000 tỷ đồng. Điều này cũng cho thấy
> tâm lý thận trọng đang chiếm thế áp đảo. […] TCB là mã hấp dẫn khối ngoại nhất với
> giá trị mua ròng hơn 444 tỷ đồng […]

```json
{"ticker_sentiments": [{"ticker": "TCB", "score": 0.35}],
 "concept_sentiments": [{"concept": "MACRO", "score": 0.0}],
 "ai_confidence": 0.4}
```
*with a low `ai_confidence` — see the confidence instructions.*

**Why `MACRO` is case (c) and not case (a).** Case (a) is two readable forces that
offset. Here the article's own framing is that the index reading and the market reading
**contradict** each other — the idiom `xanh vỏ, đỏ lòng` (green skin, red flesh) says
exactly that the headline number misrepresents what happened. Advancers lose to
decliners, liquidity falls 20%, and the piece attributes the gain to a handful of
large caps. Which of those is the signal is not determinable from the text.

**Why not ±0.1.** A small non-zero value is case (a)'s vocabulary: it claims a measured
lean. Emitting one here would be indistinguishable downstream from a real measurement.
Score `0.0` and put the doubt in `ai_confidence`, which is the channel built for it.

**Why `TCB` is scored anyway.** Case (c) attaches to the entity whose framing is
unreadable, not to the whole article. `TCB` has a specific, unambiguous claim of its
own — the largest foreign net buy of the session (`mua ròng`, a lexicon term whose
direction is fixed). That is ordinary-course favourable: `positive`.

---

### `positive` — ordinary-course favourable

**`evt_c970203638ed` · CafeF · "Tổng giám đốc Masan Consumer mua vào 2,7 triệu cổ phiếu"**

> CTCP Hàng tiêu dùng Masan (Masan Consumer, mã: MCH) vừa công bố báo cáo kết quả giao
> dịch cổ phiếu của người nội bộ là ông Trương Công Thắng - Thành viên HĐQT, kiêm Tổng
> giám đốc. […] đã mua vào 2,7 triệu cổ phiếu MCH […] Masan Consumer đã chốt danh sách
> cổ đông […] tạm ứng cổ tức đợt một năm 2026 bằng tiền mặt với tỷ lệ 20% […] trong quý
> II/2026, doanh thu của MCH đạt 7.165 tỷ đồng, tăng 14% so với cùng kỳ. Lợi nhuận sau
> thuế trong quý đạt 1.384 tỷ đồng, tăng 10% so với cùng kỳ.

```json
{"ticker_sentiments": [{"ticker": "MCH", "score": 0.5}],
 "concept_sentiments": [{"concept": "CONSUMER_STAPLES", "score": 0.3}],
 "ai_confidence": 0.85}
```

**Why the band.** Three favourable ordinary-course facts stack: an insider purchase by
the CEO, a 20% `cổ tức tiền mặt`, and double-digit revenue and profit growth. All
routine good news at company scale — none of it is a record, a transformative deal, or
a milestone approval, so `strongly_positive` is not available. `0.5` reflects the
stacking without crossing into that band.

**Why not `strongly_positive`.** `tăng 14%` is growth, not `lãi kỷ lục`. Reserve the
outer band.

**Why `CONSUMER_STAPLES` is lower.** The sector appears only as the context MCH
operates in; the concept is a secondary reading of a single-company story.

---

### `strongly_positive` — milestone event, primary subject

**`evt_a6363dabad24` · VnExpress · "Cổ phiếu Techcombank tăng kịch trần"**

> Thị giá cổ phiếu Techcombank biến động mạnh khi Reuters đưa tin BNP Paribas (Pháp) và
> KB Kookmin Bank (Hàn Quốc) đang tiến hành các cuộc đàm phán riêng để mua ít nhất 15%
> cổ phần của nhà băng này. Techcombank có khả năng chọn một trong hai để trở thành đối
> tác chiến lược trong thương vụ trị giá khoảng 2 tỷ USD. […] Chốt phiên 26/8, mã này
> "không có bên bán", còn lượng dư mua giá trần hơn 5,5 triệu cổ phiếu.

```json
{"ticker_sentiments": [{"ticker": "TCB", "score": 0.8}],
 "concept_sentiments": [{"concept": "BANKING", "score": 0.45}],
 "ai_confidence": 0.75}
```

**Why the band.** A prospective USD 2bn strategic stake by a named global bank is
transformative-M&A scale, and `TCB` is the article's primary subject. Both conditions
for `strongly_positive` hold. Two lexicon terms corroborate the framing —
`tăng kịch trần` (limit-up) and `không có bên bán` (the empty ask side, i.e.
`trắng bên bán`) — the most extreme positive state VN market coverage describes.

**But the score is the tone, not the price move.** Read Rule 1 carefully here: the
limit-up is *evidence* of how the news was received, and would not by itself justify
this band. What justifies it is the reported transaction. Had the stock hit limit-up on
no disclosed news, the correct read would be far weaker.

**Why `BANKING` is `positive`, not `strongly_positive`.** Rule 2. Foreign strategic
interest in the sector is real and favourable, but the sector is a secondary party to a
story about one bank — one band toward zero.

**Why the many other tickers in the back half are absent.** The article closes with a
market wrap naming `HDB`, `MBB`, `VCB`, `VPB`, `CTG`, `GAS`, `BSR`, `GVR`, `VIC` and
more, each with a percentage move and nothing else. A price move is not coverage tone
(Rule 1), and a name in a list is not a subject. Emitting a score for each would
manufacture sentiment out of a price table.
