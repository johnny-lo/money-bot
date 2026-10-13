"""登入後落地頁的判斷（`einvoice._login_landing()`）。

背景：登入**其實成功**（驗證碼也對）時，財政部可能把帳號導到
「資料設定／變更驗證碼(密碼)」頁 btc508w，頁面上沒有發票查詢的關鍵字；
當成未知狀態會重試到 4 次用完、抓 0 張。從那頁點「發票查詢及捐贈」就能正常查。

所以落地判斷要分三種：查詢頁（直接用）／已登入但在別頁（自己走去查詢頁）／未知。
"""
from einvoice import _login_landing

SEARCH = "https://www.einvoice.nat.gov.tw/portal/btc/mobile/btc502w/search"
SETTINGS = "https://www.einvoice.nat.gov.tw/portal/btc/mobile/btc508w/main"


def test_查詢頁直接算成功():
    assert _login_landing(SEARCH, "登出\n查詢發票\n發票號碼") == "search"


def test_被導到資料設定頁_算已登入但要改走查詢頁():
    body = "登出\n手機條碼專區\n資料設定\n變更驗證碼(密碼)\n原驗證碼(密碼)"
    assert _login_landing(SETTINGS, body) == "elsewhere"


def test_沒有登出鈕不能當成已登入():
    assert _login_landing(SETTINGS, "資料設定") == "unknown"


def test_只有登入鈕代表沒登入_不能當成已登入():
    # 判斷依據是「登出」鈕；頁上寫「登入」恰恰是未登入的樣子（drill 演習弄反過）
    assert _login_landing(SETTINGS, "登入\n手機條碼專區\n資料設定") == "unknown"


def test_不在手機條碼專區不能當成已登入():
    assert _login_landing("https://www.einvoice.nat.gov.tw/", "登出") == "unknown"
