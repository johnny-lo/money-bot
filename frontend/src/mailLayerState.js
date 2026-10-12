// 信件列表頁的狀態轉換：無 React、無 DOM，所以能直接用 node 內建 runner 測。
//
// 為什麼抽出來：「抓失敗之後畫面上還剩什麼」是規則，不是畫面。
// 寫在元件裡只能靠手機點點看；寫成 reducer（舊狀態＋動作→新狀態）就能釘住。
//
// 核心不變式：rows／data／offset 永遠是「同一個搜尋字」的結果。
// 所以換層或換搜尋字（'reload'）時整份清掉從頭來，而不是等新結果回來才換——
// 否則新搜尋一旦失敗，畫面會留著舊搜尋的列與總數，「載入更多」再拿新字去抓舊 offset，
// 把不相干的兩份結果接在一起。

export const initialLayerState = { rows: [], data: null, offset: 0, loading: true, error: '' }

export function layerReducer(state, action) {
  switch (action.type) {
    case 'reload':
      return { ...initialLayerState }
    case 'loaded':
      return {
        rows: action.d.rows || [],
        data: { kind: action.d.kind, total: action.d.total },
        offset: 0,
        loading: false,
        error: '',
      }
    case 'more':
      // 錯誤條要在重試的當下就收掉：失敗一次、再按一次成功後，條不該還掛在畫面上。
      // 已顯示的列與 offset 不動——失敗時它們仍然正確，重試就是同一段。
      return { ...state, loading: true, error: '' }
    case 'moreLoaded':
      return {
        rows: [...state.rows, ...(action.d.rows || [])],
        data: { kind: action.d.kind, total: action.d.total },
        offset: action.offset,
        loading: false,
        error: '',
      }
    case 'failed':
      return { ...state, loading: false, error: action.error }
    default:
      return state
  }
}
