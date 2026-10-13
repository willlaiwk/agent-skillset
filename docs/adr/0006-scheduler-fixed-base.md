# ADR-0006 — 排程使用固定 base 與明確依賴證據

- 日期：2026-10-13。
- 狀態：Superseded；2026-10-13 由 [ADR-0007](0007-task-base-proof-and-launch-gates.md) 取代，runtime 尚未實作。下文保留初次 Accepted 的理由與取捨。
- 關聯：[SPEC-002](../specs/002-dag-scheduler.md)、[P2-01／DS-01–DS-04](../tasks.md)、[契約檢查](../reviews/DS-01-contract-review.md)。

## 背景

既有 task 在註冊時固定 base。Acceptance 可涵蓋 dirty changes／untracked artifacts，後續 Worker 不會自動收到來源；source HEAD ancestry 也不能證明 dirty artifacts、cherry-pick 或衝突解決已整合。Scheduler 若只看 dependency done，會把狀態就緒誤當成程式碼就緒。

SPEC-001 與 ADR-0003 已採用獨立 integration tree、Manager 刻意整合／commit、combined review／checks 與 snapshot gate。Scheduler 需要明確的 task-base 約束，同時保持既有 queued base 與 migration 歷史。

## 決策

保留固定 base 與先前已註冊依賴的模型。Manager 在 plan 記錄完整 DAG，完成 prerequisites 的 accepted integration／combined verify 後，再按該 candidate OID 註冊後續 task。

新增明確 `schedule bind`，以成功且當下 eligible 的 combined verification 綁定 queued task；candidate OID 必須等於既有固定 base，proof sources 必須涵蓋全部直接 dependencies。Binding 保存 task 定義、來源及 proof hashes，後續 launch 重查。無依賴任務不需 binding。

綁定後允許 integration branch 與 delivery target 繼續前進，因 task 使用已驗證的 immutable commit。Task-base 檢查獨立於 combined delivery eligibility；sources／review／record 仍須有效，不放寬交付 gate。含 binding 的手動 spawn 也套用同一檢查。

首版一次有界排程，只啟動未開始的 queued task，不常駐、不自動接受、換 base、整合或 retry。Worker 額度沿用 per-manager live panes；實際 launch 共用既有鎖、intent 與 identity，避免平行命令重複啟動。

## 替代方案

- 依賴 done 就直接 spawn：能重用現行 API，但無法保證 Worker 有收到依賴成果。
- 只做 Git ancestry：不涵蓋 dirty accepted artifacts、cherry-pick 或 review 對整合充分性的判斷。
- 在註冊時保留未解析 base，scheduler 自動 merge／bind：可先註冊全 DAG，但改變 schema、queued task 語義、Git 整合與中斷恢復邊界；需要獨立規格，不放入首版。
- 每次 launch 要求原 combined verification 完整 eligible：會把 delivery target／integration branch 後續前進誤作固定 base 過期，妨礙正常平行工作。
- 新增專用 dependency-base verification：可以移除既有 target 要求，但重複長 checks／證據機制。先重用已驗證的 combined proof，觀察使用限制後再考慮擴充。

## 代價與限制

Manager 仍須安排依賴整合與分階段註冊，scheduler 不完成整個產品 DAG 的自動規劃。首版 bind 使用既有 combined verify，需合法本地 target／ancestry；不更新 target，checked-out target 可以準備證據。Extra proof sources 也要維持快照，因此 review 應選擇必要來源。

不能證明任意人寫入的 review 有語義品質；Runtime 的結構 gate 與 Manager 的獨立 review 分工沿用 ADR-0003。Binding 不授予新的外部操作權限。

可選 binding 保留 v2 state 與舊手動 spawn 相容性；啟用後不同 runtime 版本不能混用管理寫入，舊 binary 不具備 binding gate。Deferred registration、自動 base preparation、watcher 與 retry policy 留待後續獨立決策。

## 取代原因

Reviewer 對照 runtime 後發現 bind 使用完整 eligibility 過度依賴目前 integration／target；launch gate 的殘留判斷、全圖 reconcile 鎖與 combined verify 平行性未收斂。ADR-0007 保留固定 base／分階段註冊／明確 bind／一次有界排程，修正上述契約，並允許同 base 明確 rebind、固定 ref pin 與較早 durable launch intent。舊 binary 無法強制攔截的風險亦明確記錄。
