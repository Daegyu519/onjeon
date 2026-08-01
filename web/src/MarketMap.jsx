import { useEffect, useMemo, useState } from 'react'
import * as echarts from 'echarts'
import ReactECharts from 'echarts-for-react'
import seoulGu from './seoul_gu.json'

// 서울 25개 자치구 경계(KOSTAT 2013, Apache 2.0 — southkorea/seoul-maps). 57KB라
// 별도 fetch 없이 번들에 싣는다. 법정동 폴리곤이 아니라 구 경계인 건 의도된 선택 —
// 공개된 동 단위 경계는 대부분 행정동이라 법정동 기반인 실거래가 데이터와 안 맞는다
// (봉천동 하나가 행정동으론 여러 조각). 동은 폴리곤 대신 중심점 버블로 얹는다.
echarts.registerMap('seoul', seoulGu)

// 지표별 순차 색상 램프(밝음=쌈, 진함=비쌈). 시세 흐름 차트의 지표 색과 같은 계열이라
// 탭을 오가도 "초록=매매, 파랑=전세, 주황=월세"가 유지된다.
const RAMP = {
  mae: ['#d3f0e0', '#5fca94', '#00a84d', '#00552a'],
  jun: ['#d6e4ff', '#6aa3ff', '#0066ff', '#003a91'],
  wolse: ['#ffe3d1', '#ffab7a', '#e8590c', '#8a3306'],
}
const METRIC_LABEL = { mae: '매매', jun: '전세', wolse: '환산월세' }
const SPARSE = '#dcd7ce' // 거래 희소 → 색으로 가격을 주장하지 않는다

export default function MarketMap({ buildingType, period, metric, typeLabel, onPick }) {
  const [data, setData] = useState(null)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState(null)

  useEffect(() => {
    const q = new URLSearchParams({ buildingType, period, metric })
    setLoading(true)
    setError(null)
    fetch(`/api/market-map?${q}`)
      .then(async (r) => {
        if (!r.ok) throw new Error((await r.json()).detail || `오류 ${r.status}`)
        return r.json()
      })
      .then(setData)
      .catch((e) => setError(e.message))
      .finally(() => setLoading(false))
  }, [buildingType, period, metric])

  const priced = useMemo(() => (data?.points || []).filter((p) => p.price != null), [data])
  const sparse = useMemo(() => (data?.points || []).filter((p) => p.price == null), [data])

  const option = useMemo(() => {
    if (!priced.length && !sparse.length) return null
    const prices = priced.map((p) => p.price)
    // 거래량 → 버블 반지름. 면적이 건수에 비례하도록 sqrt(원 면적 = πr²) — r을 건수에
    // 그대로 비례시키면 많은 동이 실제 배율보다 훨씬 커 보인다.
    const maxN = Math.max(1, ...(data?.points || []).map((p) => p.n))
    const size = (n) => 7 + 21 * Math.sqrt(n / maxN)
    // 색은 로그 눈금(value[4]). 평당가는 로그정규에 가까워서 선형으로 칠하면 용산
    // 최고가가 스케일을 독점하고 나머지 90%가 램프 바닥에 뭉친다(실측: 중앙값이
    // 선형 스케일의 8.9% 지점). 로그로 펴야 동네 간 차이가 색으로 읽힌다.
    const point = (p) => ({
      name: `${p.region} ${p.dong}`,
      value: [p.lng, p.lat, p.price, p.n, p.price ? Math.log10(p.price) : 0],
    })

    return {
      geo: {
        map: 'seoul',
        roam: true,
        zoom: 1.2,
        layoutCenter: ['54%', '50%'], // 좌하단 색 범례를 피해 살짝 오른쪽
        layoutSize: '96%',
        itemStyle: { areaColor: '#faf9f6', borderColor: '#e3ded5', borderWidth: 1 },
        emphasis: { itemStyle: { areaColor: '#f0ede7' }, label: { show: false } },
        select: { disabled: true },
      },
      tooltip: {
        trigger: 'item',
        backgroundColor: '#26282b',
        borderWidth: 0,
        padding: [10, 12],
        textStyle: { color: '#fff', fontSize: 12 },
        formatter: (p) => {
          const [, , price, n] = p.value
          const head = `<div style="font-weight:700;margin-bottom:5px">${p.name}</div>`
          const body = price == null
            ? `<div>거래 ${n}건 — 평균을 내기엔 적어요</div>`
            : `<div style="display:flex;justify-content:space-between;gap:18px">
                 <span>${METRIC_LABEL[metric]}</span>
                 <b style="font-variant-numeric:tabular-nums">${price.toLocaleString()}${data.unit}</b>
               </div><div style="color:#b0b8c1">거래 ${n.toLocaleString()}건</div>`
          return head + body
        },
      },
      visualMap: prices.length ? {
        type: 'continuous',
        min: Math.log10(Math.min(...prices)),
        max: Math.log10(Math.max(...prices)),
        dimension: 4,
        seriesIndex: 0,
        left: 10,
        bottom: 12,
        itemHeight: 110,
        calculable: true,
        inRange: { color: RAMP[metric] || RAMP.mae },
        textStyle: { color: '#6f6960', fontSize: 11 }, // --text-3: 흰 배경 4.6:1(AA)
        formatter: (v) => Math.round(10 ** v).toLocaleString(), // 로그 눈금 → 원래 금액 표기
      } : undefined,
      series: [
        {
          name: METRIC_LABEL[metric],
          type: 'scatter',
          coordinateSystem: 'geo',
          data: priced.map(point),
          symbolSize: (v) => size(v[3]),
          itemStyle: { borderColor: 'rgba(255,255,255,0.85)', borderWidth: 1 },
          emphasis: { scale: 1.25 },
        },
        {
          name: '거래 희소',
          type: 'scatter',
          coordinateSystem: 'geo',
          data: sparse.map(point),
          symbolSize: (v) => size(v[3]),
          itemStyle: { color: SPARSE, borderColor: 'rgba(255,255,255,0.85)', borderWidth: 1 },
          emphasis: { scale: 1.25 },
        },
      ],
    }
  }, [priced, sparse, metric, data])

  const onEvents = useMemo(() => ({
    click: (p) => {
      // 구 경계(geo)를 누르면 그 구 전체, 버블(series)을 누르면 그 동. 버블은 이름이
      // '관악구 봉천동'이라 첫 어절이 구다. 구 클릭이 없으면 버블이 없는 동네는
      // 아예 열 수 없다 — 거래가 희소한 구일수록 그렇다.
      if (p.componentType === 'geo') return onPick(p.name, null)
      if (!p.name) return
      const [region, ...rest] = p.name.split(' ')
      onPick(region, rest.join(' '))
    },
  }), [onPick])

  return (
    <>
      <section className="chart-card">
        {loading ? (
          <div className="state">불러오는 중…</div>
        ) : error ? (
          <div className="state">{error}</div>
        ) : option ? (
          <ReactECharts option={option} style={{ height: 460 }} onEvents={onEvents} notMerge />
        ) : (
          <div className="state">이 조건은 아직 수집된 시세가 없어요. 유형이나 기간을 바꿔보세요.</div>
        )}
      </section>

      <div className="note">
        서울 <b>{typeLabel}</b> {METRIC_LABEL[metric]} 평당가를 법정동 중심점에 표시했어요.
        <b>색이 진할수록 비싸고</b>, <b>원이 클수록 거래가 많습니다</b>. <b>버블을 누르면 그 동네</b>, <b>구 경계를 누르면 그 구 전체</b>의 시세 흐름이 이 자리에 열려요.
        동네 간 가격 차가 10배를 넘어서 색은 <b>로그 눈금</b>이에요 — 색 한 칸이 일정 금액이 아니라 일정 배율입니다.
        {data && (
          <>
            <br />거래 <b>{data.min_deals}건 미만</b>인 동({sparse.length}곳)은 평균 대신 회색으로 뒀어요 —
            몇 건뿐인 평균을 색으로 주장하지 않기 위해서입니다.
            {data.missing_geo > 0 && ` 좌표를 못 찾은 동 ${data.missing_geo}곳은 지도에서 빠져 있어요.`}
          </>
        )}
        <br />구 경계: KOSTAT 2013 · 거래: 국토교통부 실거래가 · 좌표: OpenStreetMap(Nominatim).
      </div>
    </>
  )
}
