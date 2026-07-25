// 금액 문자열 ↔ 원(₩) 정수 변환. 한글 단위("1억 2천 3백만원")·콤마 입력을 원으로,
// 원을 3자리 콤마와 한글 판독("1억 2,300만원")으로. 표시/입력 전용 — 계산은 백엔드(엔진).
//
// 파싱 규칙(myriad): 억(1e8)·만(1e4)이 큰 구분자, 천/백/십은 구간 내 승수.
//   "1억2천3백만" → (2천+3백)만 + 1억 = 123,000,000
// 한계: "1억5천"처럼 억 뒤 만 없는 천/백/십은 문자 그대로(=100,005,000) 해석한다.
//   부동산 관용의 "1억5천만"을 원하면 '만'을 붙여야 하며, 하단 gloss가 결과를 즉시 보여줘 확인된다.

const BIG = { 억: 1e8, 만: 1e4 }
const SMALL = { 천: 1e3, 백: 1e2, 십: 1e1 }

/** 문자열 → 원(정수) | null(빈값·비수치). */
export function parseWon(input) {
  if (input == null) return null
  const s = String(input).trim()
  if (!s) return null

  // 한글 단위 없으면 콤마·원·공백 제거 후 숫자로
  if (!/[억만천백십]/.test(s)) {
    const n = Number(s.replace(/[,\s원]/g, ''))
    return Number.isFinite(n) && n >= 0 ? Math.round(n) : null
  }

  let total = 0
  let section = 0
  let pending = null // 방금 읽은 숫자(소수 허용)
  const re = /(\d+(?:\.\d+)?)|([억만천백십])/g
  let m
  while ((m = re.exec(s))) {
    if (m[1] != null) {
      pending = parseFloat(m[1])
    } else if (m[2] in SMALL) {
      section += (pending ?? 1) * SMALL[m[2]]
      pending = null
    } else {
      // 억/만: 지금까지의 구간을 큰 단위로 확정
      let sec = section + (pending ?? 0)
      if (sec === 0) sec = 1 // "억"/"만" 단독 → 1억/1만
      total += sec * BIG[m[2]]
      section = 0
      pending = null
    }
  }
  total += section + (pending ?? 0)
  return Math.round(total)
}

/** 원(정수) → "123,000,000". null/NaN → "". */
export function formatWon(n) {
  if (n == null || !Number.isFinite(n)) return ''
  return Math.round(n).toLocaleString('en-US')
}

/** 원(정수) → 한글 판독 "1억 2,300만원". null → "". */
export function glossKR(n) {
  if (n == null || !Number.isFinite(n)) return ''
  n = Math.round(n)
  const eok = Math.floor(n / 1e8)
  const man = Math.floor((n % 1e8) / 1e4)
  const won = n % 1e4
  const parts = []
  if (eok) parts.push(`${eok.toLocaleString('en-US')}억`)
  if (man) parts.push(`${man.toLocaleString('en-US')}만`)
  if (won || parts.length === 0) parts.push(`${won.toLocaleString('en-US')}원`)
  else parts[parts.length - 1] += '원'
  return parts.join(' ')
}

// 자체검증: `node web/src/money.js` 직접 실행 시만 (브라우저에선 process 미정의라 건너뜀).
if (typeof process !== 'undefined' && import.meta.url === `file://${process.argv[1]}`) {
  const eq = (a, b, msg) => {
    if (a !== b) throw new Error(`FAIL ${msg}: ${a} !== ${b}`)
  }
  eq(parseWon('1억 2천 3백만원'), 123000000, 'p1')
  eq(parseWon('1억2천3백만'), 123000000, 'p2')
  eq(parseWon('5천만'), 50000000, 'p3')
  eq(parseWon('55만'), 550000, 'p4')
  eq(parseWon('3억'), 300000000, 'p5')
  eq(parseWon('1.2억'), 120000000, 'p6')
  eq(parseWon('2천3백만원'), 23000000, 'p7')
  eq(parseWon('123,000,000'), 123000000, 'p8')
  eq(parseWon('550000'), 550000, 'p9')
  eq(parseWon(''), null, 'p10')
  eq(parseWon('abc'), null, 'p11')
  eq(parseWon(null), null, 'p12')
  eq(formatWon(123000000), '123,000,000', 'f1')
  eq(formatWon(null), '', 'f2')
  eq(glossKR(123000000), '1억 2,300만원', 'g1')
  eq(glossKR(550000), '55만원', 'g2')
  eq(glossKR(5000), '5,000원', 'g3')
  eq(glossKR(20000000), '2,000만원', 'g4')
  eq(glossKR(null), '', 'g5')
  console.log('money.js selfcheck OK')
}
