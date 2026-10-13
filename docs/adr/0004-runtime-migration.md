# ADR-0004 — 格式遷移由 Manager Runtime 提供

- 狀態：Accepted；MM-06 runtime 已實作，驗證見下方補充。
- 日期：2026-10-08；定案：2026-10-09（MM-01）。
- 關聯：[SPEC-001 §8–9](../specs/001-multi-manager-isolation.md#8-舊格式遷移契約)、[MM-06](../tasks.md)、[契約檢查](../reviews/MM-01-contract-review.md)。

## 背景

V1 → v2 牽涉絕對路徑、Git registration、branches、舊 prompt、attempt 與 verification。單純搬資料夾無法恢復；遷移須可重跑並診斷中斷。現有 v1 沒有常駐主控身分，runtime 不能自行證明舊 LLM Session 已離線。

## 決策

由同一 CLI 提供 `migrate --manager-id ID`，目的 ID 必須明確；純讀取 `--dry-run` 回傳來源 inventory、hash 與阻塞。正常 init 不隱式遷移。原 manager skill 補遷移指引，不另建 migration skill。

執行需要 source hash 與明確 source-quiesced assertion，搭配來源鎖／tmux／Git inventory 預檢。Manager 先處理 Worker 回報與退出／刻意停止；migration 本身不自動停止。不能以 timeout／安靜或 done claim 取代確認無 writer，新舊 runtime 同時寫來源不受支援。

Backup/journal 放 common control 的獨立 migration 目錄，保存全部管理／工作內容、staged index、private Git metadata、必要 objects 與 refs。保留舊 branch 原值，建立新的 namespaced branch，以 Git worktree move 搬移後切換分支；不 reset/stash/force。逐步 intent 與 snapshot 核對支持 forward resume，完成後以來源 tombstone 阻止舊 v1 init/load。首版不提供自動 rollback 或清理。

Historical acceptance/verification 原文保存；當前資格清空，已接受／待驗證成果須重新 review/verify/accept 才能作依賴或交付來源。Legacy assignment 作廢，retry 使用新 attempt/assignment；不恢復舊 provider 對話。詳細 mapping、phases、狀態與故障情境在 SPEC-001 §8。

## 替代方案

- 獨立 migration skill：仍需要相同 deterministic runtime，易與 schema 不同步。
- Init 自動搬移：未預覽影響就改動長期資料。
- 手動 mv／全目錄字串取代：破壞 Git registration 或歷史原文，無可靠續跑。
- 更名／刪除舊 branch：減少 refs，卻破壞歷史引用；首版保留舊 ref 成本較低。
- 重新算舊指紋延續 acceptance：沒有實際驗證，會偽造 gate 資格。
- 自動 rollback：涉及共用 Git metadata、已搬移 dirty 內容及可能新資料，無法保證安全；先提供校驗備份與 forward resume。

## 代價與限制

備份及保留 refs 占空間；曾接受任務需重新驗證，依賴暫時阻擋。Source-quiesced 是呼叫端合作前提，不是 OS 或 LLM 存活證明。Submodule/locked/missing worktree 等無法安全搬移的來源在預檢阻擋，不能偷偷改為 force。

如外部寫入使 journal 與來源/目的不一致，保留 backup 及兩側並報 ambiguous，需要刻意修復；不宣稱可自動處理所有損壞。未來大量跨專案 orchestration 再評估獨立 skill。

## 定案結果

2026-10-09 收斂 Q-03／Q-04，從 Proposed 改為 Accepted。Dirty/staged/untracked/ignored worktree 的 Git 搬移實驗與 migration 故障 walkthrough 見契約檢查；沒有對真實專案執行 migration，當時 MM-06 尚未實作。

## 實作補充（2026-10-11）

MM-06 提供 explicit dry-run/hash/quiescence、common journal/backup、object pack 及 unique backup pins、保留舊 refs／建立新 refs、Git move／只切 symbolic HEAD、歷史資格失效與 forward resume。備份保存 `.git` pointer 原文為獨立 inert 檔案，不讓 backup tree 共用 live private index；所有 staged blobs 及歷史 commit objects 一併封存。來源控制資料保留為 retired history，完成 tombstone 及 journal/destination 核對後才啟用 v2。

證據見 [MM-06 validation](../reviews/MM-06-validation.md) 與 [操作流程](../../references/runtime.md#explicit-v1-migration)。只遷移暫存 v1 fixtures，沒有搬移使用者真實專案；quiescence 仍是合作前提，無自動停止／rollback／cleanup，真實 Agent 驗證仍未完成。
