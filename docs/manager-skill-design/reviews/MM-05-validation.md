# MM-05 — 共用本地交付 gate 驗證

日期：2026-10-10。範圍：[SPEC-001 §7.2](../specs/001-multi-manager-isolation.md#72-第一版本地交付-gateq-02)、AC-08–AC-09 與 [ADR-0003](../adr/0003-isolated-integration.md)。所有資料均為暫存 Git repository；沒有交付使用者專案、push、PR、模型或 API 呼叫。

## 實作結果

- `deliver --verification ID` 只採用所選 manager 的 owner-committed successful combined evidence，沒有 target/candidate override。鎖外先核對資格；短 gate 依 common maintenance → delivery → integration operation → registry → source report locks 排序，收尾重新載入 owner/state，核對 candidate、source acceptance/fingerprint、review、record hash、target 與完整 worktree inventory。
- 僅 fast-forward 既有 direct 本地分支；任何已 checkout target（含 missing、locked、prunable registration）一律拒絕。Candidate/target 必須直接指向 commit；不更新 HEAD/index/工作內容。保留 dirty 主 checkout、untracked 使用者檔案及 accepted source trees。
- Common durable intent 保存完整 identity、generation、verification/evidence hash、old/new OID、refs 與 inventory。單一 `update-ref --stdin` transaction 明示 no-deref，同時 verify candidate、expected-old update target、create 唯一 receipt。Common result 與 manager `delivery/` 保存收據；同一 root/manager/verification 的 delivery ID 固定，完成重跑不重新交付。
- `reconcile.deliveries` 在相同 gate 診斷 committed／not_committed／ambiguous／external_change，不自動更新 refs。Matching receipt 能證明 transaction 已完成，即使 target/candidate 後來改變。缺 receipt 不憑 target 等於 candidate 推論成功；committed_once 永久保存已成功紀錄，避免失去兩份收據後重複 reconcile 轉成可重試。Explicit transaction rejection 保留旗標及 error history，防止外部 raced receipt 被採用；成功重試後保留失敗診斷歷史。
- 既存 unknown receipt/result、損壞 intent/result/evidence 與 symlink control paths 拒絕並保留。OS locks 於正常、例外或 SIGKILL 後釋放。Busy delivery reconciliation 仍可讓 task reconciliation 繼續。

## 行為驗證

17 項 delivery tests 加入 [test_manager.py](../../../skills/manager/scripts/test_manager.py)，搭配既有 integration／ownership／namespace 回歸：

| 契約 | 實際情境與觀察 |
| --- | --- |
| AC-08：競爭與資格 | 兩 manager 對同 target 競爭，只有一個 transaction 成功；敗方合併新 target、解決真實 Git conflict，重新 combined verify 後成功交付 |
| AC-08：final recheck | Preflight 後改動 candidate、source、acceptance、review 或 record 均拒絕；交接後舊 credential fenced，新 owner 可重查既有 proof |
| AC-08：中斷 | Intent 後、transaction 前例外恢復為 not_committed；實際 SIGKILL 發生於 transaction 後/result 前，matching receipt 恢復 committed；common result 後/manager 收據前中斷再遺失 receipt，多次 reconcile 仍 ambiguous |
| AC-08：收據與重跑 | Completed verification 重跑回原收據，target 已再往前不回寫；wrong/symbolic/lost receipt 與外部 target 改動只留下診斷；既存或 raced receipt 不冒認成功 |
| AC-09：common directory | 兩 canonical roots 共用 Git common dir/control；一方持 maintenance lock 時另一 root delivery bounded busy，釋放後可交付，另一候選變過期 |
| AC-09：external OID | Final checks 後外部改 target 或 candidate OID，Git transaction 全部拒絕，沒有新 receipt／部分 target 更新 |
| AC-09：inventory | 主 checkout、linked、locked、missing／prunable target registrations 皆拒絕；symbolic target、不可讀／不完整 inventory 皆拒絕 |
| Common gate 範圍 | 長 combined checks 期間另一 manager 可 deliver／spawn；stale evidence 在鎖外失敗，不建立 delivery lock；status/owner status/integration status 保持 bytes/mtime 零寫入 |
| 授權／隔離 | 無 owner、wrong manager、invalid verification、worker 呼叫拒絕；不 stage/import/force/push/建立 PR，不自動停止 worker 或清理 refs/worktrees |

## 執行證據

| 檢查 | 最終結果 |
| --- | --- |
| 預設完整回歸 | 86 項：85 通過、1 real-only skip（222.157s） |
| 真實 tmux 完整回歸 | 86 項全部通過（296.464s）；專用暫存 server／假的互動式 Worker |
| YAML 成功路徑補驗 | 暫存 PyYAML venv 執行 1 項通過（1.475s）；預設 Python 的缺依賴路徑亦於完整回歸檢查 |
| Skill 格式 | skill-creator quick_validate 通過 |
| 靜態檢查 | 最終 Python 語法、runtime 可執行權限、21 份 Markdown 的 127 個本地 links/anchors 與 fences、git diff --check 全通過 |

最終完整回歸已包含 17 項 delivery tests 與失敗方重新整合／驗證／交付、收據遺失的永久 ambiguous、readonly bytes/mtime 的補強。初輪 15 項中 checkout fixture 誤用 full ref 造成 detached checkout，已改用 branch 名並補驗 unlocked missing/prunable entry；沒有放寬 gate。初次完整 85 項與中間 17 項 focused tests 通過後，因永久成功／診斷與額外 fixture 補強，才重跑上述最終 86 項兩套完整回歸。

```sh
python3 skills/manager/scripts/test_manager.py
MANAGER_TEST_REAL_TMUX=1 python3 skills/manager/scripts/test_manager.py
```

## 限制與接續

真實 tmux 測試使用專用暫存 socket/server 與假的互動式 Worker；不關閉 MM-08／MVP-02 真實 Agent 缺口。Git advisory locks 不攔截外部 checkout 或相同 OID 的 direct/symbolic ref-type 切換；短 gate 期間參與者必須合作使用 common maintenance。沒有宣稱 refs 與 worktree registration 跨資源原子性。

下一步為 MM-06 migration；不在本輪搬移真實 v1 資料。SPEC-001 仍為 Implementing，migration、整體組合驗證與真實 provider 待後續。MM-05 變更提交狀態以 Git status/log 為準。
