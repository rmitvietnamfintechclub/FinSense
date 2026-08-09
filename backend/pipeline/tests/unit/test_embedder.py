"""Unit tests for the cluster-stage embedder."""

from datetime import UTC, datetime

import numpy as np

from backend.core.schemas.article import Article
from backend.pipeline.stages.cluster.embedder import _embedding_dim, embed_articles


def _article(title: str, summary: str = "") -> Article:
    return Article(
        title=title,
        summary=summary,
        url="http://example.com",
        source="Test",
        published_at=datetime(2026, 1, 1, tzinfo=UTC),
    )


def test_output_shape():
    articles = [_article(f"Headline {i}") for i in range(5)]
    result = embed_articles(articles)
    assert result.shape == (5, _embedding_dim())
    assert result.dtype == np.float32


def test_order_preserved():
    articles = [
        _article("VinFast khánh thành nhà máy sản xuất xe điện mới"),
        _article("Giá cà phê xuất khẩu giảm mạnh"),
        _article("Ngân hàng Nhà nước giữ nguyên lãi suất điều hành"),
        _article(
            "Vắng bóng doanh nghiệp FDI niêm yết: 'Mảnh ghép thiếu' của thị trường chứng khoán Việt"
        ),
        _article("Lọc hóa dầu Nghi Sơn báo lãi lớn nhờ vận hành tối đa công suất"),
        _article("Sunhouse rót 2.000 tỷ đồng xây nhà máy thiết bị AI và robot tự hành"),
        _article(
            "Tập đoàn robot và thị giác 3D Trung Quốc xây nhà máy 10 ha tại Bắc Ninh"
        ),
        _article(
            "Điện mặt trời Trung Nam khảo sát dự án điện mặt trời nổi trên hồ Đồng Nai 2"
        ),
    ]
    batch = embed_articles(articles)

    for i, article in enumerate(articles):
        solo = embed_articles([article])
        np.testing.assert_allclose(batch[i], solo[0], rtol=1e-5, atol=1e-6)


def test_empty_input():
    result = embed_articles([])
    assert result.shape == (0, _embedding_dim())
    assert result.dtype == np.float32


def test_blank_article():
    articles = [_article("Headline"), _article("", ""), _article("Another headline")]
    result = embed_articles(articles)
    assert result.shape == (3, _embedding_dim())
    assert result.dtype == np.float32
    assert np.isfinite(result).all()


def test_vietnamese_semantic_sanity():
    # Catches a model that doesn't genuinely support Vietnamese.

    same_event_a = _article("VinFast khánh thành nhà máy sản xuất xe điện mới")
    same_event_b = _article("VinFast mở nhà máy xe điện")
    unrelated = _article(
        "Vắng bóng doanh nghiệp FDI niêm yết: 'Mảnh ghép thiếu' của thị trường chứng khoán Việt"
    )

    vectors = embed_articles([same_event_a, same_event_b, unrelated])

    def cos(u: np.ndarray, v: np.ndarray) -> float:
        return float(np.dot(u, v) / (np.linalg.norm(u) * np.linalg.norm(v)))

    sim_same_event = cos(vectors[0], vectors[1])
    sim_unrelated = cos(vectors[0], vectors[2])

    print(f"\nsame event: {sim_same_event:.3f}")
    print(f"unrelated:  {sim_unrelated:.3f}")
    assert sim_same_event > sim_unrelated
