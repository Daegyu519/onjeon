import { useEffect, useMemo, useState } from 'react'
import ReactECharts from 'echarts-for-react'
import Decision from './Decision'
import MarketMap from './MarketMap'
import { PY_M2, m2py } from './money'

const SEOUL_GU = [
  '종로구', '중구', '용산구', '성동구', '광진구', '동대문구', '중랑구', '성북구',
  '강북구', '도봉구', '노원구', '은평구', '서대문구', '마포구', '양천구', '강서구',
  '구로구', '금천구', '영등포구', '동작구', '관악구', '서초구', '강남구', '송파구', '강동구',
]
const BUILDING_TYPES = [
  { v: 'apt', l: '아파트' },
  { v: 'rh', l: '빌라(연립·다세대)' },
  { v: 'offi', l: '오피스텔' },
  { v: 'sh', l: '원룸·투룸(단독·다가구)' },
]
const PERIODS = [
  { v: '1m', l: '1개월' },
  { v: '6m', l: '6개월' },
  { v: '1y', l: '1년' },
  { v: '3y', l: '3년' },
  { v: '5y', l: '5년' },
]
const TYPE_LABEL = { apt: '아파트', rh: '빌라', offi: '오피스텔', sh: '단독·다가구' }
const nn = (a) => (a || []).filter((v) => v != null).length // 비-null 개수(희소 판정용)
// 헤드라인으로 고를 수 있는 지표(매매/전세/월세). arr=응답 필드, name=단위 옆 표기.
const METRICS = [
  { k: 'mae', tab: '매매', name: '매매', arr: 'mae_price', unit: '만원/평', unitM2: '만원/㎡' },
  { k: 'jun', tab: '전세', name: '전세', arr: 'jun_price', unit: '만원/평', unitM2: '만원/㎡' },
  { k: 'wolse', tab: '월세', name: '환산월세', arr: 'wolse_price', unit: '만원/평·월',
    unitM2: '만원/㎡·월' },
]
// 실거래가 API는 평당가로 준다. ㎡당은 3.3058로 나눈 값 — 배열을 통째로 바꿔야
// 헤드라인·축·툴팁이 한 단위로 맞는다(한 곳만 바꾸면 축과 숫자가 다른 단위가 된다).
const conv = (arr, unit) =>
  unit === 'py' ? arr : (arr || []).map((v) => (v == null ? null : +(v / PY_M2).toFixed(v < 100 ? 2 : 1)))
// 시계열 배열 → {최근값, 기간전 대비 %} | null(데이터 없음)
const statOf = (arr) => {
  const vals = (arr || []).filter((v) => v != null)
  if (!vals.length) return null
  const first = vals[0]
  const last = vals[vals.length - 1]
  return { last, pct: first ? ((last - first) / first) * 100 : 0 }
}

export default function App() {
  const [region, setRegion] = useState('관악구')
  const [buildingType, setBuildingType] = useState('rh')
  // 1년: 현재 공개 경로(ngrok)는 로컬 캐시를 서빙하고 거기에 61개월×100조합이 들어 있다.
  // (컨테이너 폴백의 동봉 캐시는 6개월이라 그 경우 뒷구간이 비는데, cache_only 안내가 처리한다)
  const [period, setPeriod] = useState('1y')
  const [metric, setMetric] = useState('mae') // 헤드라인 지표: mae|jun|wolse
  // 면적 단위: 시세는 평당으로 오는데 등기부·매물 정보는 ㎡다. 어느 쪽으로 볼지 고르게 한다.
  const [areaUnit, setAreaUnit] = useState('py') // py|m2
  const [dong, setDong] = useState(null)
  const [jibun, setJibun] = useState(null)
  const [propertyInfo, setPropertyInfo] = useState(null)

  const [data, setData] = useState(null)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState(null)
  const [show, setShow] = useState({ mae: true, jun: true })
  // 기본 탭 = 비교. 제품이 답하는 질문이 "전세가 월세보다 싼가"라서 첫 화면이 그 답이어야
  // 한다. 시세·지도는 그 숫자의 근거이므로 뒤로 보낸다.
  const [view, setView] = useState('decide')
  // 지도에서 고른 대상. null이면 지도만 보인다 — 시세 흐름을 아래에 늘 붙여두면
  // 페이지만 길어지고, 고르기 전에는 어느 동네 숫자인지도 알 수 없다.
  const [picked, setPicked] = useState(false)
  const [pendingReg, setPendingReg] = useState(null)

  useEffect(() => {
    if (!picked) return // 고르기 전엔 그릴 곳이 없다 — 요청도 하지 않는다
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
  }, [picked, region, buildingType, period, dong, jibun])

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
      setPendingReg(body) // 자동적용 X — 확인 후 적용(특히 OCR은 값이 틀릴 수 있음)
    } catch (err) {
      setError(err.message)
    } finally {
      e.target.value = ''
    }
  }

  function applyReg() {
    const b = pendingReg
    setPropertyInfo(b)
    if (b.building_type) setBuildingType(b.building_type)
    if (b.sigungu && SEOUL_GU.includes(b.sigungu)) setRegion(b.sigungu)
    setDong(b.dong || null)
    setJibun(b.jibun || null)
    setPendingReg(null)
    setPicked(true)
  }

  // 지도와 시세 흐름이 한 화면이라 '이동'은 스크롤이다. 등기부 맥락(propertyInfo)과
  // 지번은 지운다 — 다른 동네를 골랐는데 이전 매물 주소가 헤더에 남으면 어느 곳의
  // 숫자인지 오해하게 된다.

  function pickDong(pickedRegion, pickedDong) {
    if (SEOUL_GU.includes(pickedRegion)) setRegion(pickedRegion)
    setDong(pickedDong || null)
    setJibun(null)
    setPropertyInfo(null)
    setPicked(true)
  }

  // 구를 바꾸면 이전 동은 버린다 — 안 버리면 '강남구 봉천동'을 조회해 거래 0건이 나오고
  // 화면은 그걸 '거래가 없는 동네'로 말한다(지도와 한 화면이 되면서 더 밟기 쉬워졌다).
  function pickRegion(next) {
    setRegion(next)
    setDong(null)
    setJibun(null)
    setPropertyInfo(null)
  }

  const junUnavailable = data?.unavailable?.includes('jun_price')
  const hasWolse = data?.wolse_price?.some((v) => v != null)

  // 헤드라인 지표(매매/전세/월세) 선택 — 최근값 + 기간 전 대비 등락. 데이터 있는 지표만 노출.
  const availMetrics = METRICS.filter((m) => (data?.[m.arr] || []).some((v) => v != null))
  const cur = availMetrics.find((m) => m.k === metric) || availMetrics[0] || METRICS[0]
  // 등락률은 **원본 배열**에서 뽑는다. 단위 환산은 선형이라 비율이 바뀔 이유가 없는데,
  // 환산 후 반올림한 값으로 계산하면 같은 시계열이 평/㎡에서 9.1%와 9.0%로 갈린다(실측).
  const rawStat = statOf(data?.[cur.arr])
  const heroStat = rawStat && {
    pct: rawStat.pct,
    last: areaUnit === 'py' ? rawStat.last : conv([rawStat.last], areaUnit)[0],
  }

  const option = useMemo(() => {
    if (!data) return {}
    return {
      color: ['#00a84d', '#0066ff'],
      grid: { left: 6, right: 14, top: 18, bottom: 62, containLabel: true },
      tooltip: {
        trigger: 'axis',
        backgroundColor: '#26282b',
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
        axisLine: { lineStyle: { color: '#e7e3db' } },
        axisTick: { show: false },
        axisLabel: { color: '#6f6960', fontSize: 11, hideOverlap: true },
      },
      yAxis: {
        type: 'value',
        scale: true,
        splitLine: { lineStyle: { color: '#efece7' } },
        axisLabel: { color: '#6f6960', fontSize: 11, formatter: (v) => `${v.toLocaleString()}만` },
      },
      dataZoom: [
        { type: 'inside' },
        {
          type: 'slider', height: 22, bottom: 14, borderColor: 'transparent',
          fillerColor: 'rgba(96,88,76,0.10)', handleStyle: { color: '#ffbc00' },
        },
      ],
      series: [
        {
          name: '매매', type: 'line', data: show.mae ? conv(data.mae_price, areaUnit) : [],
          smooth: true, showSymbol: nn(data.mae_price) < 3, symbolSize: 6, connectNulls: false,
          lineStyle: { width: 2.6 }, areaStyle: { color: 'rgba(0,168,77,0.06)' },
        },
        {
          name: '전세', type: 'line', data: show.jun ? conv(data.jun_price, areaUnit) : [],
          smooth: true, showSymbol: nn(data.jun_price) < 3, symbolSize: 6, connectNulls: false,
          lineStyle: { width: 2.6 },
        },
      ],
    }
  }, [data, show, areaUnit])

  // 월세는 (보증금+월세) → 실질(환산)월세라 자산가(매매·전세)와 스케일·단위가 달라
  // 이중축(dataviz 안티패턴) 대신 별도 차트로. 단일 축 · 희소하면 점.
  const wolseOption = useMemo(() => {
    if (!data || !hasWolse) return null
    // 툴팁 단위는 축과 같아야 한다 — '평당'으로 굳혀두면 ㎡로 본 값에 평 단위가 붙는다
    const unitLabel = areaUnit === 'py' ? '만원/평·월' : '만원/㎡·월'
    return {
      color: ['#e8590c'], // 월세 = 따뜻한 오렌지(자산 라인과 구분, 월 비용 함의)
      grid: { left: 6, right: 14, top: 14, bottom: 24, containLabel: true },
      tooltip: {
        trigger: 'axis', backgroundColor: '#26282b', borderWidth: 0, padding: [10, 12],
        textStyle: { color: '#fff', fontSize: 12 },
        formatter: (ps) => {
          const p = ps.find((x) => x.value != null)
          if (!p) return ''
          return `<div style="font-weight:700;margin-bottom:5px">${ps[0].axisValue}</div>
            <div style="display:flex;justify-content:space-between;gap:18px">
            <span>${p.marker}환산월세</span>
            <b style="font-variant-numeric:tabular-nums">${p.value.toLocaleString()}${unitLabel}</b></div>`
        },
      },
      xAxis: {
        type: 'category', data: data.dates, boundaryGap: false,
        axisLine: { lineStyle: { color: '#e7e3db' } }, axisTick: { show: false },
        axisLabel: { color: '#6f6960', fontSize: 11, hideOverlap: true },
      },
      yAxis: {
        type: 'value', scale: true,
        splitLine: { lineStyle: { color: '#efece7' } },
        axisLabel: { color: '#6f6960', fontSize: 11, formatter: (v) => `${v}만` },
      },
      series: [{
        name: '환산월세', type: 'line', data: conv(data.wolse_price, areaUnit),
        smooth: true, showSymbol: nn(data.wolse_price) < 3, symbolSize: 7, connectNulls: false,
        lineStyle: { width: 2.6 }, areaStyle: { color: 'rgba(232,89,12,0.06)' },
      }],
    }
  }, [data, hasWolse, areaUnit])

  // 지도에서 고른 동이 헤더에 안 보이면 어느 곳의 숫자인지 알 수 없다 — 지도가 입구가
  // 되면서 동이 기본값이 됐으므로 여기에 적는다.
  const ctx = propertyInfo
    ? `${propertyInfo.sigungu || region} ${propertyInfo.dong || ''} ${propertyInfo.jibun || ''} · ${TYPE_LABEL[buildingType]}${propertyInfo.exclusive_area_m2 ? ` · 전용 ${m2py(propertyInfo.exclusive_area_m2)}` : ''}`
    : `${region}${dong ? ` ${dong}` : ''} · ${TYPE_LABEL[buildingType]}`

  return (
    <div className="app">
      <div className="brand">
        <span className="logo">온전</span>
        <span className="tag">온전히 내 집을 가질 그날까지</span>
      </div>

      <div className="tabs">
        <button className={view === 'decide' ? 'on' : ''} onClick={() => setView('decide')}>전세 vs 월세</button>
        <span className="tab-sep">근거</span>
        <button className={view === 'map' ? 'on' : ''} onClick={() => setView('map')}>동네 지도</button>
      </div>

      {view === 'decide' ? <Decision /> : (
      <>
      {pendingReg && (
        <div className={`confirm ${pendingReg.ocr ? 'ocr' : ''}`}>
          <div className="confirm-h">
            {pendingReg.ocr ? '📸 스캔 자동인식(OCR) — 숫자가 틀릴 수 있어요. 꼭 확인하세요' : '📄 등기부 인식 결과 — 맞나요?'}
          </div>
          <div className="confirm-fields">
            {pendingReg.sigungu || '?'} {pendingReg.dong || ''} {pendingReg.jibun || ''} · {pendingReg.building_use || '?'}
            {pendingReg.exclusive_area_m2 ? ` · 전용 ${m2py(pendingReg.exclusive_area_m2)}` : ''}
          </div>
          <div className="confirm-btns">
            <button className="ok" onClick={applyReg}>맞아요, 적용</button>
            <button onClick={() => setPendingReg(null)}>취소</button>
          </div>
        </div>
      )}

      {/* 지도와 시세 흐름이 같은 자리를 나눠 쓴다. 유형·지표·기간은 둘이 같이 쓰는
          상태라 이 헤더에 한 벌만 두고, 아래 본문만 지도↔차트로 바뀐다. */}
      <section className="hero">
        {picked ? (
          <>
            <div className="pick-head">
              <button className="back" onClick={() => setPicked(false)}>← 지도</button>
              <span className="level-badge">
                <span className="dot" />
                {data?.level_label || '지역 기준'}
              </span>
            </div>
            <div className="context">
              {ctx}
              {dong && (
                // 동을 고른 뒤 구 전체로 돌아갈 길 — 지도 클릭은 항상 동 단위라 이게 없으면 못 푼다
                <button className="clear-dong" onClick={() => pickRegion(region)}>구 전체로</button>
              )}
            </div>
            <div className="price">
              <span className="num">{heroStat ? heroStat.last.toLocaleString() : '—'}</span>
              <span className="unit">{areaUnit === 'py' ? cur.unit : cur.unitM2} ({cur.name})</span>
              {heroStat && (
                <span className={`change ${heroStat.pct > 0.05 ? 'up' : heroStat.pct < -0.05 ? 'down' : 'flat'}`}>
                  {heroStat.pct > 0 ? '▲' : heroStat.pct < 0 ? '▼' : ''} {Math.abs(heroStat.pct).toFixed(1)}%
                  <span style={{ color: 'var(--text-3)', fontWeight: 600 }}> · 기간 전 대비</span>
                </span>
              )}
              {cur.k === 'wolse' && data?.conversion_rate ? (
                <span style={{ color: 'var(--text-3)', fontWeight: 600, fontSize: 13 }}>
                  · 전월세전환율 {(data.conversion_rate * 100).toFixed(1)}%
                </span>
              ) : null}
            </div>
            {/* 지표는 지도와 공유하는데 이 동네엔 그 거래가 없을 수 있다. 조용히 다른 지표를
                보여주면 사용자는 위 지표 버튼을 믿고 잘못 읽는다 — 바뀐 사실을 말한다. */}
            {cur.k !== metric && (
              <div className="fallback">
                이 조건은 {METRICS.find((m) => m.k === metric)?.name} 거래가 없어 <b>{cur.name}</b> 기준으로 보여드려요
              </div>
            )}
          </>
        ) : (
          <div className="context">서울 전체 · {TYPE_LABEL[buildingType]} · 법정동별 평당가 — 누르면 시세 흐름</div>
        )}

        <div className="metric-row">
          <div className="seg metric-seg">
            {METRICS.map((m) => (
              <button key={m.k} className={metric === m.k ? 'on' : ''} onClick={() => setMetric(m.k)}>
                {m.tab}
              </button>
            ))}
          </div>
          {/* 시세는 평당으로 오는데 등기부·매물은 ㎡다 — 환산을 사용자 머릿속에 떠넘기지 않는다 */}
          <span className="unit-tog">
            {[['py', '평'], ['m2', '㎡']].map(([u, l]) => (
              <button
                key={u} type="button" className={areaUnit === u ? 'on' : ''}
                aria-pressed={areaUnit === u}
                aria-label={`시세 단위 ${u === 'py' ? '평당' : '제곱미터당'}으로 보기`}
                onClick={() => setAreaUnit(u)}
              >{l}</button>
            ))}
          </span>
        </div>
        <div className="controls">
          {picked && (
            <select className="select" value={region} onChange={(e) => pickRegion(e.target.value)}>
              {SEOUL_GU.map((g) => <option key={g} value={g}>{g}</option>)}
            </select>
          )}
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

      {!picked ? (
        <MarketMap
          buildingType={buildingType}
          period={period}
          metric={metric}
          typeLabel={TYPE_LABEL[buildingType]}
          onPick={pickDong}
        />
      ) : (
      <>
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
        ) : data?.cache_only ? (
          // 읽기 전용 배포에선 빈 구간이 '거래 없음'이 아니라 '아직 수집 안 됨'일 수 있다
          <div className="state">이 조건은 아직 수집된 시세가 없어요. 다른 지역·유형을 골라보세요.</div>
        ) : (
          <div className="state">해당 조건의 실거래가 아직 없어요. 기간이나 유형을 바꿔보세요.</div>
        )}
      </section>

      {hasWolse && (
        <section className="chart-card mini">
          <div className="mini-title">
            <i style={{ background: '#e8590c' }} />월세 실질(환산) ·
            {areaUnit === 'py' ? ' 평당 ' : ' ㎡당 '}<span>만원/월</span>
          </div>
          <ReactECharts option={wolseOption} style={{ height: 210 }} notMerge />
        </section>
      )}

      {junUnavailable && (
        <div className="note">
          <b>{TYPE_LABEL[buildingType]} 전세·월세 실거래가가 아직 활용신청 승인 전이에요.</b> data.go.kr에서
          해당 전월세 API를 활용신청하면 같은 키로 표시됩니다. (매매선은 실데이터로 정상 표시)
        </div>
      )}
      <div className="note">
        국토교통부 실거래가 기반. 매매·전세는 <b>평당가(만원)</b> = 거래금액 ÷ (전용면적 ÷ 3.3058)로
        구하고, <b>㎡</b>를 고르면 그 값을 3.3058로 나눠 보여줍니다.
        특정 호실이 아니라 <b>{data?.level_label || '해당 지역'}</b>의 같은 유형 거래 집계이며, 당월은 신고 지연으로 불완전할 수 있어요.
        <br /><b>월세는 실질(환산월세)</b> = 월세 + 보증금 × 전월세전환율{data?.conversion_rate ? `(${(data.conversion_rate * 100).toFixed(1)}%)` : ''} ÷ 12 를 평당 환산해 <b>아래 별도 차트</b>로 표시하고, 거래가 적은 구간은 <b>점</b>으로 나타냅니다.
      </div>
      </>
      )}
      </>
      )}
    </div>
  )
}
