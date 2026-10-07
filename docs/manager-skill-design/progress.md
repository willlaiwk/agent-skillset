# Manager Skill — 當前進度與 Session 接續

最後更新：2026-10-07。實作基線：`d8b0ca5`（`feat: add manager skill and local worker runtime`）。

**目前狀態：MVP runtime 已實作，測試替身驗證通過；尚未完成真實 Agent 的端到端驗證。下一個建議任務是 MVP-02，尚未啟動。**

## 新 Session 從這裡開始

1. 先執行 `git status --short`、`git log -3 --oneline`，確認此紀錄之後是否有新變更；保留既有工作。
2. 閱讀本文件，再按任務閱讀 [設計文件](design.md) 的相關章節；先看第 31–32 節的 MVP／Phase 2 邊界。
3. 閱讀 [SKILL.md](../../skills/manager/SKILL.md)、[runtime reference](../../skills/manager/references/runtime.md) 與 [manager protocol](../../skills/manager/references/manager-protocol.md)，理解現在已提供的指令。
4. 使用者若要求「繼續推進」但沒有指定其他目標，優先處理下面的 **MVP-02**。如果最新指示另有優先順序，以最新指示為準。
5. 任務結束或交接前更新本文件：完成項目、實際驗證、遇到的阻塞、變更／commit，以及下一個可執行任務。未執行的驗證維持「未驗證」。

本文件追蹤這個 skill 的開發進度。使用 skill 管理其他專案時，該專案的任務狀態與計畫另存於其 Git 根目錄的 `.manager/`。

## 已完成的實作

| 範圍 | 當前能力 |
| --- | --- |
| Skill 行為 | Manager 擁有 outcome，規劃、派工、監督、回答問題、review、獨立驗證與整合 |
| Runtime CLI | `init`、`task`、`spawn`、`send`、`inbox`、`peek`、`status`、`report`、`verify`、`accept`、`stop`、`retry`、`reconcile`、`events` |
| Agent adapters | Codex／Claude Code 互動式 CLI；`auto` 偵測、明確指定 provider、基本角色設定 |
| 隔離 | 每個 Worker 使用獨立 tmux window 與 Git worktree；預設從已提交的 `HEAD` 建立，可指定 `--base` |
| 任務依賴 | 可登錄依賴；只允許依賴已被 Manager 接受的任務啟動；尚無自動排程 |
| 並行限制 | 預設最多 4 個 Worker；由 Manager 決定何時啟動 |
| 通訊 | Durable inbox、tmux paste、Worker `--ack`；傳送成功與收到確認分開紀錄 |
| 持久化 | `.manager/state.json`、task briefs／reports／results、events、inbox、logs、驗證紀錄 |
| 驗收 | Worker `done` 先進入 Manager `verification`；`verify` 需 review 與檢查指令，`accept` 再確認證據及成果未變動 |
| 恢復 | 偵測中斷／stale／orphan；保留成果；`retry` 沿用 worktree、遞增 attempt，拒絕舊 attempt 回報；預設最多 2 次 restart |
| 設定 | `.manager.yml`；預設流程只使用 Python 標準函式庫，YAML 語法需 PyYAML，JSON 語法不需額外依賴 |

主要檔案：

- [Runtime 與 CLI](../../skills/manager/scripts/manager)
- [Adapters](../../skills/manager/scripts/lib/adapter.py)
- [行為測試](../../skills/manager/scripts/test_manager.py)
- [Worker protocol](../../skills/manager/references/worker-protocol.md)
- [Escalation policy](../../skills/manager/references/escalation-policy.md)
- [任務 brief 模板](../../skills/manager/templates/task.md)

## 已完成的驗證

以下結果來自 MVP 實作 Session，對應 `d8b0ca5`；本次文件整理沒有重跑 runtime 測試。

| 驗證 | 結果與範圍 |
| --- | --- |
| Skill 格式驗證 | `skill-creator/scripts/quick_validate.py` 通過 |
| 預設行為測試 | 共 22 項：21 通過，1 項真實 tmux 專用測試跳過；使用暫存 Git repository 與假的 tmux／Worker |
| 真實 tmux 測試 | 共 22 項全部通過；使用獨立暫存 socket 與假的互動式 Worker，涵蓋啟動、傳訊與停止；沒有呼叫模型 API |
| 靜態檢查 | Python 語法、skill 內相對連結、行尾空白與 runtime 可執行權限通過 |
| Provider 參數 | 已核對當時安裝的 `codex --help`／`claude --help` 與官方文件；尚未驗證真實 Agent 的端到端行為 |

從 repository 根目錄重跑：

```sh
python3 skills/manager/scripts/test_manager.py
MANAGER_TEST_REAL_TMUX=1 python3 skills/manager/scripts/test_manager.py
```

測試只管理自己的暫存專案／tmux server。真實 tmux 測試需要主機允許建立 socket 與終端；上次在沙箱內失敗，取得執行權限後通過。不要把這個環境限制誤判為 runtime 功能失敗，也不要繞過主機權限。

## 已確認的規格解讀與限制

- **Scheduler／watcher 屬於 Phase 2**：設計第 17 節描述 DAG 自動派工的目標，第 26 節允許 MVP 先 polling，第 32 節明列 DAG Scheduler 與 Event Watcher。
- **關閉後不會自行醒來是當前實作限制**：spec 要求可恢復，沒有要求 MVP 自動重啟 Manager。目前 Manager 停止後，tmux Worker 可能繼續執行；重新開啟 Manager 後用 `reconcile` 恢復監督。
- **Merge／push 是預設關閉，不是 spec 明文排除能力**：第 8 節的示例設定為 `false`。目前 runtime 沒有內建 merge／push 指令，且拒絕將這兩個設定設為 `true`；這是第一版實作範圍。
- **Manager 仍負責整合**：第 9、23 節要求 Manager 整合 Worker 成果。現有 skill 指示 Manager 使用 repository 的 Git 流程，在既有授權範圍內整合並驗證；不能把整合工作交回使用者。
- **部署需要適當授權**：第 15 節將 production deployment 列為需詢問事項，沒有定義 MVP 自動部署機制。
- **任務接受不等於整體完成**：`accept` 只接受隔離成果；仍需整合及 delivery tree 的整體驗證。依賴任務的 code 不會自動加入後續 Worker 的 base。
- **Recover 有邊界**：`retry` 使用保留的 worktree 開新對話，不保證恢復死亡進程的 provider conversation；損壞／遺失的 state 或搬移的專案需刻意修復。
- **Worktree 不等於安全沙箱**：保留 provider 與主機的權限機制；Worker environment 的指令限制是合作協定，並非 OS 存取控制。
- **指紋不是語意審查**：Manager 仍需判斷 review／測試是否充分。忽略檔案不納入指紋；submodule 內未提交內容沒有深入指紋驗證。

## 下一個建議任務：MVP-02 — 真實 Worker smoke test

**目標**：在擴充排程前，確認真實互動式 Agent 能遵守 report／inbox／result 協定，並走完獨立驗收流程。這是依目前驗證缺口提出的建議，不是原 spec 額外定義的功能階段。

範圍：

1. 先檢查本機 provider 版本、登入與主機執行條件。從可用 provider 選一個，在獨立暫存 Git repository 跑一個小任務；第二個 provider 另外紀錄驗證狀態。
2. 準備包含 allowed files、驗收條件與測試命令的真實 brief。執行 `init`／`spawn`，讓 Worker 修改暫存 fixture，產出 `result.md` 並透過 `report` 回報。
3. 透過 `send` 要求一項有明確驗收條件的修正，確認 Worker 以 `--ack` 確認收訊並更新成果。
4. 由 Manager review diff、執行 `verify`，再 `accept`。確認主 checkout 保持原內容，成果在隔離 worktree，Worker claim 不會直接變成 Manager acceptance。
5. 若遭遇 trust／permission prompt，先保留診斷並依主機授權流程處理。只修正實際觀察到的 adapter／protocol 問題。

驗收條件：

- 至少一個真實 provider 完成「啟動 → structured report → 訊息 acknowledgment → 修正 → result → Manager verification → acceptance」。
- 記錄 provider 版本、平台、執行命令、報告／驗證證據位置及結果；第二個 provider 的未驗證或阻塞情況明確標示。
- 真實執行的使用量與外部存取控制在這個小任務的必要範圍；不修改真實產品專案或主機的全域權限設定。
- 如有 runtime 改動，通過既有回歸測試；如只有驗證紀錄，更新本文件即可。

## 後續任務候選

| 順序 | 任務 | 待完成的結果 |
| --- | --- | --- |
| 1 | MVP-02：真實 Agent 驗證 | 補足上述驗證缺口，處理觀察到的問題 |
| 2 | P2-01：DAG Scheduler | 自動選出 runnable tasks，遵守 Manager acceptance、並行上限與既有 attempt；明確處理依賴成果的 base／整合，不能只檢查 `done` 就用舊 HEAD 啟動 |
| 3 | P2-02：Event Watcher | 設計持續監督與 Manager 喚醒機制，驗證事件重複處理、重啟與阻塞問題；不能只產出 event files 就宣稱完成 |
| 4 | P2-03：Automatic Verification | 從 repository 設定推導適當命令，同時保留獨立 review 與 acceptance gate |
| 5 | P2-04：Routing／Retry Policy | 目前只有基本角色設定與有上限的手動 retry；再補 spec 描述的自動選擇與恢復策略 |

以上順序是建議，尚未代表新的任務已開始。Phase 3（specialization、dynamic planning、cost／token budget、project knowledge）仍未實作。

## 本次交接變更

- 將 `docs/manager-skill-design.md` 原文搬移為 [design.md](design.md)，保留內容。
- 新增本進度紀錄；設計與 Session 接續資訊集中在此資料夾。
- README 使用英文介紹專案目的、現有 skills、用途與基本使用方式，不列設計文件或進度入口。
- 沒有修改 runtime，也沒有啟動下一個開發任務。是否已提交本次文件整理，以 `git status` 與 `git log` 為準。
