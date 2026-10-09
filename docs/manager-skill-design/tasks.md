# Manager Skill — 開發任務

最後更新：2026-10-09。狀態定義與更新流程見 [README](README.md)。這份清單追蹤 skill 開發，不是產品專案 `.manager/` 的 runtime task registry。

2026-10-09 完成 MM-01：SPEC-001 為 Ready，ADR-0002–0004 為 Accepted。MM-02–MM-08 尚未開始；下一步從 MM-02 namespace 與路由實作接續。任務順序是依賴安排，不代表已啟動 worker 或授權外部交付。

## 任務索引

| ID | 目標 | 狀態 | 依賴 | 對應規格／決策 |
| --- | --- | --- | --- | --- |
| DOC-01 | 文件結構與此次設計初稿 | Done | 無 | ADR-0001；SPEC-001 初稿 |
| MM-01 | 收斂多 manager 的介面與未決契約 | Done | DOC-01 | SPEC-001 Q-01–Q-04；ADR-0002–0004 |
| MM-02 | Manager selector、namespace 與 worker 路由 | Todo | MM-01 | SPEC-001 §3–5；ADR-0002 |
| MM-03 | 同 ID 主控所有權與交接 | Todo | MM-02 | SPEC-001 §6；ADR-0002 |
| MM-04 | 每 manager 的整合工作樹與證據 | Todo | MM-02 | SPEC-001 §7.1；ADR-0003 |
| MM-05 | Repository 共用交付 gate | Todo | MM-03、MM-04 | SPEC-001 §7.2；ADR-0003 |
| MM-06 | v1 → v2 migration 與中斷恢復 | Todo | MM-02、MM-03、MM-04 | SPEC-001 §8–9；ADR-0004 |
| MM-07 | Skill／protocol／reference 同步與整體驗證 | Todo | MM-05、MM-06 | SPEC-001 AC-01–AC-14 |
| MM-08 | 新格式真實 provider smoke test | Todo | MM-07 | SPEC-001 AC-14；延續 MVP-02 缺口 |
| MVP-02 | 現有 MVP 真實 Worker smoke test | Todo | 現有 MVP | [progress 的原任務](progress.md) |
| P2-01 | DAG Scheduler | Todo | MVP 驗證及另立 spec | design §17、§32 |
| P2-02 | Event Watcher | Todo | MVP 驗證及另立 spec | design §26、§32 |
| P2-03 | Automatic Verification | Todo | MVP 驗證及另立 spec | design §24、§32 |
| P2-04 | Routing／Retry Policy | Todo | MVP 驗證及另立 spec | design §21–22、§25、§32 |

MVP-02 保留為原驗證缺口；若先實作 SPEC-001，MM-08 可涵蓋它，但只有實際證據符合原驗收條件後才能將兩者標為 Done。尚未選擇哪條路徑，不重複執行同樣 smoke test。

## 任務完成條件與接續

### DOC-01 — 文件結構與設計初稿

- 完成：建立 README、spec、ADR、task board，補 design 索引及 progress 接續。
- 證據：本目錄文件；[progress](progress.md) 記錄 9 份 Markdown、48 個本地連結／錨點及格式檢查結果。
- 邊界：只有文件完成，不代表任何新 runtime 能力完成。Commit 以 Git 實際紀錄為準。

### MM-01 — 契約收斂

- 目標：確認 selector／schema，定案主控 API、交付 workflow、migration branch mapping／backup／驗證歷史與停止條件。
- 完成條件：SPEC-001 Q-01–Q-04 各有可實作答案與故障情境；更新相關 ADR 狀態與理由；spec 達到 Ready。
- 驗證：兩 Session、長 verify、過期 target、dirty legacy worktree 與中斷的 12 項 walkthrough；8 項暫存 Git assertions 通過，另確認 symbolic-ref 邊界。不把 Git primitive 當 v2 CLI 驗收。
- 證據：[contract review](reviews/MM-01-contract-review.md)、[Git 結果](reviews/mm01-git-results.json)；Q-01–Q-04 定案，無待收斂 blocker。
- 接續：MM-02。Runtime／provider 未修改或驗證；commit 以 Git 實際紀錄為準。

### MM-02 — Namespace 與路由

- 目標：新 ID 建立／接續、明確 selector、v2 state、branch/tmux/path 與 attempt/assignment identity 隔離、managers 清單及純讀取查閱。
- 完成條件：AC-01–AC-05；不合法 ID、symlink、state 損壞與 legacy 格式有明確錯誤；每 manager 額度可辨識。
- 驗證：暫存 Git repo 中並行初始化、兩 manager 同名 task、跨 manager report/ack／reconcile，不只測字串含 ID。
- 證據／阻塞／接續：未開始；MM-01 依賴已完成。實作入口為 SPEC-001 §3–5（含 init 不自動 claim/reconcile、reserved IDs、common exclude 與 launch identity）；開始後更新 spec 為 Implementing。

### MM-03 — 主控所有權

- 目標：單一主控、純讀取查閱、交接與舊主控 fencing；長 verify 期間與交接後結果提交可辨識。
- 完成條件：AC-06；查閱不寫 registry；不同 Session 不會各自發送管理指示；長檢查不阻止 worker report。
- 驗證：兩個 CLI 呼叫端的競爭、失聯／釋放／takeover、舊 token 與長操作收尾，並檢查例外釋放。
- 證據／阻塞／接續：未開始；依賴 MM-02。

### MM-04 — 獨立整合

- 目標：從明確 base 建立 manager integration worktree，整合接受成果，保存 combined verification 與 target snapshot。
- 完成條件：AC-07；manager A/B 與主 checkout 分離；使用者 dirty files 不被搬移／提交；依賴 base 含需要的成果。
- 驗證：兩 manager 的獨立整合與衝突、dirty 主 checkout、candidate 在驗證後被修改的情境。
- 證據／阻塞／接續：未開始；依賴 MM-02。

### MM-05 — 共用交付 gate

- 目標：common-directory 短 gate；首版只更新未 checkout 的既有本地分支，以 expected-OID transaction 與 receipt 支援故障診斷；不內建 push／PR。
- 完成條件：AC-08–AC-09；過期成果不能覆蓋較新 target；checked-out branch 不被裸更新；不新增隱式 merge/push 授權。
- 驗證：不同 root 共用 repository、兩候選競爭、外部 ref 改動、中斷與鎖釋放；等待決策／長驗證時其他 manager 能繼續準備。
- 證據／阻塞／接續：未開始；依賴 MM-03、MM-04。

### MM-06 — Migration

- 目標：零寫入 dry-run、source hash/quiescence 預檢、完整 backup／journal、保留舊 refs／建立新 refs、Git worktree move、歷史資格失效、forward resume／tombstone；首版無自動 rollback。
- 完成條件：AC-10–AC-13；保存 dirty/untracked/ignored 內容及歷史，不偽造驗證通過；舊 worker 不繼續寫新資料。
- 驗證：v1 fixture、目的地衝突、symlink、未知版本、live worker、各階段注入故障、完成後重跑與失效 acceptance gate。
- 證據／阻塞／接續：未開始；依賴 MM-02–MM-04；不對使用者真實專案試搬資料。

### MM-07 — 文件同步與整體驗證

- 目標：同步 SKILL／protocol／runtime reference／範例，完整驗證 namespace、主控、整合與 migration 合用。
- 完成條件：AC-01–AC-14 的 deterministic 範圍有結果；舊單 manager 生命週期回歸通過；spec/task/progress 不誇大真實 provider 驗證。
- 驗證：既有及新行為測試、專用真實 tmux fixture、skill 格式與文件連結；實作完成前各 task 必須同步其必要 runtime 使用說明，不能全部拖到此步。
- 證據／阻塞／接續：未開始；依賴 MM-05、MM-06。此步完成後 SPEC-001 仍為 Implementing；MM-08 完成必要真實 provider 驗證後才標為 Implemented。

### MM-08 — 真實 provider smoke test

- 目標：於獨立暫存 repo 使用真實 provider 驗證 selector、report、ack、修正、verify/accept 與 manager 整合隔離。
- 完成條件：至少一個真實 provider 走完原 MVP-02 驗收流程及新路由；記錄版本、平台、命令、證據、第二 provider 狀態。
- 驗證：控制必要使用量與外部存取範圍；保留 provider 原生權限檢查。遭主機限制時記錄實際阻塞，未驗證不標 Done。
- 證據／阻塞／接續：未開始；依賴 MM-07。符合原 MVP-02 條件時連結同一證據，關閉重複缺口；所有必要驗收通過後更新 SPEC-001 為 Implemented。

P2 任務目前只是候選。啟動前按 README 流程另立功能 spec／必要 ADR 與具體驗收條件；不以這張表代替規格。
