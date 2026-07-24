import { useEffect, useMemo, useState } from 'react'
import ReactECharts from 'echarts-for-react'
import Decision from './Decision'

const SEOUL_GU = [
  '종로구', '중구', '용산구', '성동구', '광진구', '동대문구', '중랑구', '성북구',
  '강북구', '도봉구', '노원구', '은평구', '서대문구', '마포구', '양천구', '강서구',
  '구로구', '금천구', '영등포구', '동작구', '관악구', '서초구', '강남구', '송파구', '강동구',
]
const BUILDING_TYPES = [
  { v: 'apt', l: '아파트' },
  { v: 'rh', l: '빌라(연립·다세대)' },
  { v: 'offi', l: '오피스텔' },
]
const PERIODS = [
  { v: '1m', l: '1개월' },
  { v: '6m', l: '6개월' },
  { v: '1y', l: '1년' },
  { v: '3y', l: '3년' },
  { v: '5y', l: '5년' },
]
const TYPE_LABEL = { apt: '아파트', rh: '빌라', offi: '오피스텔' }

export default function App() {
  const [region, setRegion] = useState('관악구')
  const [buildingType, setBuildingType] = useState('rh')
  const [period, setPeriod] = useState('1y')
  const [dong, setDong] = useState(null)
  const [jibun, setJibun] = useState(null)
  const [propertyInfo, setPropertyInfo] = useState(null)

  const [data, setData] = useState(null)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState(null)
  const [show, setShow] = useState({ mae: true, jun: true })
  const [view, setView] = useState('trends')

  useEffect(() => {
    const q = new URLSearchParams({ region, buildingType, period })
    if (dong) q.set('dong', dong)
    if (jibun) q.set('jibun', jibun)
    setLoading(true)
    setError(null)
    fetch(`/api/market-trends?${q}`)
      .then(async (r) => {
        if (!r.ok) throw new Error((await r.json()).detail || `오류 ${r.status}`)
        return r.json()
      })
      .then(setData)
      .catch((e) => setError(e.message))
      .finally(() => setLoading(false))
  }, [region, buildingType, period, dong, jibun])

  async function onUpload(e) {
    const file = e.target.files?.[0]
    if (!file) return
    const fd = new FormData()
    fd.append('file', file)
    setError(null)
    try {
      const r = await fetch('/api/register/parse', { method: 'POST', body: fd })
      const body = await r.json()
      if (!r.ok) throw new Error(body.detail || '등기부를 읽지 못했습니다')
      setPropertyInfo(body)
      if (body.building_type) setBuildingType(body.building_type)
      if (body.sigungu && SEOUL_GU.includes(body.sigungu)) setRegion(body.sigungu)
      setDong(body.dong || null)
      setJibun(body.jibun || null)
    } catch (err) {
      setError(err.message)
    } finally {
      e.target.value = ''
    }
  }

  // 대표 평당가(매매) — 최근값과 기간 전 대비 등락
  const stat = useMemo(() => {
    if (!data?.mae_price) return null
    const vals = data.mae_price.filter((v) => v != null)
    if (!vals.length) return null
    const first = vals[0]
    const last = vals[vals.length - 1]
    const pct = first ? ((last - first) / first) * 100 : 0
    return { last, pct }
  }, [data])

  const junUnavailable = data?.unavailable?.includes('jun_price')

  const option = useMemo(() => {
    if (!data) return {}
    return {
      color: ['#00a84d', '#0066ff'],
      grid: { left: 6, right: 14, top: 18, bottom: 62, containLabel: true },
      tooltip: {
        trigger: 'axis',
        backgroundColor: '#191f28',
        borderWidth: 0,
        padding: [10, 12],
        textStyle: { color: '#fff', fontSize: 12 },
        formatter: (ps) => {
          let s = `<div style="font-weight:700;margin-bottom:5px">${ps[0].axisValue}</div>`
          ps.forEach((p) => {
            if (p.value == null) return
            s += `<div style="display:flex;justify-content:space-between;gap:18px">
              <span>${p.marker}${p.seriesName}</span>
              <b style="font-variant-numeric:tabular-nums">${p.value.toLocaleString()}만</b></div>`
          })
          return s
        },
      },
      xAxis: {
        type: 'category',
        data: data.dates,
        boundaryGap: false,
        axisLine: { lineStyle: { color: '#e5e8eb' } },
        axisTick: { show: false },
        axisLabel: { color: '#8b95a1', fontSize: 11, hideOverlap: true },
      },
      yAxis: {
        type: 'value',
        scale: true,
        splitLine: { lineStyle: { color: '#f2f4f6' } },
        axisLabel: { color: '#8b95a1', fontSize: 11, formatter: (v) => `${v.toLocaleString()}만` },
      },
      dataZoom: [
        { type: 'inside' },
        {
          type: 'slider', height: 22, bottom: 14, borderColor: 'transparent',
          fillerColor: 'rgba(49,130,246,0.12)', handleStyle: { color: '#3182f6' },
        },
      ],
      series: [
        {
          name: '매매', type: 'line', data: show.mae ? data.mae_price : [],
          smooth: true, showSymbol: false, connectNulls: false,
          lineStyle: { width: 2.6 }, areaStyle: { color: 'rgba(0,168,77,0.06)' },
        },
        {
          name: '전세', type: 'line', data: show.jun ? data.jun_price : [],
          smooth: true, showSymbol: false, connectNulls: false, lineStyle: { width: 2.6 },
        },
      ],
    }
  }, [data, show])

  const ctx = propertyInfo
    ? `${propertyInfo.sigungu || region} ${propertyInfo.dong || ''} ${propertyInfo.jibun || ''} · ${TYPE_LABEL[buildingType]}${propertyInfo.exclusive_area_m2 ? ` · 전용 ${propertyInfo.exclusive_area_m2}㎡` : ''}`
    : `${region} · ${TYPE_LABEL[buildingType]}`

  return (
    <div className="app">
      <div className="brand">
        <span className="logo">온전</span>
        <span className="tag">이 집, 주변 시세는 어떻게 흘러왔나</span>
      </div>

      <div className="tabs">
        <button className={view === 'trends' ? 'on' : ''} onClick={() => setView('trends')}>시세 흐름</button>
        <button className={view === 'decide' ? 'on' : ''} onClick={() => setView('decide')}>내 조건 진단</button>
      </div>

      {view === 'decide' ? <Decision /> : (
      <>
      <section className="hero">
        <span className="level-badge">
          <span className="dot" />
          {data?.level_label || '지역 기준'}
        </span>
        <div className="context">{ctx}</div>
        <div className="price">
          <span className="num">{stat ? stat.last.toLocaleString() : '—'}</span>
          <span className="unit">만원/평 (매매)</span>
          {stat && (
            <span className={`change ${stat.pct > 0.05 ? 'up' : stat.pct < -0.05 ? 'down' : 'flat'}`}>
              {stat.pct > 0 ? '▲' : stat.pct < 0 ? '▼' : ''} {Math.abs(stat.pct).toFixed(1)}%
              <span style={{ color: 'var(--text-3)', fontWeight: 600 }}> · 기간 전 대비</span>
            </span>
          )}
        </div>

        <div className="controls">
          <select className="select" value={region} onChange={(e) => setRegion(e.target.value)}>
            {SEOUL_GU.map((g) => <option key={g} value={g}>{g}</option>)}
          </select>
          <select className="select" value={buildingType} onChange={(e) => setBuildingType(e.target.value)}>
            {BUILDING_TYPES.map((t) => <option key={t.v} value={t.v}>{t.l}</option>)}
          </select>
          <label className="upload">
            📄 등기부 올리기
            <input type="file" accept="application/pdf" onChange={onUpload} />
          </label>
          <div className="seg">
            {PERIODS.map((p) => (
              <button key={p.v} className={period === p.v ? 'on' : ''} onClick={() => setPeriod(p.v)}>
                {p.l}
              </button>
            ))}
          </div>
        </div>
      </section>

      <section className="chart-card">
        <div className="legend">
          <span className={show.mae ? '' : 'off'} onClick={() => setShow((s) => ({ ...s, mae: !s.mae }))} style={{ cursor: 'pointer' }}>
            <i style={{ background: '#00a84d' }} />매매
          </span>
          <span className={show.jun && !junUnavailable ? '' : 'off'} onClick={() => setShow((s) => ({ ...s, jun: !s.jun }))} style={{ cursor: 'pointer' }}>
            <i style={{ background: '#0066ff' }} />전세
          </span>
        </div>
        {loading ? (
          <div className="state">불러오는 중…</div>
        ) : error ? (
          <div className="state">{error}</div>
        ) : data?.dates?.length ? (
          <ReactECharts option={option} style={{ height: 340 }} notMerge />
        ) : (
          <div className="state">해당 조건의 실거래가 아직 없어요. 기간이나 유형을 바꿔보세요.</div>
        )}
      </section>

      {junUnavailable && (
        <div className="note">
          <b>전세 데이터는 아직 표시할 수 없어요.</b> 이 서비스키는 현재 <b>{TYPE_LABEL[buildingType]} 매매</b>만
          공공데이터포털 활용신청이 승인돼 있습니다. 전세·아파트·오피스텔까지 보려면 data.go.kr에서
          해당 실거래가 API를 추가로 활용신청하세요. (매매선은 실데이터로 정상 표시됩니다.)
        </div>
      )}
      <div className="note">
        국토교통부 실거래가 기반. 값은 <b>평당가(만원)</b> = 거래금액 ÷ (전용면적 ÷ 3.3058).
        특정 호실이 아니라 <b>{data?.level_label || '해당 지역'}</b>의 같은 유형 거래 집계이며, 당월은 신고 지연으로 불완전할 수 있어요.
      </div>
      </>
      )}
    </div>
  )
}
