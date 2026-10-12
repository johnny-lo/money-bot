// 信件分頁的純函式：無 React、無 DOM、無 I/O，所以能直接用 node 內建 runner 測。
//
// 為什麼把這些從 Mail.jsx 拆出來：「哪幾層算 🛡」「各種列要顯示什麼字」都是規則，不是畫面。
// 規則混在 JSX 裡就只能靠手機點點看；放在這裡就能寫測試釘住（跟 ledgerFilter.js 同一招）。
//
// 跑測試：cd frontend && npm test

// 🛡 三層是「寧可留在收件匣也不能被整理掉」的保護名單（求職字眼／重視的公司／真人來信），
// 總覽把它們排在最前面一組，一眼就看得到保護網現在抓了幾封。
const SHIELD_KEYS = ['job', 'valued', 'human']

// layers = API 回的 [{key, title, count}]。
// 🛡 組的順序以 SHIELD_KEYS 為準（不是 API 回傳順序），其餘照原順序——
// 後端哪天調整 LAYERS 排序，🛡 三張卡的位置也不會跟著亂跳。
export function groupOverview(layers) {
  const shield = SHIELD_KEYS
    .map((k) => layers.find((l) => l.key === k))
    .filter(Boolean)
  const rest = layers.filter((l) => !SHIELD_KEYS.includes(l.key))
  return { shield, rest }
}

// 每層都 0 筆 ＝ 信件還沒同步進來過。
// 這時畫一排 0 會被誤認成「整理過了、什麼都沒抓到」，所以要另外講清楚。
export function allEmpty(layers) {
  return layers.every((l) => l.count === 0)
}

// 一列要顯示的三段字：main（主標）、sub（小字）、badge（右側標籤）。
// 四種 kind 的欄位不一樣（見後端 mailrules/views.py），統一收斂成同一個形狀，
// 這樣 Mail.jsx 只需要一種「列」元件，不用依 kind 寫四套 JSX。
export function rowText(kind, row) {
  switch (kind) {
    case 'messages':
      // next＝下一步預告（例如「10/20 丟」），有的話比所在位置更值得看，所以優先顯示
      return {
        main: row.subject,
        sub: `${row.date ?? ''}・${row.sender}`,
        badge: row.next ?? row.where,
      }
    case 'domains':
      return {
        main: row.domain,
        sub: `加入 ${row.since}・${row.pattern ?? ''}`,
        badge: `${row.count} 封`,
      }
    case 'rules':
      return {
        main: row.sender,
        sub: row.pattern,
        badge: `${row.category}・${row.status}`,
      }
    case 'groups':
      return {
        main: row.sender,
        sub: row.pattern,
        badge: `${row.count} 封`,
      }
    default:
      // 後端新增了前端還不認得的 kind：給個看得出來的字，而不是整頁炸掉
      return { main: '（未知的列）', sub: '', badge: '' }
  }
}
