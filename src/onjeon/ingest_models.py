"""Pydantic v2 인입 모델 — jsonschema 게이트(l1.schema)와 병행하는 타입 게이트.

역할 분담: l1.schema의 jsonschema 게이트는 LLM 추출 직후의 구조 검증
(원칙 4 — 기존 경로, 건드리지 않음), 이 모듈은 파이프라인 내부에서
타입이 붙은 객체로 다룰 때의 검증·결측 추적을 담당한다.

- 검증 실패는 pydantic ValidationError 그대로 전파 (감싸지 않음)
- 선택 필드 결측은 오류가 아니라 missing_fields() + warning 로그로 드러낸다
  ("모르면 비워라"가 파서 지침이므로 결측은 정상 경로다)
- 스키마 밖 여분 키(region, ownership_changes 등)는 보존한다 (extra="allow")
"""

from __future__ import annotations

import logging
import warnings
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

logger = logging.getLogger("onjeon.ingest")


class _Model(BaseModel):
    """공통 설정 — 여분 키 보존 (jsonschema 게이트도 여분 키를 허용한다)."""

    model_config = ConfigDict(extra="allow")


class SourceLoc(_Model):
    """등기부 원문 좌표 — 인용·하이라이트용 (원칙 2)."""

    page: int
    section: str
    entry_no: int


class GapEntry(_Model):
    """갑구 등기 항목 (가압류·가처분 등)."""

    rank: int
    type: str
    date: str
    cancelled: bool
    source_loc: SourceLoc


class EulEntry(_Model):
    """을구 등기 항목 — 채권최고액은 선택 (전세권·임차권 등은 없을 수 있음)."""

    rank: int
    type: str
    max_claim_krw: int | None = Field(default=None, ge=0)
    set_date: str | None = None
    cancelled: bool
    source_loc: SourceLoc


class PriceSource(_Model):
    """시세 출처 — 조회 기준일 필수 (CLAUDE.md 컨벤션)."""

    api: str
    queried_at: str


class RegisterProperty(_Model):
    address: str = Field(min_length=1)
    building_type: Literal["빌라", "오피스텔", "아파트", "기타"]
    market_price_krw: int = Field(ge=0)
    price_source: PriceSource


class TitleSection(_Model):
    owner: str


class RegisterSection(_Model):
    title_section: TitleSection
    gap_section: list[GapEntry] = []
    eul_section: list[EulEntry] = []
    senior_lease_deposits_krw: int = Field(ge=0)


# 필드명 register가 abc.ABCMeta.register(가상 서브클래스 등록 API)를 가리는
# 경고 억제 — 입력 JSON 키와 동형 유지가 우선이고, 해당 API는 쓰지 않는다.
warnings.filterwarnings("ignore", message='Field name "register" in "RegisterDoc"')


class RegisterDoc(_Model):
    """등기부 추출 문서 전체 — 픽스처(data/fixtures/register_*.json)와 동형."""

    property: RegisterProperty
    register: RegisterSection
    offer: dict[str, Any] | None = None

    def missing_fields(self) -> list[str]:
        """None으로 남은 선택 필드의 경로 목록 — 파서가 '모르면 비워라'로 남긴 곳."""
        missing: list[str] = []
        for i, entry in enumerate(self.register.eul_section):
            if entry.max_claim_krw is None:
                missing.append(f"register.eul_section[{i}].max_claim_krw")
            if entry.set_date is None:
                missing.append(f"register.eul_section[{i}].set_date")
        if self.offer is None:
            missing.append("offer")
        return missing

    @model_validator(mode="after")
    def _warn_on_missing_optional_fields(self) -> RegisterDoc:
        missing = self.missing_fields()
        if missing:
            logger.warning("인입 문서 선택 필드 결측: %s", ", ".join(missing))
        return self


class RuleCriterion(_Model):
    """정책상품 자격요건 1개 조항."""

    field: str
    op: Literal["<=", ">=", "==", "in"]
    value: Any
    clause: str
    boundary_tests: list[dict[str, Any]] = []


class RuleSource(_Model):
    url: str = ""
    clause_refs: list[str] = []


class RuleDoc(_Model):
    """정책상품 룰 (rules/products/*.json) — 룰은 코드가 아니라 데이터 (원칙 3)."""

    rule_id: str
    product_name: str
    version: str
    criteria: list[RuleCriterion]
    source: RuleSource | None = None
    verified_at: str = ""
    verify_note: str = ""
    alternatives: list[str] = []


class TradeRecord(_Model):
    """실거래 1건 — data_pipeline.molit.parse_trades 출력과의 계약.

    금액은 원(₩) 정수, 날짜는 YYYY-MM-DD (CLAUDE.md 컨벤션).
    """

    price_krw: int = Field(ge=0)
    area_m2: float = Field(ge=0)
    floor: int
    deal_date: str = Field(pattern=r"^\d{4}-\d{2}-\d{2}$")
    dong: str
    build_year: int = Field(ge=0)
