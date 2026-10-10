# MM-04 — 獨立整合與 combined verification 驗證

- 日期：2026-10-10；起始 commit：`b302ee8`（MM-03 已提交）。MM-04 本輪工作樹是否提交以 Git status/log 為準。
- 規格：[SPEC-001 §7.1](../specs/001-multi-manager-isolation.md#71-manager-整合工作區)、AC-07；[MM-04](../tasks.md#mm-04--獨立整合)、[ADR-0003](../adr/0003-isolated-integration.md)。
- 實作：[CLI](../../../skills/manager/scripts/manager)、[namespace helper](../../../skills/manager/scripts/lib/namespace.py)、[行為測試](../../../skills/manager/scripts/test_manager.py)、[runtime reference](../../../skills/manager/references/runtime.md)。
- 結果：MM-04／AC-07 deterministic 範圍完成；SPEC-001 維持 Implementing，下一步 MM-05。
- 範圍：integration init/status/verify、來源 acceptance 與 combined snapshots、長 checks／busy／fencing／中斷診斷。沒有 deliver／target ref 更新／自動 import/merge/push；MM-05 尚未實作，真實 Agent 驗證仍待後續完成。

## 1. 行為與證據

| 驗收範圍 | 已實作與實際檢查 |
| --- | --- |
| 兩 manager 隔離 | Alpha/Beta 並行建立不同 branch/tree，分別整合同一 base.txt 的不同內容並 verify；每次操作核對另一 namespace 的 bytes/mtime 無改動。Integration 不被誤列為 worker orphan |
| 明確 base／重跑 | Init 必須給 committed base，記錄 resolved OID／creation intent。相同 base 再跑保存 tree/metadata/events，不 reset；不同 base、未知已有 ref/tree、symlink、foreign checkout/registration 拒絕並保留 |
| 主 checkout | Staged／working／untracked user files、HEAD/index 保留；integration tree 只含 committed base。沒有搬移、stash、stage 或 commit 主 checkout 的內容 |
| Dirty accepted source | Manager 先接受 dirty tracked＋task-owned untracked 成果，fixture 刻意複製 reviewed artifacts 到 integration 並 commit；combined verify 通過，原 accepted source tree bytes/mtime 與 main index/dirty content 不變 |
| Current acceptance | Source 必須同 manager、done/current，attempt/assignment、accepted marker／verification ID、stored verification/review、HEAD/fingerprint 相符。Unaccepted/reverify_required、wrong-manager marker、review/content mutation 均拒絕；依賴 launch 同樣重查 fingerprint，不只相信 current flag |
| 依賴與多來源 | 後續 worker 使用 committed integration ref，確實看到前一 source code；其成果被刻意 cherry-pick 後，combined snapshot 保存兩項 accepted sources。Duplicate／missing sources 拒絕 |
| 真實衝突 | 第二項 accepted source 與第一項衝突，真實 cherry-pick 進入 conflict；verify 拒絕 unfinished Git operation。Fixture 刻意解決／commit，combined checks 核對兩項成果後通過，兩個 source trees 保留原樣 |
| Clean candidate | Dirty／staged／untracked、cherry-pick marker／conflict 拒絕。Initialized clean submodule 可以通過；nested dirty/untracked、wrong revision／uninitialized submodule 拒絕。Ignored cache output 不使 clean committed candidate 失效 |
| Target／不可變證據 | Full direct local branch／ancestor 核對，拒絕 tags、remote、missing、symbolic、manager namespace、divergent target。Target OID／candidate commit／source/review/record 改動後，read-only eligibility 失效；新 run 使用新 ID，不重算舊 run 的 fingerprint |
| 準備與交付分工 | Verify 可針對 main checkout 正在持有的分支建立證據，HEAD/ref/index 不變；eligible 僅表示 evidence 相符，checked-out delivery 拒絕與 transaction/receipt 留 MM-05 |
| 長操作 | 同 integration init/verify 回 busy，reconcile 提示 busy；worker report、依賴 worker spawn、另一 manager worktree creation／verify 能在 checks 結束前完成，證明 checks 不持 common／registry lock |
| Handoff／fencing | 長 combined verify 期間 takeover 後，舊 run 回 fenced／非零，保留 record/log/journal，不提交 current verification／hash index。New owner reconcile 後可重驗；既有 completed unchanged proof 可跨 takeover 查閱為 eligible |
| 檢查中的變化 | Commands 自己改 candidate 或 accepted source、長 checks 期間 target/review 改動，即使 exit 0 仍 snapshot_changed；不產生 current qualification，並保留診斷 |
| 失敗與中斷 | Failed checks／timeout 保留 logs/code，之後 lock 可再用。強制結束 runtime 後，fixture 另處理 checks child，reconcile 取得 resource lock／核對 journal/snapshot 並分類 interrupted；不推論成功 |
| Qualification commit 故障 | 注入「record 已 passed、owner 尚未寫 integration metadata/hash index」故障；record 保留 passed 診斷，但 status/reconcile 都不恢復 eligibility。只有新的完整 owner commit 才取得資格 |
| 初始化中斷 | 注入 worktree/ref 已建立但 ready metadata 尚未提交；pure status 顯示 pending。Matching clean original base 可接續；dirty partial tree 拒絕並保留，不能 reset/recreate |
| 純讀查閱 | integration status、status.integration、owner pending operation 與 explicit run 查閱不改 bytes/mtime，不建 report/operation locks；worker environment 拒絕 integration management/inspection。Git 禁用 optional index refresh |

Control metadata/lock/evidence 都在 integration Git tree 外。Source report locks 只在短 snapshot 階段取得，long checks 只持 integration resource lock。收尾重讀最新 registry/metadata，task 並行變更不被舊 state 覆寫。Task/integration checks 共用同一 timeout／environment/logging helper；worker credentials 不傳入 check environment。

## 2. 實際執行

所有 repositories、sources/candidates、local submodule fixture、owner credentials、markers、tmux servers 與假 provider binaries 都使用測試自己的 TemporaryDirectory。沒有模型/API、遠端 fetch/push、真實專案 migration 或既有 tmux server 操作。Submodule 使用 fixture-owned 本地 Git URL 與單次 `protocol.file.allow=always`，不改主機全域設定。

```sh
python3 skills/manager/scripts/test_manager.py
MANAGER_TEST_REAL_TMUX=1 python3 skills/manager/scripts/test_manager.py
```

- 最終預設：69 項，68 通過／1 real-only 跳過，143.870 秒。
- 最終真實 tmux：69 項全部通過，193.229 秒；使用既有主機許可與專用暫存 server。
- YAML 設定成功路徑：沿用暫存 PyYAML venv，1 項通過（1.166 秒），未新增全域依賴。
- Skill 格式：skill-creator quick_validate 通過。
- Python 語法、runtime 可執行權限、20 份 Markdown 的 115 個本地 links/anchors 與 fences、`git diff --check` 通過。

前一輪完整 68 項：預設 67 通過／1 skip（134.798s），真實 tmux 68 項全通過（176.634s）。後補 qualification metadata commit 故障與明確 report-during-checks assertions，兩項重點驗證通過（10.757s），再執行上列最終 suite。重啟中斷前的舊 test session 無結果可恢復，沒有把 unknown session 當通過；恢復後先確認 Git status／`b302ee8`，再重跑重點 checks。

## 3. 邊界與接續

- Source/candidate snapshots 是一致性 gate；Manager 的 review 必須證明實際整合充分及範圍正確，runtime 不由 ancestry 或 source ID 推論 semantic correctness。
- Accepted task 可有 dirty 成果；Manager 使用普通 Git／檔案工具刻意轉移 reviewed changes/artifacts 並 commit，保留 sources 與 user checkout，遵守既有 repository/user 授權。
- Resource locks 與 token 仍為合作協定，不能攔截任意 host Git/edit；takeover 不終止 providers/checks，runtime 退出也不代表 child quiescence。中斷後等待或按 host 授權處理 children，不刪鎖。
- Init unknown/ambiguous partial artifacts 保留；reconcile 不 reset/adopt ref，也不從 passed journal 重建 qualification。Legacy v1 migration 仍待 MM-06。
- 下一步 [MM-05](../tasks.md#mm-05--共用交付-gate)：common maintenance/delivery 短 gate、最終 source/candidate/review/target/inventory 核對、expected-OID transaction＋receipt 與中斷恢復。MM-07 整體驗證及 MM-08／MVP-02 真實 Agent smoke test 保留。
