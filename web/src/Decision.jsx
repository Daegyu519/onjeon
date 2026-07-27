import { useState } from 'react'
import { parseWon, formatWon, glossKR, errorText } from './money'

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
  annual_income_krw: '연소득', assets_krw: '자산', age: '나이', deposit_krw: '보증금',
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
      setF((s) => ({
        ...s,
        ...(b.sigungu && SEOUL_GU.includes(b.sigungu) ? { region: b.sigungu } : {}),
        ...(b.building_type ? { btype: b.building_type } : {}),
        ...(b.exclusive_area_m2 ? { area: b.exclusive_area_m2 } : {}),
        ...(b.senior_claims_krw != null ? { senior: b.senior_claims_krw } : {}),
      }))
    } catch (err) {
      setError(err.message)
    } finally {
      e.target.value = ''
    }
  }

  const a = res?.affordability
  const jw = res?.jeonse_vs_wolse
  const jzWins = jw?.cheaper === '전세'
  // 두 바를 같은 눈금으로 그려야 길이 비교가 성립한다 — 각 안의 지불 합 중 최대값 기준
  const scale = jw
    ? Math.max(barParts(jw.jeonse.breakdown).gross, barParts(jw.wolse.breakdown).gross)
    : 1
  const allKeys = jw
    ? [...new Set([...Object.keys(jw.jeonse.breakdown), ...Object.keys(jw.wolse.breakdown)])]
    : []

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
              {prop.sigungu || ''} {prop.dong || ''} {prop.jibun || ''}
              {prop.building_use ? ` · ${prop.building_use}` : ''}
              {prop.exclusive_area_m2 ? ` · 전용 ${prop.exclusive_area_m2}㎡` : ''}
              {prop.senior_claims_count > 0 && ` · 근저당 ${prop.senior_claims_count}건`}
            </span>
          )}
        </div>
        {prop?.includes_cancelled && (
          // 텍스트 레이어엔 취소선이 없어 말소된 근저당을 구분할 수 없다.
          // 합계를 임의로 깎지 않고 사용자가 등기부를 보고 고치게 한다.
          <div className="risk-off">
            ⚠️ <b>말소사항 포함</b> 증명서예요. 말소된 근저당까지 더해져 선순위가 실제보다
            클 수 있습니다 — 아래 채권최고액을 등기부와 대조해 고쳐주세요.
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
            <label>
              전용면적 <span>㎡</span>
              <input type="number" step="0.01" value={f.area ?? ''} onChange={set('area')}
                placeholder="시세 추정용" />
            </label>
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
            <label>나이<input type="number" value={f.age} onChange={set('age')} /></label>
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

        <button className="submit" onClick={submit} disabled={loading}>
          {loading ? '계산 중…' : '전세 vs 월세 비교하기'}
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
          <div className="comp-title">항목별 연비용</div>
          <table className="bt">
            <thead>
              <tr><th>항목</th><th>전세</th><th>월세</th></tr>
            </thead>
            <tbody>
              {allKeys.map((k) => {
                const j = jw.jeonse.breakdown[k]
                const w = jw.wolse.breakdown[k]
                if (!j && !w) return null
                return (
                  <tr key={k} className={k === RISK ? 'risk' : ''}>
                    <td>{CREDIT_LABEL[k] || k}</td>
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
          {/* 근거는 상품 자격이 아니라 '실제로 무슨 이자를 냈는지'로 쓴다.
              자산이 보증금을 다 덮으면 대출이 0이라, 자격만 보고 "정책대출 1.2% 적용"이라
              적으면 표의 정책대출이자 0원과 어긋난다. breakdown이 사실이다. */}
          <ul className="why">
            {['jeonse', 'wolse'].map((side) => {
              const s = jw[side]
              const label = side === 'jeonse' ? '전세' : '월세'
              const policy = s.breakdown['정책대출이자'] || 0
              const market = s.breakdown['시장대출이자'] || 0
              if (!policy && !market) {
                return <li key={side}>{label} — 보증금을 자기자금으로 충당해 대출이자가 없어요</li>
              }
              return (
                <li key={side}>
                  {label} —{' '}
                  {policy > 0 ? (
                    <>
                      <b>{s.product_name}</b> {(s.loan_rate * 100).toFixed(2)}%
                      {s.loan_limit_krw ? ` · 한도 ${won(s.loan_limit_krw)}원` : ''}
                      {/* 한도 초과 안내는 계산 설명이라 인용(블록)보다 앞에 둔다 */}
                      {market > 0 && (
                        <span className="over"> · 한도를 넘는 만큼은 시장금리로 계산했어요</span>
                      )}
                      <Cite src={s.loan_source} />
                    </>
                  ) : (
                    '쓸 수 있는 정책대출이 없어 시장금리로 계산했어요'
                  )}
                </li>
              )
            })}
            {jw.wolse.support_name && (
              <li>
                월세 지원 — <b>{jw.wolse.support_name}</b> 한시 지원을
                거주 {jw.wolse.support_stay_years}년 평균으로 환산해 연 {won(jw.wolse.support_annual_krw)}원 반영
                <Cite src={jw.wolse.support_source} />
              </li>
            )}
            {jw.jeonse.risk.adjusted && (
              <>
                {/* LGD 0이면 "0원 = 0.44% × 0.0% × 2억"보다 왜 0인지를 말하는 게 낫다.
                    안전한 매물이라는 결론 자체가 이 제품의 답 중 하나다. */}
                {jw.jeonse.risk.lgd === 0 ? (
                  <li>
                    미회수 기대손실 — <b>없음</b>. 경매 회수 예상액이 보증금을 덮어요
                    {jw.jeonse.risk.insured && ' (전세보증보험 가입)'}
                  </li>
                ) : (
                  <li>
                    미회수 기대손실 — 연 <b>{won(jw.jeonse.risk.e_loss_krw)}원</b>
                    {' = '}사고확률 {(jw.jeonse.risk.p_accident * 100).toFixed(2)}%
                    {' × '}미회수율 {(jw.jeonse.risk.lgd * 100).toFixed(1)}%
                    {' × '}보증금 {won(f.jz || 0)}원
                    {/* 사고확률은 해마다 몇 배 움직인다 — 어느 시점 기준인지가 결론을 바꾼다 */}
                    {jw.jeonse.risk.p_accident_range?.[1] > jw.jeonse.risk.p_accident_range?.[0] && (
                      <div className="cite">
                        사고확률은 시점에 따라{' '}
                        {(jw.jeonse.risk.p_accident_range[0] * 100).toFixed(2)}~
                        {(jw.jeonse.risk.p_accident_range[1] * 100).toFixed(2)}% 범위로 움직였어요
                        (공개 통계 4개 시점 실측)
                      </div>
                    )}
                  </li>
                )}
                <li>
                  회수 근거 — 시세 {won(jw.jeonse.risk.market_price_krw)}원 ×
                  낙찰가율 {(jw.jeonse.risk.auction_rate * 100).toFixed(0)}% −
                  선순위 {won(jw.jeonse.risk.senior_claims_krw)}원
                  {res.sources.market_price_estimate && (
                    <span className="ver">
                      {' '}· 시세는 {res.sources.market_price_estimate.level_label} 평당
                      {' '}{res.sources.market_price_estimate.pyeong_price_manwon.toLocaleString()}만원
                      ({res.sources.market_price_estimate.bucket}) × 전용
                      {' '}{res.sources.market_price_estimate.area_m2}㎡ 추정
                    </span>
                  )}
                </li>
                {/* 밴드 폭은 시세가 어느 집계 단위에서 왔는지에 달려 있다.
                    직접 입력한 매매가는 추정이 아니라 밴드가 0 — 그때는 표시하지 않는다. */}
                {jw.jeonse.risk.price_band > 0 && jw.jeonse.risk.e_loss_range_krw[1] > 0 && (
                  <li className="band">
                    기대손실 범위{' '}
                    <b>{won(jw.jeonse.risk.e_loss_range_krw[0])}~{won(jw.jeonse.risk.e_loss_range_krw[1])}원</b>
                    {' '}— 시세 추정 ±{(jw.jeonse.risk.price_band * 100).toFixed(0)}%와
                    사고확률의 시점 변동을 함께 반영했어요.
                    {LEVEL_NOTE[jw.jeonse.risk.price_level] || ''}
                  </li>
                )}
                {jw.jeonse.risk.priority_krw > 0 && (
                  <li>
                    소액임차인 최우선변제 — 보증금 중 <b>{won(jw.jeonse.risk.priority_krw)}원</b>은
                    선순위 근저당보다 먼저 배당받아요
                    <div className="cite">주택임대차보호법 §8, 시행령 §10·§11 · 서울 기준 [확인]</div>
                  </li>
                )}
              </>
            )}
            {jw.rates && (
              // 적용 금리를 감추지 않는다. 전부 가정값이고 시중금리는 아직 데모 대표값이라
              // 사용자가 "내 견적과 다르다"를 판단할 수 있어야 한다 (CLAUDE.md 원칙 2·5).
              <li>
                <b>적용 금리</b> — 이 숫자들이 위 금액을 만들었어요
                <div className="rate-rows">
                  {[['전세', jw.jeonse], ['월세', jw.wolse]].map(([label, plan]) => plan.funding && (
                    <div key={label} className="rate-row">
                      <span className="rate-plan">{label}</span>
                      {plan.funding.policy_krw > 0 && (
                        <span>정책대출 {won(plan.funding.policy_krw)}원 × <b>{(plan.funding.policy_rate * 100).toFixed(1)}%</b>
                          {plan.product_name ? ` (${plan.product_name})` : ''}</span>
                      )}
                      {plan.funding.market_krw > 0 && (
                        <span>시중대출 {won(plan.funding.market_krw)}원 × <b>{(plan.funding.market_rate * 100).toFixed(1)}%</b></span>
                      )}
                      {plan.funding.own_krw > 0 && (
                        <span>내 돈 {won(plan.funding.own_krw)}원 × <b>{(plan.funding.opportunity_rate * 100).toFixed(1)}%</b> (기회비용)</span>
                      )}
                    </div>
                  ))}
                </div>
                <div className="cite">
                  기회비용 {(jw.rates.opportunity * 100).toFixed(1)}% — {jw.rates.opportunity_source}
                </div>
                <div className="cite">시중대출 {(jw.rates.market_loan * 100).toFixed(1)}% — {jw.rates.market_loan_source}</div>
              </li>
            )}
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
              사고확률은 <b>공개 통계에 보정</b>했어요 — 한국부동산원·국토부가 공개한
              시군구별 전세가율·보증사고율·경매낙찰가율 920개 관측치(4개 시점)에 맞췄습니다.
              다만 <b>지역 집계</b>로 구한 계수를 개별 매물에 적용하는 것이라 한계가 있고,
              보증 <b>가입</b> 매물만의 통계라 실제 위험은 더 클 수 있어요.
            </li>
            <li>
              근저당비율의 영향력만은 <b>가정값</b>이에요 — 공개 통계에 이 항목이 없습니다.
            </li>
            <li>
              등기부 <b>밖의 위험</b>은 반영하지 못해요 — 세금 체납, 다가구 선순위 임차인,
              신탁등기 같은 건 등기부 을구에 안 나옵니다.
            </li>
            <li>
              <b>소액임차인 최우선변제</b>는 서울 기준(보증금 1억 6,500만원 이하 →
              5,500만원까지)만 반영했어요. 수도권 과밀억제권역·광역시 등 지역 구분과
              최신 고시는 아직 확인 전입니다.
            </li>
            <li>
              금리·한도·지원금은 <b>2026-07 기준 대표값</b>이에요. 소득 구간별 실금리와
              가구 유형별 우대는 아직 반영 전입니다.
            </li>
            {res.sources.market_price_estimate && (
              <li>
                시세는 특정 호실이 아니라 <b>{res.sources.market_price_estimate.level_label} 평균</b>
                {' '}추정치예요. 같은 동네여도 매물별로 크게 다릅니다 — 그래서 위 근거에
                범위를 함께 적었습니다.
              </li>
            )}
            <li>
              시세 추정의 <b>범위 폭(±10~30%)은 판단값</b>이에요. 집계 단위별 실제 분산을
              측정해 대체해야 합니다.
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
              <div className="fin-head"><span className="badge-ok">자격</span>{p.product_name}</div>
              <div className="fin-terms">
                {p.product_type === 'loan' ? `${rate(p.terms)}${limit(p.terms)}` : (p.terms.note || '지원 상품')}
              </div>
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
