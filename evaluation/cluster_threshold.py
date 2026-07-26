"""Reproduce the cosine threshold calibration for event clustering.

Run from the repository root:

    python -m evaluation.cluster_threshold

The benchmark deliberately includes hard negatives that mention the same
company or topic but describe a different event. It is not part of the fast
unit suite because it loads the configured sentence-transformer model.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime

import numpy as np

from backend.core.schemas.article import Article
from backend.pipeline.stages.cluster.centroid import calculate_centroid
from backend.pipeline.stages.cluster.clustering import cosine_similarity
from backend.pipeline.stages.cluster.embedder import embed_articles

EVENTS = (
    (
        "Hòa Phát báo lãi quý II năm 2026 tăng 32% lên 4.500 tỷ đồng",
        "Lợi nhuận HPG quý 2/2026 đạt 4.500 tỷ, tăng 32%",
        "Tập đoàn Hòa Phát công bố lợi nhuận quý II đạt 4,5 nghìn tỷ đồng",
    ),
    (
        "VinFast khánh thành nhà máy sản xuất xe điện tại Hà Tĩnh",
        "Nhà máy ô tô điện VinFast ở Hà Tĩnh chính thức đi vào hoạt động",
        "VinFast khai trương cơ sở sản xuất xe điện mới tại Hà Tĩnh",
    ),
    (
        "Ngân hàng Nhà nước giữ nguyên lãi suất điều hành trong tháng 7",
        "Lãi suất điều hành tháng 7 được Ngân hàng Nhà nước duy trì",
        "NHNN không thay đổi các mức lãi suất điều hành tháng 7",
    ),
    (
        "Vietcombank được duyệt phương án tăng vốn thêm 27.666 tỷ đồng",
        "VCB sắp tăng vốn điều lệ hơn 27.600 tỷ đồng",
        "Vietcombank thông qua kế hoạch bổ sung 27,7 nghìn tỷ vốn điều lệ",
    ),
    (
        "VN-Index vượt mốc 1.500 điểm trong phiên 15/7",
        "Chứng khoán ngày 15/7: VN-Index đóng cửa trên 1.500 điểm",
        "Phiên 15 tháng 7 đưa chỉ số VN-Index qua ngưỡng 1.500",
    ),
    (
        "Giá cà phê xuất khẩu Việt Nam giảm 8% trong tháng 6",
        "Cà phê Việt xuất khẩu tháng 6 mất giá 8 phần trăm",
        "Giá xuất khẩu cà phê tháng 6 giảm 8%, sản lượng tăng",
    ),
    (
        "Lọc hóa dầu Nghi Sơn báo lãi lớn nhờ vận hành tối đa công suất",
        "Nhà máy Nghi Sơn có lãi khi chạy hết công suất",
        "Vận hành tối đa công suất giúp lọc dầu Nghi Sơn báo lợi nhuận cao",
    ),
    (
        "FPT mở nhà máy AI tại Nhật Bản với vốn đầu tư 200 triệu USD",
        "Nhà máy trí tuệ nhân tạo 200 triệu USD của FPT ra mắt ở Nhật",
        "FPT đầu tư 200 triệu đô xây AI Factory tại Nhật Bản",
    ),
    (
        "Vingroup phát hành 5.000 tỷ đồng trái phiếu kỳ hạn ba năm",
        "VIC huy động 5 nghìn tỷ qua lô trái phiếu ba năm",
        "Lô trái phiếu 5.000 tỷ đồng mới của Vingroup có kỳ hạn 36 tháng",
    ),
    (
        "Trung Nam khảo sát dự án điện mặt trời nổi trên hồ Đồng Nai 2",
        "Dự án điện mặt trời nổi hồ Đồng Nai 2 được Trung Nam nghiên cứu",
        "Trung Nam đề xuất khảo sát điện mặt trời nổi tại thủy điện Đồng Nai 2",
    ),
    (
        "Novaland đạt thỏa thuận gia hạn lô trái phiếu 1.500 tỷ đồng",
        "Chủ nợ đồng ý kéo dài kỳ hạn trái phiếu 1,5 nghìn tỷ của NVL",
        "NVL tái cơ cấu lô trái phiếu 1.500 tỷ bằng cách gia hạn",
    ),
    (
        "Petrolimex điều chỉnh giá xăng RON95 tăng 320 đồng mỗi lít chiều 18/7",
        "Giá xăng RON95 tăng 320 đồng một lít từ 15 giờ ngày 18 tháng 7",
        "PLX công bố tăng 320 đồng/lít với xăng RON95 trong kỳ điều hành 18/7",
    ),
)

HARD_NEGATIVES = (
    "Hòa Phát tăng giá thép xây dựng thêm 200.000 đồng mỗi tấn",
    "VinFast triệu hồi 5.000 xe VF 8 để cập nhật phần mềm",
    "Ngân hàng Nhà nước nâng hạn mức tín dụng cho các ngân hàng",
    "Vietcombank giảm lãi suất cho vay mua nhà",
    "VN-Index giảm 30 điểm trong phiên 18/7 do áp lực bán",
    "Xuất khẩu cà phê Việt Nam lập kỷ lục 5 tỷ USD",
    "Lọc hóa dầu Nghi Sơn tạm dừng một phân xưởng để bảo dưỡng",
    "FPT ký hợp đồng chuyển đổi số với hãng hàng không Nhật Bản",
    "Vingroup khởi công khu đô thị mới tại Cần Giờ",
    "Trung Nam hoàn thành đường dây truyền tải điện ở Ninh Thuận",
    "Novaland bàn giao 500 căn hộ tại dự án Aqua City",
    "Petrolimex báo lãi quý II giảm 15 phần trăm",
)


@dataclass(frozen=True, slots=True)
class Metrics:
    threshold: float
    precision: float
    recall: float
    specificity: float
    f1: float
    false_positives: int
    false_negatives: int


def _article(title: str) -> Article:
    return Article(
        title=title,
        summary="",
        url="https://threshold-benchmark.invalid/article",
        source="threshold-benchmark",
        published_at=datetime(2026, 7, 19, tzinfo=UTC),
    )


def _metrics(
    positive_scores: np.ndarray, negative_scores: np.ndarray, threshold: float
) -> Metrics:
    true_positives = int(np.sum(positive_scores >= threshold))
    false_negatives = int(np.sum(positive_scores < threshold))
    true_negatives = int(np.sum(negative_scores < threshold))
    false_positives = int(np.sum(negative_scores >= threshold))

    predicted_positives = true_positives + false_positives
    precision = true_positives / predicted_positives if predicted_positives else 0.0
    recall = true_positives / (true_positives + false_negatives)
    specificity = true_negatives / (true_negatives + false_positives)
    f1 = 2 * precision * recall / (precision + recall) if precision + recall else 0.0
    return Metrics(
        threshold=threshold,
        precision=precision,
        recall=recall,
        specificity=specificity,
        f1=f1,
        false_positives=false_positives,
        false_negatives=false_negatives,
    )


def _score_benchmark() -> tuple[np.ndarray, np.ndarray]:
    titles = [title for event in EVENTS for title in event] + list(HARD_NEGATIVES)
    vectors = embed_articles([_article(title) for title in titles])
    event_vectors = vectors[: len(EVENTS) * 3].reshape(len(EVENTS), 3, -1)
    hard_negative_vectors = vectors[len(EVENTS) * 3 :]
    full_centroids = np.stack([calculate_centroid(group) for group in event_vectors])

    positive_scores: list[float] = []
    negative_scores: list[float] = []
    for event_index, group in enumerate(event_vectors):
        for held_out_index in range(group.shape[0]):
            training_rows = np.delete(group, held_out_index, axis=0)
            positive_scores.append(
                cosine_similarity(
                    group[held_out_index], calculate_centroid(training_rows)
                )
            )
            negative_scores.extend(
                cosine_similarity(group[held_out_index], full_centroids[other_index])
                for other_index in range(len(EVENTS))
                if other_index != event_index
            )

    negative_scores.extend(
        cosine_similarity(vector, full_centroids[index])
        for index, vector in enumerate(hard_negative_vectors)
    )
    return np.asarray(positive_scores), np.asarray(negative_scores)


def main() -> None:
    positive_scores, negative_scores = _score_benchmark()
    candidates = np.round(np.arange(0.90, 0.991, 0.01), 2)
    results = [
        _metrics(positive_scores, negative_scores, float(value)) for value in candidates
    ]
    # F1 penalizes missed matches and false merges equally. On the tested
    # hundredth-resolution grid this chooses 0.91 without a round-number guess.
    selected = max(
        results, key=lambda result: (result.f1, result.precision, result.threshold)
    )

    print(
        "positive centroid scores "
        f"(n={positive_scores.size}): min={positive_scores.min():.4f}, "
        f"median={np.median(positive_scores):.4f}, max={positive_scores.max():.4f}"
    )
    print(
        "negative centroid scores "
        f"(n={negative_scores.size}): min={negative_scores.min():.4f}, "
        f"median={np.median(negative_scores):.4f}, max={negative_scores.max():.4f}"
    )
    print("threshold precision recall specificity f1 false-positive false-negative")
    for result in results:
        print(
            f"{result.threshold:.2f}      {result.precision:.3f}     "
            f"{result.recall:.3f}  {result.specificity:.3f}       "
            f"{result.f1:.3f} {result.false_positives:14d} "
            f"{result.false_negatives:14d}"
        )
    print(f"selected threshold: {selected.threshold:.2f}")


if __name__ == "__main__":
    main()
