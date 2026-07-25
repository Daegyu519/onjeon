import { useState } from 'react'
import { parseWon, formatWon, glossKR } from './money'

const SEOUL_GU = [
  '종로구', '중구', '용산구', '성동구', '광진구', '동대문구', '중랑구', '성북구',
  '강북구', '도봉구', '노원구', '은평구', '서대문구', '마포구', '양천구', '강서구',
  '구로구', '금천구', '영등포구', '동작구', '관악구', '서초구', '강남구', '송파구', '강동구',
]
const FIELD_LABEL = {
  annual_income_krw: '연소득', assets_krw: '자산', age: '나이', deposit_krw: '보증금',
  works_at_sme: '중소기업 재직', is_homeless: '무주택', is_household_head: '세대주',
}
const won = (v) => `${Math.round(v / 10000).toLocaleString()}만`
const rate = (t) =>
  t.interest_rate != null ? `금리 ${(t.interest_rate * 100).toFixed(1)}%` : '금리 구간별 변동'
const limit = (t) => (t.limit_krw ? ` · 한도 ${won(t.limit_krw)}` : '')

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
    income: 2800000, assets: 20000000, age: 27, region: '관악구',
    homeless: true, head: true, sme: true,
    kind: 'wolse', deposit: 20000000, rent: 550000, maint: 70000, market: null,
    jz: null, wsDep: null, wsRent: null,
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
        is_homeless: f.homeless,
        is_household_head: f.head,
        works_at_sme: f.sme,
      },
      listing: {
        kind: f.kind,
        deposit_krw: f.deposit || 0,
        monthly_rent_krw: f.kind === 'jeonse' ? 0 : (f.rent || 0),
        maintenance_krw: f.maint || 0,
        ...(f.market ? { market_price_krw: f.market } : {}),
        ...(f.jz && f.wsRent
          ? {
              jeonse_deposit_krw: f.jz,
              wolse_deposit_krw: f.wsDep || 0,
              wolse_monthly_rent_krw: f.wsRent,
            }
          : {}),
      },
    }
    try {
      const r = await fetch('/api/decision', {
        method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body),
      })
      const j = await r.json()
      if (!r.ok) throw new Error(j.detail || `오류 ${r.status}`)
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
      if (!r.ok) throw new Error(b.detail || '등기부를 읽지 못했습니다')
      setProp(b)
      if (b.sigungu && SEOUL_GU.includes(b.sigungu)) setF((s) => ({ ...s, region: b.sigungu }))
    } catch (err) {
      setError(err.message)
    } finally {
      e.target.value = ''
    }
  }

  const a = res?.affordability
  const over = a && a.over_under_krw > 0
  // 게이지: 실제 주거비 / 적정선 비율(150% 상한으로 클램프)
  const pct = a ? Math.min(150, (a.monthly_cost / a.appropriate) * 100) : 0

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
            </span>
          )}
        </div>
        <div className="form-grid">
          <MoneyField label="월소득" value={f.income} onChange={setMoney('income')} />
          <MoneyField label="보유자산" value={f.assets} onChange={setMoney('assets')} />
          <label>나이<input type="number" value={f.age} onChange={set('age')} /></label>
          <label>희망지역
            <select value={f.region} onChange={set('region')}>
              {SEOUL_GU.map((g) => <option key={g}>{g}</option>)}
            </select>
          </label>
          <div className="checks">
            <label className="chk"><input type="checkbox" checked={f.homeless} onChange={set('homeless')} />무주택</label>
            <label className="chk"><input type="checkbox" checked={f.head} onChange={set('head')} />세대주</label>
            <label className="chk"><input type="checkbox" checked={f.sme} onChange={set('sme')} />중소기업 재직</label>
          </div>
        </div>
        <div className="form-grid listing">
          <label>임차유형
            <select value={f.kind} onChange={set('kind')}>
              <option value="wolse">월세</option>
              <option value="jeonse">전세</option>
            </select>
          </label>
          <MoneyField label="보증금" value={f.deposit} onChange={setMoney('deposit')} />
          {f.kind === 'wolse' && <MoneyField label="월세" value={f.rent} onChange={setMoney('rent')} />}
          <MoneyField label="관리비" value={f.maint} onChange={setMoney('maint')} />
          <MoneyField label="예상 매매가" hint="원·선택" value={f.market} onChange={setMoney('market')} placeholder="매수 비교용" />
        </div>
        <div className="form-grid listing">
          <div className="checks" style={{ fontWeight: 800, color: 'var(--text-2)' }}>전세 vs 월세 비교 (선택·혜택 반영)</div>
          <MoneyField label="전세 보증금" value={f.jz} onChange={setMoney('jz')} placeholder="전세안" />
          <MoneyField label="월세 보증금" value={f.wsDep} onChange={setMoney('wsDep')} placeholder="월세안" />
          <MoneyField label="월세" value={f.wsRent} onChange={setMoney('wsRent')} placeholder="월세안" />
        </div>
        <button className="submit" onClick={submit} disabled={loading}>
          {loading ? '진단 중…' : '적정 주거비·지원 진단'}
        </button>
        {error && <div className="err">{error}</div>}
      </section>

      {a && (
        <section className="hero gauge-card">
          <div className={`verdict ${over ? 'over' : 'ok'}`}>{a.verdict}</div>
          <div className="gauge-num">
            월 실질 주거비 <b>{won(a.monthly_cost)}원</b> · 적정선 {won(a.appropriate)}원
            <span className={over ? 'over' : 'ok'}> · {won(Math.abs(a.over_under_krw))}원 {over ? '초과' : '여유'}</span>
          </div>
          <div className="gauge">
            <div className="gauge-cap" />
            <div className={`gauge-fill ${over ? 'over' : 'ok'}`} style={{ width: `${(pct / 150) * 100}%` }} />
          </div>
          <div className="gauge-legend">RIR {(a.rir_actual * 100).toFixed(0)}% · 적정 상한 {(a.rir_cap * 100).toFixed(0)}%</div>
        </section>
      )}

      {res?.comparison && (
        <section className="hero comp-card">
          <div className="comp-title">임차 vs 매수 · 연 실질비용</div>
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
            <span> · 예상 매매가 {won(res.comparison.buy.market_price_krw)}원 기준(엔진 결정론)</span>
          </div>
        </section>
      )}

      {res?.jeonse_vs_wolse && (
        <section className="hero comp-card">
          <div className="comp-title">전세 vs 월세 · 연비용 (혜택 반영)</div>
          <div className="comp-row">
            <div className={`comp-cell ${res.jeonse_vs_wolse.cheaper === '전세' ? 'win' : ''}`}>
              <span>전세{res.jeonse_vs_wolse.jeonse.loan_benefit ? ' · 대출혜택' : ''}</span>
              <b>{won(res.jeonse_vs_wolse.jeonse.annual_krw)}원</b>
            </div>
            <div className={`comp-cell ${res.jeonse_vs_wolse.cheaper === '월세' ? 'win' : ''}`}>
              <span>월세{res.jeonse_vs_wolse.wolse.monthly_support ? ' · 월세지원' : ''}</span>
              <b>{won(res.jeonse_vs_wolse.wolse.annual_krw)}원</b>
            </div>
          </div>
          <div className="comp-verdict">
            혜택 반영 유리 → <b>{res.jeonse_vs_wolse.cheaper}</b>
            {res.jeonse_vs_wolse.jeonse.loan_benefit && <span> · 전세 자격최저금리 {(res.jeonse_vs_wolse.jeonse.loan_rate * 100).toFixed(1)}% 적용</span>}
            {res.jeonse_vs_wolse.wolse.monthly_support && <span> · 월세 청년월세지원 반영</span>}
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
