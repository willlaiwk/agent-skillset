# SPEC-001 — 多 Manager 隔離、整合與遷移

- 狀態：Implementing；MM-02 namespace／路由已完成，MM-03 已接基本 claim，完整功能尚未完成。
- 建立：2026-10-08；更新：2026-10-10。
- 實作基線：MVP `d8b0ca5`（v1）；契約定案 `68cc99f`。目前工作樹含 v2 namespace 實作；完成／缺口見 [MM-02 validation](../reviews/MM-02-validation.md)。
- 決策：[ADR-0002](../adr/0002-manager-identity.md)、[ADR-0003](../adr/0003-isolated-integration.md)、[ADR-0004](../adr/0004-runtime-migration.md)，均為 Accepted（設計採用）。
- 任務：[MM-01–MM-08](../tasks.md)；契約檢查：[MM-01 review](../reviews/MM-01-contract-review.md)。

## 1. 問題與目標

V1 中兩個 Session 使用相同 `--root`，會共用 state、plan、task ID、tmux session 與 worker。CLI 的專案鎖只序列化單次操作，無法隔離兩個 manager 的規劃與指示。即使資料分開，manager 在相同主 checkout 切分支或整合也仍會互相影響。

本功能提供：使用者指定 ID 建立／接續 manager；未指定 ID 時建立新 manager；同專案的不同 manager 使用獨立管理資料、worker 與整合工作區；舊資料可以刻意遷移並恢復。

Manager 是持久化工作單位，Session 是暫時操作它的對話。新 Session 可接續既有 ID，原 Session 也能在 context compaction 後沿用 ID。

## 2. 範圍與非目標

範圍包含 manager 身分與選擇、namespaced state、worker 路由、同 ID 主控交接、整合工作樹、本地交付協調、v1 格式遷移，以及必要的 skill/protocol/測試更新。

不包含 distributed 或多主機執行、跨 manager 的 task DAG、背景 scheduler、event watcher、任意外部 Git 客戶端的強制管制、內建 PR/MR 或遠端 push／merge／部署。第一版不更新任何已 checkout 的目標分支，也不提供 migration 自動 rollback。工作樹是協作隔離，不新增 OS 安全沙箱。

## 3. Manager 身分與選擇契約

| 啟動情境 | 目標行為 |
| --- | --- |
| `init` 指定已存在且有效的 ID | 開啟該 manager，保留 plan、task、attempt、成果與歷史；不自動 claim／reconcile |
| `init` 指定不存在的 ID | 建立該 ID 的 manager；owner 初始為 released |
| `init` 未指定 ID | 產生新 ID，建立新 manager；每次獨立啟動都建立新工作單位 |
| 後續 task／status／report 等操作未指定 ID | 明確報錯；不推測最近使用、不挑唯一 manager、不偷偷建立新 manager |
| 指定 ID 但 state 遺失／損壞或身分不符 | 報錯並保留資料，不覆寫或自動重建 |
| 同 ID 已有主控 | 可查閱；管理寫入需由既有主控執行或完成交接 |

自動產生 ID 僅發生在 `init`。Runtime 回傳 `manager_id`、canonical root、管理目錄、schema version 與 initialized；skill 明確告知使用者 ID，記住 selector 與主控 credential 檔案位置。Context 恢復依明確記錄進行，不建立專案全域 current-manager 指標。

ID 規則：1–64 字元，僅小寫 ASCII 字母、數字、`-`、`_`，首字元為字母或數字。保留名稱為 `state`、`plan`、`owner`、`events`、`inbox`、`tasks`、`worktrees`、`integration`、`migrations`、`backups`、`runtime`、`control`；拒絕路徑分隔符、`.`／`..`、symlink 導向。小寫避免大小寫不敏感檔案系統別名衝突。自動 ID 使用 UTC 時間加隨機值，原子檢查衝突，碰撞重新產生；指定 ID 不偷偷改名。

身分範圍為 `(canonical project root, manager_id)`。同 repository 的不同 root 不自動代表同一 manager；共用 Git 資源依 canonical Git common directory 協調。Project key 固定使用 canonical root 的 SHA-256 前 12 位，衝突時核對完整 root 並拒絕接管。搬移 project root 不在一般恢復範圍。

## 4. 目標 CLI

以下是 MM-02–MM-06 的完整目標介面。MM-02 已提供 namespace／查閱／worker 路由命令及基本 owner status/claim；release/takeover、integration/deliver/migrate 尚未提供。已實作使用方式與限制見 [runtime reference](../../../skills/manager/references/runtime.md)。全域參數置於子命令前；只有目標 `migrate` 的目的 ID 使用子命令參數。

```sh
manager --root /project init
manager --root /project --manager-id feature-login init
manager --root /project managers
manager --root /project --manager-id feature-login owner status
manager --root /project --manager-id feature-login owner claim --session-id session-a --credential-file /tmp/session-a.owner.json
manager --root /project --manager-id feature-login --owner-file /tmp/session-a.owner.json reconcile
manager --root /project --manager-id feature-login --owner-file /tmp/session-a.owner.json task --id T001 --title 'Login' --brief /tmp/T001.md
manager --root /project --manager-id feature-login --owner-file /tmp/session-a.owner.json spawn --id T001
manager --root /project --manager-id feature-login status
manager --root /project --manager-id feature-login report T001 --attempt 1 --assignment-id ASSIGNMENT_ID --state working --summary 'Working'
manager --root /project --manager-id feature-login --owner-file /tmp/session-a.owner.json integration init --base refs/heads/release
manager --root /project --manager-id feature-login --owner-file /tmp/session-a.owner.json integration verify --target refs/heads/release --source T001 --review /tmp/combined-review.md --command 'python3 -m unittest'
manager --root /project --manager-id feature-login --owner-file /tmp/session-a.owner.json deliver --verification VERIFICATION_ID
manager --root /project --manager-id feature-login --owner-file /tmp/session-a.owner.json owner release
manager --root /project --manager-id feature-login owner takeover --expect-generation 3 --session-id session-b --credential-file /tmp/session-b.owner.json --reason 'Previous session ended; credential lost'
manager --root /project migrate --manager-id legacy --dry-run
manager --root /project migrate --manager-id legacy --expect-source SOURCE_SHA256 --source-quiesced
manager --root /project migrate --manager-id legacy --resume MIGRATION_ID --source-quiesced
```

`--manager-id` 是 selector；既有 `--id` 與 positional ID 保持代表 task。`migrate` 的 ID 是目的地，必須明確提供；不能同時另給全域 selector。`managers` 不需 selector，純讀取各 namespace 的 ID、版本與 owner 摘要；損壞項目逐項列出，不自動修復。

管理寫入使用 `--owner-file`，可由 `MANAGER_OWNER_FILE` 指定同一 credential 路徑；明確參數優先。Worker 不繼承這個環境變數／credential。`report` 的 `--assignment-id` 可由 launch environment 的 `MANAGER_WORKER_ASSIGNMENT` 提供，兩者同時提供時須一致；缺少時拒絕。

Read commands 為 `managers`、`owner status`、`status`、`peek`、`events`、`inbox` 與 migration `--dry-run`：不建立目錄／鎖檔、不改 registry／events／ignore。`status` 回傳持久化狀態及分開的 observed 診斷；`peek` 可讀取 pane，但不保存 reconcile 結果。需要狀態更新時明確執行 owner-only `reconcile`。

只讀 Git 盤點使用 `GIT_OPTIONAL_LOCKS=0`，避免 status 等命令刷新 index 造成隱式寫入（[Git status background refresh](https://git-scm.com/docs/git-status#_background_refresh)）；不執行 prune/repair/fetch。跨檔案讀取遇到 concurrent write 時回傳明確 busy／inconsistent 診斷，不把讀到的部分資料當成完整成功狀態，也不為了修復一致性寫入資料。

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
        .operation.lock
        .report.lock
        verification/
        accepted.json
        history/             # migration 保存的 v1 原文
    worktrees/
      T001/
    integration/             # 獨立 Git worktree，需要整合時建立
    integration.json         # base、來源與 worktree 身分
    integration-verification/
    delivery/                # manager 的交付收據
```

State schema 固定為 `version: 2`，保留 v1 task 基本欄位，新增 `manager_id`、`project_key`、canonical `root`、canonical `git_common_dir`；`session` 專指 namespaced tmux session，Session 主控身分只存 `owner.json`。State 中每個 task、assignment、status、inbox、event 皆含 root／manager／task 身分。Task 的 `attempt` 為遞增整數；每次 launch 另產生隨機 `assignment_id`，assignment 與 report／ack 必須完全相符，不因 owner 交接更換 worker attempt。Queued／attempt 0 的 assignment ID 為 null，不能 report。Task 初始 `accepted_history: null`、`acceptance_eligibility: unaccepted`；可執行資格只允許 unaccepted／reverify_required／current 三值。

Branch 固定為 `manager/{project-key}/{manager-id}/tasks/{task-id}`，整合分支為 `manager/{project-key}/{manager-id}/integration`。tmux session 為 `manager-{project-key}-{manager-id}`；同 manager 內 window 為 `mgr-{task-id}`。tmux session 的 metadata 記錄完整 root／manager；名稱存在但 metadata 不符或缺失時拒絕接管。相同 task ID 不跨 namespace。

Worker launch prompt、assignment、環境、report/inbox 命令都攜帶 canonical root、manager ID、task ID、attempt 與 assignment ID。設定 worker environment 時清除 owner credential 變數，檢查 CLI identity 與 launch identity 一致；Worker 只能 report／讀自己的 inbox。Operator 可純讀 inbox；worker inbox 讀取須核對完整 launch identity。Ack 只接受同 namespace、同 task、同 attempt／assignment 的訊息；重試保留舊 inbox 作歷史，不讓舊訊息 ack 變成新 attempt 的收訊證據。

Report 以 task `.report.lock` 寫自己的 status/event，不寫 manager registry、不需 owner token。`reconcile` 僅分類該 manager 的 panes、tasks、worktrees，不能接管其他 manager 的 orphan。這些檢查是合作路由，非 host 使用者間的安全隔離。

`.manager.yml` 仍是專案共用設定；`manager.max_workers` 按單一 manager 計數，預設 4。兩個 manager 可合計超過 4，文件須明示。Repository 總額度是後續能力。

V2 初始化只在 common `info/exclude` 補入 `/.manager/`（不足時），不再修改主 checkout 的 `.gitignore`；既有 v1 ignore 編輯保持原樣。寫入 exclude 需短持 maintenance 鎖並拒絕 symlink／無法安全保存的內容；readonly／既有 ID 接續不修改 exclude。建立前完整檢查 ID/state/config/legacy 格式，不能先寫 ignore 才發現來源無效。

## 6. 同 ID 的主控與鎖

### 6.1 明確主控與交接（Q-01）

`owner.json` 保存 `version: 1`、root、manager ID、`generation`、`state: active|released`、session ID、token SHA-256、取得／最後管理活動／釋放時間。初始 generation 為 0；每次成功 claim、release、takeover 都遞增，永不重設。Session ID 是診斷標籤，不是授權依據；PID／時間只作提示，不判定對話存活。

| 操作 | 前置條件與結果 |
| --- | --- |
| `owner claim` | owner 為 released；持 `.lock` 原子發出 generation + 1 與隨機 token。已有 active owner 一律拒絕，即使 session ID 相同 |
| `owner release` | 有效 owner credential；持 `.lock` 清除 token、改 released 並遞增 generation。Workers 不自動停止 |
| `owner takeover` | 明確 `--expect-generation`、非空 reason、新 session ID／credential-file；持 `.lock` 核對 generation 且 owner 為 active，再旋轉 token、遞增 generation並記錄交接事件。不依活動時間自動觸發 |
| 既有 credential 接續 | root／manager／generation／token 皆相符便可沿用，包含 compaction／同主控恢復；credential 遺失則明確 takeover |

Claim／takeover 的 credential-file 由呼叫端指定，存 root／manager／generation／raw token；以 0600、exclusive create 寫入，拒絕 symlink、現有檔案與 manager／worker 管理目錄內路徑。原始 token 不出現在 stdout、events、plan 或 worker prompt。先完整寫入 credential 再提交 owner；若中斷留下未生效 credential，依 `owner status` 診斷，不直接重用它或覆寫。Owner 更新與事件須可透過同一 operation ID 恢復／補記，不能只留下無法診斷的 active 狀態。

不提供自動 lease expiry 或「PID 消失就接管」。失聯與長 verify／LLM 思考／compaction 無法可靠區分，takeover 是明確合作式交接。Takeover 可 fence 仍在執行的舊 Session；不殺它的 provider、不停止 Worker、不取消已產生的檔案變更。Skill 接續時顯示 pending 操作，等候其結束或由 host 合法處理，不強行刪鎖。

### 6.2 長操作與寫入資格

每次管理寫入在 `.lock` 內重新檢查 credential；`task`、`spawn`、`send`、`stop`、`retry`、`escalate`、`reconcile`、`verify`、`accept`、integration 寫入與 `deliver` 皆適用。短 side effect 的最後 owner 檢查及操作在同一 registry 臨界區，避免檢查完立刻被 takeover 後仍送訊或改 ref；外部呼叫須有界，失敗留下 intent 供 reconcile 診斷。

Skill 直接編輯 plan 或用 Git 修改 integration tree 時也必須是有效主控並遵守 operation busy；這些檔案／Git 命令仍由合作規則管制，token 不攔截任意 host 寫入。`owner status` 若帶 owner-file 可純讀核對 credential 是否有效，不輸出原始 token；交接前的檢查不能保證之後的直接 host 操作仍有效，因此新舊 Session 必須遵守交接停止指示。

長 verify 分成：預留 operation／保存起始 snapshot → 鎖外執行 checks → 短鎖重新檢查與提交。Task／integration `.operation.lock` 在 checks 期間持有，防止兩個管理操作同時修改同一 worktree。開始與結束只短持 `.lock`／`.report.lock`；worker report 可持續寫入，其變化會使 snapshot 驗證失敗。

收尾重讀最新 registry，只更新該 operation 的欄位，不把開始時的整份 state 寫回。核對 owner generation/token、task attempt／assignment、report/result/review、HEAD/index/working tree 與 operation ID。Owner 已交接或 snapshot 改變時回傳 `fenced`／`snapshot_changed`，保留該 run 的診斷，但不能設定 current verification、acceptance 或 delivery 資格。新 owner 的同 task 寫入因 operation busy 立即失敗，可查閱或管理其他 task；report 不拿 operation lock。Takeover 後未改動的既有成功 verification 可由新 owner重新核對後使用；尚在跑的舊 owner verification 不可提交成功。

### 6.3 鎖與中斷

Common control 目錄固定為 `<canonical-git-common-dir>/manager-runtime/`。鎖順序為：common `maintenance.lock`（需要時）→ common `delivery.lock`（交付時）→ manager/task 或 integration `.operation.lock`（操作資源時）→ manager `.lock` → task `.report.lock`。只取需要的鎖，同層多資源按 canonical 路徑排序；operation lock 一律 nonblocking；共同鎖與 registry 鎖的等待有界並回傳 busy。不得持 registry 鎖等待 operation lock。

長 verify 持 operation lock，不持 common／registry／report 鎖。Owner 交接只拿 registry 鎖；report 只拿 report 鎖；read commands 不拿會建立檔案的鎖。初始化與共享 exclude 更新短持 maintenance；migration 持 maintenance 保護來源與 Git registration，其他 root 的 metadata 寫入暫時回 busy。交付持 maintenance 及 delivery 只涵蓋 final checks／ref transaction／收據。

鎖使用 OS advisory lock，正常／例外／進程退出由 close 釋放；不能用鎖檔存在判定仍被持有，也不能刪鎖檔解鎖。Pending operation 的 PID 可作診斷；僅在取得 operation lock、核對 journal／snapshot 後分類中斷，未知 side effect 保留為需診斷，不猜測成功。

## 7. 各自整合，共用交付

### 7.1 Manager 整合工作區

`integration init --base REF` 將 REF 解析為明確 commit，建立專屬 integration branch/worktree 並記錄 base。已建立時只核對身分並回傳原資料；base 不同或 artifacts 不符時拒絕，不 reset。主 checkout 的未提交內容不能自動搬移、stash 或 commit。

Manager 依既有授權，在自己的 integration tree 使用 Git 整合已接受且目前 snapshot 仍相符的 task 成果。Task acceptance 可含 dirty 成果；Manager 將已 review 的 diff／task-owned untracked 成果帶入 integration tree 並刻意提交，保持 accepted task tree 原樣，不能自動 stage 使用者檔案。依賴 task 的 code 透過明確已提交 integration ref／base 傳給下一個 worker，不把 `done` 當 code 已存在。

`integration verify --target REF --source TASK --review FILE --command CMD` 保存不可變 run ID、target ref/OID、candidate ref/OID、source acceptance、review hash、combined commands/結果與 candidate snapshot。`--source` 可重複、至少一項且必須為同 manager 的 current accepted task；保存各 source attempt、accepted verification ID、HEAD 與 fingerprint，review 說明來源如何對應 candidate。Runtime 核對來源未改動，Manager 的 review 負責確認合併充分性。Target 必須為第 7.2 節允許的既有本地 ref；candidate 必須乾淨、無 staged/untracked 成果或進行中的 Git 操作，且 target OID 是 candidate 的 ancestor。Ignored cache 不當作交付內容；submodule 有 dirty/untracked 內容或不一致的 revision 時拒絕此版交付驗證。

Combined checks 在 integration tree、operation lock 下、common 鎖外執行，套用第 6.2 節收尾檢查；target 在 checks 期間變動則 run 不可交付。Source 成果改變、candidate 有變更、review 改變或指紋失效，須重新 review／verify，不能重算指紋沿用通過資格。

### 7.2 第一版本地交付 gate（Q-02）

唯一內建 workflow 是 **既有、未被任何 worktree checkout 的本地分支 fast-forward**。不新建 target、不更新 tags／remote-tracking refs／symbolic refs，不提供 force、已 checkout 分支交付、PR 建立或 push。Target 必須為完整 `refs/heads/...`，通過 Git ref 格式檢查，且不在任何 manager runtime／backup 保留 namespace。

`deliver --verification ID` 只使用該 manager 的成功 combined verification；沒有任意 `--candidate`／`--target` override。命令須已在使用者與 repository 的交付授權內；CLI 不把 token、verification、flag 或設定值視為外部授權證明，也不自動詢問／取得新授權。

1. 鎖外核對 evidence，候選缺資料／需要決策或重跑 checks 時不取得 common 鎖。
2. 依第 6.3 節短取得 maintenance、delivery、integration operation 與 registry 鎖，重新驗 owner、candidate、source acceptance、review、target OID 與完整 worktree inventory。Inventory 不可讀、target 是 symbolic ref、已在任何已登錄 worktree checkout（包含 missing/locked entry）或 target 已過期時拒絕。不同 canonical root 必須共用這些 common 鎖。
3. 先 durable 寫入 common `deliveries/{delivery-id}/intent.json`，包含 root／manager／generation、verification ID、target、old/new OID 及 evidence hash。以單一 Git ref transaction 同時核對 candidate ref/OID、更新 target（expected old OID）、建立唯一 `refs/manager-runtime/deliveries/{delivery-id}` receipt ref 指向 candidate。明確使用 no-deref，target 必須維持 direct ref；任何 ref 預期不符則全部拒絕。不使用無 expected-old 的裸 ref 更新。
4. 成功後寫 common result 及 manager 收據；失敗保留診斷並釋放鎖。Target 過期時回到 integration tree 整合最新 target、重新驗證；不能覆蓋較新 target。
5. 中斷後，owner `reconcile` 在相同短鎖下核對 intent 與 receipt ref：receipt 存在且 OID 相符表示 transaction 已完成（即使 target 後來再往前）；缺 receipt 且 target 仍是 old OID 表示未完成，可完整重檢後重試；其他組合為 ambiguous／external_change，保留證據並拒絕自動回寫。Receipt ref 遺失／不符不憑 target 相等推論成功。完成的同一 verification 重跑回傳原收據，不再次更新 target；需要再次交付必須建立新 verification。

已 checkout 的 target 一律拒絕，因此此版不建立專用交付 checkout，也不更新 HEAD/index/檔案。常見主分支在主 checkout 時，Manager 保留 committed candidate，依 repository 既有 PR/MR 或明確交接流程另行交付；那個外部流程不算 runtime gate 成功。

外部 direct ref 的 OID 變更由 expected-OID transaction 偵測；advisory lock 不阻止外部工具同時 checkout target，expected OID 也不能證明 ref 未被改成指向相同 OID 的 symbolic ref。支援前提是交付短區間內，參與者不繞過 common maintenance 協調來建立／切換 target worktree 或改變 target/candidate ref 的 direct/symbolic 類型。若無法維持此條件，使用 repository 的外部交付流程。沒有宣稱跨 Git ref 與 worktree registration 的原子鎖；MM-05 測試必須分開驗證 external OID race、symbolic ref 預檢與已 checkout 的拒絕。

Git 機制依據：[update-ref 的 expected old OID 與 transaction](https://git-scm.com/docs/git-update-ref)、[worktree inventory 與 checkout 限制](https://git-scm.com/docs/git-worktree)。這些 Git 性質不代表 manager gate 已實作。

## 8. 舊格式遷移契約

### 8.1 純預覽與停止條件（Q-04）

來源是 v1 `.manager/state.json` 及配套目錄，目的地為 `.manager/{manager-id}/` v2。一般命令偵測 v1 時提供 migration 指引，不隱式搬移，也不忽略舊資料直接 init。

`migrate --manager-id ID --dry-run` 純讀取，回傳 source version、canonical root/common dir、task／attempt／worktree／branch／tmux、引用轉換、目的地、unknown artifacts、阻塞與 `source_sha256`。指紋涵蓋管理檔案、工作內容（含 dirty/staged/untracked/ignored）、worktree registration、task refs/OID，排除鎖檔與無關主 checkout 內容。預覽不建立 backup／journal／鎖檔、不停止 worker、不改 Git／ignore。

實際執行必須帶 `--expect-source HASH --source-quiesced`，resume 必須帶 migration ID 與同一 quiescence assertion。`--source-quiesced` 表示呼叫端已讓舊 Session 停止管理寫入與所有 worker／子進程退出；不是自動停止指令或新的使用者 permission prompt。Runtime 沒有常駐 v1 owner，無法由 PID／一段安靜時間證明 LLM Session 離線，必須明示這個合作式前提。

停止準備由 Manager 在授權範圍處理：可透過舊 `send` 要求 Worker 保存 result、report 並退出，或以舊 `stop` 刻意停止；dry-run／migrate 不發 stop、不依 timeout 自動 kill。停止後刷新預覽再取 source hash。Live tmux pane、未確認退出的 provider／子進程、busy v1 `.lock`／task report lock、未知 ownership 的 pane/worktree、hash 已改變、缺 quiescence assertion 均阻擋。已死 pane可作歷史保存，不能只用 worker report `done` 判定進程退出。

取得維護與 v1 鎖後再盤點及核對 hash。僅靠新鎖不能阻止舊 CLI，搬移前重查來源；備份與每階段核對來源／目的 snapshot，偵測非 journal 變動立即停止保留兩側，不繼續覆寫。此版不支援新舊 runtime 同時寫入；來源無法確認安靜時不能實際 migration。

拒絕損壞／未知版本、目的地衝突、symlink 路徑或越界 ownership、重複 branch/worktree、missing／locked worktree、worktree 內 submodule／進行中的 merge/rebase 等此版無法安全搬移的情境。Dirty/staged/untracked/ignored 內容本身不是阻塞。工作內容中的 symlink 不追蹤，保存連結原值；控制目錄的 symlink 一律拒絕。Unknown 一般檔案保留並列出，未知的 Git worktree／writer 不能當普通檔案搬走。

### 8.2 備份、branch mapping 與續跑（Q-03）

Common control 目錄使用 `migrations/{project-key}/{migration-id}/`，包含 `journal.json`、`inventory.json`、`backup/`；不放在被搬移的 `.manager/`。建立來源 marker，維護操作在 active migration 期間拒絕對同 root init／claim／其他 migration。Journal 固定記錄 source/target version、完整 root/common dir、destination manager、source hash、路徑/ref mapping、backup hashes、每步 intent／結果與 phase；目的 v2 state 在完成前帶 migration marker，一般命令不可使用。

Backup 必須完成並核對後才搬移：原始管理檔案、各 worktree 的完整檔案樹（含 modes/symlink、staged/dirty/untracked/ignored）、對應 private Git directory/index/HEAD metadata、worktree registration 與 refs inventory。Git object 備份須涵蓋 task base／HEAD／歷史證據所引用的 commits，不能只拷貝 `.git` pointer 或只保留當前 branch。以 journal 記錄的唯一 backup refs pin 住必要 commits，再建立可校驗 object archive；不更名／刪除既有 task refs。Backup 不是可直接執行的 worktree，不自動還原共用 Git metadata。

Branch mapping 採 **保留舊 ref，建立新 namespaced ref**：`manager/{project-key}/{T}` → `manager/{project-key}/{id}/tasks/{T}`，新 ref 指向來源原 HEAD。Queued 尚無 branch 的 task 只轉 metadata，不先建 worktree。新 ref 存在時只允許 journal 證明同 migration 已建立且 OID 相符的續跑；其他既有 ref 即使同 OID 也視為衝突。用 `git worktree move` 搬移 linked worktree，再在該 tree 切換至新 branch；不 reset／stash／force，驗證 index、tracked/untracked/ignored bytes 與 HEAD 保持一致。此版不搬 main worktree／submodule worktree，依 [Git move 限制](https://git-scm.com/docs/git-worktree) 阻擋並診斷。

Phase 固定為 `preflight → backed_up → refs_prepared → worktrees_moved → data_converted → validated → completed`。每個 task 的 ref／move／switch／資料轉換各有 durable intent 與完成指紋；副作用後、journal 更新前中斷時，續跑核對兩側與 Git inventory，僅在唯一符合 intent 的狀態補記，兩側衝突或內容改變則報 ambiguous，不強制覆蓋。其他已完成 task 可保留，不要求所有 task 一起移動的假原子性。

轉換已知 schema 的 runtime 引用與完整 identity；歷史 plan／brief／logs／results／reviews／events 保持原文，寫獨立 mapping 與恢復指引。新 retry prompt 使用 v2 命令，不讓原始 brief 的舊指令直接沿用。恢復 worktree 的執行依 journal 新位置進行。

Validated 核對 counts、task/dependency/attempt、ack 歷史、所有內容、index、HEAD、Git registration、新舊 refs、歷史 hash 與無 writer。最後在來源 `.manager/state.json` 原子寫入 `version: 2, kind: migration_tombstone`（含 root、destination／migration ID，不是可用 manager state），使舊 v1 init/load 明確失敗；標記 journal completed 與目的 state 可用。中斷於 tombstone／完成標記之間仍由 journal 續跑，不把 tombstone 當損壞來源重建。新 runtime 遇 completed tombstone 時核對 journal/destination 後可建立其他 v2 namespace，不把它當 v1 來源或可用 state；pending tombstone 只允許查閱／resume。

同 root／目的 ID 已完成 migration 重跑為純查證的 no-op，回傳完成證據，不要求來源 hash 仍相同，也不改後來的 v2 任務。未完成時須明確 `--resume ID`，不能用新的 migration 覆寫 pending destination。第一版 **只支援 forward resume，不提供自動 rollback**；backup 保留供刻意人工修復，不能以 rollback 覆蓋已產生的新資料、不自動清理 refs／worktree／backup。

### 8.3 歷史接受與目前資格（Q-03）

所有 v1 acceptance／verification／report／ack 保存原始檔案與 hash 至 `tasks/{T}/history/v1/` 及 backup。V2 task 的 `accepted_history` 連結原接受證據；`accepted` 與 `verification` 一律清空，曾接受／待驗證成果設 `acceptance_eligibility: reverify_required`，其他任務為 unaccepted，不用重新計算舊 fingerprint 偽造通過。V2 的 report/assignment 轉換記錄 `origin: migration`，current acks 清空、舊 inbox 僅作歷史；它們是可診斷 snapshot，不是存活 Worker 已遵守新協定的證明。

| v1 task | v2 可執行狀態 |
| --- | --- |
| queued／attempt 0 | queued，保留 dependencies，首次 spawn 使用 v2 identity |
| done（已接受）或有完整 done claim／result 的 verification | verification，保留完成 claim 與 accepted_history；重新 review／verify／accept 前不作可用依賴或交付來源 |
| working／needs_manager／needs_user，或停止的未完成工作 | failed 或原 cancelled，保留原狀態／問題／stop 歷史；需要新 attempt 才能再啟動 |
| 原 failed／cancelled | 保留狀態，保留所有成果；適用既有 retry 上限 |
| 缺 result 或 report 損壞，但 state schema／worktree inventory 可驗明 | 不推論成功；failed 並列出修復原因，history 不刪除；無有效 worktree 則依 §8.1 阻擋 migration |

舊 `accepted.json` 只存在 history，不當作 v2 gate marker；新的 accept 寫新的 marker、verification 與 `acceptance_eligibility: current`。新 acceptance 不覆寫 accepted_history。`spawn`／integration 都檢查 `done`、current eligibility、當前 snapshot 與所需 committed base；migration 不讓整個依賴圖憑歷史 done 自動開跑。

所有 legacy assignment 在 migration 作廢；生成 v2 snapshot identity 並標記 `reporting_enabled: false`。Attempt 歷史保留；retry/spawn 遞增 attempt 並產生新 assignment ID、啟用 reporting。Migration 後無 selector／assignment、錯 manager／舊 attempt／舊 assignment 的 report/ack 都拒絕。新 owner 必須明確 claim 再 reconcile，migration 不發 owner credential、不恢復 provider 原對話。

## 9. 相容性與發布

V2 task 命令明確攜帶 manager selector，不猜舊命令的目的地。一般命令對 v1 回報 migration 指引、對不支援版本明確報錯；完成 tombstone 與 pending journal 有獨立診斷。Readonly 操作不得偷偷 initialize 或修復。

各 task 實作時同步其必要 SKILL／protocol／runtime reference／範例，MM-07 再整體驗證。現行工作樹已提供 v2 namespace，完整功能仍在 Implementing；這份 spec 不是已支援命令的使用手冊。Migration 尚未提供，不能直接用新 CLI 接續 v1；遷移前不得讓新舊 runtime 同時寫來源，不因 migration 啟用 merge／push／部署或變更原生 provider 權限。

## 10. 驗收情境

| ID | 情境 | 必須成立的結果 |
| --- | --- | --- |
| AC-01 | 同 root 兩次無 ID 的 init | 不同 ID/state，owner released，不覆寫既有資料 |
| AC-02 | 指定 ID 新建／接續 | 保留計畫/task/attempt；接續不 claim/reconcile；非法 ID／損壞資料不寫入 |
| AC-03 | 一般命令無 selector／純讀取 | 明確報錯不推測；read commands 不建檔／不改 state，observed 與 persisted 分開 |
| AC-04 | A、B 都有 T001 | branch/tmux/path 分開；send/stop/verify/accept/retry 不跨 manager |
| AC-05 | 錯 manager／舊 attempt／assignment 的 report/ack | 完整 identity 拒絕；reconcile 不接管他人資源；舊 inbox 不冒充新 attempt acknowledgment |
| AC-06 | 同 ID 兩 Session／長 verify／交接 | claim 競爭只有一個成功；不因時間過期接管；takeover expected generation；舊 token／長操作不能提交；report 不被長 checks 阻塞 |
| AC-07 | 兩 manager 各自整合／dirty 主 checkout | 獨立 integration；明確 committed base 與 current accepted 來源；candidate/review 改變後 gate 失效；主 checkout 不變 |
| AC-08 | A 交付後 B target 過期／中斷 | B 不覆蓋 A；重新整合驗證；transaction receipt 分辨已提交／未提交／ambiguous；釋放 common 鎖 |
| AC-09 | 不同 root 同 common dir／外部 ref／checked-out target | 共用 gate；Git transaction 拒絕 expected OID 不符；任何 checked-out target 拒絕；不宣稱禁止外部 checkout race |
| AC-10 | dry-run／source hash 變動／衝突／未知版本 | 預覽零寫入；實際執行拒絕不符與 missing quiescence；不覆寫資料 |
| AC-11 | dirty/staged/untracked/ignored worktree／歷史 | backup 可校驗；index/bytes/HEAD 保留；新 registration/ref 路由有效、舊 ref 原值保留；submodule move 不支援時預檢拒絕 |
| AC-12 | 各 phase 中斷／重跑／恢復 | 明確 resume；intent 核對不猜測；完成重跑 no-op；保留 backup/tombstone；舊 assignment/report 作廢 |
| AC-13 | 舊 verification／acceptance／依賴 | history 原文可追溯；reverify_required 阻擋 accept/依賴/交付；新驗證與接受後才恢復 eligibility |
| AC-14 | provider／worker 額度 | 每 manager 額度獨立且明示總量；原生權限保留；至少一個真實 provider 通過新路由及管理生命週期，第二 provider 按證據記錄 |

## 11. MM-01 決策結論

| ID | 已定案契約 | 故障情境／後續 |
| --- | --- | --- |
| Q-01 | §6：explicit claim/release/takeover、持久 generation/token、無自動 expiry；長操作釋放 registry，收尾 fencing | MM-03 測兩 Session、失聯、busy task、長 verify 與舊 token；Session 存活不靠 PID 推論 |
| Q-02 | §7：未 checkout 本地分支 fast-forward，expected-OID transaction＋receipt；checked-out target 拒絕 | MM-05 測兩 candidate、外部 ref 變更／crash；外部 PR/checkout workflow 不在此版 gate |
| Q-03 | §8.2–8.3：保留舊 ref、新 namespaced ref、完整 backup/journal、history 與 reverify_required、只 forward resume | MM-06 故障注入與 dirty/staged/ignored fixture；不提供自動 rollback |
| Q-04 | §8.1：顯式 source-quiesced＋source hash＋locks/inventory；live 或無法確認的 writer 阻擋，migration 不自動停止 | MM-06 檢查 mixed-version 邊界；不以靜默／worker done 證明舊 Session 離線 |

MM-01 的流程檢查結果在 [contract review](../reviews/MM-01-contract-review.md)。MM-02 的 AC-01–AC-05 範圍另有 [實作驗證](../reviews/MM-02-validation.md)；其餘 runtime 行為與 AC 仍待實作，不以契約定案或 fake provider 宣稱整體驗收。

## 12. 修訂記錄

| 日期 | 變更 |
| --- | --- |
| 2026-10-10 | MM-02：實作 namespace、完整 launch identity、純查閱與基本 claim 前置；補驗證證據，維持 Implementing，未完成 ownership handoff／integration／delivery／migration／真實 provider |
| 2026-10-09 | MM-01：selector/schema、主控 API/fencing、首版本地交付 transaction、migration mapping/歷史/停止/續跑定案；狀態改 Ready，ADR-0002–0004 Accepted；無 runtime 修改 |
| 2026-10-08 | 初稿：manager ID、namespace、主控、整合交付、v1 遷移與 AC；runtime 未實作 |
