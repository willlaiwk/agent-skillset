# Manager Skill — 當前進度與 Session 接續

最後更新：2026-10-13。MVP 基線：`d8b0ca5`；多 manager 初稿：`0b4083e`；契約定案：`68cc99f`。MM-02 提交：`385e331`；MM-03：`b302ee8`；MM-04：`11644a4`。MM-05：`a5521bb`；MM-06：`81b2104`；MM-07：`c58cbf7`；MM-08 與 Claude 補驗：`86e5273`；提交狀態文件：`77d55f4`。原分支已 fast-forward 合併並推送至 main；DOC-02 結構調整完成，提交／推送狀態以 Git status/log 與 origin/main 為準；使用者要求先 commit/push，再自行進行 GitHub rename。

**目前狀態：MM-01–MM-08／MVP-02／DOC-02 Done，SPEC-001 Implemented。P2-01 In progress：SPEC-002 經 reviewer核對修訂後 Ready、ADR-0007 Accepted／ADR-0006 Superseded、DS-01文件完成；下一步 DS-02 proof binding／pin／三層 gate／較早 launch intent，runtime尚未實作。本輪只有開發文件修訂與暫存 Git primitive probe，不啟動 Worker。先前回歸與 MM-08不代表 scheduler驗收。**

## 新 Session 從這裡開始

1. 先執行 `git status --short`、`git log -3 --oneline`，確認此紀錄之後是否有新變更；保留既有工作。
2. 閱讀 [文件入口](README.md)、本文件與 [任務清單](tasks.md)，再按任務閱讀 spec／ADR／[設計文件](design.md) 的相關章節；原 MVP／Phase 2 邊界在第 31–32 節。
3. 閱讀 [SKILL.md](../SKILL.md)、[runtime reference](../references/runtime.md) 與 [manager protocol](../references/manager-protocol.md)，理解現在已提供的指令。
   單一 repository 調整已通過 [DOC-02 validation](reviews/DOC-02-layout-validation.md)；開發命令見 [專案 README](../README.md#development-and-validation)。本次純讀核對 origin 已為 `git@github.com:willlaiwk/manager-skill.git`，HEAD／本機 origin/main 同為 `50e8581`；沒有 fetch 或改 remote。
4. 接續 [SPEC-002](specs/002-dag-scheduler.md)、[ADR-0007](adr/0007-task-base-proof-and-launch-gates.md)、[DS-01 review](reviews/DS-01-contract-review.md) 與 DS-02。Reviewer 1–12點已核對；bind／launch查同一歷史 proof、無 integration operation lock、共用 gate與 scheduler eligibility分開、每 candidate全部 tasks try-lock，另補 pin／rebind與完整 launch窗口。SPEC-001／MM-08已完成，不重跑 provider smoke；P2-02–P2-04仍需另立 spec。
5. 任務結束或交接前更新本文件：完成項目、實際驗證、遇到的阻塞、變更／commit，以及下一個可執行任務。未執行的驗證維持「未驗證」。

本文件追蹤這個 skill 的開發進度。使用 skill 管理其他專案時，該專案的任務狀態與計畫另存於其 Git 根目錄的 `.manager/`。

## 2026-10-13：SPEC-002 第二輪 review 修訂

- Reviewer 第二輪指出 5 個剩餘缺口，使用者要求補進 spec 並收集 probe 證據。
- SPEC-002：§6.1 列出 launch intent stage 與結束狀態，未結束者擋下全部 launch 路徑；§6.2 規定 retry intent 早於 kill／history／marker 移除／status 重設，history create-only 不覆寫；§4.2 共用 gate 檢查 pending bind intent，新增 reason `bind_needs_resume`；§5.1 補 expect-binding 七種組合，同 proof 重播一律零寫入。AC-05／AC-09 與 §9 決定表同步更新。
- Probe 證據：首次 `result.json` 原樣收進 [docs/reviews/ds01-pin-probe](reviews/ds01-pin-probe/result.json)。首次 inline script 沒有保存，因此重建 [tests/probe_ds01_pin.py](../tests/probe_ds01_pin.py)（相同 check 名稱，另加 GC 對照組，依 DOC-02 慣例放在 `tests/`），重跑 6 項通過並存為 [rerun-result.json](reviews/ds01-pin-probe/rerun-result.json)。暫存 fixture 未刪除。
- Runtime／adapters／已發布使用文件未改；沒有 Worker、模型、行為回歸或 tmux tests。尚未 commit／push。接續 DS-02。

## 2026-10-13：Reviewer 核對／SPEC-002 修訂

- 使用者提供 Reviewer Agent 的12點意見，要求評估真實性與調整必要。逐一對照 `scripts/manager` 的 load／launch／retry／reconcile／source_snapshot／integration verify/status與 lock flow，並核對 migration轉換。第1–4點為契約缺口，第5–12點為合理補充；兩項說法收窄：不必宣稱唯一恢復是新 task ID，既有 retry需 owner明確呼叫且不是 scheduler自動重啟。
- 初版 Ready標得過早，已修正後重新核對契約。Bind／launch共用歷史 proof檢查，不重用目前 delivery eligibility或取 integration operation lock；三層 gate區分手動有效 tree reuse與 scheduler無殘留；每 candidate全部 task nonblocking取鎖／busy標記，讓全圖 reconcile不碰未持鎖 task。
- 同時補同 base expected-binding rebind／歷史、固定 commit pin與 bind intent／恢復、所有 launch的 intent早於 worktree與 assignment副作用、timestamp單項分類、reason precedence／capacity／outcome、takeover沿用 binding、舊 binary無法強制攔截風險與 source保留。原 AC-01–AC-12增加對應情境，不宣稱已通過 runtime。
- 依 ADR-0001的歷史維護規則，新增 ADR-0007 Accepted，ADR-0006標 Superseded且保留原理由；DS-01 review保留原14項 walkthrough並新增12項 reviewer核對。
- Git primitive probe：Git 2.55.0，結果原存於暫存目錄，現已收進 [ds01-pin-probe](reviews/ds01-pin-probe/result.json)，5項 assertions通過：expected-missing pin、拒絕既有同 OID ref、integration rewrite後 pin不變、reflog expire／gc後 candidate仍為 commit、symbolic pin可辨識。只驗 Git機制，不是 scheduler／bind runtime驗收，未刪 fixture。
- 文件驗證：`python3 -B tests/validate_docs.py`通過（39份 Markdown、263個本地 links／anchors、paired fences、67個現行 CLI examples）；tracked diff與新增文件 whitespace檢查通過。Runtime／adapters／已發布使用文件未改，沒有 Worker／模型呼叫、完整行為回歸或 tmux tests，尚未 commit／push。接續 DS-02。

## 2026-10-13：P2-01 規格啟動／DS-01 完成

- 使用者要求開始下一步；本輪完成 DAG Scheduler 規格、ADR、契約 walkthrough 與具體任務拆解。SPEC-002 Ready／ADR-0006 Accepted 僅代表可實作的契約，runtime 尚未開始。
- 定案：沿用固定 committed base、Manager 整合／combined verify 後再註冊依賴 task、`schedule bind` 明確綁定 proof、純讀 `schedule status` 與有界 `schedule run`。每 manager live capacity，共用 launch gate；不新增背景 watcher 或自動 retry。
- 實作對照揭露現行手動 spawn 可在依賴 accepted 後仍使用舊 base；新 scheduler 要求依賴 binding，保留舊手動 API 相容性。Binding 後重查 immutable commit／sources／proof，不把 integration branch 或 target 後續前進誤當作 base 失效，也不放寬 delivery gate。
- [DS-01 review](reviews/DS-01-contract-review.md) 記錄 source inspection、14 項設計 walkthrough；12 個 runtime AC 待 DS-02–DS-04 驗收。此次沒有執行行為回歸、tmux 或真實模型 smoke，runtime／adapters／已發布 skill guidance 均未改。
- 文件驗證：`python3 -B tests/validate_docs.py` 通過（38 份 Markdown、256 個本地 links／anchors、paired fences、67 個現行 CLI examples）；`git diff --check` 通過。新 spec 的目標命令尚未加入 parser，不計為現行 CLI 範例驗收。
- 變更：新增 SPEC-002／ADR-0006／DS-01 review，同步 docs 入口、design、tasks 與本文件；尚未 commit／push。下一個可執行任務 DS-02，不重跑已完成的 MM-08。

## 2026-10-13：單一 manager-skill repository 結構調整

- 使用者將於 GitHub 把專案改名為 `manager-skill`；本輪只整理 repository 內容，保留 skill 名稱 `manager`，不改本機 checkout 名稱、Git remote 或已安裝的其他 skill 副本。
- 原 `skills/manager/` 的 SKILL／agents／scripts／references／templates 移至根目錄；原 `docs/manager-skill-design/` 移至 `docs/`，行為測試與三個開發 helper 集中至 `tests/`。決策見 [ADR-0005](adr/0005-single-skill-repository.md)，追蹤於 DOC-02。
- 同步專案 README、文件相對 links、範例命令與 helper／test 的 CLI 定位；runtime／adapters 不變。Archived provider evidence 原樣保留，舊絕對路徑仍代表歷史執行位置。
- 最終驗證：107 項預設回歸（106 通過、1 real-only skip，375.486s）、2 項真實 tmux focused tests（3.314s）、3 項獨立安裝 payload tests（5.100s）通過；skill／UI YAML／文件 links／67 個 CLI examples、11 份 Python 語法、runtime 可執行權限、8 項 Git primitive assertions 與 diff check 通過。13 份 skill/runtime payload files、兩份 manifests 與 41 份 archived evidence 原值相同，原 81 份追蹤檔案均保留；證據見 [DOC-02 validation](reviews/DOC-02-layout-validation.md)。
- 真實 provider helper 僅執行 `prepare --agent codex`，暫存 fixture `/private/tmp/mm08-real-provider-dafdiem7` 的 runtime 指向新 `scripts/manager`，沒有 spawn／trust／模型使用量。本輪不重跑已完成的真實 provider lifecycle；DOC-02 Done；使用者要求將結構調整 commit/push 至 main，GitHub rename 隨後由使用者處理。

## 2026-10-13：提交狀態核對

- MM-08 與 Claude 補驗已於 2026-10-12 提交為 `86e5273`（`test: validate real Codex and Claude Code provider smoke`）。本次更新前工作樹乾淨，HEAD 與本機遠端追蹤分支 `origin/docs/manager-multi-session-spec` 一致。
- 同步 README／tasks／本文件的提交狀態；Phase 2 尚未開始，下一個候選仍為 P2-01 DAG Scheduler，啟動前另立 spec。

## 2026-10-12：MM-08／MVP-02 完成

- 使用者明確同意信任暫存 fixture 後，重新 inspect 原生畫面並僅確認該 repository，保留 workspace-write／原生 permissions；沒有改全域 approval/sandbox 或啟動第二 provider。
- 真實 Codex 0.162.1（pane 顯示 gpt-6.1-sol high）同 session／attempt 1 完成 structured working/done、2 項初版 tests；runtime send 後讀 inbox，ack message `4443d5f4ca3d4374b14561d319e52be5`，修正 trim／blank ValueError、4 項 tests、新 result/done。Worker 初次 report 參數誤用被 CLI 明確拒絕，同 session 自行修正，不需 runtime/adapter 改動。
- 獨立 review 後，task verification `ead15e392ce04db8b10ff02b76397acc` 的 tests 與 exact-output/error assertions 均 exit 0／unchanged；accept/current 並停止 matching pane。只將 review 過的兩檔轉入 alpha integration，commit candidate `34b2d1553bd367f505dd36ad202aca5a2da66fa7`；combined run `01cc02cbc1ce4c85906733b59747b353` passed，最後 eligible true。
- Main HEAD/index/staged/working/untracked files hashes、beta 同名 queued T001／integration tree bytes/mtime/modes、accepted source snapshot 保留；完成後再核對 accepted／combined 資格、無活 Worker，停止專用 tmux server。原 runtime/Git/private artifacts 留在 `/private/tmp/mm08-real-provider-elquvjt2`，沒有操作使用者產品專案或更新 fixture delivery target。
- 證據：[MM-08 validation](reviews/MM-08-validation.md)、[結果／21 個 artifact hashes](reviews/mm08-results.json)；artifact copies 不含 owner credentials/raw native logs。Helper 全部流程實跑；trust 無 confirm／已確認重播各拒絕，Python 語法／artifact hashes／文件 links/anchors/fences／66 個 CLI examples／skill／diff checks 通過。Runtime/adapters 未修改，沿用 MM-07 的完整回歸，沒有重新冒稱本輪 fake tests 是真實模型驗收。
- Claude Code 2.1.296 初次未登入；登入後同日補跑真實 lifecycle 通過（host 原生 auto 權限模式，見 [MM-08 Claude](reviews/MM-08-validation.md#claude-code-第二-provider)）；MM-08/MVP-02 共用同一證據 Done，SPEC-001 Implemented。同步入口／runtime reference／spec/task/progress。此段完成時尚未 commit/push，後續已提交為 `86e5273`，提交狀態見上方 2026-10-13 核對紀錄；下一個候選 P2-01 需另立 spec，本輪沒有自動開始。

## 2026-10-12：MM-07 push 與 MM-08 開始

- 使用者要求 commit/push 後接續下一步；MM-07 提交為 `c58cbf7`，已推送 `origin/docs/manager-multi-session-spec`，再接 MM-08。
- 本機 Codex 0.162.1 已用 ChatGPT 登入，configured model 為 gpt-6.1-sol／high reasoning；Claude Code 2.1.296 未登入，沒有啟動第二 provider。原生 workspace-write 與權限檢查保留，不改全域 permissions。
- [real_provider_smoke.py](../tests/real_provider_smoke.py) 建立 `/private/tmp/mm08-real-provider-elquvjt2`，包含隔離 Git repo、獨立 tmux socket、同名 alpha/beta T001、beta integration tree、dirty/staged/untracked 主 checkout 與 private owner credential。Codex Worker 已由 runtime spawn，停在原生 folder-trust 畫面；等待使用者明確確認，不自動通過。Main HEAD/index/files 與 beta namespace bytes/mtime 保留。
- 尚未有真實 Worker structured completion/ack/verification/acceptance；MM-08/MVP-02 未完成，SPEC-001 維持 Implementing。證據暫存在 fixture 的 evidence/ 與 commands.jsonl，private credential 不進 repository。

## 2026-10-12：MM-07 完成與下一步

- 接續使用者指定的 MM-07；開始時工作樹乾淨，MM-06 為 `81b2104`。沒有啟動真實 provider 或修改 runtime API。
- 新增 migration → historical source 拒絕／fresh acceptance → dirty snapshot 整合 → fresh dependent committed base → correction/ack/verify/accept → release/claim → competing delivery／Git conflict／new proof／receipt 的完整組合回歸。保留 user staged/working/untracked files、HEAD/index、accepted source、backup/history/舊 refs，完成後多 namespace 查閱與 migrate no-op 維持 bytes/mtime。
- 補長 combined checks 中 takeover、新 assignment retry/report/ack、同名 task 路由拒絕、每 manager quota 與其他 manager delivery；舊 run fenced，reconcile/new verify 後才可交付。另驗 global/subcommand/same-value/conflicting migration selectors。
- 同步 SKILL/manager protocol/runtime/template/專案與設計入口；worker protocol/escalation/adapter flags 核對一致。澄清 task 註冊即固定 base、existing queued 無 edit API，改 base 需新 task ID；spec 修正相同 selector 可並存的文字，不變更 runtime 行為。
- 證據：[MM-07 validation](reviews/MM-07-validation.md) 含 AC-01–AC-14 deterministic 對照。最終預設 107 項（106 通過、1 real-only skip，312.805s）；真實 tmux 107 項全通過（342.166s）。YAML 成功路徑 1 項（1.209s）、skill/UI YAML、10 份 Python 語法／runtime 可執行權限、Markdown links/anchors/fences 與 66 個現行 CLI 範例 parser、diff check 通過；文件可用 [validate_docs.py](../tests/validate_docs.py) 重跑。
- 真實 tmux 初次沙箱 socket 受限，依既有主機許可通過完整專用 server；只有假的 Codex/Claude Worker、沒有模型/API。MM-07 Done；MM-08/MVP-02 Todo，SPEC-001 維持 Implementing。下一步 MM-08，尚未 commit/push；Git status/log 為準。

## 2026-10-11：MM-05 提交與 MM-06 完成

- 使用者要求 commit 後接續任務；MM-05 提交為 `a5521bb`，再接 MM-06，沒有 push。
- 完成 explicit selector／零寫入 dry-run、source hash/quiescence、maintenance/v1 registry/report locks、immutable inventory、common phase/intent journal、完整 raw/tree/private Git/index 備份與 object pins/pack。Git move 及同 OID symbolic HEAD 切換保留 dirty/staged/untracked/ignored/modes/links，舊 refs 不刪改。
- 清空 current acceptance/verification/acks，保存 accepted_history 與 raw history；disabled snapshot assignment 拒絕 Worker report。新 owner 明確 claim，重新 review/verify/accept 才能啟用依賴／整合，新 spawn/retry 使用新身份。原 failed/cancelled 不被舊 done claim 覆蓋。
- 完成 phase／side-effect forward resume、source/backup/tree/ref/mode 外部變動拒絕與保留、SIGKILL locks 釋放、pending root guard／completion tombstone。Completed rerun 零寫入查證並保留後續合法 v2 任務變化；沒有自動停止／rollback／cleanup。
- 證據：[MM-06 validation](reviews/MM-06-validation.md)。修正後 18 項 focused migration（72.568s）及損壞 namespace 清單查閱回歸（0.434s）通過；最終預設 104 項：103 通過、1 real-only skip（302.326s）；真實 tmux 104 項全通過（332.926s）。YAML 成功路徑 1 項（1.263s）、skill 格式通過；靜態結果以 validation 最終紀錄為準。
- 同步 SKILL/protocol/runtime/README、spec/ADR/tasks/progress。只用暫存 v1 fixtures／假的 Worker，不操作使用者真實 runtime；MM-06 提交以 `feat: add recoverable v1 manager migration` 識別，Git status/log 為準。
- 下一步 MM-07；MM-07–MM-08 未開始，SPEC-001 維持 Implementing；真實 Agent／MM-08／MVP-02 未驗證。

## 2026-10-10：MM-05 完成與下一步

- 接續使用者指定的 MM-05；開始時工作樹乾淨，確認 MM-04 已提交為 `11644a4`，沒有重複提交舊工作。
- 完成 deliver／common maintenance-delivery gate、最終 owner/evidence/inventory 核對，以及單一 no-deref transaction 同時 verify candidate、expected-old 更新 target、create unique receipt。只交付既有未 checkout 本地分支；dirty 主 checkout、accepted task trees、HEAD/index 保留。
- 完成 durable intent、common result／manager 收據、same-verification 重跑、owner reconcile 中斷診斷。Matching receipt 證明已提交；缺 receipt 與 old target 只允許完整重查後重試；ambiguous／external_change 不推論成功或自動回寫。永久保存 committed_once 及 rejected transaction/error history，避免收據遺失或外部衝突後誤交付。
- 證據：[MM-05 validation](reviews/MM-05-validation.md)。最終預設 86 項（85 通過、1 real-only skip）；真實 tmux 86 項全通過；YAML 成功路徑補驗 1 項通過（1.475s）、skill 格式通過。只有假的互動式 Worker，沒有模型/API；真實 Agent／MM-08／MVP-02 保留。
- 同步 SKILL／protocol／runtime reference／README、spec／ADR／task／progress。Python 語法、可執行權限、Markdown 本地連結／anchors／fences 與 diff check 結果見 validation。尚未 commit/push，不操作使用者真實 runtime。
- 下一步 MM-06；MM-06–MM-08 未開始，SPEC-001 維持 Implementing。Git advisory locks 仍需合作協調 external checkout／same-OID symbolic ref-type 改動，不宣稱跨 refs/worktree registration 原子性。

## 2026-10-10：MM-04 完成與下一步

- 使用者要求先 commit MM-03 再接 MM-04；MM-03 提交為 `b302ee8`。中途 server restart 後先核對 status/log，保留未提交 MM-04 工作，沒有重複 commit 或假定舊 test session 已通過。
- 實作 integration init/status/verify、explicit committed base／creation intent／identity resume、source acceptance/evidence/fingerprint recheck、clean committed candidate／target ancestry、不可變 run 與 owner-committed hash index。Control lock/evidence 在 Git tree 外；主 checkout 和 accepted source trees 不動。
- Manager 使用普通 repository 工具刻意整合並 commit；fixture 驗證 dirty accepted artifacts、依賴透過 committed integration base 收到 source code，以及真實 cherry-pick conflict 解決後 combined checks。Runtime 不自動 import/stage/merge/push，也不更新 target。
- 長 checks 只持 integration operation lock，其他 manager／task／report 能繼續；同 resource 回 busy，handoff 後舊 run fenced。Target/source/candidate/review/record 改變時資格失效。Init partial artifacts 和 interrupted verify 保存診斷；只有 passed record／journal、不含 owner metadata/hash index commit 的 run 不恢復成功。
- 證據：[MM-04 validation](reviews/MM-04-validation.md)。最終預設 69 項：68 通過／1 real-only skip（143.870s）；真實 tmux 69 項全通過（193.229s）。YAML 成功路徑補驗 1 項通過（1.166s），skill 格式通過。只有假的互動式 Worker，沒有模型/API。
- 同步 SKILL／manager protocol／runtime reference／README、spec／ADR／task／progress；Python 語法、runtime 可執行權限、20 份 Markdown 的 115 個本地 links/anchors 與 fences、diff check 通過。
- 下一步 MM-05；MM-05–MM-08 未開始。Integration eligible 僅是當前證據相符；checked-out delivery target、final inventory、transaction/receipt gate 仍未實作。Migration／真實 Agent smoke test 繼續保留，MM-04 改動尚未提交，實際 Git status/log 為準。

## 2026-10-10：MM-03 完成與下一步

- 完成 explicit owner release/takeover、expected generation／reason gate、generation/token fencing、private credential exclusive create／fsync、owner transition journal 與同 operation ID 的事件恢復。不依時間／PID 自動接管；workers／provider／checks 保留。
- 長 verify 預留 operation／snapshot，僅持 task operation lock 跑 checks；起始／收尾短持 registry/report 鎖，完成報告在起始 snapshot 內重查。收尾重載最新 registry，只更新所屬操作；fenced／snapshot_changed 不取得 current verification 資格。Checks 環境清除 owner credential 變數。
- Task management 的 operation lock nonblocking；busy target 立即拒絕，reconcile 跳過 busy task，其他 task／worker report 可繼續。中斷 verify 只在取得 operation lock、核對 journal/snapshot 後診斷，不推論成功；殘留 checks 子進程須另外依法處理，不刪鎖解鎖。補 short-operation intent／delivery error 診斷。
- 證據：[MM-03 validation](reviews/MM-03-validation.md)。最終預設 50 項：49 通過、1 real-only 跳過（63.668s）；真實 tmux 50 項全通過（84.650s）。最後的 task inventory busy 修正另以 3 項重點回歸通過（4.102s）；YAML 設定補驗 1 項通過（1.361s），skill 格式通過。
- 同步 SKILL／manager protocol／runtime reference／README 與設計入口、spec、ADR、task、progress。Python 語法、19 份 Markdown 的 100 個本地 links／anchors 與 fences、runtime 可執行權限及 git diff --check 通過。
- 真實 tmux 初次沙箱探測無法建立 socket，依既有主機許可使用專用暫存 server 通過；只有假的互動式 Worker，沒有模型/API。真實 Agent smoke test／MM-08／MVP-02 仍未驗證。
- 下一步 MM-04；MM-04–MM-08 未開始，legacy migration／內建交付尚未提供。本輪不修改使用者真實 runtime 資料，Git 提交狀態以實際 status/log 為準。

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
- 證據：[contract review](reviews/MM-01-contract-review.md) 的 12 項 walkthrough、[可重跑 Git probe](../tests/probe_git_primitives.py) 與 [當次結果](reviews/mm01-git-results.json)。8 項 Git assertions 通過；另確認 expected OID 不防止同 OID symbolic-ref 切換，已明示合作式 workflow 邊界。
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
| Runtime CLI | namespaced `init`、`task`、`spawn`、`send`、`inbox`、`peek`、`status`、`report`、`verify`、`accept`、`stop`、`retry`、`reconcile`、`events`、`escalate`；`managers`、`owner status/claim/release/takeover`、`integration init/status/verify`、`deliver` 與 explicit `migrate` |
| Agent adapters | Codex／Claude Code 互動式 CLI；`auto` 偵測、明確指定 provider、基本角色設定 |
| 隔離 | 每個 Worker 使用獨立 tmux window 與 Git worktree；預設從已提交的 `HEAD` 建立，可指定 `--base` |
| 任務依賴 | 可登錄依賴；只允許依賴已被 Manager 接受的任務啟動；尚無自動排程 |
| 並行限制 | 每 manager 預設最多 4 個 Worker；不同 manager 可合計超過 4，由 Manager 決定何時啟動 |
| 通訊 | Durable inbox、tmux paste、Worker `--ack`；傳送成功與收到確認分開紀錄 |
| 持久化 | `.manager/{id}/state.json`／owner、task briefs／reports／results、namespaced events/inbox/logs/驗證紀錄及 retry ack 歷史 |
| 查閱／主控 | status/peek/events/inbox/managers/owner status 零管理資料寫入；claim/release/takeover、credential guard／generation fencing 與交接恢復 |
| 驗收 | Worker `done` 先進入 Manager `verification`；`verify` 需 review 與檢查指令，`accept` 再確認證據及成果未變動 |
| 整合／交付 | 每 manager integration branch/tree、current accepted 來源、combined evidence／hash index／純讀資格核對；common 短 gate 對既有未 checkout 本地分支 transaction／receipt 交付與中斷診斷 |
| Migration | v1 dry-run/hash/quiescence、backup/journal/object archive、新 refs／Git move、歷史資格重驗、forward resume/tombstone；無自動 rollback |
| 恢復 | 偵測中斷／stale／orphan；保留成果；`retry` 沿用 worktree、遞增 attempt，拒絕舊 attempt 回報；預設最多 2 次 restart |
| 設定 | `.manager.yml`；預設流程只使用 Python 標準函式庫，YAML 語法需 PyYAML，JSON 語法不需額外依賴 |

主要檔案：

- [Runtime 與 CLI](../scripts/manager)
- [Adapters](../scripts/lib/adapter.py)
- [行為測試](../tests/test_manager.py)
- [Worker protocol](../references/worker-protocol.md)
- [Escalation policy](../references/escalation-policy.md)
- [任務 brief 模板](../templates/task.md)

## 已完成的驗證

本節保留 MVP Session 的歷史結果，對應 `d8b0ca5`；最新 deterministic 結果見 [MM-07 validation](reviews/MM-07-validation.md)，真實 provider 結果見 [MM-08 validation](reviews/MM-08-validation.md)，不將 v1 歷史結果當成新功能驗收。

| 驗證 | 結果與範圍 |
| --- | --- |
| Skill 格式驗證 | `skill-creator/scripts/quick_validate.py` 通過 |
| 預設行為測試 | 共 22 項：21 通過，1 項真實 tmux 專用測試跳過；使用暫存 Git repository 與假的 tmux／Worker |
| 真實 tmux 測試 | 共 22 項全部通過；使用獨立暫存 socket 與假的互動式 Worker，涵蓋啟動、傳訊與停止；沒有呼叫模型 API |
| 靜態檢查 | Python 語法、skill 內相對連結、行尾空白與 runtime 可執行權限通過 |
| Provider 參數 | 已核對當時安裝的 `codex --help`／`claude --help` 與官方文件；尚未驗證真實 Agent 的端到端行為 |

從 repository 根目錄重跑：

```sh
python3 tests/test_manager.py
MANAGER_TEST_REAL_TMUX=1 python3 tests/test_manager.py
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

狀態：Done（2026-10-12），[MM-08 同一份真實 provider 證據](reviews/MM-08-validation.md) 已符合下方原驗收條件。Codex 與 Claude 均通過（Claude 為登入後補跑）；下方保留原任務與驗收定義供追溯。

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
