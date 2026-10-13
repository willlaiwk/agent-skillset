# Manager Skill — 開發任務

最後更新：2026-10-13。狀態定義與更新流程見 [README](README.md)。這份清單追蹤 skill 開發，不是產品專案 `.manager/` 的 runtime task registry。

2026-10-12 完成 MM-08／MVP-02，SPEC-001 Implemented；真實 Codex 與 Claude Code 流程通過。2026-10-13 P2-01 規格啟動後經 reviewer核對修訂：SPEC-002 Ready、ADR-0007 Accepted（取代 ADR-0006）、DS-01 Done，scheduler runtime尚未實作。P2-02–P2-04 仍為候選；任務順序不代表授權外部交付。

## 任務索引

| ID | 目標 | 狀態 | 依賴 | 對應規格／決策 |
| --- | --- | --- | --- | --- |
| DOC-01 | 文件結構與此次設計初稿 | Done | 無 | ADR-0001；SPEC-001 初稿 |
| DOC-02 | 單一 manager-skill repository 結構與路徑同步 | Done | MM-08 | ADR-0005 |
| MM-01 | 收斂多 manager 的介面與未決契約 | Done | DOC-01 | SPEC-001 Q-01–Q-04；ADR-0002–0004 |
| MM-02 | Manager selector、namespace 與 worker 路由 | Done | MM-01 | SPEC-001 §3–5；ADR-0002 |
| MM-03 | 同 ID 主控所有權與交接 | Done | MM-02 | SPEC-001 §6；ADR-0002 |
| MM-04 | 每 manager 的整合工作樹與證據 | Done | MM-02、MM-03 | SPEC-001 §7.1；ADR-0003 |
| MM-05 | Repository 共用交付 gate | Done | MM-03、MM-04 | SPEC-001 §7.2；ADR-0003 |
| MM-06 | v1 → v2 migration 與中斷恢復 | Done | MM-02、MM-03、MM-04 | SPEC-001 §8–9；ADR-0004 |
| MM-07 | Skill／protocol／reference 同步與整體驗證 | Done | MM-05、MM-06 | SPEC-001 AC-01–AC-14 |
| MM-08 | 新格式真實 provider smoke test | Done | MM-07 | SPEC-001 AC-14；延續 MVP-02 缺口 |
| MVP-02 | 現有 MVP 真實 Worker smoke test | Done | 現有 MVP | [MM-08 同一證據](reviews/MM-08-validation.md) |
| P2-01 | DAG Scheduler | In progress | MVP-02、DS-01–DS-04 | SPEC-002；ADR-0007 |
| DS-01 | Scheduler 契約、ADR 與驗收拆解 | Done | MVP-02、DOC-02 | SPEC-002 §1–9；ADR-0007 |
| DS-02 | 固定 base binding 與共用 launch gate | Todo | DS-01 | SPEC-002 §4–5、§7 |
| DS-03 | 排程預覽、一次 run 與恢復 | Todo | DS-02 | SPEC-002 §3–4、§6 |
| DS-04 | Scheduler 整體驗收與發布文件同步 | Todo | DS-02、DS-03 | SPEC-002 AC-01–AC-12 |
| P2-02 | Event Watcher | Todo | MVP 驗證及另立 spec | design §26、§32 |
| P2-03 | Automatic Verification | Todo | MVP 驗證及另立 spec | design §24、§32 |
| P2-04 | Routing／Retry Policy | Todo | MVP 驗證及另立 spec | design §21–22、§25、§32 |

MVP-02 的原驗收條件由 MM-08 真實 provider 流程涵蓋；兩者連結同一證據結案，不重複執行同樣 smoke test。Claude 另以獨立 fixture 實際補跑，不以 Codex 結果推論。

## 任務完成條件與接續

### P2-01 — DAG Scheduler

- 目標：按同 manager DAG 與即時額度，自動啟動已註冊且具備必要依賴成果的 queued tasks；保留人工 acceptance、整合與固定 base。
- 狀態：In progress；本輪開始規格工作，runtime 尚未實作。
- 完成條件：DS-01–DS-04 完成，SPEC-002 AC-01–AC-12 有 runtime 證據；完整既有回歸與必要真實 tmux focused tests 通過，已發布使用文件同步。
- 決策／證據：[SPEC-002](specs/002-dag-scheduler.md)、[ADR-0007](adr/0007-task-base-proof-and-launch-gates.md)、[DS-01 review](reviews/DS-01-contract-review.md)。
- 接續：DS-02；P2-02 Watcher 等仍需另立 spec，不與此次合併。

### DS-01 — 契約與拆解

- 目標：決定 task 註冊時機、committed dependency base 證據、capacity、一次排程與中斷行為。
- 結果：初版缺口經 reviewer對照後修正，SPEC-002重新 Ready，ADR-0007 Accepted／ADR-0006 Superseded；保留固定 base／分階段註冊／明確 bind／有界 run，補同一歷史 proof gate、三層 eligibility、完整 reconcile鎖與 intent／pin／rebind。12個 AC、原14項 walkthrough及12項 reviewer核對。
- 驗證：source inspection 與文件檢查，詳見 [DS-01 review](reviews/DS-01-contract-review.md)／[progress](progress.md)；不是 scheduler runtime 或模型驗收。
- 接續：DS-02；不新增可用 CLI、不啟動 Worker。

### DS-02 — Base binding 與 launch gate

- 目標：實作 `schedule bind`、binding／歷史／pin與故障 intent、同一歷史 task-base proof helper、三層 gate，以及所有 launch副作用前的 durable starting intent。
- 受影響範圍：`scripts/manager`、必要的 `scripts/lib/` helper、`tests/test_manager.py`；已實作命令的 runtime guidance 同步，不預先發布未完成的 run。
- 完成條件：bind／同 base expected-binding替換原子提交且留歷史，有效同 bind重播零寫入；拒絕 base mismatch／stale expected-binding／proof篡改／跨 manager／unknown version；pin與 registry中斷可診斷；dirty accepted artifact實際進入 dependent Worker；bind／launch皆允許 integration／target前進與另一個 combined verify running，來源失效仍拒絕；launch intent早於 worktree／assignment，partial publication明確診斷；手動 valid tree reuse及 migration固定 base相容。
- 驗收對應：AC-03–AC-06、AC-08–AC-11的 binding／launch範圍；全部 tasks try-lock／busy標記、來源／owner fencing涵蓋必要 gate。
- 證據：待實作／驗證，不沿用 MM 證據宣稱完成。
- 接續：DS-03。

### DS-03 — Status／run 與恢復

- 目標：純讀 DAG 預覽、明確分類／排序、一次有界 run、run journal 與 launch 中斷診斷。
- 受影響範圍：runtime CLI／helpers、行為 tests、已完成命令的 runtime guidance。
- 完成條件：run/run 與 run/spawn 不超額／重複啟動，busy 分支不阻擋獨立工作，limit／初始 budget 正確；owner takeover、partial launch、SIGKILL、partial worktree 均保留 artifacts 且不盲目重啟；status 零寫入。
- 驗收對應：AC-01–AC-02、AC-07–AC-10、AC-12；DS-02 gate 在每次 launch 重查。
- 證據：待實作／驗證。
- 接續：DS-04。

### DS-04 — 整體驗收與文件

- 目標：逐項 AC 證據對照、既有 lifecycle 回歸、隔離 tmux focused tests、發布文件與進度同步。
- 完成條件：AC-01–AC-12 均有行為證據，完整 `tests/test_manager.py`、`tests/validate_docs.py` 與必要 focused tests 通過；SKILL／protocol／runtime reference／README 反映真實可用能力，SPEC-002 才改 Implemented、P2-01 才 Done。
- 邊界：fake-provider tests 不等於真實模型驗收；adapter 未變更不重跑既有 MM-08 lifecycle。若需要新的 provider probe，另記明確範圍與結果。
- 證據：待實作／驗證。
- 接續：P2-02 另立 spec；本任務不啟動 Watcher 或自動驗證。

### DOC-02 — 單一 skill repository

- 目標：將 skill 入口、runtime、protocols 與 templates 移至根目錄；集中開發測試至 `tests/`、設計與驗收資料至 `docs/`；更新 README、相對連結及工具路徑。
- 完成條件：skill 格式、文件 links／CLI examples、完整行為回歸、獨立安裝 payload 均通過；runtime／adapters 與 41 份 archived provider evidence 保持原值。
- 結果：根目錄單一 skill 結構完成；107 項完整回歸（106 通過、1 real-only skip）、2 項真實 tmux focused tests、3 項獨立安裝 payload tests、skill／UI YAML／文件／hash 檢查通過。真實 provider helper 僅 prepare，沒有啟動 provider。
- 證據：[ADR-0005](adr/0005-single-skill-repository.md)、[DOC-02 validation](reviews/DOC-02-layout-validation.md)、[progress](progress.md)。使用者要求先將結構調整 commit/push 至 main，再自行進行 GitHub rename；提交狀態以 Git status/log 為準。
- 當時接續：P2-01 需另立 spec；DOC-02 不開始 Phase 2。後續已完成 DS-01，現行接續為 DS-02。

### DOC-01 — 文件結構與設計初稿

- 完成：建立 README、spec、ADR、task board，補 design 索引及 progress 接續。
- 證據：本目錄文件；[progress](progress.md) 記錄 9 份 Markdown、48 個本地連結／錨點及格式檢查結果。
- 邊界：只有文件完成，不代表任何新 runtime 能力完成。Commit 以 Git 實際紀錄為準。

### MM-01 — 契約收斂

- 目標：確認 selector／schema，定案主控 API、交付 workflow、migration branch mapping／backup／驗證歷史與停止條件。
- 完成條件：SPEC-001 Q-01–Q-04 各有可實作答案與故障情境；更新相關 ADR 狀態與理由；spec 達到 Ready。
- 驗證：兩 Session、長 verify、過期 target、dirty legacy worktree 與中斷的 12 項 walkthrough；8 項暫存 Git assertions 通過，另確認 symbolic-ref 邊界。不把 Git primitive 當 v2 CLI 驗收。
- 證據：[contract review](reviews/MM-01-contract-review.md)、[Git 結果](reviews/mm01-git-results.json)；Q-01–Q-04 定案，無待收斂 blocker。
- 接續：MM-02。Runtime／provider 未修改或驗證；commit 以 Git 實際紀錄為準。

### MM-02 — Namespace 與路由

- 目標：新 ID 建立／接續、明確 selector、v2 state、branch/tmux/path 與 attempt/assignment identity 隔離、managers 清單及純讀取查閱。
- 完成條件：AC-01–AC-05；不合法 ID、symlink、state 損壞與 legacy 格式有明確錯誤；每 manager 額度可辨識。
- 驗證：暫存 Git repo 中並行初始化、兩 manager 同名 task、跨 manager report/ack／reconcile，不只測字串含 ID。
- 證據：[MM-02 validation](reviews/MM-02-validation.md)、runtime/namespace helper 與行為測試；預設 35 項（34 通過、1 real-only 跳過），真實 tmux 35 項全通過，skill 格式與 YAML configuration 補驗通過。
- 結果：AC-01–AC-05 的 deterministic 範圍完成；runtime 使用說明已同步。只有假的 provider，沒有真實 Agent 驗收；commit 以 Git 實際紀錄為準。
- 接續：MM-03 主控交接／長操作。為啟動 v2 生命週期先接 basic claim 與寫入 credential guard；這些前置不代表 MM-03 Done。

### MM-03 — 主控所有權

- 目標：單一主控、純讀取查閱、交接與舊主控 fencing；長 verify 期間與交接後結果提交可辨識。
- 完成條件：AC-06；查閱不寫 registry；不同 Session 不會各自發送管理指示；長檢查不阻止 worker report。
- 驗證：兩個 CLI 呼叫端的競爭、失聯／釋放／takeover、舊 token 與長操作收尾，並檢查例外釋放。
- 結果：claim/release/takeover、private credential、owner journal／事件恢復、nonblocking operation lock、鎖外 checks／收尾 fencing 與中斷診斷完成；查閱仍零寫入，既有成功 verification 可由新主控重新核對後 accept。
- 證據：[MM-03 validation](reviews/MM-03-validation.md)；預設 50 項（49 通過、1 real-only 跳過）、真實 tmux 50 項全通過，包含 AC-06 競爭、busy／跨 task、report／review／完成快照競態、釋放／接管及中斷恢復。
- 接續：MM-04。真實 provider／MM-08／MVP-02 仍未驗證；本輪只用假的 Worker，不擴張整合／交付／migration 範圍。

### MM-04 — 獨立整合

- 目標：從明確 base 建立 manager integration worktree，整合接受成果，保存 combined verification 與 target snapshot。
- 完成條件：AC-07；manager A/B 與主 checkout 分離；使用者 dirty files 不被搬移／提交；依賴 base 含需要的成果。
- 驗證：兩 manager 的獨立整合與衝突、dirty 主 checkout、candidate 在驗證後被修改的情境。
- 結果：integration init/status/verify、明確 base／creation intent、current accepted source recheck、clean committed candidate／target ancestry、不可變 combined run／owner hash index、busy／fencing／中斷診斷完成；主 checkout／accepted task trees 保留。
- 證據：[MM-04 validation](reviews/MM-04-validation.md)；最終預設 69 項（68 通過、1 real-only skip）、真實 tmux 69 項全通過，涵蓋 AC-07、真實衝突解決、submodules、來源／target／review／record 失效、proof commit 中斷及 read-only bytes/mtime。
- 接續：MM-05；只有 combined evidence，不更新 target，不提供 deliver／自動 import/merge/push。真實 Agent／MM-08／MVP-02 仍未驗證。

### MM-05 — 共用交付 gate

- 目標：common-directory 短 gate；首版只更新未 checkout 的既有本地分支，以 expected-OID transaction 與 receipt 支援故障診斷；不內建 push／PR。
- 完成條件：AC-08–AC-09；過期成果不能覆蓋較新 target；checked-out branch 不被裸更新；不新增隱式 merge/push 授權。
- 驗證：不同 root 共用 repository、兩候選競爭、外部 ref 改動、中斷與鎖釋放；等待決策／長驗證時其他 manager 能繼續準備。
- 結果：deliver、common maintenance/delivery gate、最終 owner/evidence/inventory 核對、expected-OID transaction／unique receipt、reconcile 中斷診斷與永久成功／失敗歷史完成；首版仍拒絕所有 registered checkout targets，無 force/push/PR。
- 證據：[MM-05 validation](reviews/MM-05-validation.md)；最終預設 86 項（85 通過、1 real-only skip）、真實 tmux 86 項全通過，包含 AC-08–AC-09、external OID race、不同 roots、競爭後重新整合／驗證、SIGKILL 與 receipt 遺失／衝突。
- 接續：MM-06 migration；MM-07 整體組合驗證與 MM-08／MVP-02 真實 Agent 缺口保留。Git 提交以實際 status/log 為準。

### MM-06 — Migration

- 目標：零寫入 dry-run、source hash/quiescence 預檢、完整 backup／journal、保留舊 refs／建立新 refs、Git worktree move、歷史資格失效、forward resume／tombstone；首版無自動 rollback。
- 完成條件：AC-10–AC-13；保存 dirty/untracked/ignored 內容及歷史，不偽造驗證通過；舊 worker 不繼續寫新資料。
- 驗證：v1 fixture、目的地衝突、symlink、未知版本、live worker、各階段注入故障、完成後重跑與失效 acceptance gate。
- 結果：explicit dry-run/hash/quiescence、immutable inventory／完整 backup／object pins/pack、舊新 refs mapping、Git move／symbolic HEAD、歷史資格失效／disabled assignment、phase/intent forward resume／tombstone 完成；完成重跑為零寫入查證，不覆寫後續 v2 資料。
- 證據：[MM-06 validation](reviews/MM-06-validation.md)；18 項遷移測試涵蓋 AC-10–AC-13、phase/side-effect 中斷、SIGKILL、來源／backup／tree／ref／mode 外部變動、dirty/index/ignored 歷史保留與重新驗收。最終預設 104 項（103 通過、1 real-only skip）、真實 tmux 104 項全通過；skill／YAML／靜態檢查通過。
- 接續：MM-07；只操作暫存 v1 fixtures，不搬移使用者真實專案，不自動 rollback／cleanup；MM-08／MVP-02 真實 Agent 缺口保留。

### MM-07 — 文件同步與整體驗證

- 目標：同步 SKILL／protocol／runtime reference／範例，完整驗證 namespace、主控、整合與 migration 合用。
- 完成條件：AC-01–AC-14 的 deterministic 範圍有結果；舊單 manager 生命週期回歸通過；spec/task/progress 不誇大真實 provider 驗證。
- 驗證：既有及新行為測試、專用真實 tmux fixture、skill 格式與文件連結；實作完成前各 task 必須同步其必要 runtime 使用說明，不能全部拖到此步。
- 結果：補 migration → fresh acceptance／dependent committed base → correction/ack → release/claim → 競爭 target／真實 conflict／重新驗證／receipt 的完整流程；長 combined checks 中 takeover／retry/new identity／跨 manager report 拒絕／獨立額度及 delivery 合用。另驗 global/subcommand migration selector；同步 SKILL/protocol/reference/template/入口，澄清註冊固定 base 與 queued task 無 edit API 的限制。
- 證據：[MM-07 validation](reviews/MM-07-validation.md) 含 AC-01–AC-14 對照；最終預設 107 項（106 通過、1 real-only skip，312.805s），真實 tmux 107 項全通過（342.166s）。YAML 成功路徑 1 項、skill/UI YAML、10 份 Python 語法／可執行權限、Markdown links/anchors/fences、66 個現行 CLI 範例 parser 與 diff check 通過；只有假的 Worker。
- 接續：MM-08；SPEC-001 維持 Implementing，MVP-02/MM-08 真實 provider 缺口不關閉。沒有操作使用者 runtime、commit/push；Git status/log 為準。

### MM-08 — 真實 provider smoke test

- 目標：於獨立暫存 repo 使用真實 provider 驗證 selector、report、ack、修正、verify/accept 與 manager 整合隔離。
- 完成條件：至少一個真實 provider 走完原 MVP-02 驗收流程及新路由；記錄版本、平台、命令、證據、第二 provider 狀態。
- 驗證：控制必要使用量與外部存取範圍；保留 provider 原生權限檢查。遭主機限制時記錄實際阻塞，未驗證不標 Done。
- 結果：使用者明確同意暫存 fixture 的原生信任後，Codex 0.162.1／gpt-6.1-sol high 同 session 完成 structured working/done、send/inbox ack、trim/blank error 修正、新 result、Manager review/verify/accept 與專屬 integration/combined verify。Main HEAD/index/staged/working/untracked 與 beta 同名 queued task／integration tree 保留，accepted source 未修改；停止專用 tmux server 並保留 artifacts。沒有 runtime/adapter 變更。
- 證據：[MM-08 validation](reviews/MM-08-validation.md)、[結果與 artifact hashes](reviews/mm08-results.json)；初版 2／修正版 4 項 Worker tests、Manager 2 個 task checks、1 個 combined check 通過，current acceptance／combined eligible 再核對通過；21 份審查後證據不含 credentials/raw native logs。原 MVP-02 同一證據符合驗收，兩者 Done；SPEC-001 Implemented。
- 邊界／接續：Claude Code 2.1.296 登入後補跑通過（host auto 權限模式；未驗證 default 手動核准模式）；原生 sandbox/permissions 保留。Helper trust 無 confirm／重播拒絕、語法／文件／skill／diff 檢查通過。MM-07 已 push `c58cbf7`；MM-08 與 Claude 補驗已提交為 `86e5273`，2026-10-13 核對本機 `origin/docs/manager-multi-session-spec` 指向同一提交。Phase 2 需另立 spec，不自動開始。

P2-01 已完成規格並開始追蹤實作子任務。P2-02–P2-04 仍只是候選，啟動前按 README 流程另立功能 spec／必要 ADR 與具體驗收條件；不以這張表代替規格。
