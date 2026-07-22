from onjeon.market.buckets import average_by_bucket, bucket_key


def test_bucket_key_month():
    assert bucket_key("2026-07-12", "month") == "2026-07"


def test_bucket_key_week_first_and_second():
    assert bucket_key("2026-07-01", "week") == "2026-07-W1"
    assert bucket_key("2026-07-08", "week") == "2026-07-W2"
    assert bucket_key("2026-07-31", "week") == "2026-07-W5"


def test_average_by_month_groups_and_rounds():
    recs = [
        {"deal_date": "2026-06-03", "pyeong_krw": 10_000_000},
        {"deal_date": "2026-06-20", "pyeong_krw": 20_000_000},
        {"deal_date": "2026-07-01", "pyeong_krw": 30_000_000},
    ]
    out = average_by_bucket(recs, "month")
    assert out["2026-06"] == {"pyeong_krw": 15_000_000, "n": 2}
    assert out["2026-07"] == {"pyeong_krw": 30_000_000, "n": 1}
    assert list(out.keys()) == ["2026-06", "2026-07"]  # 정렬


def test_empty_returns_empty():
    assert average_by_bucket([], "month") == {}
