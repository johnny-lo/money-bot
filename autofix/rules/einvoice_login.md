- 真實登入只能用 `bin/probe einvoice --carrier <N>`。**整個事件最多送出 3 次登入表單**（harness 在網路層強制，
  超過會被 abort）——財政部帳密/驗證碼錯誤累計 40 次會鎖帳號，而且無法復原。先讀程式、讀現場 attempts，想清楚再打。
- probe 失敗時會把每個頁面的 URL、遮罩後的內文、截圖存到 `.autofix-probe/`，用 Read 看。
- 若是密碼過期、帳號被鎖、需要使用者到財政部網站操作 → `needs_human`。
