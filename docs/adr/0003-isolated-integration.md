# ADR-0003 — 隔離 Manager 整合，序列化共同交付

- 狀態：Accepted；MM-04 獨立整合與 MM-05 共同本地交付已實作。
- 日期：2026-10-08；定案：2026-10-09（MM-01）。
- 關聯：[SPEC-001 §7](../specs/001-multi-manager-isolation.md#7-各自整合共用交付)、[MM-04–MM-05](../tasks.md)、[契約檢查](../reviews/MM-01-contract-review.md)。

## 背景

Namespaced state 無法隔離同一主 checkout 的 checkout、merge、index 與未提交檔案。不同 worktree 仍共用 Git refs 與部分 metadata。交付相同目標時，另一 manager 可能已先更新目標；檢查完 target 再無條件 merge 仍有競爭。

## 決策

各 manager 使用自己的 integration branch 與 `.manager/{id}/integration/` worktree，從明確 committed base 平行準備、解衝突與驗證。使用者主 checkout 的 dirty 內容不搬移／stash／提交。Combined verification 綁定來源 acceptance、review、candidate 與 target snapshot。

第一版內建交付只支援既有、未在任何 registered worktree checkout 的本地分支 fast-forward。使用 canonical Git common-directory 的短 maintenance/delivery 鎖，在最後核對 evidence/ownership/inventory 後，以 Git expected-OID transaction 同時檢查 candidate、更新 target、建立唯一 receipt ref。Durable intent 與 receipt 分辨 ref 更新後、收據檔案前的中斷；不憑 target OID 相等猜測成功。

任何 checked-out target 一律拒絕。第一版不建立專用 delivery checkout，也不做 HEAD/index 同步恢復；常見主分支需要依既有 PR/MR 或明確交接流程另行交付。準備、長驗證與等待決策在 common 鎖外。詳細 workflow、API、重試與鎖順序在 SPEC-001 §6–7。

不新增自動 merge/push/部署或授權。CLI token 與驗證紀錄不取代使用者／repository 的交付權限。

## 替代方案

- 主 checkout 加大鎖：所有準備與 review 序列化，長操作阻塞其他 manager。
- 不同 worktree 即完全隔離：忽略共用 refs 的競爭。
- 只在 merge 前看一次 target：無法辨識 checks 後／寫入前的 ref 變更。
- 專用 delivery worktree 更新已 checkout target：可擴大適用範圍，但 ref、index、working tree 的一致性與中斷恢復更複雜，首版延後。
- 內建 PR/MR/push：需遠端權限、provider workflow 與新的相容性契約，不在本功能擴大範圍。

## 代價與限制

常見 checked-out 主分支無法直接用這版 gate 交付；可保留已提交 candidate 走既有流程，不將它誤記為 gate 成功。新增 receipt refs/journal，須保留並驗證，沒有自動清理。

External direct-ref OID 競爭由 transaction 偵測，但 Git expected OID 不防止外部 checkout 或轉成相同 OID 的 symbolic ref。此類 metadata 操作需合作遵守短區間維護協調；不能宣稱 advisory lock 是任意 Git 工具的強制管制。

## 定案結果

2026-10-09 收斂 Q-02，採取上述較小的本地 workflow，取代 Proposed 草案中待定的專用 checkout 型交付。暫存 Git 實驗確認 transaction、receipt 與 inventory 性質，也確認 symbolic-ref 邊界；結果見契約檢查。MM-04／MM-05 均尚未實作。

2026-10-10 MM-04 實作隔離 integration init/status/verify、source acceptance／combined snapshots、owner-committed evidence hash index 與中斷／busy／fencing，證據見 [MM-04 validation](../reviews/MM-04-validation.md)。Control lock 放在 Git tree 外，避免影響 clean candidate。Verify 可準備 checked-out branch 的證據而不更新 ref；最終 inventory／checked-out 拒絕仍屬 MM-05 delivery gate，未放寬交付決策。沒有內建 merge/import/push 或新的授權；本補充記錄實作，不改寫原取捨。

2026-10-10 MM-05 實作 `deliver --verification ID`、共用 maintenance/delivery 短 gate、最終 evidence/owner/inventory 核對、expected-OID transaction 與 unique receipt，以及 owner reconcile 的中斷診斷。永久保存曾成功紀錄及 transaction rejection/error history，避免 receipt 遺失或外部衝突後誤認可重交／成功。仍拒絕任何 registered checkout target，不更新 HEAD/index，不提供 force/push/PR 或新授權；證據見 [MM-05 validation](../reviews/MM-05-validation.md)。本補充記錄採用決策的實作，未改寫原取捨。
