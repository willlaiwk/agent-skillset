# ADR-0007 — 歷史 task-base proof 與分層 launch gate

- 日期：2026-10-13。
- 狀態：Accepted；僅設計，runtime 尚未實作。
- 取代：[ADR-0006](0006-scheduler-fixed-base.md)。
- 關聯：[SPEC-002](../specs/002-dag-scheduler.md)、[DS-01 review](../reviews/DS-01-contract-review.md)、[DS-02–DS-04](../tasks.md)。

## 背景

初版要求 bind 當下完整 combined eligibility，卻允許之後 integration／target 前進。兩個時點使用不同 gate，讓相同 immutable base 的首次 bind受目前 checkout／交付狀態影響。現行 integration_status 也拒絕 running operation，會把長 combined verify變成所有下游工作障礙。

現行 launch 的全圖 reconcile 只有在呼叫端先逐 task nonblocking 取鎖／設定 busy_tasks 才安全；attempt 0 有效 worktree 可以手動沿用。初版對 scheduler 的 artifacts 限制沒有區分這些共同與專用前提，且漏掉 assignment/status 在 registry intent 之前寫入的窗口。

## 決策

- 保留固定 base、分階段註冊、明確 bind與一次有界排程；bind／launch 用同一個歷史 task-base proof檢查，不讀目前 candidate／target eligibility。
- 必須有 owner-committed successful／unchanged record、相符 candidate OID／proof hashes／current sources；在 registry `.lock` 下讀歷史 index，不取 integration operation lock，也不因另一個 combined verify running 拒絕既有 proof。Delivery gate維持原契約。
- 分開共用 launch gate、有 binding才啟用的 proof gate、scheduler 首次啟動 eligibility。手動 spawn 可沿用有效舊 worktree，scheduler 要無殘留；未知 intent或 report／assignment 不一致仍須共用診斷。
- 每 candidate 沿用現行全部 tasks nonblocking取鎖／busy 標記，確保全圖 reconcile只寫已取得鎖的 task；每 candidate 結束即釋放。
- 所有 launch 在 worktree／branch／assignment／status 副作用前 durable記錄 intent；多檔案 partial publication由 identity／stage診斷，不宣稱 exactly-once。
- 未開始、同 base／定義的 task允許 explicit expected-binding替換成功新 proof，完整保留舊 binding。固定 direct runtime ref保護 base commit，bind以 intent／expected-missing ref／registry提交支持診斷與明確 forward resume。
- Owner generation僅稽核；新 owner可沿用有效 binding。缺／壞／無時區 created_at只排除該 task。Source worktree／evidence保留到使用它的下游 launch完成，以及後續 retry／integration不再需要為止。

完整 API、分類、pin identity及故障契約只維護在 SPEC-002。

## 替代方案與取捨

- 保留首次 bind完整 eligibility：形成不必要的時間順序限制；只在 proof 建立時驗證 candidate clean／ancestry已足以保護 immutable base。
- 所有 launch拒絕殘留 worktree：簡化規則，但破壞現行手動 recovery；用 scheduler專用 eligibility保留相容。
- Launch只 reconcile target／sources：可減少鎖數，但需改動共用 reconcile行為；先沿用現行全部 tasks try-lock，busy分支不寫。
- Binding禁止替換：避開競爭但迫使換 ID；expected-binding提供明確比較交換，base與task定義保持固定。
- 只記錄 GC風險、不 pin：commit可能在 integration改寫後消失；採 fixed ref，多一個有界、可診斷的 bind副作用。

## 代價與已知限制

需要 bind／launch intents、binding history與 commit pins，增加故障測試；未提供 cleanup。Pin不保護 source working tree或 review bytes，launch仍須重查來源；runtime gate不證明 review語義品質。

新可選欄位維持 v2相容，但**舊 binary會忽略 binding，無法機制性阻擋混用**。停用舊 writer是營運前提，不能當成已實作的強制 fencing；如要防 downgrade，需另立 schema／migration決策。

本修訂沒有新增自動 acceptance、Git整合、retry、watcher或交付授權。Ready／Accepted只表示實作契約收斂，待 DS-02–DS-04 runtime驗收。
