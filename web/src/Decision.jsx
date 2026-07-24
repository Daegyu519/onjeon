import { useState } from 'react'

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

export default function Decision() {
  const [f, setF] = useState({
    income: 280, assets: 2000, age: 27, region: '관악구',
    homeless: true, head: true, sme: true,
    kind: 'wolse', deposit: 2000, rent: 55, maint: 7,
  })
  const [res, setRes] = useState(null)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState(null)
  const set = (k) => (e) => {
    const v = e.target.type === 'checkbox' ? e.target.checked : e.target.value
    setF((s) => ({ ...s, [k]: v }))
  }

  async function submit() {
    setLoading(true)
    setError(null)
    const body = {
      profile: {
        monthly_income_krw: Number(f.income) * 10000,
        assets_krw: Number(f.assets) * 10000,
        age: Number(f.age),
        region: f.region,
        is_homeless: f.homeless,
        is_household_head: f.head,
        works_at_sme: f.sme,
      },
      listing: {
        kind: f.kind,
        deposit_krw: Number(f.deposit) * 10000,
        monthly_rent_krw: f.kind === 'jeonse' ? 0 : Number(f.rent) * 10000,
        maintenance_krw: Number(f.maint) * 10000,
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

  const a = res?.affordability
  const over = a && a.over_under_krw > 0
  // 게이지: 실제 주거비 / 적정선 비율(150% 상한으로 클램프)
  const pct = a ? Math.min(150, (a.monthly_cost / a.appropriate) * 100) : 0

  return (
    <div className="decide">
      <section className="hero">
        <div className="form-grid">
          <label>월소득 <span>만원</span><input type="number" value={f.income} onChange={set('income')} /></label>
          <label>보유자산 <span>만원</span><input type="number" value={f.assets} onChange={set('assets')} /></label>
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
          <label>보증금 <span>만원</span><input type="number" value={f.deposit} onChange={set('deposit')} /></label>
          {f.kind === 'wolse' && <label>월세 <span>만원</span><input type="number" value={f.rent} onChange={set('rent')} /></label>}
          <label>관리비 <span>만원</span><input type="number" value={f.maint} onChange={set('maint')} /></label>
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
