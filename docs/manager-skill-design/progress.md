# Manager Skill — 當前進度與 Session 接續

最後更新：2026-10-10。MVP 基線：`d8b0ca5`；多 manager 初稿：`0b4083e`；契約定案：`68cc99f`。MM-02 實作提交以 `feat: isolate manager namespaces and worker routing` 識別；commit hash 依實際 Git log 確認。

**目前狀態：MM-02 namespace／worker 路由完成，預設／真實 tmux 行為驗證通過；SPEC-001 為 Implementing。MM-03 已有基本 claim/credential guard，下一步完成 release/takeover、長操作交接與 fencing。真實 Agent smoke test 仍未驗證。**

## 新 Session 從這裡開始

1. 先執行 `git status --short`、`git log -3 --oneline`，確認此紀錄之後是否有新變更；保留既有工作。
2. 閱讀 [文件入口](README.md)、本文件與 [任務清單](tasks.md)，再按任務閱讀 spec／ADR／[設計文件](design.md) 的相關章節；原 MVP／Phase 2 邊界在第 31–32 節。
3. 閱讀 [SKILL.md](../../skills/manager/SKILL.md)、[runtime reference](../../skills/manager/references/runtime.md) 與 [manager protocol](../../skills/manager/references/manager-protocol.md)，理解現在已提供的指令。
4. 接續 **MM-03**：先讀 [SPEC-001 §6](specs/001-multi-manager-isolation.md#6-同-id-的主控與鎖)、ADR-0002 與 [MM-02 validation](reviews/MM-02-validation.md)。保留已完成 namespace/claim；實作 release/takeover、credential/owner 交接中斷恢復、operation lock、長 verify 鎖外 checks/收尾 generation fencing 及 AC-06。不要再以 registry 大鎖阻擋整段 checks。原 **MVP-02/MM-08** 真實 provider 缺口保留。
5. 任務結束或交接前更新本文件：完成項目、實際驗證、遇到的阻塞、變更／commit，以及下一個可執行任務。未執行的驗證維持「未驗證」。

本文件追蹤這個 skill 的開發進度。使用 skill 管理其他專案時，該專案的任務狀態與計畫另存於其 Git 根目錄的 `.manager/`。

## 2026-10-10：MM-02 完成與下一步

- 實作 v2 init/create/resume、明確 selector、namespace/path/branch/tmux、per-manager 額度、完整 root/manager/task/attempt/assignment identity、report/inbox/ack 與純讀取查閱；主 checkout/dirty ignore 不改，shared exclude 與 Git worktree metadata 用 common 維護鎖協調。
- 同步 SKILL、manager/worker protocol、runtime reference、task template 與專案 README；已實作指令與未實作完整目標分開描述。
- 為可執行 namespace 生命週期補 basic owner claim/private credential/寫入 guard；MM-03 因前置開始，仍不算完成。無 release/takeover；目前 verify 仍持 registry lock，完整長操作 fencing 待接續。
- 證據：[MM-02 validation](reviews/MM-02-validation.md)。預設 35 項：34 通過、1 real-only 跳過（43.200s）；真實 tmux 35 項全通過（56.326s），使用專用暫存 socket 與假的互動式 Worker，沒有模型/API 呼叫。預設 Python 缺 PyYAML 的明確錯誤路徑與暫存 venv 的 YAML 設定成功路徑均已驗證。
- Skill 格式驗證通過；PyYAML 6.0.3 只裝於 `/tmp/mm02-skill-validation` venv，不改全域 Python。Python 語法及 runtime 可執行權限、18 份 Markdown 的 86 個本地連結／錨點、code fences 與 `git diff --check` 均通過。
- 首次真實 tmux 因 sandbox socket 限制失敗，經主機許可後通過。修正 stop 在 identity 確認前寫 marker 的問題；real-fixture 快照排除 Worker 可持續寫入的診斷 log，仍核對 registry/report/inbox/evidence bytes 與時間。
- 接續 MM-03；MM-04–MM-08 未實作。Legacy v1 只診斷保留，migrate/integration/deliver 尚未提供；fake provider 的通過不關閉 MVP-02/MM-08。
- Git：本輪提交以 `feat: isolate manager namespaces and worker routing` 識別；commit hash 與後續未提交變更依實際 status/log 確認。

## 2026-10-09：MM-01 定案紀錄

- 定案 Q-01–Q-04：explicit owner claim/release/takeover 與長操作 fencing、未 checkout 本地 target 的 transaction/receipt gate、保留 branch/歷史且重驗資格的 forward migration，以及 source-quiesced/hash/locks 停止契約。詳細行為只維護在 SPEC-001，ADR 說明取捨。
- 證據：[contract review](reviews/MM-01-contract-review.md) 的 12 項 walkthrough、[可重跑 Git probe](reviews/mm01_git_primitives.py) 與 [當次結果](reviews/mm01-git-results.json)。8 項 Git assertions 通過；另確認 expected OID 不防止同 OID symbolic-ref 切換，已明示合作式 workflow 邊界。
- 實驗只在暫存 Git repo 執行，未啟動 provider/tmux/manager runtime，未遷移真實資料。本輪沒有修改 `skills/manager/`，未重跑既有 runtime tests；下方歷史結果仍只對應 MVP 基線。
- 同步 README/design/task/progress、SPEC-001 與 ADR-0002–0004。文件驗證：10 份 Markdown、66 個本地連結／錨點及 code fence 配對通過；Git probe Python 語法、所有變更檔案行尾空白與 `git diff --check` 通過。
- 接續 MM-02；MM-03–MM-08 仍依 tasks 的順序。現有主控／遷移／交付契約已收斂，沒有需使用者補答的 MM-01 blocker。
- Git：本輪文件提交以 `docs: finalize multi-manager contracts for MM-01` 識別；commit hash 與後續未提交變更依實際 status/log 確認。

## 2026-10-08：初稿文件紀錄

- `design.md` 保留整體架構基線，補功能索引；新的行為契約放在 SPEC-001，避免將所有討論整併成更大的單一設計文件。
- README 定義 spec／ADR／task／progress 分工。ADR-0001 採用文件管理方式；ADR-0002–0004 仍為 Proposed。
- SPEC-001 記錄 manager ID 建立／接續、完整 namespace、同 ID 主控、獨立整合工作樹、短鎖交付、migration 與 AC-01–AC-14。
- MM-01 需收斂 owner／takeover、交付 workflow、migration 歷史證據及停止條件；MM-02–MM-08 均未開始。
- 本輪文件驗證：9 份 Markdown 的 48 個本地連結（含章節錨點）與 code fence 配對檢查通過，`git diff --check` 通過；沒有重跑 runtime 測試，也未執行任何真實專案 migration。

## 已完成的實作

| 範圍 | 當前能力 |
| --- | --- |
| Skill 行為 | Manager 擁有 outcome，規劃、派工、監督、回答問題、review、獨立驗證與整合 |
| Runtime CLI | namespaced `init`、`task`、`spawn`、`send`、`inbox`、`peek`、`status`、`report`、`verify`、`accept`、`stop`、`retry`、`reconcile`、`events`、`escalate`；`managers` 與 `owner status/claim` |
| Agent adapters | Codex／Claude Code 互動式 CLI；`auto` 偵測、明確指定 provider、基本角色設定 |
| 隔離 | 每個 Worker 使用獨立 tmux window 與 Git worktree；預設從已提交的 `HEAD` 建立，可指定 `--base` |
| 任務依賴 | 可登錄依賴；只允許依賴已被 Manager 接受的任務啟動；尚無自動排程 |
| 並行限制 | 每 manager 預設最多 4 個 Worker；不同 manager 可合計超過 4，由 Manager 決定何時啟動 |
| 通訊 | Durable inbox、tmux paste、Worker `--ack`；傳送成功與收到確認分開紀錄 |
| 持久化 | `.manager/{id}/state.json`／owner、task briefs／reports／results、namespaced events/inbox/logs/驗證紀錄及 retry ack 歷史 |
| 查閱／主控 | status/peek/events/inbox/managers/owner status 零管理資料寫入；basic owner claim 與 credential guard；完整主控交接待 MM-03 |
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

本節保留 MVP Session 的歷史結果，對應 `d8b0ca5`；本輪 MM-02 的 v2 結果在上方接續紀錄及 validation，不將 v1 歷史結果當成新功能驗收。

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

## 原 MVP 驗證缺口：MVP-02 — 真實 Worker smoke test

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

以上保留為 2026-10-07 的候選順序；最新任務狀態及多 manager 依賴以 [tasks.md](tasks.md) 為準，這裡不再維護另一份狀態表。MM-08 若完成原 MVP-02 驗收，可共用證據關閉缺口。Phase 3（specialization、dynamic planning、cost／token budget、project knowledge）仍未實作。

## 2026-10-07 交接紀錄

- 將 `docs/manager-skill-design.md` 原文搬移為 [design.md](design.md)，保留內容。
- 新增本進度紀錄；設計與 Session 接續資訊集中在此資料夾。
- README 使用英文介紹專案目的、現有 skills、用途與基本使用方式，不列設計文件或進度入口。
- 沒有修改 runtime，也沒有啟動下一個開發任務。是否已提交本次文件整理，以 `git status` 與 `git log` 為準。
