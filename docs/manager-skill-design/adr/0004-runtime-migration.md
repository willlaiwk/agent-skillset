# ADR-0004 — 格式遷移由 Manager Runtime 提供

- 狀態：Proposed。
- 日期：2026-10-08。
- 關聯：[SPEC-001 §8–9](../specs/001-multi-manager-isolation.md#8-舊格式遷移契約)、[MM-06](../tasks.md)。

## 背景

從 `.manager/state.json` 遷到 `.manager/{id}/state.json` 牽涉絕對路徑、Git worktree 註冊、branches、worker 舊 prompt、attempt 與 verification 證據，單純搬資料夾無法保證恢復。遷移需要可重跑與中斷診斷。

## 提議決策

提供同一 CLI 的 `manager migrate --manager-id ID` 與純讀取 `--dry-run`。遷移目的 ID 必須明確指定，正常 init 不隱式遷移。原 manager skill 補上偵測、預覽、執行與恢復的指引，初期不另建 migration skill。

Runtime 使用版本化 schema、前置檢查、備份、journal、Git worktree 支援的搬移與遷移後一致性檢查。來源 workers 與舊 manager 必須先停止管理／寫入；歷史證據保留，失效驗證資格不能偽造修復。詳細契約由 spec 維護。

## 替代方案

- 獨立 migration skill：仍需同一 deterministic runtime，且容易與 schema 更新不同步。
- `init` 自動搬移：使用者尚未知道影響範圍就改動長期工作資料。
- 手動 `mv` 加全目錄字串取代：破壞 Git registration 或歷史原文，無法提供可驗證續跑。
- 丟棄舊資料重開：違反保留成果與接續需求。

## 代價與限制

需要維護版本轉換及故障恢復測試，backup 可能占用較多空間。舊 runtime 不遵守新鎖，遷移前的停止條件不能省略。具體 rollback 範圍、branch mapping 與已接受任務的表示方式仍待 SPEC-001 Q-03／Q-04 收斂。

若未來需要大量專案、多個工具的 migration orchestration，再評估獨立 skill；不在此次擴大範圍。
