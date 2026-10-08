# ADR-0003 — 隔離 Manager 整合，序列化共同交付

- 狀態：Proposed。
- 日期：2026-10-08。
- 關聯：[SPEC-001 §7](../specs/001-multi-manager-isolation.md#7-各自整合共用交付)、[MM-04–MM-05](../tasks.md)。

## 背景

Namespaced state 仍無法隔離同一主 checkout 的 checkout、merge、index 與未提交檔案。不同 worktree 也仍共用 Git refs 與部分 metadata。最後交付相同目標分支時，另一個 manager 可能已先更新目標。

## 提議決策

各 manager 使用自己的整合分支及 `.manager/{id}/integration/` worktree，平行準備、解衝突、驗證，不在使用者主 checkout 操作。

共用交付操作使用 Git common-directory 對應的協調鎖與 gate。準備與長時間驗證在鎖外；交付前取得鎖，核對驗證所對應的 target/candidate 與 Git 預期 ref。過期則釋放鎖並重新整合／驗證。交付保留來源與結果證據。

本地 checkout 型交付使用專用 worktree；目標若已在使用者 checkout，拒絕裸更新 ref，使用 repository 的 PR/MR 流程或明確交接。第一版支援的 workflow 與更新機制在 SPEC-001 Q-02 定案。

這是交付協調設計，不啟用預設 auto-merge、auto-push 或部署，也不自動取得外部操作授權。

## 替代方案

- 共用主 checkout 加大鎖：所有實作與 review 被序列化，長操作也容易阻塞其他 manager。
- 不同 worktree 即完全隔離：忽略共用 refs 與交付目標的競爭。
- 只在 merge 開始前看一次 target：無法辨識驗證後目標已變動。
- 直接更新使用者 checkout 的 branch ref：可能造成 HEAD/index/檔案不一致。

## 代價與限制

新增整合工作樹與交付紀錄，必須處理 target 過期、鎖順序與中斷恢復。Git ref 原子檢查與 checkout 一致性仍需具體實作方案，不能只靠 advisory lock 宣稱已解決。

外部 Git 工具不受此協作鎖約束，需檢查並拒絕不符合預期的變更。此階段不承諾自動背景排隊或喚醒 manager。
