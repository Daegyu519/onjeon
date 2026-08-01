import { useState } from 'react'
import { parseWon, formatWon, glossKR, errorText, PY_M2, toPy, m2py } from './money'

const SEOUL_GU = [
  '종로구', '중구', '용산구', '성동구', '광진구', '동대문구', '중랑구', '성북구',
  '강북구', '도봉구', '노원구', '은평구', '서대문구', '마포구', '양천구', '강서구',
  '구로구', '금천구', '영등포구', '동작구', '관악구', '서초구', '강남구', '송파구', '강동구',
]
// 시세 탭과 같은 유형 코드를 쓴다 — 서버가 낙찰가율 표의 한글 유형으로 정규화한다.
const BUILDING_TYPES = [
  { v: 'apt', l: '아파트' },
  { v: 'rh', l: '빌라(연립·다세대)' },
  { v: 'offi', l: '오피스텔' },
  { v: 'sh', l: '원룸·투룸(단독·다가구)' },
]
const FIELD_LABEL = {
  annual_income_krw: '연소득', assets_krw: '자산', age: '만 나이', deposit_krw: '보증금',
  works_at_sme: '중소기업 재직', is_homeless: '무주택', is_household_head: '세대주',
}
// 만원 단위로 읽되 1억 이상은 억을 분리한다 — "10,000만원"은 읽는 사람이 자리수를 세게 만든다.
// (표시 계층 전용. 계산은 원(₩) 정수로 백엔드가 한다 — CLAUDE.md 컨벤션)
const won = (v) => {
  const man = Math.round(v / 10000)
  if (Math.abs(man) < 10000) return `${man.toLocaleString()}만`
  const eok = Math.trunc(man / 10000)
  const rest = Math.abs(man % 10000)
  return rest ? `${eok}억 ${rest.toLocaleString()}만` : `${eok}억`
}
const rate = (t) =>
  t.interest_rate != null ? `금리 ${(t.interest_rate * 100).toFixed(1)}%` : '금리 구간별 변동'
const limit = (t) => (t.limit_krw ? ` · 한도 ${won(t.limit_krw)}` : '')

// 누적 바의 항목별 색. 시세 탭의 색 언어를 그대로 이어받는다(전세=파랑, 월세=오렌지)
// — 같은 대상을 두 탭에서 같은 색으로 부르면 탭을 옮겨도 읽는 법을 다시 배우지 않는다.
// 미회수기대손실만 두 안에서 같은 빨강이다. 유일하게 '지불'이 아니라 '위험'인 항목이라
// 색 계열에서 떼어놓는다.
const RISK = '미회수기대손실'
const SEG_COLOR = {
  jeonse: { 정책대출이자: '#0066ff', 시장대출이자: '#5b9bff', 보증금기회비용: '#a8c8ff' },
  wolse: {
    연월세: '#e8590c', 정책대출이자: '#f08c4a',
    시장대출이자: '#f7a76c', 보증금기회비용: '#f7c9a8',
  },
}
const CREDIT_LABEL = { 월세세액공제: '세액공제', 청년월세지원: '월세지원' }
// 등기부 권리관계 등급 → 안내 배너 색. 초록/노랑/빨강이 이 화면에서 이미 같은 뜻으로
// 쓰이고 있다(.risk-off / .good / .blocked). 등급용 색을 따로 만들면 뜻이 갈린다.
const REG_RISK_CLASS = { high: 'blocked', caution: '', low: 'good', unknown: '' }
// 집계 단위가 넓으면 왜 밴드가 넓은지 한 마디로 알려준다 — 사용자가 좁힐 방법을 알게.
const LEVEL_NOTE = {
  sigungu: ' 등기부를 올리면 동 단위로 좁혀져 범위가 줄어요.',
  dong: '',
  jibun: '',
}

// breakdown(음수=혜택 포함) → 바 렌더에 필요한 값. gross는 지불 항목 합,
// credit은 혜택 합(양수로), net은 실제 연비용(= gross − credit).
function barParts(breakdown) {
  const segs = []
  let gross = 0
  let credit = 0
  for (const [k, v] of Object.entries(breakdown)) {
    if (v < 0) credit += -v
    else if (v > 0) {
      gross += v
      segs.push([k, v])
    }
  }
  return { segs, gross, credit, net: gross - credit }
}

function CostBar({ kind, breakdown, scale, label, amount, win }) {
  const { segs, gross, credit } = barParts(breakdown)
  const pct = (v) => `${(v / scale) * 100}%`
  return (
    <div className={`bar-row ${win ? 'win' : ''}`}>
      <div className="bar-head">
        <span className="bar-label">{label}</span>
        <b className="bar-amount">{won(amount)}원</b>
        {win && <span className="bar-win">유리</span>}
      </div>
      {/* 세그먼트 식별은 색에만 의존하지 않는다 — 아래 '항목별 연비용' 표가
          항상 보이는 텍스트 채널이다(hover title은 보조). */}
      <div className="bar-track" role="img"
        aria-label={`${label} 연 ${won(amount)}원. ` + segs.map(([k, v]) => `${k} ${won(v)}원`).join(', ')}>
        <div className="bar-stack" style={{ width: pct(gross) }}>
          {segs.map(([k, v]) => (
            <div
              key={k}
              className={`bar-seg ${k === RISK ? 'risk' : ''}`}
              style={{
                width: `${(v / gross) * 100}%`,
                // backgroundColor로 둔다 — 단축 background는 .bar-seg.risk의
                // background-image(사선)를 덮어써서 위험 항목의 질감이 사라진다.
                backgroundColor: k === RISK ? '#f04452' : SEG_COLOR[kind][k],
              }}
              title={`${k} ${won(v)}원`}
            />
          ))}
        </div>
        {credit > 0 && (
          // 혜택은 '깎아주는 만큼'이라 지불 구간 오른쪽 끝에서 되돌아오게 그린다.
          <div className="bar-credit" style={{ width: pct(credit), left: pct(gross - credit) }} />
        )}
      </div>
    </div>
  )
}

// 룰 출처 인용 — 조항·버전·원문 링크 (CLAUDE.md 원칙 2: 모든 출력에 원문 출처).
// 조항(clause_refs)은 모든 상품 룰에 있고 note는 일부에만 있다.
function Cite({ src }) {
  if (!src) return null
  return (
    <div className="cite">
      {src.clause_refs?.length > 0 && <span>{src.clause_refs.join(' · ')}</span>}
      {src.version && <span> · {src.version}</span>}
      {src.url && (
        <>
          {' · '}
          <a href={src.url} target="_blank" rel="noreferrer noopener">원문</a>
        </>
      )}
      {src.note && <div className="cite-note">{src.note}</div>}
    </div>
  )
}

const pct = (v, d = 1) => `${(v * 100).toFixed(d)}%`
const SIDE_LABEL = { jeonse: '전세', wolse: '월세' }

// 한 항목이 두 안에 다 있으면 전세·월세를 나란히 놓는다. 인용은 안마다 다르므로
// 그 줄 바로 아래에 붙인다 — 두 인용을 블록 끝에 몰면 어느 안의 근거인지 섞인다.
function Sides({ jw, k, line, cite }) {
  return (
    <div className="rate-rows">
      {['jeonse', 'wolse'].filter((s) => jw[s].breakdown[k]).map((s) => (
        <div key={s}>
          <div className="rate-row">
            <span className="rate-plan">{SIDE_LABEL[s]}</span>
            <span>{line(jw[s], s)}</span>
          </div>
          {cite && <Cite src={cite(jw[s])} />}
        </div>
      ))}
    </div>
  )
}

// 미회수 기대손실 — 이 제품의 핵심 숫자라 산식·회수근거·범위를 한 블록에 모은다.
function WhyRisk({ jw, res, dep }) {
  const r = jw.jeonse.risk
  const est = res.sources.market_price_estimate
  const [lo, hi] = r.e_loss_range_krw || [0, 0]
  const pr = r.p_accident_range
  return (
    <>
      보증금을 못 돌려받을 확률에, 그때 못 받는 비율을 곱해 <b>연간 비용</b>으로 바꾼 값이에요.
      <Sides
        jw={jw} k={RISK}
        line={(p, side) => (
          <>
            사고확률 {pct(p.risk.p_accident, 2)} × 미회수율 {pct(p.risk.lgd)}
            {' × '}보증금 {won(dep[side])}원 = <b>{won(p.breakdown[RISK])}원</b>
          </>
        )}
      />
      <div className="cite">
        경매에서 돌려받을 수 있는 돈은 <b>시세 {won(r.market_price_krw)}원 ×
        낙찰가율 {pct(r.auction_rate, 0)} − 선순위 {won(r.senior_claims_krw)}원</b>으로 봤어요
        {est && `. 시세는 ${est.level_label} 평당 ${est.pyeong_price_manwon.toLocaleString()}만원(㎡당 ${Math.round(est.pyeong_price_manwon / PY_M2).toLocaleString()}만원, ${est.bucket})에 전용 ${m2py(est.area_m2)}를 곱한 추정치입니다`}
      </div>
      {r.priority_krw > 0 && (
        <div className="cite">
          이 중 <b>{won(r.priority_krw)}원</b>은 소액임차인 최우선변제라 선순위 근저당보다
          먼저 받습니다 — 주택임대차보호법 §8, 시행령 §10 제1호·§11 제1호(서울 기준,
          법제처 원문·시행 2026-07-01).
        </div>
      )}
      {r.priority_supported === false && (
        // 서울 밖은 업로드 단계에서 막으므로 여기 남는 것은 '지역을 못 읽은' 경우다.
        // 조용히 0으로 두면 사용자는 왜 보호가 없는지 모른다.
        <div className="cite">
          <b>매물 지역을 확인하지 못해 최우선변제 보호액을 0으로 뒀어요</b> — 실제로 받을 금액이
          있다면 기대손실은 이보다 작습니다. 모름을 서울로 가정하면 반대로 위험을 과소평가하게
          되고요(시행령 §10·§11은 지역을 4구간으로 나눠 서울 5,500만 / 과밀억제권역 4,800만 /
          광역시 2,800만 / 그 밖 2,500만원으로 갈립니다).
        </div>
      )}
      {/* 밴드 폭은 시세가 어느 집계 단위에서 왔는지에 달려 있다.
          직접 입력한 매매가는 추정이 아니라 밴드가 0 — 그때는 표시하지 않는다. */}
      {r.price_band > 0 && hi > 0 && (
        <div className="band">
          전세 기준 범위 <b>{won(lo)}~{won(hi)}원</b> — 시세 추정 ±{pct(r.price_band, 0)}와
          {pr?.[1] > pr?.[0]
            ? ` 공개 통계 4개 시점에서 ${pct(pr[0], 2)}~${pct(pr[1], 2)}로 움직인 사고확률을`
            : ' 사고확률의 시점 변동을'}
          {' '}함께 반영했어요.{LEVEL_NOTE[r.price_level] || ''}
        </div>
      )}
    </>
  )
}

// 표의 항목 하나가 어떻게 그 금액이 됐는지. 표와 같은 키를 쓰기 때문에 표에서 온
// 링크가 빈 곳으로 떨어지지 않는다 — 표에 없는 항목은 여기에도 없고, 반대도 없다.
function WhyItem({ k, jw, res, dep }) {
  const w = jw.wolse
  switch (k) {
    case '연월세':
      return (
        <>
          월세 <b>{won(w.breakdown['연월세'] / 12)}원 × 12개월</b>이에요. 관리비는 여기 넣지 않고
          아래 주거비 부담(RIR)에서만 봅니다.
        </>
      )
    case '월세세액공제':
      return (
        <>
          연말정산에서 <b>{won(-w.breakdown['월세세액공제'])}원</b>을 돌려받는 만큼 비용에서
          뺐어요. 월세로 낸 돈의 15~17%를 세금에서 깎아주는 제도입니다.
          <div className="cite">
            조세특례제한법 §95조의2 제1항 · 무주택 세대주 + 연 월세 1,000만원 한도
            {' · '}{res.sources.tax_rules_version}
          </div>
        </>
      )
    case '청년월세지원':
      return (
        <>
          <b>{w.support_name}</b>은 몇 년만 받는 한시 지원이라, 거주 {w.support_stay_years}년으로
          나눠 연 <b>{won(w.support_annual_krw)}원</b>으로 넣었어요.
          <Cite src={w.support_source} />
        </>
      )
    case '정책대출이자':
      // 근거는 자격이 아니라 '실제로 무슨 이자를 냈는지'다. 자산이 보증금을 다 덮으면
      // 대출이 0이라, 자격만 보고 적으면 표의 0원과 어긋난다 — breakdown이 사실이다.
      return (
        <>
          금리가 가장 싼 정책대출을 한도까지 먼저 쓴다고 봤어요.
          <Sides
            jw={jw} k={k} cite={(p) => p.loan_source}
            line={(p) => (
              <>
                {won(p.funding.policy_krw)}원 × <b>{pct(p.funding.policy_rate)}</b>
                {p.product_name ? ` · ${p.product_name}` : ''}
                {p.loan_limit_krw ? ` (한도 ${won(p.loan_limit_krw)}원)` : ''}
              </>
            )}
          />
        </>
      )
    case '시장대출이자': {
      // 시중대출은 익명의 '시장금리'가 아니라 실제 상품이다. 다만 그 상품이 KB라서
      // 시장평균보다 낮으면 전세가 유리해 보이므로, 대조값을 항상 옆에 붙인다.
      const mp = jw.rates?.market_loan_product
      return (
        <>
          정책대출 한도를 넘거나 자격이 안 되는 만큼은{' '}
          {mp ? <><b>{mp.product_name || mp.label}</b> 금리로</> : '시중 전세대출 금리로'} 계산했어요.
          <Sides
            jw={jw} k={k}
            line={(p) => <>{won(p.funding.market_krw)}원 × <b>{pct(p.funding.market_rate)}</b></>}
          />
          {mp && (
            <div className="cite">
              {mp.label}{mp.sub_label ? ` · ${mp.sub_label}` : ''} — {mp.rate_basis}
              {mp.loan_count ? ` ${mp.loan_count.toLocaleString()}건` : ''}
              {mp.rate_min_pct != null && ` (개인별 ${mp.rate_min_pct}~${mp.rate_max_pct}%)`}
              {mp.market_avg_rate != null && (
                <>
                  {/* 두 금리의 차는 %가 아니라 %p다 — %로 적으면 배율로 읽힌다 */}
                  {' · '}대조: 같은 통계의 <b>{mp.market_avg_banks}개 은행 평균 {pct(mp.market_avg_rate, 2)}</b>
                  {' '}— 이 상품이 {((mp.market_avg_rate - mp.rate) * 100).toFixed(2)}%p 낮아
                  {' '}전세 비용이 그만큼 작게 나와요.
                </>
              )}
              {mp.posted && (
                <> · 금감원 공시({mp.posted.dcls_month}) {mp.posted.posted_rate_min_pct}~{mp.posted.posted_rate_max_pct}%</>
              )}
              {mp.url && <> · <a href={mp.url} target="_blank" rel="noreferrer noopener">상품 보기</a></>}
            </div>
          )}
          {jw.rates && <div className="cite">{jw.rates.market_loan_source}</div>}
        </>
      )
    }
    case '보증금기회비용':
      return (
        <>
          보증금으로 묶인 <b>내 돈</b>이 그 사이 벌지 못한 이자예요. 통장에서 빠져나가진
          않지만, 목돈을 맡기는 전세와 매달 내는 월세를 같은 자로 재려면 넣어야 합니다.
          <Sides
            jw={jw} k={k}
            line={(p) => <>{won(p.funding.own_krw)}원 × <b>{pct(p.funding.opportunity_rate)}</b></>}
          />
          {jw.rates && (
            <div className="cite">기회비용 {pct(jw.rates.opportunity)} — {jw.rates.opportunity_source}</div>
          )}
        </>
      )
    case RISK:
      return <WhyRisk jw={jw} res={res} dep={dep} />
    default:
      return null
  }
}

// 금액 입력: 내부값은 원(₩) 정수. 타이핑 중엔 raw 그대로(한글 "1억2천"·콤마 방해 없음),
// blur 시 콤마 정규화, 아래 gloss로 "= 1억 2,300만원" 실시간 판독(입력 즉시 확인 피드백).
function MoneyField({ label, hint = '원', value, onChange, placeholder }) {
  const [focused, setFocused] = useState(false)
  const [raw, setRaw] = useState('')
  const display = focused ? raw : formatWon(value)
  return (
    <label>
      {label} <span>{hint}</span>
      <input
        type="text"
        placeholder={placeholder}
        value={display}
        onFocus={() => { setFocused(true); setRaw(value != null ? String(value) : '') }}
        onChange={(e) => { setRaw(e.target.value); onChange(parseWon(e.target.value)) }}
        onBlur={() => setFocused(false)}
      />
      {value != null && <span className="gloss">= {glossKR(value)}</span>}
    </label>
  )
}

// 전용면적 입력 — 내부값은 항상 ㎡(백엔드 계약: exclusive_area_m2). 버튼으로 입력 단위를
// 바꾸고 반대 단위는 아래에 함께 적는다(양방향 환산기). 타이핑 중엔 raw 문자열을 유지한다
// — 매 글자마다 환산·반올림하면 '12'가 '12.00'이 돼 커서가 튄다(MoneyField와 같은 이유).
function AreaField({ value, onChange }) {
  const [unit, setUnit] = useState('m2')
  const [raw, setRaw] = useState(null) // null = 편집 중 아님
  const m2 = value === '' || value == null ? null : Number(value)
  const display = raw ?? (m2 == null ? '' : unit === 'm2' ? String(m2) : toPy(m2).toFixed(2))
  const commit = (t) => {
    setRaw(t)
    const n = parseFloat(t)
    // 빈 칸·숫자 아님은 null — 0㎡로 두면 시세가 0이 되고 위험 계산이 조용히 어긋난다.
    if (!t.trim() || Number.isNaN(n)) return onChange(null)
    onChange(unit === 'm2' ? n : Math.round(n * PY_M2 * 100) / 100)
  }
  // 바깥을 label로 두면 안 된다 — <label> 안의 첫 labelable 요소가 ㎡ 버튼이라
  // 라벨이 입력칸이 아니라 버튼에 붙고, 입력칸은 접근성 이름을 잃는다(실측).
  return (
    <div className="fld">
      <span className="lbl-row">
        <label htmlFor="area-in">전용면적</label>
        <span className="unit-tog">
          {[['m2', '㎡'], ['py', '평']].map(([u, l]) => (
            <button
              key={u} type="button" className={unit === u ? 'on' : ''} aria-pressed={unit === u}
              aria-label={`면적 단위 ${u === 'm2' ? '제곱미터로' : '평으로'} 입력`}
              // 단위를 바꾸면 편집 중인 raw는 버린다 — 다른 단위의 숫자를 그대로 들고 있으면
              // '12평'이 '12㎡'로 읽혀 면적이 3.3배 어긋난다.
              onClick={() => { setUnit(u); setRaw(null) }}
            >{l}</button>
          ))}
        </span>
      </span>
      <input
        id="area-in" type="number" step="0.01" inputMode="decimal" value={display}
        onChange={(e) => commit(e.target.value)}
        onBlur={() => setRaw(null)}
        placeholder={unit === 'm2' ? '시세 추정용 · ㎡' : '시세 추정용 · 평'}
      />
      {m2 != null && <span className="gloss">= {m2py(m2)}</span>}
    </div>
  )
}

export default function Decision() {
  const [f, setF] = useState({
    income: 2800000, assets: 20000000, age: 27, region: '관악구', stay: 4,
    homeless: true, head: true, sme: true,
    // 가구 형태·신용. 기본값은 전부 '해당 없음'이라 안 건드리면 지금까지와 같은 결과가 나온다.
    married: false, marriageYears: null, children: 0, youngestAge: null, delinquent: false,
    jz: 200000000, wsDep: 20000000, wsRent: 550000, maint: 70000, market: null,
    senior: null, btype: '', area: null, insured: false,
  })
  const [res, setRes] = useState(null)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState(null)
  const [prop, setProp] = useState(null)
  // 자동채움이 덮어쓰기 직전의 값. '지우기'가 문서 없던 상태로 되돌리는 데 쓴다.
  const [preFill, setPreFill] = useState(null)
  // 표에서 눌러 이동한 근거 항목(강조용)
  const [why, setWhy] = useState(null)
  const set = (k) => (e) => {
    const v = e.target.type === 'checkbox' ? e.target.checked : e.target.value
    setF((s) => ({ ...s, [k]: v }))
  }
  const setMoney = (k) => (v) => setF((s) => ({ ...s, [k]: v })) // 원(₩) 정수 | null

  async function submit() {
    setLoading(true)
    setError(null)
    const body = {
      profile: {
        monthly_income_krw: f.income || 0,
        assets_krw: f.assets || 0,
        age: Number(f.age),
        region: f.region,
        // 거주기간은 결론을 가른다(한시 지원의 연평균화·매수 취득비 분산) — 숨기지 않는다
        expected_stay_years: Number(f.stay) || 1,
        is_homeless: f.homeless,
        is_household_head: f.head,
        works_at_sme: f.sme,
        is_married: f.married,
        // 빈 칸은 0이 아니라 null로 보낸다 — "혼인 0년"과 "안 적었다"는 다르다.
        // 서버는 null이면 신혼 판정을 하지 않는다(모르는 걸 아니라고 단정하지 않는다).
        marriage_years: f.marriageYears === null || f.marriageYears === '' ? null : Number(f.marriageYears),
        children_count: Number(f.children) || 0,
        youngest_child_age: f.youngestAge === null || f.youngestAge === '' ? null : Number(f.youngestAge),
        has_credit_delinquency: f.delinquent,
      },
      listing: {
        // 적정주거비(RIR)는 월세안 기준으로 진단한다 — 화면에도 그렇게 표기한다
        kind: 'wolse',
        deposit_krw: f.wsDep || 0,
        monthly_rent_krw: f.wsRent || 0,
        maintenance_krw: f.maint || 0,
        jeonse_deposit_krw: f.jz || 0,
        wolse_deposit_krw: f.wsDep || 0,
        wolse_monthly_rent_krw: f.wsRent || 0,
        insured: f.insured,
        ...(f.market ? { market_price_krw: f.market } : {}),
        // E[Loss] 입력. 채권최고액은 0도 유효한 값(선순위 없음)이라 null만 걸러낸다.
        ...(f.senior != null ? { senior_claims_krw: f.senior } : {}),
        ...(f.btype ? { building_type: f.btype } : {}),
        ...(f.area ? { exclusive_area_m2: Number(f.area) } : {}),
        // 매물 소재지는 희망지역과 다른 개념이다. 등기부에서 읽은 시군구가 있으면
        // 그걸 보낸다 — 시세·낙찰가율은 매물이 있는 곳 기준이어야 한다.
        ...(prop?.sigungu ? { region: prop.sigungu } : {}),
        // 동·지번을 주면 시세 추정이 그 단위로 좁혀진다. 구 평균은 오차가 커서
        // 기대손실 밴드가 6배까지 벌어진다 — 좁을수록 숫자를 믿을 수 있다.
        ...(prop?.dong ? { dong: prop.dong } : {}),
        ...(prop?.jibun ? { jibun: prop.jibun } : {}),
      },
    }
    try {
      const r = await fetch('/api/decision', {
        method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body),
      })
      const j = await r.json()
      if (!r.ok) throw new Error(errorText(j.detail, r.status))
      setRes(j)
    } catch (e) {
      setError(e.message)
    } finally {
      setLoading(false)
    }
  }

  async function onRegister(e) {
    const file = e.target.files?.[0]
    if (!file) return
    const fd = new FormData()
    fd.append('file', file)
    setError(null)
    try {
      const r = await fetch('/api/register/parse', { method: 'POST', body: fd })
      const b = await r.json()
      if (!r.ok) throw new Error(errorText(b.detail, r.status) || '등기부를 읽지 못했습니다')
      setProp(b)
      // 자동채움은 편의일 뿐이라 값은 전부 입력칸에 들어가 사용자가 확인·수정한다.
      // senior_claims_krw는 0(근저당 없음)과 null(못 읽음)이 다르므로 null만 거른다.
      const patch = {
        ...(b.sigungu && SEOUL_GU.includes(b.sigungu) ? { region: b.sigungu } : {}),
        ...(b.building_type ? { btype: b.building_type } : {}),
        ...(b.exclusive_area_m2 ? { area: b.exclusive_area_m2 } : {}),
        ...(b.senior_claims_krw != null ? { senior: b.senior_claims_krw } : {}),
      }
      // 되돌릴 값은 patch의 키에서 파생시킨다 — 목록을 따로 적으면 자동채움에 필드를
      // 추가할 때 갈라지고, 지운 문서의 값이 조용히 폼에 남는다(_CARRIED 함정과 같은 실패).
      // 갈아끼워도 스냅샷은 첫 업로드 직전 값을 유지한다 — '지우기'는 앞선 등기부가
      // 아니라 '문서 없던 상태'로 돌아가야 한다.
      setPreFill((p) => p ?? Object.fromEntries(Object.keys(patch).map((k) => [k, f[k]])))
      setF((s) => ({ ...s, ...patch }))
    } catch (err) {
      setError(err.message)
    } finally {
      e.target.value = ''
    }
  }

  function clearRegister() {
    setProp(null)
    // 자동채움 값까지 되돌린다. 남겨두면 지운 문서의 채권최고액·면적으로
    // 기대손실이 계산되는데, 화면에는 등기부를 안 올린 것처럼 보인다.
    if (preFill) setF((s) => ({ ...s, ...preFill }))
    setPreFill(null)
  }

  // 서울 밖 매물이면 계산을 막는다. 시세(캐시에 거래 0건)와 최우선변제(서울 구간만)가
  // 동시에 비어서 기대손실이 근거 없이 나오는데, 화면엔 그냥 '결론'으로 보인다.
  // 서버도 400으로 거절하지만(api/main.post_decision) 버튼을 눌러 에러를 보게 하는
  // 대신 누를 수 없게 한다 — 막힌 이유를 먼저 읽게 만드는 편이 낫다.
  const outsideSeoul = prop?.sigungu && prop.region_supported === false
  const a = res?.affordability
  const jw = res?.jeonse_vs_wolse
  const jzWins = jw?.cheaper === '전세'
  // 두 바를 같은 눈금으로 그려야 길이 비교가 성립한다 — 각 안의 지불 합 중 최대값 기준
  const scale = jw
    ? Math.max(barParts(jw.jeonse.breakdown).gross, barParts(jw.wolse.breakdown).gross)
    : 1
  // 표와 근거 목록이 같은 배열을 쓴다 — 표에 있는 항목은 근거에도 있고 반대도 없다.
  // 따로 만들면 링크가 빈 곳으로 떨어진다(_CARRIED 함정과 같은 실패).
  const rows = jw
    ? [...new Set([...Object.keys(jw.jeonse.breakdown), ...Object.keys(jw.wolse.breakdown)])]
      .filter((k) => jw.jeonse.breakdown[k] || jw.wolse.breakdown[k])
    : []
  const dep = { jeonse: f.jz || 0, wolse: f.wsDep || 0 }
  // 표에서 누른 항목으로 이동 + 도착한 자리를 강조. 부드러운 스크롤은 CSS
  // scroll-behavior에 맡긴다 — prefers-reduced-motion을 CSS가 알아서 지킨다.
  const jump = (k) => () => {
    setWhy(k)
    document.getElementById(`why-${k}`)?.scrollIntoView({ block: 'center' })
  }

  return (
    <div className="decide">
      <section className="hero">
        <div className="register-row">
          <label className="upload">
            📄 등기부로 자동채움
            <input type="file" accept="application/pdf" onChange={onRegister} />
          </label>
          {prop && (
            <span className="prop-ctx">
              <span>
                {prop.sigungu || ''} {prop.dong || ''} {prop.jibun || ''}
                {prop.building_use ? ` · ${prop.building_use}` : ''}
                {prop.exclusive_area_m2 ? ` · 전용 ${m2py(prop.exclusive_area_m2)}` : ''}
                {prop.senior_claims_count > 0 && ` · 근저당 ${prop.senior_claims_count}건`}
              </span>
              {/* 알약이 곧 '올라간 문서'다 — 알약을 지우는 것으로 업로드를 취소한다. */}
              <button type="button" className="clear" onClick={clearRegister}
                aria-label="올린 등기부 지우고 자동채움 되돌리기" title="등기부 지우기">✕</button>
            </span>
          )}
        </div>
        {outsideSeoul && (
          // 계산을 막는 유일한 조건이라 다른 안내보다 위에 둔다.
          <div className="risk-off blocked">
            🚧 <b>{prop.sigungu}는 아직 계산할 수 없어요.</b> 지금은 <b>서울 25개 구</b>만
            다룹니다.
            <div style={{ fontWeight: 500, marginTop: 6 }}>
              계산에 꼭 필요한 두 가지가 서울 밖에는 없어요. 실거래가 시세를 서울만 모아둬서
              이 집 시세를 추정할 수 없고, 소액임차인 최우선변제 금액도
              서울 구간(1억 6,500만원 이하 → 5,500만원)만 넣어뒀습니다(주택임대차보호법 시행령
              §10·§11). 이 상태로 낸 기대손실은 근거 없는 숫자인데 화면에서는 결론처럼
              보이거든요. 그래서 <b>틀린 답을 드리기보다 여기서 멈췄습니다.</b>
            </div>
          </div>
        )}
        {prop?.register_risk && (
          // 등기부에 '적힌' 권리 제한. 기대손실(E[Loss])과 **다른 축**이라 마지막 줄로
          // 못 박는다 — 둘 다 '위험도'라고 부르면 사용자는 하나로 읽고, 🟢을 보고
          // 전세가율이 높은 집을 안전하다고 판단한다.
          <div className={`risk-off ${REG_RISK_CLASS[prop.register_risk.grade]}`}>
            🧾 <b>등기부 권리관계 — {prop.register_risk.label}</b>
            {prop.register_risk.items.length === 0
              && ' 갑구·을구에서 확인된 권리 제한이 없어요.'}
            {prop.register_risk.items.map((it, i) => (
              <div key={i} style={{ fontWeight: 500, marginTop: 6 }}>
                · <b>{it.key}</b>
                {/* 원문 위치를 항목마다 붙인다 (CLAUDE.md 원칙 2). 순위번호·접수일을
                    못 붙인 항목도 버리지 않는다 — 버리면 위험이 조용히 사라진다. */}
                {it.section && (
                  <span>
                    {' '}({it.section}{it.rank ? ` ${it.rank}번` : ''}
                    {it.date ? ` · ${it.date}` : ''})
                  </span>
                )}
                {' '}{it.why}{it.action && ` → ${it.action}`}
              </div>
            ))}
            {prop.register_risk.note && (
              <div style={{ fontWeight: 500, marginTop: 6 }}>· {prop.register_risk.note}</div>
            )}
            {prop.register_risk.explanation && (
              // LLM이 쓴 문장이라고 밝힌다. 위 항목들은 룰 테이블에서 나온 것이고
              // 이 문단만 생성된 것이라, 같은 무게로 보이면 안 된다.
              <div style={{ fontWeight: 500, marginTop: 8 }}>
                <b>AI 요약</b> — {prop.register_risk.explanation}
              </div>
            )}
            <div style={{ fontWeight: 500, marginTop: 8, opacity: 0.8 }}>
              이 등급은 <b>등기부에 적힌 권리 제한</b>만 봅니다. 보증금을 못 돌려받을
              기대손실은 아래 계산을 보세요 — 등기부가 깨끗해도 전세가율이 높으면
              기대손실은 큽니다.
            </div>
          </div>
        )}
        {prop?.cancelled_claims_count > 0 && (
          // 선순위가 조용히 줄면 사용자는 등기부와 대조할 때 이유를 알 수 없다.
          // 무엇을 왜 뺐는지 금액까지 말한다(뺀 근거는 문서에 적힌 순위번호다).
          <div className="risk-off">
            🗑 <b>말소된 근저당 {prop.cancelled_claims_count}건({won(prop.cancelled_claims_krw)}원)</b>은
            선순위에서 뺐어요 — 등기부에 '…번근저당권설정등기말소'로 적혀 있습니다.
            이미 말소된 근저당은 담보 부담이 아니라서, 더하면 기대손실이 부풀려집니다.
          </div>
        )}
        {prop?.struck_rows > 0 && (
          // 실물 등기부는 각주에 "실선으로 그어진 부분은 말소사항을 표시함"이라 적는다.
          // 실선은 말소된 근저당뿐 아니라 변경 전 채무자·근저당권자에도 쓰인다 —
          // 그래서 '말소 N건'이 아니라 '빼고 읽은 줄 수'로 말한다(섞으면 오해를 만든다).
          <div className="risk-off">
            ✂️ 등기부에 <b>실선(말소·변경 전)이 그어진 {prop.struck_rows}줄</b>은 빼고 읽었어요.
            실선은 말소된 근저당뿐 아니라 바뀌기 전 채무자·근저당권자에도 쓰입니다.
          </div>
        )}
        {prop?.includes_cancelled && !prop?.struck_rows && (
          // 실선을 하나도 못 봤다 = 스캔·촬영본이라 도형이 없다. 그럼 말소분을 짚을
          // 방법이 순위번호 문구뿐이고, 그것도 없으면 합계가 과대일 수 있다.
          <div className="risk-off">
            ⚠️ <b>말소사항 포함</b> 증명서인데 실선(말소 표시)을 읽지 못했어요. 말소된 근저당이
            합계에 남아 선순위가 실제보다 클 수 있습니다 — 아래 채권최고액을 등기부와 대조해 주세요.
          </div>
        )}
        {prop && prop.senior_claims_krw == null && (
          <div className="risk-off">
            ⚠️ 채권최고액을 읽지 못했어요. 등기부 을구를 보고 직접 입력하면
            미회수 위험까지 반영됩니다.
          </div>
        )}
        {prop?.ocr && (
          // 스캔·촬영본은 OCR로 읽었다. 숫자 한 자리가 틀려도 예외가 안 나고
          // E[Loss]만 조용히 어긋나므로, 자동채움 값을 원본과 대조하게 만든다.
          <div className="risk-off">
            📷 스캔본이라 <b>글자를 인식해서</b> 읽었어요. 아래 자동채움된 채권최고액·면적을
            등기부 원본과 한 번 대조해 주세요 — 숫자가 한 자리만 달라도 결과가 크게 바뀝니다.
          </div>
        )}
        {prop?.area_note && (
          // 층별 면적이 여러 개인 건물 등기부. 하나를 골라 채우면 시세가 과대추정되고
          // 그만큼 E[Loss]가 과소평가된다 — 위험한 집이 안전해 보이는 방향이라 비워둔다.
          <div className="risk-off">
            📐 전용면적을 자동으로 정하지 않았어요. {prop.area_note}
          </div>
        )}
        {prop?.warnings?.length > 0 && (
          // 등기부에 '없는' 위험. 조용히 넘어가면 깨끗한 등기부가 안전으로 읽힌다.
          <div className="risk-off">
            ⚠️ 이 문서로는 확인할 수 없는 것
            {prop.warnings.map((w, i) => (
              <div key={i} style={{ fontWeight: 500, marginTop: 6 }}>· {w}</div>
            ))}
          </div>
        )}

        <div className="input-group">
          <div className="group-title">비교할 두 집</div>
          <div className="form-grid listing">
            <MoneyField label="전세 보증금" value={f.jz} onChange={setMoney('jz')} placeholder="전세안" />
            <MoneyField label="월세 보증금" value={f.wsDep} onChange={setMoney('wsDep')} placeholder="월세안" />
            <MoneyField label="월세" value={f.wsRent} onChange={setMoney('wsRent')} placeholder="월세안" />
            <MoneyField label="관리비" value={f.maint} onChange={setMoney('maint')} />
          </div>
        </div>

        <div className="input-group">
          <div className="group-title">
            이 집의 위험 <span className="opt">선택 · 넣으면 미회수 기대손실까지 반영해요</span>
          </div>
          <div className="form-grid listing">
            <MoneyField
              label="선순위 채권최고액" value={f.senior} onChange={setMoney('senior')}
              placeholder="등기부 을구 근저당 합계"
            />
            <label>건물유형
              <select value={f.btype} onChange={set('btype')}>
                <option value="">선택 안 함</option>
                {BUILDING_TYPES.map((t) => <option key={t.v} value={t.v}>{t.l}</option>)}
              </select>
            </label>
            <AreaField value={f.area} onChange={(v) => setF((s) => ({ ...s, area: v }))} />
            <div className="checks">
              <label className="chk">
                <input type="checkbox" checked={f.insured} onChange={set('insured')} />
                전세보증보험 가입
              </label>
            </div>
          </div>
        </div>

        <div className="input-group">
          <div className="group-title">내 조건</div>
          <div className="form-grid">
            <MoneyField label="월소득" value={f.income} onChange={setMoney('income')} />
            <MoneyField label="보유자산" value={f.assets} onChange={setMoney('assets')} />
            <label>만 나이<input type="number" value={f.age} onChange={set('age')} /></label>
            <label>
              거주기간 <span>년</span>
              <input type="number" min="1" max="30" value={f.stay} onChange={set('stay')} />
              <span className="gloss">결론이 바뀔 수 있어요</span>
            </label>
            <label>희망지역
              <select value={f.region} onChange={set('region')}>
                {SEOUL_GU.map((g) => <option key={g}>{g}</option>)}
              </select>
            </label>
            <MoneyField label="예상 매매가" hint="원·선택" value={f.market} onChange={setMoney('market')} placeholder="매수 비교용" />
            {/* 자녀 수는 미혼도 해당될 수 있어(한부모) 항상 보인다. 혼인기간·막내 나이는
                해당될 때만 펼친다 — 대부분의 사용자에게 빈 칸 5개를 보여줄 이유가 없다. */}
            <label>자녀 수 <span>미성년</span>
              <input type="number" min="0" max="10" value={f.children} onChange={set('children')} />
            </label>
            {Number(f.children) > 0 && (
              <label>막내 나이 <span>만</span>
                <input type="number" min="0" max="19" value={f.youngestAge ?? ''} onChange={set('youngestAge')} />
                <span className="gloss">2살 미만이면 신생아 특례 대상이에요</span>
              </label>
            )}
            {f.married && (
              <label>혼인기간 <span>년</span>
                <input type="number" min="0" max="60" value={f.marriageYears ?? ''} onChange={set('marriageYears')} />
                <span className="gloss">7년 이내면 신혼가구 상품을 받을 수 있어요</span>
              </label>
            )}
            <div className="checks">
              <label className="chk"><input type="checkbox" checked={f.homeless} onChange={set('homeless')} />무주택</label>
              <label className="chk"><input type="checkbox" checked={f.head} onChange={set('head')} />세대주</label>
              <label className="chk"><input type="checkbox" checked={f.sme} onChange={set('sme')} />중소기업 재직</label>
              <label className="chk"><input type="checkbox" checked={f.married} onChange={set('married')} />기혼</label>
              {/* 기금 대출은 신용'점수'가 아니라 연체·대위변제 등 등록정보 유무로 거른다 */}
              <label className="chk"><input type="checkbox" checked={f.delinquent} onChange={set('delinquent')} />연체 이력 있음</label>
            </div>
          </div>
        </div>

        <button className="submit" onClick={submit} disabled={loading || outsideSeoul}>
          {loading ? '계산 중…' : outsideSeoul ? '서울 매물만 계산할 수 있어요' : '전세 vs 월세 비교하기'}
        </button>
        {error && <div className="err">{error}</div>}
      </section>

      {jw && (
        <section className="hero answer">
          <div className="answer-sub">{jw.wolse.support_stay_years}년 거주 기준 · 혜택 반영</div>
          <h2 className="answer-h">
            전세가 월세보다<br />
            <b className={jzWins ? 'cheap' : 'dear'}>
              연 {won(jw.diff_krw)}원 {jzWins ? '싸요' : '비싸요'}
            </b>
          </h2>
          {!jw.jeonse.risk.adjusted && (
            <div className="risk-off">⚠️ {jw.jeonse.risk.reason}</div>
          )}
          {/* 위험이 0인 것도 이 제품의 답 중 하나다 — 표에 행이 안 생겨 사라지는 대신
              여기서 말한다. "0원 = 0.44% × 0.0% × 2억"보다 왜 0인지가 낫다. */}
          {jw.jeonse.risk.adjusted && jw.jeonse.risk.lgd === 0 && (
            <div className="risk-off good">
              ✅ <b>미회수 위험은 없어요</b> — 경매로 돌려받을 예상액이 보증금을 덮습니다
              {jw.jeonse.risk.insured && ' (전세보증보험 가입)'}.
            </div>
          )}

          <div className="bars">
            <CostBar kind="jeonse" breakdown={jw.jeonse.breakdown} scale={scale}
              label="전세" amount={jw.jeonse.annual_krw} win={jzWins} />
            <CostBar kind="wolse" breakdown={jw.wolse.breakdown} scale={scale}
              label="월세" amount={jw.wolse.annual_krw} win={!jzWins} />
          </div>
          <div className="bar-legend">
            <span><i className="sw" style={{ background: '#0066ff' }} />전세 비용</span>
            <span><i className="sw" style={{ background: '#e8590c' }} />월세 비용</span>
            <span><i className="sw hatch" />혜택으로 깎인 만큼</span>
          </div>
        </section>
      )}

      {jw && (
        <section className="hero">
          <div className="comp-title">
            항목별 연비용 <span className="opt">항목을 누르면 계산식으로 이동해요</span>
          </div>
          <table className="bt">
            <thead>
              <tr><th>항목</th><th>전세</th><th>월세</th></tr>
            </thead>
            <tbody>
              {rows.map((k) => {
                const j = jw.jeonse.breakdown[k]
                const w = jw.wolse.breakdown[k]
                return (
                  // 행 전체가 눌린다(금액 칸을 눌러도 같은 곳으로) — 키보드는 항목 이름의
                  // 버튼으로 접근하고, 클릭은 tr에서 한 번만 처리한다.
                  <tr key={k} className={`linked ${k === RISK ? 'risk' : ''}`} onClick={jump(k)}>
                    <td>
                      <button type="button" className="why-link">{CREDIT_LABEL[k] || k}</button>
                    </td>
                    <td className={j < 0 ? 'minus' : ''}>{j ? `${won(j)}원` : '—'}</td>
                    <td className={w < 0 ? 'minus' : ''}>{w ? `${won(w)}원` : '—'}</td>
                  </tr>
                )
              })}
              <tr className="sum">
                <td>합계</td>
                <td>{won(jw.jeonse.annual_krw)}원</td>
                <td>{won(jw.wolse.annual_krw)}원</td>
              </tr>
            </tbody>
          </table>
        </section>
      )}

      {jw && (
        <section className="hero">
          <div className="comp-title">이 숫자의 근거</div>
          {/* 항목별 산식은 WhyItem이 표와 같은 키(rows)로 낸다 — 표에서 누르면 여기로 온다.
              근거는 상품 자격이 아니라 '실제로 무슨 이자를 냈는지'로 쓴다. 자산이 보증금을
              다 덮으면 대출이 0이라, 자격만 보고 "정책대출 1.2% 적용"이라 적으면 표의
              0원과 어긋난다 — breakdown이 사실이다. */}
          <ul className="why">
            {rows.map((k) => (
              <li key={k} id={`why-${k}`} className={why === k ? 'lit' : ''}>
                <span className="why-h">{CREDIT_LABEL[k] || k}</span>
                <WhyItem k={k} jw={jw} res={res} dep={dep} />
              </li>
            ))}
            <li className="ver">
              세제·시장 룰 {res.sources.tax_rules_version} / {res.sources.market_params_version} 기준
              {jw.jeonse.risk.adjusted && ` · ${jw.jeonse.risk.data_note}`}
            </li>
          </ul>
        </section>
      )}

      {jw && (
        // 한계를 각주가 아니라 결과 옆에 둔다 (CLAUDE.md 원칙 5).
        // 심사·사용자 모두 "이 숫자를 어디까지 믿을지"를 알아야 한다.
        <section className="limits">
          <div className="limits-h">이 계산이 다루지 못하는 것</div>
          <ul>
            <li>
              <b>서울 25개 구만 다뤄요.</b> 실거래가 시세를 서울만 모아뒀고, 소액임차인
              최우선변제도 시행령 §10·§11의 서울 구간(1억 6,500만원 이하 → 5,500만원)만
              넣었습니다. 그래서 서울 밖 매물은 아예 계산을 막아요 — 근거가 반쪽인
              결론을 내놓는 것보다 낫다고 봤습니다.
            </li>
            <li>
              <b>사고확률은 지역 통계에서 왔어요.</b> 한국부동산원·국토부가 공개한 시군구별
              전세가율·보증사고율·경매낙찰가율 920개 관측치(4개 시점)에 맞춘 값입니다.
              지역 평균으로 구한 계수를 개별 매물에 적용하는 것이라 오차가 있고, 보증에
              가입한 매물만 잡힌 통계라 실제 위험은 이보다 클 수 있어요. 근저당비율의
              영향력만은 통계에 항목이 없어 <b>가정값</b>을 씁니다.
            </li>
            <li>
              <b>등기부에 안 적히는 위험은 못 봐요.</b> 집주인의 세금 체납, 다가구주택의
              선순위 임차인, 신탁등기 같은 것은 을구에 나오지 않습니다.
            </li>
            {res.sources.market_price_estimate && (
              <li>
                <b>시세는 이 호실이 아니라 {res.sources.market_price_estimate.level_label} 평균</b>
                {' '}추정치예요. 같은 동네여도 매물마다 크게 다릅니다 — 그래서 위 근거에 범위를
                함께 적었어요. 그 범위 폭(±10~30%)도 아직 판단값이라 실제 분산으로 바꿔야 합니다.
              </li>
            )}
            <li>
              <b>매수안 세제는 법령 원문 그대로예요</b>(2026-07-28 법제처 대조) — 취득세는
              지방세법 §11①8호 3구간에 §151①1호 지방교육세, 중개보수는 공인중개사법
              시행규칙 별표 1의 상한요율입니다. 다만 보유세는 구간 누진 대신 시세의 0.15%로
              어림했고, 전세·월세의 <b>임대차 중개보수</b>는 아직 비용에 안 넣었어요 —
              넣으면 전세 쪽이 연 15만원쯤 불리해집니다.
            </li>
            <li>
              <b>시중 전세대출은 KB국민은행 한 곳의 실측 금리예요.</b> 은행마다 다르고
              15개 은행 평균보다 0.19%p 낮아서, 다른 은행을 쓰면 전세가 이 계산보다
              불리해집니다. 개인별로도 1.0~5.68%로 갈리니 본인 조건으로 견적을 받아보세요.
            </li>
            <li>
              <b>나머지 금리는 판단값이에요.</b> 매수대출 4.5%·보증금 기회비용 4.0%·
              적정주거비 상한 30%는 실측이 아닙니다. 특히 기회비용은 전세 보증금에 크게
              작용해서 ±1%p면 연 ±200만원이 움직입니다.
            </li>
          </ul>
        </section>
      )}

      {a && (a.available === false ? (
        // 소득 0 → RIR은 분모가 없어 산출 불가. 0%나 빈칸을 보여주면 "부담이 없다"로
        // 읽히므로, 못 낸다는 사실과 그래도 알 수 있는 주거비를 같이 말한다.
        <div className="rir">
          {a.reason} 월 주거비 <b>{won(a.monthly_cost)}원</b>
        </div>
      ) : (
        <div className={`rir ${a.over_under_krw > 0 ? 'over' : 'ok'}`}>
          월세 기준 주거비 부담(RIR) <b>{(a.rir_actual * 100).toFixed(0)}%</b>
          · 적정선 {(a.rir_cap * 100).toFixed(0)}%
          <span> — {a.verdict}</span>
        </div>
      ))}

      {res?.comparison && (
        <section className="hero comp-card">
          <div className="comp-title">참고 — 임차 vs 매수 · 연 실질비용</div>
          <div className="comp-row">
            <div className={`comp-cell ${res.comparison.cheaper !== '매수' ? 'win' : ''}`}>
              <span>{res.comparison.rental.kind}(임차)</span>
              <b>{won(res.comparison.rental.annual_krw)}원</b>
            </div>
            <div className={`comp-cell ${res.comparison.cheaper === '매수' ? 'win' : ''}`}>
              <span>매수</span>
              <b>{won(res.comparison.buy.annual_krw)}원</b>
            </div>
          </div>
          <div className="comp-verdict">
            연비용 유리 → <b>{res.comparison.cheaper}</b>
            {/* 매매가가 사용자 입력인지 캐시 추정인지 밝힌다 — 추정치를 '예상 매매가'로
                제시하면 사용자가 자기가 넣은 값이라고 오해한다 */}
            {res.sources.market_price_estimate?.estimated ? (
              <span>
                {' '}· <b>추정</b> 시세 {won(res.comparison.buy.market_price_krw)}원 기준
                ({res.sources.market_price_estimate.level_label} 평균)
              </span>
            ) : (
              <span> · 입력한 예상 매매가 {won(res.comparison.buy.market_price_krw)}원 기준</span>
            )}
          </div>
        </section>
      )}

      {res && (
        <section className="hero">
          <h3 className="fin-title">받을 수 있는 청년 금융지원</h3>
          {res.recommendations.eligible.map((p) => (
            <div key={p.rule_id} className="fin-card ok">
              <div className="fin-head">
                <span className="badge-ok">자격</span>{p.product_name}
                {/* provider 없이 그리면 "None 상품"이 뜬다 — 룰에 표시를 빠뜨렸을 때
                    화면이 거짓말을 하는 대신 조용히 생략한다 */}
                {p.is_policy_product === false && p.provider && (
                  <span className="badge-bank">{p.provider} 상품</span>
                )}
              </div>
              <div className="fin-terms">
                {p.product_type === 'loan'
                  ? `${p.terms.rate_display ? `금리 ${p.terms.rate_display} · ` : rate(p.terms)}${limit(p.terms)}`
                  : (p.terms.note || '지원 상품')}
              </div>
              {/* 어디서 신청하는지까지 말해야 판정이 행동으로 이어진다.
                  정책상품은 수탁은행 창구, 은행 상품은 그 은행이다. */}
              {p.channels?.length > 0 && (
                <div className="fin-channel">
                  신청 · {p.channels.map((c, i) => (
                    <span key={i}>
                      {i > 0 && ' / '}
                      <a href={c.url} target="_blank" rel="noreferrer">{c.name}</a>
                      {c.note ? ` — ${c.note}` : ''}
                    </span>
                  ))}
                </div>
              )}
            </div>
          ))}
          {res.recommendations.ineligible.map((p) => (
            <div key={p.rule_id} className="fin-card no">
              <div className="fin-head"><span className="badge-no">미자격</span>{p.product_name}</div>
              <div className="fin-gap">
                {p.failed.map((x, i) => (
                  <div key={i}>
                    · {FIELD_LABEL[x.field] || x.field}
                    {x.gap != null && x.gap > 0 ? ` ${won(x.gap)}원 초과` : ' 조건 미충족'}
                    {x.clause ? ` (${x.clause})` : ''}
                  </div>
                ))}
              </div>
              {/* 미자격 반증에서 문장을 끊지 않는다. 자격이 **실제로 되는** 대안만
                  붙인다 — 안 되는 걸 대안이라고 내밀면 반증이 두 번 실패한다. */}
              {p.alternatives?.length > 0 && (
                <div className="fin-alt">
                  대신 받을 수 있어요
                  {p.alternatives.map((a) => (
                    <div key={a.rule_id} className="fin-alt-row">
                      · <b>{a.product_name}</b>
                      {a.is_policy_product === false && ` (${a.provider} 상품)`}
                      {a.rate_display
                        ? ` — 금리 ${a.rate_display}`
                        : a.interest_rate != null && ` — 금리 ${(a.interest_rate * 100).toFixed(1)}%`}
                      {a.limit_krw ? ` · 한도 ${won(a.limit_krw)}원` : ''}
                      {a.channels?.[0] && (
                        <> · <a href={a.channels[0].url} target="_blank" rel="noreferrer">{a.channels[0].name}</a></>
                      )}
                    </div>
                  ))}
                </div>
              )}
            </div>
          ))}
          {!res.recommendations.eligible.length && !res.recommendations.ineligible.length && (
            <div className="fin-gap">해당 조건에 매칭되는 상품이 없습니다.</div>
          )}
        </section>
      )}
    </div>
  )
}
