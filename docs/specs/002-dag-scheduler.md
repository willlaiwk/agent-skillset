# SPEC-002 — DAG Scheduler

- 狀態：Ready；2026-10-13 reviewer 核對後修訂，僅契約完成，runtime 尚未實作。
- 建立／更新：2026-10-13。
- 實作基線：`50e8581`；沿用 [SPEC-001](001-multi-manager-isolation.md) 的 namespace、ownership、acceptance、integration 與 recovery。
- 決策：[ADR-0007](../adr/0007-task-base-proof-and-launch-gates.md)，取代 [ADR-0006](../adr/0006-scheduler-fixed-base.md)。任務：[P2-01／DS-01–DS-04](../tasks.md)。契約檢查：[DS-01 review](../reviews/DS-01-contract-review.md)。

## 1. 問題與目標

現行 Manager 手動選擇 queued task 並呼叫 `spawn`。Runtime 會檢查直接依賴已接受且來源仍有效，也限制活 Worker 數，但不證明後續 task 的固定 base 包含依賴成果。僅把依賴的 `done` 當成排程條件，可能啟動拿不到新程式碼的 Worker。

本功能讓 Manager 一次呼叫即可依 DAG 選出並啟動安全可執行的已註冊任務，提供純讀取預覽、依賴 base 的證據綁定、明確阻塞原因，以及重複呼叫／中斷後不重複 launch 的行為。Worker completion 仍須 Manager 獨立 review、verify、accept。

## 2. 首版範圍

- 同一 root／manager ID 內的已註冊 DAG；一次有界排程，不常駐、不自動喚醒。
- 既有 task 的固定 committed base、同 manager Worker 額度、provider routing 與 launch identity。
- 從現有成功 combined verification 綁定依賴成果的 base 證據；不新增自動 import、merge、commit 或 task-edit。
- 保留既有 `spawn`／`retry`，不自動 retry、stop、accept、deliver、push 或處理原生 permission prompt。

完整工作 DAG 可先記錄在 `plan.md`。Runtime task 仍按依賴順序註冊；有依賴的 task，先由 Manager 整合及驗證 prerequisites，再從該 committed candidate 註冊。首版沒有「先註冊全圖、之後自動換 base」，也沒有跨 manager 依賴、優先權或全 repository 額度。

## 3. 目標介面

以下是尚未實作的 CLI 契約，不是現行可執行範例。全域 selector／owner-file 規則沿用 SPEC-001。

| 命令 | 權限與結果 |
| --- | --- |
| `schedule status` | 純讀取；回傳 DAG 分類、容量、排序與預計選擇；不需 owner credential |
| `schedule bind --id TASK --verification VERIFICATION_ID [--expect-binding BINDING_ID]` | 有效 owner；綁定成功 combined proof；同 base 的明確替換需預期舊 binding ID；不 launch |
| `schedule run [--limit N]` | 有效 owner；執行一次有界排程，回傳實際 launched／skipped／errors 與容量 |

`--limit` 必須為正整數，只縮小本次 launch 預算。未提供時，預算等於開始時 `max(0, max_workers - active)`；提供時取兩者最小值。即使 Worker 迅速退出，本次也不補發超過該初始預算。`status` 回報未指定 limit 的選擇，並清楚標示是當下預覽，不能作為之後 launch 的授權／reservation。

`status` 與 `run` 每項結果包含 `task_id`、`classification`、`reasons`、`primary_reason`。沒有 reason 才是 `runnable`。`blocked` 表示等待既有依賴流程／資源釋放或下次 run 可解除；`ineligible` 表示不屬於首次自動啟動候選，或需要 Manager 診斷／bind／修復。下表由上往下是 reason 的穩定排序；多個 reason 一起保留，任一 ineligible 優先於 blocked，primary_reason 取最高優先分類中第一個 reason。

| Reason | 分類 | 條件 |
| --- | --- | --- |
| `launch_needs_diagnosis` | ineligible | 第 4.3 節的殘留／不明 launch intent 或 artifacts，優先於一般 state 不符 |
| `attempt_already_started` | ineligible | 既有 attempt／assignment，不是首次自動 launch |
| `not_queued` | ineligible | 正常已開始／完成或 failed／cancelled task；不將正常執行誤報為殘留 |
| `invalid_created_at` | ineligible | 缺少、無法解析或不帶時區的 created_at |
| `bind_needs_resume` | ineligible | 持有該 task operation lock 時仍見 pending bind intent，代表 bind 已中斷；須明確重播 bind（§5.3） |
| `binding_invalid` | ineligible | Schema、identity、task 定義、proof／review／pin 缺失或被改，含未知版本 |
| `base_mismatch` | ineligible | 固定 base 不是 commit，或 proof candidate／pin 與 base 不符 |
| `base_unbound` | ineligible | 有依賴卻沒有 committed binding |
| `dependency_changed` | ineligible | 來源的 accepted evidence／worktree 已改或缺失，含額外 proof sources |
| `dependency_needs_attention` | ineligible | 依賴 failed／cancelled 或 historical／reverify_required acceptance |
| `dependency_not_accepted` | blocked | 依賴仍 queued／working／verification／等待問答，尚待正常 Manager acceptance |
| `operation_busy` | blocked | 所需 task/source 操作尚未結束，或純讀 status 未持鎖時看到 pending bind intent（可能仍在執行）；不包含另一個 combined verify 本身 |
| `capacity_full` | blocked | 其他 gate 通過，但當下 live capacity 沒有名額 |
| `run_budget_exhausted` | blocked | 其他 gate 通過，但本次初始 budget／limit 或選擇名額已用完 |

Manager 層回報 active／max_workers／budget；task 層亦列 capacity_full／run_budget_exhausted，指出本項未被選擇的原因。只有通過其他 gate 的任務才附加這兩個 capacity reasons；不改 task 的持久 state。競爭中發現 `dependency_changed` 與 `binding_invalid` 時保留兩者，後者為 primary_reason。Busy 導致無法安全檢查來源時只報 busy，不猜測來源已壞。

純讀 status 的 busy 判斷來自已記錄的 pending operations，不建立／取得寫入鎖；沒有 pending 紀錄不保證 operation lock 可取得。Run 最後取得鎖時才確認即時 busy，預覽與執行結果可以因此不同。

`run` 回傳 root／manager ID、`schedule_run_id`、初始 budget、launched 的 task／attempt／assignment／pane、各項未啟動原因與 errors。VERIFICATION_ID 是 combined verification ID；SCHEDULE_RUN_ID 是本次排程的另一個隨機 ID，不可交替使用。

| Outcome | 條件 | Exit code |
| --- | --- | --- |
| `completed` | 本次候選走訪／budget 結束，無致命錯誤；包含正常 blocked／ineligible skip 與零 launch | 0 |
| `partial` | 至少一個 Worker 已成功 launch，之後遇到致命 provider／Git／tmux／registry 錯誤 | 1 |
| `failed` | 致命錯誤且尚無成功 launch；若副作用不明，另列診斷，不推論它沒啟動 | 1 |
| `fenced` | Owner credential 失效，無論之前有無成功 launch；優先於其他 outcome | 1 |

圖／namespace／設定整體損壞為致命錯誤。單一 task 的分類問題是 skip，與致命 errors 分開回報。`status` 資料一致時 exit 0（含 ineligible）；無法取得一致 snapshot／全局資料錯誤 exit 1。Argument syntax／非法 limit 為 argparse exit 2，零 launch，不建立 run journal。已啟動的 Worker 保留，不能因後續項目失敗 rollback 或殺掉。

## 4. DAG 與可執行條件

### 4.1 圖與排序

依賴仍須引用同 manager 先前註冊的 task；拒絕 self、duplicate、unknown dependency。讀取持久 registry 時另檢查 cycle，包含人工改壞或遷移後的資料；cycle／未知節點為整次排程錯誤，零 launch，不偷偷修復。

對當下 runnable 集合按 `(created_at 轉換為 UTC 的時間, task_id)` 遞增排序。created_at 必須存在、可解析且帶明確 timezone offset（接受 UTC／Z）。缺失、naive 或非法 timestamp 只使該 task `ineligible: invalid_created_at`，不阻止其他分支，亦不在 load／純讀時補時間或改寫 migrated task。不依 JSON dictionary 順序或 pane 回報順序排程，不新增 priority。

### 4.2 三層 gate

1. **共用 launch gate**：所有 spawn／retry／scheduler launch 都檢查有效 owner、namespace、queued state、直接依賴 current acceptance／`source_snapshot`、固定 base commit、所需資源與 report consistency、live capacity、tmux identity、provider 與 worktree registration；並要求該 task 沒有 pending bind intent（§5.3），也沒有未結束的 launch intent（§6.1）。Pending bind 與有無 committed binding 無關：手動 spawn 也不能在 bind 中斷後跳過重播而直接 launch。共用 launch side effects／intent，不複製一套啟動邏輯。
2. **Binding gate**：有 `scheduler_binding` 的任何 launch 路徑另執行第 5 節 task-base 檢查；沒有 binding 的舊手動 spawn 保留既有 dependency／base 語義。Retry 不自動換 proof。
3. **Scheduler eligibility**：只允許 queued／attempt 0／assignment null、合法 created_at、無第 4.3 節 artifacts 的 task；有依賴必須具備 committed binding，所需來源不 busy。這一層不套用到手動 spawn／retry。

因此手動 spawn 對 attempt 0 的有效既有 worktree仍可沿用，並由 Manager 刻意承擔其內容／恢復判斷；scheduler 同樣情況拒絕自動啟動。若有 unresolved launch intent 或 report／assignment 不一致，共用 gate 也需先診斷，不能以 worktree valid 忽略。Worker done／tests 通過不代替 current acceptance。

accepted、verification、working、needs_manager、needs_user、failed、cancelled task 都不自動 launch。既有 attempt 的 queued 狀態也不重新 launch；診斷後使用既有明確 recovery／retry 流程。Stale report 只是診斷，不授予 retry／kill 權限。

活 Worker 數以符合 manager namespace 的 `mgr-*` live panes 為準，包含 report 為 done／failed、正在等問答及 orphan panes；dead pane 不佔額度。未知／不符 tmux session identity 或無法可靠盤點時停止排程，不以 0 推測。其他 manager 額度獨立。

### 4.3 Launch artifacts 的判斷範圍

首次 scheduler 候選（queued／attempt 0／assignment null）除註冊時建立的 brief、queued status、operation lock、events／inbox 目錄外，以下任何一項都需 `launch_needs_diagnosis`：task worktree 路徑或 registration、task branch、`assignment.json`、非 queued／identity 不符的 `status.json`、`log.txt`（即使空檔）、同 namespaced session 下名為 `mgr-ID` 的 window（活或死均算）。另檢查 unresolved launch intent、stopped／accepted／result／verification 等不符合未啟動 task 的 artifacts；未知一般檔案列出供診斷，不刪除／採用。

合法已提交的 binding／history／binding-intents／pin 是 queued task 的預期管理資料，不是 launch殘留；pending bind 未持鎖時按 operation_busy、持鎖時按 bind_needs_resume 判斷。這些已知控制資料不列為未知 artifacts。

尚未恢復的 intent／assignment-report-registry 不一致，即使 reconcile 已把 state 改成 failed，仍優先標 `launch_needs_diagnosis`，另保留 not_queued 等 reason。正常已開始 task 的 assignment／worktree／pane 是預期成果，分類為非首次候選，不一律當成異常。Artifact inventory 需在 reconcile 前讀取，並在最終 gate 重查，避免 generic failed state 掩蓋中斷來源。

## 5. 依賴 base 的綁定

### 5.1 註冊時機與 bind

Manager 先在自己的 integration tree 整合 accepted sources，保留來源與主 checkout，commit 乾淨 candidate，執行既有 `integration verify`。Review 必須說明如何涵蓋後續 task 的依賴，含 code 與必要 research artifacts；checks 由 Manager 審閱。Runtime 保證證據一致性，Manager 保證整合充分性。

再以該 candidate 的確切 OID 註冊後續 task，然後呼叫 `schedule bind`：

- Task 必須 queued／attempt 0／assignment null，無第 4.3 節殘留、pending task operation 或未處理的 bind intent。Binding 不變更 base、brief 或 dependencies。
- Bind 與之後 launch 使用同一份第 5.2 節的 task-base proof 檢查。VERIFICATION_ID 須存在於同 manager owner-committed hash index，record 成功／unchanged，candidate OID 等於固定 base，sources 仍 current 且涵蓋全部直接 dependencies。可以有額外來源，但也須重查那些來源。
- 不呼叫 `integration status` 的完整 delivery eligibility，不要求目前 integration HEAD／tree、target／ancestry 與驗證當時相同，不因目前有 combined verify running 拒絕歷史 proof。Clean／無 Git operation／ancestry 已在原 run 的 before/after unchanged verification 證明；不重跑長 checks。
- 持 common maintenance 與 target／全部 proof sources 的 canonical task operation locks，最後在 registry `.lock` 內重查 owner、task 定義、proof hash／index 與 sources，依第 5.3 節固定 ref pin 再提交 binding。**不取得 integration operation lock**。
- 相同已提交 binding 的 VERIFICATION_ID／record hash／task 定義重播，須確認 proof／pin 仍有效，為零寫入 no-op（含不更新 owner last_activity_at、journal、event或 binding history）。若已失效，回報錯誤，不把重播當修復。
- Task 未開始、base／定義不變時，允許用成功新 proof 替換 binding；必須明確 `--expect-binding` 並符合當前 BINDING_ID，完整驗證新 proof 後一次原子提交新 binding，舊 binding 完整追加到 registry 的 binding history。預期不符、已開始或 base 改變一律拒絕。首次 bind 不接受 expect-binding；相同 binding 的成功重播不新增歷史／event。
- 判斷順序固定：先比對要求的 VERIFICATION_ID／record hash 是否等於目前 committed binding。相等即為重播，不論有無 `--expect-binding`；若有提供，值必須等於目前 BINDING_ID，否則以 stale expectation 拒絕且零寫入。同一份 proof 永遠不算替換，不產生新 BINDING_ID、history 或 event。只有 proof 不同時才走替換規則。

| 呼叫 | 目前狀態 | 結果 |
| --- | --- | --- |
| 無 `--expect-binding` | 無 binding | 首次 bind |
| 無 `--expect-binding` | 已有 binding，proof 相同 | 重播，零寫入 |
| 無 `--expect-binding` | 已有 binding，proof 不同 | 拒絕，需 expect-binding |
| `--expect-binding X` | 無 binding | 拒絕 |
| `--expect-binding X` | 目前 BINDING_ID 為 X，proof 相同 | 重播，零寫入 |
| `--expect-binding X` | 目前 BINDING_ID 為 X，proof 不同 | 替換，舊 binding 進 history |
| `--expect-binding X` | 目前 BINDING_ID 不是 X | 拒絕（stale expectation），零寫入 |

固定 base 不符時明確拒絕；不能把已 queued 任務默默 rebase 到目前 integration HEAD。這包含 migration 保留下來的舊 base。

### 5.2 同一份 task-base proof 檢查

Task 新增可選 `scheduler_binding`（version 1），包含完整 task envelope、BINDING_ID、VERIFICATION_ID、record SHA-256、review SHA-256、candidate OID、pin ref／creation identity、task 定義摘要（base／有序 dependencies／brief SHA-256）、原 run 全部 source snapshots、bind 時 owner generation 與 timestamp。Binding history 保留每份舊 binding，不含 raw credential，不取得 acceptance 或 delivery 資格。

Bind／替換／launch 都重查：合法 integration metadata 與歷史 `verifications` hash index、record 的 version／完整 root-manager identity／resource／ID／review path、原 bytes hash、`passed is true`／`outcome: passed`／`unchanged is true`／before-after snapshots 相同、review hash、candidate commit 存在且等於固定 base、來源集合涵蓋直接 dependencies，且全部 sources 與當前 `source_snapshot` 相等。Committed binding 額外核對自身 schema／task 定義與 pin。額外 proof sources 也必須仍 current；不能靠 ancestry 猜 dirty artifacts 已整合。

Proof／review 篡改與來源失效按 §3 分類為 ineligible，不重新計算 hash 沿用；新 proof 可依 §5.1 明確 rebind，但不是自動修復。Owner generation 僅供稽核，不是 proof 的到期條件；release／claim／takeover 後，新有效 owner 可使用仍有效的 binding。

管理寫入的 proof 重查在 registry `.lock` 內讀取 integration.json／hash index。現行 integration verify 的 metadata 更新也在此鎖內，原成功 index 在長 checks 期間保留；不取得 `.integration.operation.lock`，不檢查 metadata 的最新 verification pointer 或 `operation: running`。Proof helper本身不做 reconcile／operation recovery，只要求 caller已持有所需 task/source operation locks 與 report locks；bind只處理這些來源，launch caller仍按 §6對全部 tasks try-lock，供全圖 reconcile使用。Source 自身 busy／失效才阻塞該分支。純讀 status 不取寫入鎖，使用既有一致性追蹤／重讀，競態回 busy/inconsistent，不自動修復。

目前 integration branch／tree dirty、target 前進或另一個 combined verify running，不單獨妨礙**首次 bind 及 launch**，因兩者指向已成功驗證的 immutable commit。這份 helper 明確與 delivery eligibility 分開，不放寬 `integration status`／`deliver` 的候選／target gate。原 proof 仍需用既有 `integration verify` 在驗證時提供合法 target／ancestry；bind／launch 不再要求原 target 當前存在或相同。

### 5.3 固定 ref 與 bind 中斷

Bind 首次提交前建立 direct commit pin：`refs/manager-runtime/bases/{project-key}/{manager-id}/{TASK}`，指向 task 固定 base。Task base 不變，rebind 共用同一 pin；不得移動至另一 commit、轉為 symbolic 或自動刪除。Git GC 可保留 pinned commit，即使 integration branch amend／reset；pin 本身不證明整合充分性。

Bind 在持短 maintenance／task／registry 鎖時，先 durable 寫 `tasks/{TASK}/binding-intents/{BINDING_ID}.json` 的 version 1 intent（獨立 BINDING_ID、task 定義／old binding ID／new proof hash／pin ref／OID／creation identity／owner generation），再以 expected-missing、no-deref 建 ref，最後 atomic registry 提交 binding 與完整舊歷史。Pin 已存在只能在匹配已提交 binding 或 matching pending creation intent 且 direct OID 相同時採用；無 ownership 證據即使 OID 相同也拒絕。

Ref 與 registry 無跨檔案原子性。中斷時保留 intent／pin；未提交的 proof 不取得 binding 資格，也不自動刪除 pin／替換舊 binding。新 owner reconcile 只分類 pending／committed／ambiguous：核對 registry binding ID／hash／歷史與 intent 證明已提交時才補診斷；不從 ref 或 journal 重建成功。明確重播 bind 經重新驗證與相同 intent 才能 forward resume；pending intent 與同一 task 的 launch／不同 rebind 互斥。Unknown／錯 OID／symbolic ref 拒絕並保留。

每次 committed binding 重查要求 pin 仍存在、direct commit 且 OID 正確。外部刪 ref／篡改不由 advisory lock 強制阻止；回報 ineligible、拒絕自動 repin 或重算證據。未 binding 的舊 queued task 仍沒有 GC pin 保證，commit 消失由 base gate 拒絕；未來 cleanup 必須另立保留契約。

### 5.4 Source 保留

Commit pin 只保護 task base，不保存 accepted source 的 dirty working tree 或 evidence。全部直接依賴及額外 proof sources 的 worktree、registration、report／result／reviews／accepted evidence，至少須保留到所有使用該 snapshot 的下游 task 都完成 launch。仍可能 retry／再次 integration verify 的來源也須保留；本版不提供 cleanup，不自動移除 artifacts。

## 6. 一次排程、競爭與恢復

1. 純讀預檢 namespace／registry／DAG／設定／ownership；全局錯誤不 launch，單 task 問題按分類 skip。先讀取 artifact／pending intent 診斷，再在相應鎖下保存及做合法 reconcile，不能 accept completion 或修復未知 artifacts。
2. 取本次 task ID 集合與初始容量 budget；run 中新註冊的 task 留待下次。按排序檢查既有任務，capacity 為 0 時不啟動。
3. 每個 candidate 沿用現行 spawn 的鎖策略：先取 common maintenance，按 canonical task 路徑對**當時全部已知 tasks**逐一嘗試 nonblocking operation lock，失敗者放進 busy_tasks；再取 registry／所需 report locks。Target／直接及全部 proof sources 若 busy 就 skip；其他 busy task 仍可讓獨立分支前進。重載後新註冊而未取得鎖的 task 也放進 busy_tasks。Launch 內全圖 reconcile／operation recovery 只能寫已取得鎖的 task，不能把未嘗試取鎖的 task 當安全。每個 candidate 完成即釋放，不能持有整次 run。
4. 重查 owner、三層 gate、proof／sources、live capacity，才走共用 launch side effects／intent。手動 spawn、retry 與 scheduler 共用同一 capacity 與 process creation 邏輯；同 manager run/run 或 run/spawn 由最後 registry gate 序列化，不超額、不重複 launch。此處不取 integration operation lock；另一個 combined verify 可繼續長 checks。
5. Busy／依賴變動為 skip，可繼續獨立候選；provider、worktree 或 tmux launch 錯誤停止本次 run，保留前面成功與當前診斷。Owner fencing 立即停止後續管理寫入／launch，回傳已知部分結果。

### 6.1 Launch intent 與 stage

沒有 exactly-once 外部 process 保證。DS-02 將**所有 launch 路徑的 durable starting intent 移到 worktree／branch 建立和 assignment／status 改寫之前**；provider／tmux 預檢可先做，尚未保存 intent 就不做任何 launch side effect。`tasks/{TASK}/launch-intents/{LAUNCH_ID}.json` 的 version 1 intent 包含完整 envelope、launch ID、owner generation、prior／next attempt 與 assignment、base、branch／worktree／window、啟動來源（manual／retry／scheduler）、目前 stage 與已知 pane；不含 credential。歷史 intents 保留。

Stage 只在對應副作用 durable 後才前進，且每次以 atomic write 更新 intent。因此 stage 最多落後實際副作用一步；reconcile 與診斷必須同時檢查下一個 stage 的 artifacts。

| Stage | 已發生的副作用 | 結束？ |
| --- | --- | --- |
| `prepared` | 只有 intent | 否 |
| `previous_quiesced` | 僅 retry：舊 matching pane 已 kill，或已確認不存在（§6.2） | 否 |
| `history_saved` | 僅 retry：舊 status／markers 已 create-only 存入 history | 否 |
| `report_reset` | 僅 retry：markers 已移除、status 已重設為 queued | 否 |
| `worktree_ready` | Branch／worktree 已建立，或手動 spawn 已採用既有有效 worktree | 否 |
| `assignment_published` | assignment.json／status.json 已寫為 next identity | 否 |
| `registry_committed` | Registry 已存 next attempt／assignment 與 working state | 否 |
| `pane_created` | Pane 已建立，可核對的 pane 標記已保存 | 否 |
| `spawned` | Log pipe 與 `worker.spawned` 已記錄 | 是 |
| `aborted` | Intent 後的最終 gate 失敗，且沒有發生任何 launch side effect（retry 的 kill／history 也沒有） | 是 |
| `launch_failed` | Launcher 自己捕捉到已知錯誤而終止，已有副作用且 artifacts 保留。已到 `registry_committed` 時 registry 記 failed 與診斷；更早失敗時 task 保持 queued／attempt 0，scheduler 由 §4.3 artifacts 判 `launch_needs_diagnosis` | 是 |
| `superseded` | 明確 retry 依 §6.2 確認 quiescence 後接手，intent 記錄新的 LAUNCH_ID 與觀察結果 | 是 |

- 「未結束的 launch intent」指 stage 不屬於結束狀態。共用 gate 對所有 launch 路徑拒絕這種 task；scheduler 分類為 `launch_needs_diagnosis`。只有 §6.2 的明確 retry 能把它改成 `superseded`，scheduler 與 reconcile 都不能。
- Reconcile 唯一能做的 stage 推進是改成 `spawned`，條件是存在帶完整 namespace／attempt／assignment／LAUNCH_ID 標記的 pane；其他情況保留原 stage 並附診斷，不推論失敗或成功。`launch_failed` 只由 launcher 在同一程序內寫入。
- `aborted` 不消耗 attempt；若 §4.3 artifacts 也不存在，task 可再次成為 scheduler 候選。已 failed 的 `launch_failed` 走既有 retry 規則。

Assignment／status 與 registry 仍是多次檔案寫入，不能宣稱消除所有部分提交。Reconcile 先核對 intent 的 prior/next identity 與 artifacts，再判 report mismatch；意圖尚未提交至 registry 就有 next-attempt assignment/report，應保留為 `launch_needs_diagnosis`，而非只有 generic failed。它可記錄 failed／診斷，但不自動 launch、consume 新 attempt 或推論成功。成功 pane 只按完整 namespace／attempt／assignment／launch identity 找回，不能只靠 window 名；launcher須保存可核對的 pane標記，若 pane建立後標記尚未保存就中斷，保留為不明副作用，不自動採用或啟動另一 pane。

必測中斷點：intent 前／後、branch-worktree add 前／後、assignment 寫入後但 status 未寫、assignment/status 已寫但 registry 未存、registry 已存但 tmux 未呼叫、pane 已建立但結果未存、log pipe／成功記錄前後。舊版本無 intent 的殘留也按 §4.3 診斷。手動 spawn 可沿用舊有效 worktree的相容性，不代表可忽略矛盾的 assignment/report 或未知 writer。明確 retry 仍可用，但須先確認舊 matching pane／provider／子進程已按授權 quiesced、保留舊 intent／artifacts 與結果，不能只看到 failed 就跳過未知副作用診斷。

### 6.2 Retry 的準備步驟

現行 `retry` 在呼叫 launch 前就會 kill pane、寫 `history/attempt-N/status.json`、移除 `accepted.json`／`stopped.json`、把 status 重設為 queued。這些都是 launch side effect，必須納入同一份 launch intent：

1. Retry intent（啟動來源 `retry`）在 kill 之前 durable 寫入，另記錄舊 status.json 與 accepted／stopped markers 的 SHA-256，以及預計的 history 路徑。
2. 依序執行並推進 stage：`previous_quiesced` → `history_saved` → `report_reset` → 之後與一般 launch 相同。若同一 task 有未結束的舊 launch intent，先確認舊 identity 的 pane／provider／子進程已 quiesced，把舊 intent 標為 `superseded` 並記錄觀察，再寫新 intent。
3. History 一律 create-only，絕不覆寫：status.json 與 markers 以 expected-missing 寫入 `history/attempt-N/`。目標已存在時，bytes 等於 intent 記錄的 hash 才視為同一 retry 的重播而沿用；不同則拒絕、保留兩者並標 `launch_needs_diagnosis`。
4. Markers 先 create-only 複製到同一 history 目錄，hash 符合後才移除。
5. 重播已到 `report_reset` 的 retry 時，以 intent 的 hash 辨識目前 status.json 已是重設後的 queued 版本，從下一個 stage 繼續；不能把它再次存成 attempt-N 的 history。

### 6.3 Scheduler journal

`run` 保存 `.manager/{ID}/scheduler-runs/{SCHEDULE_RUN_ID}/` 的 versioned intent 與有界結果摘要，記錄 owner generation、候選集合、budget、逐項 launch identity／結果；不保存 credential。結果只是診斷，恢復依 task launch intent／identity，不從 scheduler journal 推論 acceptance／成功。每項最後 gate 時在 registry 臨界區保存結果；takeover 後舊 owner 不再提交 manager state/journal。中斷／fenced run 可以保持未收尾，新 owner reconcile 只能標診斷，不續跑舊候選；下一次 run 重新計算。

## 7. 相容性

- Registry 仍為 v2；binding／bind intent／launch intent／scheduler journal 各帶 version 1；新 runtime 拒絕未知版本／壞格式。無 binding 的舊 v2 task 不在純讀取時補寫欄位。
- 無依賴舊 queued task 可由 scheduler 啟動；有依賴舊 task 在 scheduler 顯示 `base_unbound`，既有手動 spawn 契約維持，Manager 仍負責選擇 committed base。可對尚未啟動且 base 相符的舊 task 明確 bind；不符用新 ID。
- 有 binding 的 task 由手動 spawn 或 scheduler launch 均須執行 binding gate，避免在新 runtime 用手動命令繞過已記錄的證據約束。Retry 不自動更新 binding；既有來源失效仍須診斷。
- v1 migration 保留原 queued base／歷史，不生成 binding 或 scheduler 成功證據，也不補造缺少的 task created_at。新 runtime 的 scheduler 按 §4.1 單項分類。
- **已知、無法強制的舊 binary 風險**：現行 v2 loader 會忽略新可選欄位，舊手動 spawn 可繞過 binding gate／新的 launch intent。營運上應停止舊 writer，不混用 runtime 版本，但本版沒有對舊 binary 的機制性 fencing；owner token／新欄位不能宣稱攔住它。需要強制防 downgrade 時須另立 schema migration／compatibility 決策。
- 已發布 skill/runtime guide 只有在相應行為實作並驗證後才加入命令；此次 spec 不代表使用者專案已啟動 Worker。

## 8. 驗收條件

以下均為待實作驗收；DS-01 walkthrough 不等於 runtime 通過。

| ID | 必須驗證的情境／結果 |
| --- | --- |
| AC-01 | 純讀 status 在零容量、blocked／busy／dirty source 情境正確分類；state、events、locks、Git metadata 的 bytes／mtime 保持；並行變更回一致性錯誤 |
| AC-02 | 線性／分叉／匯合 DAG、確定排序與獨立分支；self／duplicate／unknown／cycle 整次拒絕且零 launch；缺失／非法／無時區 timestamp 單項 ineligible，其他合法 task 可啟動；不同 timezone 正確轉 UTC 排序 |
| AC-03 | Worker done／verification／migration historical acceptance 均不解鎖；只有 current accepted 且未改的來源符合 dependency gate |
| AC-04 | 使用真實 Git commits 與 dirty accepted artifacts：Manager review／combined checks 後 bind，後續 Worker 實際讀到依賴 code／artifact；主 checkout 與 accepted source 保留 |
| AC-05 | 舊 base／缺來源／失敗 run／未提交 proof／跨 manager／task 定義改動／record 或 review 篡改拒絕；有效同 bind 重播零寫入；未開始同 base 以 expected-binding 替換新 proof且完整保留舊歷史；stale expected-binding／變 base／已開始拒絕；pin 建立／registry 提交各窗口故障可診斷，不採用未知同 OID ref；§5.1 expect-binding 表七種組合（含帶 expect-binding 的同 proof 重播零寫入）；中斷的 bind intent 使手動 spawn 與 scheduler 都拒絕（bind_needs_resume），未持鎖 status 報 operation_busy |
| AC-06 | Source acceptance／result／report／review／HEAD/index/dirty 變化使 binding 失效；首次 bind 前及 launch 前 integration branch／tree／target 變動單獨不阻塞；刪除原 target 仍可檢查歷史 proof；deliver gate 仍拒絕過期證據；固定 pin 在 integration amend／reset 後令 candidate 可經 GC 保留；pin 缺失／篡改／symbolic 拒絕；source worktree 遺失使下游 ineligible |
| AC-07 | max_workers／limit／初始 budget；等問答、done live pane、orphan 計額度，dead 不計；兩 manager 同名 task 額度隔離；非法 limit／未知 tmux identity 零 launch |
| AC-08 | 兩 run 並行、run 與 spawn 競爭不超額／重複 launch；長 task verify 的 source 分支 busy，獨立 task 可前進，reconcile 不寫未取得鎖的 task；長 combined verify 期間從歷史 proof 首次 bind及 launch 均可前進，不取 integration operation lock；report 可繼續，無死鎖 |
| AC-09 | 重播 run、§6 全部 launch 中斷窗口與 SIGKILL；intent 早於 git worktree add／assignment 寫入；assignment/status 已寫但 registry 未存仍標 launch_needs_diagnosis，含 generic failed 後；殘留 branch/worktree/assignment/status/log／活或死 window 保留；scheduler 不 relaunch，explicit retry 要先診斷並確認 quiescence；§6.1 每個 stage 與結束狀態（未結束 intent 擋下全部 launch 路徑、reconcile 只依完整 pane 標記改 spawned、aborted 不消耗 attempt）；§6.2 retry intent 早於 kill／history／marker 移除／status 重設，各步驟中斷後重播不覆寫 history、不把重設後的 status 存成舊 attempt，history 衝突標 launch_needs_diagnosis |
| AC-10 | run 前／任務間 owner release／takeover；舊 credential 零 launch／後續寫入，成功 Worker 保留；generation 僅稽核，新 owner 可沿用有效舊 binding，並可明確 resume pending bind／重新排程；journal 中斷不推論成功 |
| AC-11 | Root task、無 binding 舊 task／有 binding 手動 spawn、有效舊 attempt-0 worktree 的 manual reuse與 scheduler 拒絕、v1 migration 固定 base／缺 created_at 單項 skip及 unknown binding version；既有 lifecycle／delivery 不退化；舊 binary 忽略 binding 是已知風險，不宣稱新 gate 能 fencing 舊 writer |
| AC-12 | 多 reason 的 primary precedence、manager／task 容量欄位、全部 outcome／exit code與部分成功持久診斷一致；argument error零副作用；沒有自動 acceptance／routing retry／prompt confirmation／deliver/push |

用 fake providers＋暫存真實 Git repositories 做主要行為驗收；必要的 tmux focused tests 使用隔離 server。每個 AC 的結果與命令存於 DS review，不把既有 MM-08 真實模型證據宣稱為 scheduler 驗收。Provider adapter 若無變更，不重跑耗用帳戶的真實模型 smoke；若觀察到 adapter 邊界問題，再另定小型驗證範圍。

## 9. 定案與接續

| 問題 | 本版決定 |
| --- | --- |
| 後續 task 何時註冊？ | Manager 完成 prerequisite integration／combined verification 後，按固定 candidate OID 註冊；全圖先存在 plan |
| 如何確定 base 含依賴？ | 明確 bind 成功 combined proof；Runtime 查 snapshot 一致，Manager review 查成果充分 |
| Worker 額度／自動 retry？ | 每 manager 現行 live capacity；一次有界 run，無自動 retry |
| 要不要背景執行？ | 不常駐；由 Manager 明確呼叫，P2-02 另立 spec |
| 舊 queued 任務要不要改 base？ | 不改；相符可 bind，不符另註冊 ID，保留歷史 |
| 已有 binding 是否可換 proof？ | 未開始且同 base／定義時明確 expected-binding 替換，保留完整舊歷史 |
| Bind／launch 是否等 integration operation lock？ | 不等；registry 內重查歷史 proof index，source 自身 busy 另判 |
| 帶 expect-binding 重播同一份 proof？ | 視為重播零寫入；expect 值不符則拒絕 |
| Launch intent 何時算結束？ | 只有 spawned／aborted／launch_failed／superseded；未結束者擋下全部 launch 路徑 |

2026-10-13 修訂：採 reviewer 指出的 bind／launch 一致 proof、三層 gate、全圖 reconcile 的鎖前提與 combined verify 平行性；另補同 base rebind、pin／中斷、timestamp、分類／outcome、owner handoff、舊 binary 風險與 source 保留。已收斂實作契約，Ready 不表示任何 AC 已通過 runtime。

2026-10-13 第二輪修訂：補 launch intent stage 與結束狀態（§6.1）、retry 準備步驟納入 intent 且 history create-only（§6.2）、共用 gate 檢查 pending bind intent 並新增 `bind_needs_resume`、帶 expect-binding 的同 proof 重播規則（§5.1）；對應更新 AC-05／AC-09。

目前無阻擋實作的未決問題。DS-02 先實作 binding／pin／歷史 proof 重查、共用 launch intent 與三層 gate；DS-03 才接預覽、排程與恢復；DS-04 做 AC 對照、回歸及已發布使用文件。若實作證據推翻契約，先修訂本 spec／必要 ADR，不默默縮減 AC。
