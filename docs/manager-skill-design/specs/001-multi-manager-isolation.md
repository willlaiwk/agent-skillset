# SPEC-001 — 多 Manager 隔離、整合與遷移

- 狀態：Draft；本輪只整理規格，尚未實作。
- 建立／更新：2026-10-08。
- 實作基線：`d8b0ca5`；目前格式為 `.manager/state.json`，沒有 manager ID。
- 決策：[ADR-0002](../adr/0002-manager-identity.md)、[ADR-0003](../adr/0003-isolated-integration.md)、[ADR-0004](../adr/0004-runtime-migration.md)，均為 Proposed。
- 任務：[MM-01–MM-08](../tasks.md)。

## 1. 問題與目標

目前兩個 Session 使用相同 `--root`，會共用 state、plan、task ID、tmux session 與 worker。CLI 的專案鎖只序列化單次操作，無法隔離兩個 manager 的規劃與指示。即使資料分開，manager 在相同主 checkout 切分支或整合也仍會互相影響。

本功能提供：使用者指定 ID 建立／接續 manager；未指定 ID 時建立新 manager；同專案的不同 manager 使用獨立管理資料、worker 與整合工作區；舊資料可以刻意遷移並恢復。

Manager 是持久化工作單位，Session 是暫時操作它的對話。新 Session 可接續既有 ID，原 Session 也能在 context compaction 後沿用 ID。

## 2. 範圍與非目標

範圍包含 manager 身分與選擇、namespaced state、worker 路由、同 ID 主控交接、整合工作樹、共用交付協調、v1 格式遷移，以及必要的 skill/protocol/測試更新。

不包含 distributed 或多主機執行、跨 manager 的 task DAG、背景 scheduler、event watcher、任意外部 Git 客戶端的強制管制、預設自動 merge／push／部署。工作樹是協作隔離，不新增 OS 安全沙箱。

## 3. Manager 身分與選擇契約

| 啟動情境 | 目標行為 |
| --- | --- |
| `init` 指定已存在且有效的 ID | 開啟該 manager，保留 plan、task、attempt、成果與歷史；再 reconcile |
| `init` 指定不存在的 ID | 建立該 ID 的 manager |
| `init` 未指定 ID | 產生新 ID，建立新 manager；每次獨立啟動都建立新工作單位 |
| 後續 task／status／report 等操作未指定 ID | 明確報錯；不推測「最近使用」、不挑唯一 manager、不偷偷建立新 manager |
| 指定 ID 但 state 遺失／損壞或身分不符 | 報錯並保留資料，不覆寫或自動重建 |
| 同 ID 已有有效主控 | 可查閱；管理寫入需由既有主控執行或完成交接 |

自動產生 ID 僅發生在 skill 啟動時的 `init`。Runtime 回傳 `manager_id`、root 與管理目錄；skill 明確告知使用者新 ID，並在後續命令沿用它。Context 恢復依明確 ID／記錄進行，不共用一個專案全域的「current manager」檔案。

提議 ID 規則：1–64 字元，僅小寫 ASCII 字母、數字、`-`、`_`，首字元為字母或數字；拒絕路徑分隔符、`.`／`..`、保留名稱與 symlink 導向。小寫可避免 macOS 大小寫不敏感檔案系統的別名衝突。自動 ID 使用 UTC 時間加隨機值，建立時原子檢查衝突，碰撞重新產生。

身分範圍為 `(canonical project root, manager_id)`。同 repository 的不同 root 不自動代表同一個 manager；共用 Git 資源另依 canonical Git common directory 協調。搬移 project root 不在此次一般恢復範圍內。

## 4. CLI 草案

以下為目標介面，目前 CLI 尚未提供：

```sh
manager --root /project init
manager --root /project --manager-id feature-login init
manager --root /project --manager-id feature-login reconcile
manager --root /project --manager-id feature-login task --id T001 --title 'Login' --brief /tmp/T001.md
manager --root /project --manager-id feature-login spawn --id T001
manager --root /project --manager-id feature-login status
manager --root /project --manager-id feature-login report T001 --attempt 1 --state working --summary 'Working'
manager --root /project migrate --manager-id legacy --dry-run
manager --root /project migrate --manager-id legacy
```

`--manager-id` 是 manager selector；既有 `--id` 與 positional task ID 保持代表 task。`migrate` 的 ID 表示遷移目的地，未指定時報錯，避免資料被搬到使用者不知道的 manager。`managers` 作為不需 selector 的清單指令，回傳 ID、格式版本與主控摘要，不修改各 manager 的 task 狀態。

主控 claim／release／takeover 與交付命令的公開名稱待第 11 節收斂；上述草案不暗示這些能力已存在。

## 5. 資料與識別隔離

```text
.manager/
  feature-login/
    state.json
    plan.md
    owner.json
    .lock
    events/
    inbox/
    tasks/
      T001/
        brief.md
        assignment.json
        status.json
        result.md
        log.txt
        verification/
        accepted.json
    worktrees/
      T001/
    integration/             # 獨立 Git worktree；需要整合時建立
```

提議新的 state schema `version: 2`，保存 `manager_id`、root、session 與 tasks。state、assignment、report、events、inbox 的身分驗證須包含 manager ID；舊 attempt 與其他 manager 的 report／ack 不得影響目前 task。

Branch 包含 project key、manager ID 與 task ID，例如 `manager/{project-key}/{manager-id}/tasks/T001`；整合分支使用 `manager/{project-key}/{manager-id}/integration`，避免 task 名稱與 integration 衝突。tmux session 以 root 與 manager ID 派生識別；同 manager 內可沿用 `mgr-T001` window。縮短／hash 後的識別仍須核對原始身分，遇到衝突不能接管別人的 session。

Worker launch prompt、assignment、環境與 report/inbox 命令都攜帶 manager ID。授予的 task/inbox/event 目錄限於該 manager；合作路由檢查也同時核對 manager、task 與 attempt，不把此限制描述為 OS 存取控制。

`reconcile` 只分類該 manager 的 panes、tasks 與 worktrees；Git inventory 可看見其他 worktree，但不能將其誤判為可修復／停止的 orphan。不同 manager 可各有 `T001`，各自的 verify／accept／stop／retry 不跨 manager 生效。

`.manager.yml` 仍是專案共用設定。提議 `manager.max_workers` 按單一 manager 計數，預設 4；兩個 manager 可合計超過 4，文件須明示。repository 總額度是後續能力，本次不默默變更設定鍵的意思。

## 6. 同 ID 的主控與鎖

Per-manager CLI 鎖保護單次 registry 操作；report 使用自己的 task 鎖，仍需能在長時間 verify 中回報。這些鎖不能代替 Session 主控所有權。

提議以持久化 owner token 與 generation 建立合作式主控所有權：主控取得後，manager 寫入命令須攜帶有效身分；另一 Session 可讀資料，但不能直接 send、stop、accept 或改計畫。釋放／接續／takeover 的條件要可診斷並保留事件；交接後舊 token 的後續管理寫入必須被拒絕。

不能只看 timestamp 過期就無條件接管仍在工作的 manager。對失聯、長時間測試、context compaction 與 Session 結束的判定尚待收斂。直接編輯 `plan.md` 仍須遵守 skill 的主控規則；runtime token 不會阻止 host 使用者任意修改檔案。

現有 `status`／`peek` 會 reconcile 並寫 state；新設計需區分無副作用的查閱與主控 reconcile，不能把舊 `status` 假定為純讀取。

Repository 共用維護鎖放在 Git common directory 對應的 runtime control 目錄，例如 `<git-common-dir>/manager-runtime/`，涵蓋 ignore/exclude 設定、初始化／遷移協調與交付，不依某個 manager 或 checkout 的 `.manager/.lock`。實作需定義鎖順序、例外釋放與長操作的再檢查，避免互鎖。

## 7. 各自整合，共用交付

### 7.1 Manager 整合工作區

每個 manager 在自己的 `integration/` 與分支整合已接受 task。從明確 committed base 建立，保留來源 commit、整合 commit、驗證 snapshot 與交付目標。主 checkout 的未提交使用者變更不能自動搬移、stash 或 commit。

Worker acceptance 仍只接受 task 的隔離成果；manager 必須 review 並驗證合併後的結果。依賴 task 的 code 必須透過明確整合 ref／base 傳給後續 worker，不能只因依賴 `done` 就認為其 code 已存在。

### 7.2 共用交付入口

各 manager 可以平行準備整合、解衝突與驗證。Repository 的共同交付操作走同一 gate，遵守既有 repository workflow 與使用者授權，不預設自動 merge、push 或部署。

1. 在隔離工作樹準備 candidate，記錄驗證時的 target commit 與 candidate commit。
2. 取得 common-directory 的交付鎖，重新核對 target、candidate、驗證 snapshot、工作樹 ownership 與授權。
3. target 已變動則不交付；釋放鎖，再於隔離工作樹整合最新 target、解衝突並重新驗證。
4. 條件仍有效時才執行受控交付，記錄舊／新 target commit、來源 manager、驗證與結果；任何失敗保留可恢復狀態。
5. 釋放鎖。等待 LLM 決策、使用者輸入或長時間測試時不占用交付鎖。

本地目標分支若需 checkout，提議由專用交付 worktree 單獨持有。若目標已在使用者主 checkout 被 checkout，不能直接更新 ref 造成 HEAD 與檔案內容不一致；改走 PR/MR workflow，或經明確交接後使用受控交付方式。建立專用 worktree 不代表可強制占用已 checkout 的分支。

CLI 鎖是參與此協定者的協調。外部 Git 工具可能不遵守，因此交付還需 Git 層級的預期 target 檢查；具體更新方式與 checkout 一致性在 MM-01／MM-05 定案及驗證。外部變更應造成拒絕或重新準備，不能以 force 操作覆蓋。

## 8. 舊格式遷移契約

### 8.1 格式與前置檢查

來源是 v1 `.manager/state.json` 與其配套目錄；目的地為 `.manager/{manager-id}/` v2。偵測舊格式後，提供 migration 指引；正常新格式命令不自動搬移，也不忽略舊資料直接建立一套新的環境。

`--dry-run` 是純檢查：列出來源版本、task、worktree、branch、tmux、目的地、待改引用、未知檔案與阻塞；不停止 worker、不搬檔案、不初始化新 manager、不修改 Git 設定。

拒絕損壞／不支援的來源版本、目的地衝突、symlink／越界路徑、無法確認 ownership 的 worker/worktree。未知資料保留並列出，不能依檔名猜測後刪除。

### 8.2 執行與恢復

1. 取得維護協調與來源鎖，防止參與新 runtime 的 init、管理操作或另一 migration 競爭；重新檢查來源未變。
2. 來源主控停止管理；workers 須完成回報並退出或刻意停止。原本啟動的 worker 仍引用舊 prompt/cwd，不能搬完檔案就假定可繼續。停止策略及 mixed-version 邊界見第 11 節。
3. 建立獨立於搬移來源的 backup、inventory 與 migration journal，保存版本、來源指紋、路徑／ref mapping 和已完成步驟。Backup 涵蓋管理檔案與需要保存的 tracked/untracked/ignored 工作內容，不能只複製 state.json。
4. 使用 Git 支援的 worktree 搬移與 branch 處理，驗證 Git registration、`.git` 指向與 branch；禁止直接 `mv` 整個 `.manager/` 後假定 worktree 有效。
5. 搬移其餘資料，針對已知 schema 更新 runtime 引用與身分。Plan／brief 中的舊命令需有恢復時的新路由說明；歷史 logs/results/reviews/events 保持原文，不做全目錄字串取代。
6. 檢查 counts、task/attempt、inbox ack、內容保存、worktree HEAD、branch mapping 與待驗證項目。完成後才標記新格式可用。
7. 新 runtime reconcile 後依保留狀態恢復。重啟 worker 走新的 attempt，拒絕舊 generation 回報；不宣稱可恢復 provider 原對話。

重跑完成的同一 migration 是 no-op，回傳已完成證據。中斷時根據 journal 明確續跑；不能猜測 state、不經核對覆寫目的地或刪除 backup。新 manager 已開始產生新資料後，不允許盲目 rollback 覆蓋；rollback 的具體支援範圍待第 11 節定案，至少提供可驗證的續跑方式。

### 8.3 驗證與已接受成果

遷移保留歷史 acceptance 與 verification 證據，但路徑、report 或 schema 改動可能使既有指紋失效。待接受任務須清除可執行的舊驗證資格並重新 verify，不得重算指紋後偽裝成已通過。

已接受任務的歷史記錄不得抹除；遷移後作為依賴／交付來源前須核對內容與 commit。歷史接受與目前可用驗證的表示方式需在 MM-01 明定，避免既有 `done` 被誤用或整個依賴圖無故遺失。

## 9. 相容性與發布

- v2 manager 命令明確攜帶 ID，舊版不帶 selector 的 task 命令不猜測目的地。
- 新 runtime 對 legacy 格式回報 migration 指引，對不支援的新版本明確報錯。
- 同步更新 SKILL、manager/worker protocol、runtime reference、範例與測試；遷移前不讓新舊 runtime 同時寫同一組資料。
- 舊 CLI 不理解新的協調鎖，無法只靠新 runtime 保證 mixed-version 安全；遷移前必須停止舊 manager／worker，限制與診斷寫入文件。
- 不因 migration 自動啟用 merge／push，不變更 provider 原生權限規則，不自動清除 worktree／backup。

## 10. 驗收情境

| ID | 情境 | 必須成立的結果 |
| --- | --- | --- |
| AC-01 | 同 root 兩次無 ID 的 init | 不同 ID、不同 state，不覆寫既有資料 |
| AC-02 | 指定 ID 新建／接續 | 重用同一工作單位，保留任務、計畫與 attempt；ID 不合法／資料損壞時不寫入 |
| AC-03 | 一般命令無 selector | 明確錯誤，不新增 manager、不選最近／唯一 manager |
| AC-04 | A、B 都有 T001 | branch/tmux/path 分開；A 的 send/stop/verify/accept/retry 不改變 B |
| AC-05 | 錯 manager 或舊 attempt 的 report/ack | 拒絕且不污染其他 namespace；reconcile 不接管其他 manager 資源 |
| AC-06 | 同 ID 兩個 Session／主控交接 | 第二個不能管理寫入；交接後舊 owner 被拒絕；查閱不修改 task state |
| AC-07 | 兩個 manager 各自整合 | 使用各自 integration worktree；主 checkout 的 branch 與使用者內容不被修改 |
| AC-08 | A 交付後 B 的 target 已過期 | B 不覆蓋 A；重新整合與驗證後才能交付；鎖遇到失敗／退出可恢復 |
| AC-09 | 同 Git common dir 的不同 root／外部 ref 變動 | 共用交付協調；過期 target 被拒絕；checked-out branch 不被裸更新 |
| AC-10 | migration dry-run／目的地衝突／未知版本 | 純預覽；不停止 worker、不寫檔案／Git、不覆寫資料 |
| AC-11 | v1 含 dirty/untracked worktree 與歷史證據 | 完整保存內容、HEAD 與歷史；新 worktree 註冊有效、路由正確 |
| AC-12 | migration 中斷／重跑／恢復 | 可依 journal 續跑；完成後重跑 no-op；保留 backup，舊 report 不被接受 |
| AC-13 | 舊 verification 與 acceptance | 歷史可追溯；失效證據不能通過 accept；依賴／交付前重新確認來源 |
| AC-14 | Worker 使用 provider 與額度 | 每 manager 額度獨立且明示總量；原生權限保留；至少一個真實 provider 通過路由與管理生命週期，另一 provider 狀態按證據記錄 |

## 11. 實作前需收斂的問題

| ID | 問題 | 影響／處理任務 |
| --- | --- | --- |
| Q-01 | Owner claim／release／takeover 的 CLI、存活判定與 generation；長 verify 如何保持有效並在交接後拒絕提交結果 | 阻擋 MM-03；MM-01 先定案 |
| Q-02 | 共用交付 gate 的 API、第一版支援的 repository workflow、預期 ref 更新與 checked-out worktree 一致性 | 阻擋 MM-05；MM-01 定案，不預設自動 merge/push |
| Q-03 | 遷移時接受歷史與當前驗證如何表示、舊 branch 保留或更名、backup／journal 位置、續跑與 rollback 範圍 | 阻擋 MM-06；MM-01 定案 |
| Q-04 | Live legacy worker 的停止／回報策略，以及如何確認舊 manager 已離線 | 阻擋實際 migration；MM-06 的預檢不得略過 |

以上是設計缺口，不能在文件中宣稱已解決。可依下一輪實作授權、原型與 repository 規則收斂；只有無法自行判斷且影響使用者選擇時才提問。

## 12. 修訂記錄

| 日期 | 變更 |
| --- | --- |
| 2026-10-08 | 初稿：記錄 manager ID、namespace、主控、整合交付、v1 遷移與驗收情境；所有 runtime 能力仍未實作 |
