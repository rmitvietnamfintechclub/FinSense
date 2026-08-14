from __future__ import annotations
 
import logging
from datetime import date, datetime, time, timedelta, timezone
from typing import Callable
from zoneinfo import ZoneInfo
 
from backend.core.enums import Ticker
from backend.core.formulas import confidence_weighted_avg
 
logger = logging.getLogger("pipeline.aggregate.eod_batch")
 
ICT = ZoneInfo("Asia/Ho_Chi_Minh")
 
EVENT_CLUSTERS_COLLECTION = "event_clusters"
DAILY_SENTIMENT_HISTORY_COLLECTION = "daily_sentiment_history"
 
# Chu ky ham price adapter mong doi — DE XUAT, chua xac nhan voi lead
# vi backend/api/external/price/client.py hien dang trong. Truyen vao
# nhu 1 tham so (dependency injection) thay vi tu import cung, de
# khong bi chan tien do trong luc cho xac nhan interface that.
PriceAdapter = Callable[[str, date], "float | None"]
 
 
def ict_day_bounds_utc(target_date: date) -> tuple[datetime, datetime]:
    """
    Tra ve (start_utc, end_utc) — khoang thoi gian UTC tuong ung voi
    dung 1 ngay lich ICT cua target_date.
 
    start_utc: 00:00:00 ICT cua target_date, quy doi UTC (INCLUSIVE)
    end_utc: 00:00:00 ICT cua ngay HOM SAU, quy doi UTC (EXCLUSIVE)
 
    Dung [start_utc, end_utc) khi query Mongo — vi ICT = UTC+7, so voi
    UTC thi 1 ngay ICT bat dau tu 17:00 UTC ngay hom truoc va ket thuc
    16:59:59.999999 UTC ngay hien tai.
    """
    start_ict = datetime.combine(target_date, time.min, tzinfo=ICT)
    end_ict = start_ict + timedelta(days=1)
    return start_ict.astimezone(timezone.utc), end_ict.astimezone(timezone.utc)
 
 
def utc_to_ict_date(utc_dt: datetime) -> date:
    """
    Quy doi 1 timestamp UTC ve ngay lich ICT tuong ung — dung de xac
    dinh 1 event (created_at/updated_at dang UTC) thuoc ve ngay nao
    theo lich ICT.
 
    QUAN TRONG: neu utc_dt la naive (khong co tzinfo — co the xay ra
    neu doc tu 1 driver Mongo khac khong bat tz_aware=True, giong dung
    bug da biet trong aggregator cu), TU DONG gan tzinfo=UTC truoc khi
    tinh, thay vi de crash hoac tinh sai am tham. Day la buoc phong
    ho de khong lap lai chinh xac loi da duoc canh bao trong ticket.
    """
    if utc_dt.tzinfo is None:
        utc_dt = utc_dt.replace(tzinfo=timezone.utc)
    return utc_dt.astimezone(ICT).date()
 
 
def compute_target_date(now_utc: datetime | None = None) -> date:
    """
    Tinh "ngay hom qua" theo lich ICT — CHI duoc goi 1 lan duy nhat o
    entry point (vd trong khoi `if __name__ == "__main__":` hoac
    workflow GitHub Actions), KHONG BAO GIO goi ben trong logic
    aggregation. Day la ly do lam cho 1 lan chay bi mien (missed day)
    co the re-run tay duoc — logic tinh toan luon nhan target_date
    tuong minh, khong tu quyet dinh "hom nay la ngay nao".
 
    now_utc: cho phep inject gio "hien tai" khi test (mac dinh dung
    dong ho he thong that neu khong truyen).
    """
    now = now_utc or datetime.now(timezone.utc)
    today_ict = utc_to_ict_date(now)
    return today_ict - timedelta(days=1)
 
 
def _collect_ticker_scores(
    events: list[dict], ticker: str
) -> tuple[list[float], list[float], set[str]]:
    """
    Duyet qua source_breakdown cua tung event, gom (score, confidence)
    cho MOI source nhac toi dung ticker nay — bat ke confidence cao
    hay thap, vi confidence_weighted_avg() se tu loc theo threshold.
 
    Tra ve them 1 set cluster_id cua cac event THAT SU dong gop (tuc
    la co it nhat 1 source qua threshold) — dung de tinh data_points_used
    theo don vi "event", dung nhu wording trong schema
    ("count of valid events used"), khong phai dem theo "source".
    """
    scores: list[float] = []
    confidences: list[float] = []
    contributing_event_ids: set[str] = set()
 
    for event in events:
        for source in event.get("source_breakdown", []):
            ai_response = source.get("ai_response", {})
            confidence = ai_response.get("ai_confidence")
            if confidence is None:
                continue
            for ts in ai_response.get("ticker_sentiments", []):
                if ts.get("ticker") != ticker or ts.get("score") is None:
                    continue
                scores.append(ts["score"])
                confidences.append(confidence)
                contributing_event_ids.add(event.get("cluster_id", str(event.get("_id"))))
 
    return scores, confidences, contributing_event_ids
 
 
def run_eod_batch(
    target_date: date,
    db,
    price_adapter: PriceAdapter,
    confidence_threshold: float,
) -> dict:
    """
    Chay EOD batch cho DUNG 1 ngay lich ICT (target_date) — khong bao
    gio tu tinh "hom nay la ngay nao" ben trong ham nay (xem
    compute_target_date() — chi goi o entry point).
 
    Ghi DUNG 1 dong cho MOI ticker trong enum Ticker (30 ma VN30), ke
    ca ticker khong co event nao ngay hom do (van ghi voi
    daily_sentiment_score=None). Upsert theo (ticker, date) — chay lai
    cung 1 ngay se cap nhat dong cu, khong tao dong moi.
 
    KHONG ap dung recency decay o day — EOD la 1 ngay lich co dinh,
    decay chi la read-time concern cua serving API (S_final).
    """
    start_utc, end_utc = ict_day_bounds_utc(target_date)
    date_str = target_date.isoformat()
 
    collection = db[EVENT_CLUSTERS_COLLECTION]
    history_collection = db[DAILY_SENTIMENT_HISTORY_COLLECTION]
 
    stats = {"tickers_processed": 0, "tickers_with_score": 0, "date": date_str}
 
    for ticker_member in Ticker:
        ticker = ticker_member.value
 
        # updated_at (theo quyet dinh cua lead) nam trong ngay ICT nay,
        # va event co nhac toi dung ticker nay o cap aggregated_analysis
        # (pre-filter nhanh truoc khi duyet source_breakdown chi tiet)
        events = list(
            collection.find(
                {
                    "updated_at": {"$gte": start_utc, "$lt": end_utc},
                    "aggregated_analysis.ticker_sentiments.ticker": ticker,
                }
            )
        )
 
        scores, confidences, contributing_ids = _collect_ticker_scores(events, ticker)
        daily_score = confidence_weighted_avg(
            scores, confidences, threshold=confidence_threshold
        )
 
        try:
            closing_price = price_adapter(ticker, target_date)
        except Exception as e:
            # KHONG BAO GIO crash vi loi price adapter — log lai va
            # tiep tuc voi closing_price=None, dung yeu cau ticket
            logger.warning(f"Price adapter failed for {ticker} on {date_str}: {e}")
            closing_price = None
 
        record = {
            "ticker": ticker,
            "date": date_str,
            "daily_sentiment_score": daily_score,
            "closing_price": closing_price,
            "data_points_used": len(contributing_ids),
        }
 
        history_collection.update_one(
            {"ticker": ticker, "date": date_str},
            {"$set": record},
            upsert=True,
        )
 
        stats["tickers_processed"] += 1
        if daily_score is not None:
            stats["tickers_with_score"] += 1
 
    logger.info(f"EOD batch complete for {date_str}: {stats}")
    return stats
 
 
if __name__ == "__main__":
    # Entry point that — CHI o day moi duoc goi compute_target_date(),
    # khong bao gio ben trong run_eod_batch() hay cac ham phia tren.
    import sys
 
    from backend.core.config import pipeline_settings
    from backend.core.database import get_database
 
    # TODO: thay bang price adapter that khi backend/api/external/price/
    # co implementation — hien dang la stub tra ve None, CAN XAC NHAN
    # VOI LEAD truoc khi coi la xong.
    def _stub_price_adapter(ticker: str, target_date: date) -> float | None:
        logger.warning(f"Price adapter chua duoc implement — tra ve None cho {ticker}")
        return None
 
    target = compute_target_date()
    if len(sys.argv) > 1:
        target = date.fromisoformat(sys.argv[1])  # cho phep re-run tay: python eod_batch.py 2026-08-09
 
    db = get_database()
    run_eod_batch(
        target_date=target,
        db=db,
        price_adapter=_stub_price_adapter,
        confidence_threshold=pipeline_settings.AI_CONFIDENCE_THRESHOLD,
    )
 