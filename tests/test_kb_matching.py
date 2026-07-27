"""KB 상품 연계 — 계산 결과를 바꾸지 않고 채널만 붙인다.

이 제품의 가치는 정직한 숫자다. 자사 상품을 밀어 랭킹이 흔들리면 제품이 죽는다.
그래서 KB 연계는 **자격 판정과 비용 비교 뒤에 붙는 채널 레이어**다:

  1. 정책상품 자격 O → "KB국민은행에서 신청" (KB는 주택도시기금 수탁은행)
  2. 정책상품 자격 X → 자격이 **실제로 되는** KB 자체 상품을 대안으로

여기 테스트는 "무작정 추천 금지"를 코드로 고정한 것이다. 말로만 두면 다음에 깨진다.
"""

import json
import pathlib

import pytest

from onjeon.l3.recommend import recommend
from onjeon.rules_io import load_products

RULES = pathlib.Path(__file__).resolve().parent.parent / "src/onjeon/rules/products"
KB = "kb-youth-jeonse-2026-07"

BASE = {"age": 27, "assets_krw": 20_000_000, "deposit_krw": 150_000_000,
        "is_homeless": True, "is_household_head": True, "works_at_sme": False,
        "no_credit_delinquency": True, "is_newlywed": False}


def rec(**over):
    return recommend({**BASE, "annual_income_krw": 30_000_000, **over}, load_products())


class TestRankingNotBent:
    """자사 상품이 정책상품을 앞지르면 안 된다."""

    def test_kb_ranks_after_rated_policy_loans(self):
        el = rec()["eligible"]
        names = [r["rule_id"] for r in el]
        rated = [i for i, r in enumerate(el)
                 if r.get("is_policy_product") and r["terms"].get("interest_rate") is not None]
        assert names.index(KB) > max(rated), f"KB가 정책 대출보다 앞: {names}"

    def test_adding_kb_does_not_change_policy_eligibility(self):
        """KB 룰을 넣었다고 정책상품 판정이 달라지면 안 된다."""
        with_kb = {r["rule_id"] for r in rec()["eligible"]}
        without = {r["rule_id"] for r in
                   recommend({**BASE, "annual_income_krw": 30_000_000},
                             [p for p in load_products() if p["rule_id"] != KB])["eligible"]}
        assert with_kb - {KB} == without


class TestNoInventedRate:
    """KB 자체 상품은 COFIX+가산 변동금리라 사전에 숫자로 확정할 수 없다."""

    def test_kb_rule_has_no_numeric_rate(self):
        d = json.loads((RULES / f"{KB}.json").read_text(encoding="utf-8"))
        assert d["terms"]["interest_rate"] is None, "KB 금리를 숫자로 지어냈다"
        assert d["terms"]["rate_display"], "금리를 안 쓰면 무엇으로 정해지는지는 밝혀야 한다"

    def test_kb_excluded_from_cost_comparison(self):
        """비용 비교에 쓰이는 정책대출 선택에 KB가 끼면 안 된다(금리가 없으니 계산 불가)."""
        from onjeon.decision import _best_policy_loan

        el = rec()["eligible"]
        best = _best_policy_loan("jeonse", el, market_rate=0.035)
        assert best["product_name"] != "KB 청년 맞춤형 전세자금대출"
        assert best["rate"] is not None


class TestOnlyRealAlternatives:
    """자격이 안 되는 상품을 대안이라고 내밀면 반증이 두 번 실패한다."""

    def test_alternatives_are_all_eligible(self):
        out = rec()
        by_id = {r["rule_id"]: r for r in out["eligible"]}
        for bad in out["ineligible"]:
            for alt in bad["alternatives"]:
                assert alt["rule_id"] in by_id, \
                    f"{bad['rule_id']}의 대안 {alt['rule_id']}이 자격이 없다"

    def test_alternatives_carry_name_not_just_id(self):
        """화면이 rule_id를 그대로 보여줄 수는 없다."""
        out = rec()
        alts = [a for b in out["ineligible"] for a in b["alternatives"]]
        assert alts, "대안이 하나도 안 붙었다 — 미자격 반증이 문장에서 끊긴다"
        for a in alts:
            assert a["product_name"] and not a["product_name"].startswith("kb-")

    def test_income_excess_routes_to_kb(self):
        """정책 버팀목 소득 초과(5,000만) → KB(7,000만)가 대안으로 나와야 한다."""
        out = recommend({**BASE, "annual_income_krw": 60_000_000}, load_products())
        bad = {b["rule_id"]: b for b in out["ineligible"]}
        assert "youth-jeonse-loan-2026-07" in bad, "소득 6천만인데 버팀목이 안 막혔다"
        assert KB in [a["rule_id"] for a in bad["youth-jeonse-loan-2026-07"]["alternatives"]]

    def test_no_alternative_when_kb_also_fails(self):
        """KB도 소득 초과면 대안이 비어야 한다 — 안 되는 걸 권하지 않는다."""
        out = recommend({**BASE, "annual_income_krw": 90_000_000}, load_products())
        bad = {b["rule_id"]: b for b in out["ineligible"]}
        assert KB in bad, "연 9천만인데 KB가 자격으로 남았다"
        assert bad["youth-jeonse-loan-2026-07"]["alternatives"] == []


class TestChannelsCarried:
    """_CARRIED에 빠지면 채널이 조용히 빈 채로 나온다(CLAUDE.md 함정 3)."""

    def test_policy_loans_carry_kb_channel(self):
        for r in rec()["eligible"]:
            if r.get("is_policy_product") and r["product_type"] == "loan":
                assert r["channels"], f"{r['rule_id']} 신청 채널 없음"
                assert any(c["name"] == "KB국민은행" for c in r["channels"])

    def test_kb_product_marked_as_bank_not_policy(self):
        kb = next(r for r in rec()["eligible"] if r["rule_id"] == KB)
        assert kb["is_policy_product"] is False
        assert kb["provider"] == "KB국민은행"

    def test_every_rule_declares_whether_it_is_policy(self):
        """기본값(False)에 기대면 정책상품이 은행 상품으로 표시된다.

        실제로 지원금·적금에 표시를 빠뜨려 화면에 "None 상품"이 떴다.
        상품을 추가할 때마다 명시해야 한다.
        """
        missing = [p["rule_id"] for p in load_products() if "is_policy_product" not in p]
        assert not missing, f"is_policy_product 미선언: {missing}"

    def test_bank_products_name_their_provider(self):
        """은행 상품이면 어느 은행인지 밝혀야 한다 — 화면이 provider를 표시한다."""
        bad = [p["rule_id"] for p in load_products()
               if p.get("is_policy_product") is False and not p.get("provider")]
        assert not bad, f"provider 없는 은행 상품: {bad}"


class TestConservativeBounds:
    """자격 판정에서 넉넉한 가정은 곧 과잉 추천이다."""

    def test_kb_deposit_cap_uses_narrower_regional_bound(self):
        """수도권 7억 / 그 외 5억 — 시도를 모르면 좁은 쪽(5억)."""
        d = json.loads((RULES / f"{KB}.json").read_text(encoding="utf-8"))
        cap = next(c for c in d["criteria"] if c["field"] == "deposit_krw")
        assert cap["value"] == 500_000_000

    @pytest.mark.parametrize("deposit,expect", [(500_000_000, True), (500_000_001, False)])
    def test_deposit_boundary(self, deposit, expect):
        out = recommend({**BASE, "annual_income_krw": 30_000_000, "deposit_krw": deposit},
                        load_products())
        assert (KB in [r["rule_id"] for r in out["eligible"]]) is expect
