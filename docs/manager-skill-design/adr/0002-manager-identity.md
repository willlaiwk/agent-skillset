# ADR-0002 — 以 Manager ID 隔離工作單位

- 狀態：Accepted；MM-02 namespace 已實作，MM-03 主控交接待完成。
- 日期：2026-10-08；定案：2026-10-09（MM-01）。
- 關聯：[SPEC-001 §3–6](../specs/001-multi-manager-isolation.md#3-manager-身分與選擇契約)、[MM-01–MM-03](../tasks.md)、[契約檢查](../reviews/MM-01-contract-review.md)。

## 背景

同 root 的 Session 現在共用 `.manager/` 與 tmux。現有檔案鎖只能序列化 CLI 操作，不能分開計畫與管理決策。使用者希望指定 ID 接續／新建；未指定時建立新的 manager。

## 決策

Manager 是持久化工作單位，Session 是暫時主控。以 `(canonical project root, manager_id)` 識別，資料放在 `.manager/{manager-id}/`；task/branch/tmux/report/recovery 都包含 manager 身分。採用 v2 schema 與完整 worker launch identity，使用 assignment ID 區分同名 task／同 attempt 的錯誤路由。

只有 `init` 可以省略 ID 並建立新的工作單位；後續操作明確攜帶 selector。Skill 記住並顯示 ID，不建立專案全域 current-manager 指標。`init` 接續不自動 claim 或 reconcile；查閱命令不修改 registry。

同 ID 採明確 `owner claim`／`release`／`takeover`，以 token 與遞增 generation fence 舊主控。Credential 存呼叫端指定的私有檔案，不進入 worker prompt/environment。Takeover 需 expected generation 與原因；時間或 PID 只提供診斷，不自動判定失聯或接管。Compaction／同主控恢復沿用有效 credential；遺失時明確交接。

長 verify 在 registry 鎖外執行，operation lock 保護同 worktree；收尾重新檢查 ownership/snapshot，只提交該操作欄位。Owner 交接不阻塞 worker report，也不讓舊主控將長操作結果寫成有效驗證。CLI 與失敗情境的唯一詳細契約在 SPEC-001 §4–6。

## 替代方案

- 每 Session 一套暫存資料：隔離容易，但 Session 重啟與有意接續失去穩定身分。
- 只要求 task ID 不重複：plan、worker 指示、資源計數仍共用。
- 專案 current-manager 檔案：第二個 Session 可改變第一個的路由。
- 每次 CLI 沒有 ID 都建立新的：同一流程被拆成無關資料。
- Owner 自動 lease expiry／以 PID 判定失聯：LLM 思考、compaction 與長檢查無可靠 Session 存活訊號，可能錯誤接管；明確 fencing 較可診斷。

## 代價與限制

CLI、protocol、schema、測試與 migration 需同步。Owner credential 的保存與交接增加操作成本；遺失不能靜默恢復。同 host 使用者仍能直接改檔案或複製 token，這是合作式所有權，不是安全沙箱。Takeover 不終止 provider 或長 checks；新主控需尊重 operation busy。

每 manager 的 worker 額度會增加專案總並行數，文件須明示。不同 ID 不解決共享主 checkout／Git metadata 干擾，由 [ADR-0003](0003-isolated-integration.md) 處理。

## 定案結果

2026-10-09 依使用者開始 MM-01 的指示，完成 selector/schema 與 Q-01 契約收斂，從 Proposed 改為 Accepted。兩 Session／長 verify 的 walkthrough 記錄於契約檢查；不是 MM-02／MM-03 runtime 驗收。

2026-10-10 MM-02 完成 namespace／路由／純查閱與基本 claim/credential guard，實作證據見 [MM-02 validation](../reviews/MM-02-validation.md)。Release/takeover、交接恢復與長操作 fencing 仍由 MM-03 接續；本補充不改變原決策或宣稱完整主控驗收。
