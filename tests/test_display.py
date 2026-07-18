"""표시 계층 헬퍼 테스트 — 만원 변환·인용 라벨은 표시 계층에서만."""

from onjeon.display import citation_label, krw_man


class TestKrwMan:
    def test_converts_won_to_man(self):
        assert krw_man(1_800_000) == "180만원"

    def test_thousands_separator(self):
        assert krw_man(72_000_000) == "7,200만원"


class TestCitationLabel:
    def test_eul_entry_with_amount(self):
        label = citation_label(
            {"type": "근저당권설정", "amount_krw": 72_000_000,
             "section": "을구", "entry_no": 3, "page": 2}
        )
        assert "근저당권설정" in label
        assert "7,200만원" in label
        assert "을구 3번" in label

    def test_gap_entry_without_amount_no_crash(self):
        # 갑구(압류·가압류)는 금액이 없다 — None이어도 죽지 않고 'None'도 노출 금지
        label = citation_label(
            {"type": "압류", "amount_krw": None,
             "section": "갑구", "entry_no": 1, "page": 1}
        )
        assert "압류" in label
        assert "None" not in label
        assert "갑구 1번" in label
