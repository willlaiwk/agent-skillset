# ADR-0002 — 以 Manager ID 隔離工作單位

- 狀態：Proposed。
- 日期：2026-10-08。
- 關聯：[SPEC-001 §3–6](../specs/001-multi-manager-isolation.md#3-manager-身分與選擇契約)、[MM-01–MM-03](../tasks.md)。

## 背景

同 root 的 Session 現在共用 `.manager/` 與 tmux。現有檔案鎖只能序列化 CLI 操作，不能分開計畫與管理決策。使用者希望指定 ID 接續／新建；未指定時建立新的 manager。

## 提議決策

Manager 是持久化工作單位，Session 是暫時主控。資料使用 `.manager/{manager-id}/`，task/branch/tmux/report/recovery 都包含 manager 身分。

只有啟動 `init` 可以省略 ID 並產生新 ID；後續操作明確攜帶 selector。Skill 記住並顯示 ID，不建立專案全域 current-manager 指標。Task ID 在各 manager 內獨立，同名 T001 不衝突。

同 ID 的兩個 Session 仍需單一主控與交接，提出 owner token／generation 機制；存活與 takeover 規則先在 SPEC-001 Q-01 收斂，namespace 本身不能取代 ownership。

## 替代方案

- 每個 Session 一套暫存資料：隔離容易，但 Session 重啟與有意接續失去穩定身分。
- 只要求 task ID 不重複：plan、worker 指示、資源計數仍共用。
- 專案 current-manager 檔案：第二個 Session 可改變第一個的路由。
- 每次 CLI 沒有 ID 都建新的：同一個工作流程被拆成多組無關資料。

## 代價與限制

CLI、worker protocol、state schema、測試與 migration 都要更新。新的 selector 不能猜測舊命令的目的地，必須提供明確相容性錯誤。每 manager 的 worker 額度會增加專案總並行數，需在文件明示。

不同 ID 不解決共享主 checkout 或 Git metadata 的干擾；由 [ADR-0003](0003-isolated-integration.md) 處理。
