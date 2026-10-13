# MM-03 — 主控釋放／接管與長操作交接驗證

- 日期：2026-10-10；起始 commit：`385e331`。本輪工作樹的提交狀態以 Git status/log 為準。
- 規格：[SPEC-001 §6](../specs/001-multi-manager-isolation.md#6-同-id-的主控與鎖)、AC-06；[MM-03](../tasks.md#mm-03--主控所有權)、[ADR-0002](../adr/0002-manager-identity.md)。
- 實作：[CLI](../../scripts/manager)、[行為測試](../../tests/test_manager.py)、[runtime reference](../../references/runtime.md)。
- 結果：MM-03 deterministic 範圍完成；SPEC-001 維持 Implementing，下一步 MM-04。真實 Agent／MM-08／MVP-02 仍待後續完成。

## 1. 行為與證據

| 範圍 | 實作與實際驗證 |
| --- | --- |
| 單一主控 | 並行 CLI claim 只有一個成功，失敗者不建立 credential；session label 相同仍不能再次 claim；舊 last_activity 不自動過期 |
| Release／takeover | Release 清 token、遞增 generation，worker 繼續；重新 claim 再遞增。Takeover 核對 active／expected generation／非空 reason，競爭者只有一個成功；不停止 worker 或改 attempt／assignment |
| Credential | 0600、exclusive create、token 不出現在 stdout/events/worker environment；拒絕現有檔案、symlink、manager/worker artifact 路徑；舊 credential 對全部管理命令拒寫，worker report 仍可提交 |
| Owner 中斷 | 故障注入涵蓋 claim 在 credential 寫入前失敗、takeover 在 credential 完成後／owner commit 前失敗，以及 takeover／release 在 owner commit 後／event 前失敗。未提交 credential 純讀診斷為 invalid，恢復不啟用；已提交 owner 的事件按 operation ID 補記一次，重跑不重複 |
| 長 verify 與 busy | Checks 以外部 marker 控制真實 CLI 執行時機；同 task send/stop/retry/spawn/verify/accept 回 busy，takeover／release／report／其他 task 可在 checks 結束前完成。Reconcile 跳過 busy task；收尾保存其他 task 最新 registry，未覆寫並行新登錄 |
| 收尾 fencing | 長 verify 期間 takeover 或 release 後，舊 run 回 fenced／非零，保留 journal/record/log，不能設定 current verification。新主控 reconcile 後可重新 verify/accept；先前完整提交且成果未改的 successful verification 可跨 takeover 使用 |
| Snapshot | Report／review 在長 checks 期間變動回 snapshot_changed，current verification 為 null；既有 HEAD/index/worktree/result 檢查回歸通過。另注入「reconcile 已觀測 done、起始 snapshot 前 report 改 working」，鎖內重查完成條件拒絕通過 |
| 進程中斷 | 強制結束 verify runtime 後，OS operation lock 可再次取得；新主控核對 journal/snapshot，標 interrupted 且不授予成功。Fixture 另外結束 checks 子進程，不把 takeover 當 kill，也不刪鎖檔 |
| 查閱／相容性 | Owner status 純讀 journal／pending operation 與 credential validity，不修復或建鎖；既有 namespace、report/inbox/ack、read-only bytes/mtime、依賴、retry、verification、tmux identity、user checkout preservation 測試仍通過 |

Owner transition journal 不存 raw token，credential 先完成寫入與 fsync，再提交 owner；atomic replacement 另 fsync 所在目錄。Short side effects 保留 launch/message/stop/retry/accept intent；send 保存 delivery error，pending accept intent 由 reconcile 提示需診斷，不猜測成功。

## 2. 實際執行

平台：macOS／POSIX，Python 3.9.6。所有 Git repos、credential、markers、provider fixtures 與 tmux sockets 都在測試自己的 TemporaryDirectory；只使用假的互動式 Worker，不呼叫模型/API，不改使用者真實 runtime 資料或既有 tmux server。

```sh
python3 tests/test_manager.py
MANAGER_TEST_REAL_TMUX=1 python3 tests/test_manager.py
```

- 最終預設：50 項，49 通過／1 real-only 跳過，63.668 秒。
- 最終真實 tmux：50 項全部通過，84.650 秒；使用既有主機許可與專用暫存 server。
- Task inventory 在取得 registry 鎖後再補上非 target busy 集合的最後修正，另重跑長 verify takeover／完成快照競態／owner event repair 三項重點回歸，全部通過（4.102 秒）。
- YAML 設定成功路徑：沿用 `/tmp/mm02-skill-validation` 的 PyYAML venv，1 項通過（1.361 秒），未新增全域依賴。
- Skill 格式：以 skill-creator `quick_validate.py` 與上述暫存 venv 通過。
- Python 語法／runtime 可執行權限、19 份 Markdown 的 100 個本地連結／錨點與 code fences、`git diff --check` 通過。

首次沙箱 real-tmux 單項探測無法建立 socket；按主機權限流程重跑完整 suite。開發中測試曾捕捉 operation lock 初次建檔改變失敗操作的 artifact snapshot，改為 task 登錄時建立；另一 fault-injection 因 macOS 暫存路徑 `/var`／`/private/var` alias 沒命中，fixture 改用 canonical path 比較。最後新增的完成快照競態測試以 fixture environment 執行，不存取主機預設 tmux server。這些問題修正後才採用上列成功結果。

## 3. 恢復邊界與接續

- Takeover 旋轉 token／generation，保留既有檔案與 Worker；舊 Session 停止 CLI 及直接 plan/Git 管理寫入。Token 與 operation locks 是合作式管制，不是 OS sandbox。
- Runtime 退出只釋放自身 advisory lock；checks 子進程可能仍執行。新主控須等待或按 host 授權處理子進程，確認後再改 task；reconcile 不以 PID 或鎖可取得推論 checks 成功／已 quiesced。
- Fenced run 的收尾只保存診斷，registry reservation 由新 owner 取得 operation lock 再 reconcile 分類；current verification／acceptance 不從 journal 的 passed 字樣重建。
- 既有 MM-02 manager 可沿用原 credential／state；沒有 owner journal 的舊 claim 不偽造事件，task 缺 operation lock 時只由 management 補建。Legacy v1 migration 仍未提供。
- 下一步 [MM-04](../tasks.md#mm-04--獨立整合)：每 manager integration worktree 與 combined evidence；沿用長 checks／operation lock／generation fencing。MM-05 delivery gate、MM-06 migration、MM-07 整體驗證及 MM-08／MVP-02 真實 Agent smoke test 尚未完成。
