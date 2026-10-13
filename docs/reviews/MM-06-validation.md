# MM-06 — v1 遷移與中斷恢復驗證

日期：2026-10-11。範圍：[SPEC-001 §8–9](../specs/001-multi-manager-isolation.md#8-舊格式遷移契約)、AC-10–AC-13 與 [ADR-0004](../adr/0004-runtime-migration.md)。只使用暫存 Git repository／v1 fixtures；沒有搬移使用者真實資料、呼叫模型/API 或恢復舊 provider 對話。

## 實作結果

- `migrate` 要求明確目的 manager ID；zero-write dry-run 回傳 inventory/hash/blockers，實際執行要求 matching hash／source-quiesced，pending migration 要求同 migration ID／quiescence。Common maintenance、v1 registry/report locks 與每階段 snapshot 核對協調來源；migration 不自動停止任何 pane／child。
- Common migration 目錄保存 immutable inventory、phase/step intent/result journal、raw controls/human artifacts、完整工作內容及 private Git/index 備份。Object roots 包含 base/HEAD、歷史不可達 commit 及 index-only staged blobs；unique backup pins 與 verified pack/index 保存必要 objects。原 `.git` pointer 分開保存，backup tree 不會共用 live index。
- 保留舊 ref 原值，以單一 no-deref transaction 建立新的 namespaced refs；Git worktree move 後只切 symbolic HEAD 至同 OID 分支，不 reset/stash/force。Tree bytes/modes/links、HEAD/index 與不應改動的 private metadata 全部核對。Queued task 不先建立 tree。
- 原 briefs/logs/events/raw reports/accepted/inbox 保留為歷史。Current acceptance/verification/acks 清空，accepted_history 綁定 raw history hash。Valid done 先進入 verification；unfinished/damaged completion 進入 failed，原 failed/cancelled 不被 done claim 覆蓋。Snapshot assignment disabled，不能冒充活 Worker；新 owner 明確 claim，重新 review/verify/accept 後才取得依賴／整合資格，spawn/retry 才啟用新 reporting identity。
- Fixed phases 與逐 ref/move/switch/copy intents 支援 forward resume；來源／destination／refs／backup 非 journal 變動拒絕並保留兩側。Explicit ref transaction rejection 永久記錄，不能在下次重跑冒認 raced ref。完成 tombstone 防止 v1 init/load，pending state 不能啟用 v2。完成重跑查證 identity/backup/pins 後為 zero-write no-op，可保留後續合法 v2 任務變化。

## 行為驗證

18 項 migration tests 加入 [test_manager.py](../../tests/test_manager.py)，搭配既有 namespace／ownership／integration／delivery 回歸：

| 契約 | 情境與觀察 |
| --- | --- |
| AC-10：預覽與停止契約 | Source／Git/control bytes/mtime 保持不變；不建立 write locks、修改 exclude 或停止 panes；無 hash/quiescence、source hash 變更、busy registry/report locks 均拒絕 |
| AC-10：安全預檢 | Unknown/non-integer schema、foreign root/session、control symlink、existing destination/ref、unknown task/tree、missing/locked trees、Git operation/submodule 拒絕；live/unknown panes（包含 dead unknown）保留，不 kill |
| AC-11：搬移與備份 | Accepted dirty tree 含 staged/unstaged/untracked/ignored/executable/link 內容，搬移後 manifest/index/HEAD 相符；舊 ref 原值、新 ref/HEAD 正確，queued tree 尚未建立；pack 內含 staged-only blob 與不可達歷史 commit |
| AC-11：歷史保留 | Plan/brief/log/accepted/report/events 保留原文；未知普通檔案保留；backup pointer inert，不可用作另一個 live Git checkout |
| AC-12：資格與身份 | Historical accepted 不可直接 accept 或啟動依賴；disabled assignment report 拒絕；current/prior-attempt ack 僅歷史；新 review/verify/accept 後可 spawn 依賴，failed retry 得新 attempt/assignment；完成 migrate 不覆寫這些新 v2 變化 |
| AC-12：損壞／終態 | Broken JSON、JSON array report、missing result 不推論成功，raw history 保留且 task failed；原 failed/cancelled 即使帶 done claim 仍保留終態與失效資格 |
| AC-13：各 phase | 在 backed_up／refs_prepared／worktrees_moved／data_converted／validated／completed phase commit 前注入例外，同 journal forward resume，pending root init/claim 拒絕 |
| AC-13：已發生 side effect | Ref transaction／worktree move／symbolic HEAD switch／partial copy 發生後但 intent 尚未完成，重查副作用與 snapshot 後續跑；實際 SIGKILL 於 move 後，OS locks 釋放並可 resume |
| AC-13：外部變動 | 來源控制、ignored bytes、index、moved tree、backup、ref、mapping 改動或 raced ref 均拒絕；不覆寫外部資料、不冒認既有同 OID ref；完成重跑不寫 bytes/mtime，另建 namespace 不採用 legacy 控制資料 |

## 執行證據

| 檢查 | 最終結果 |
| --- | --- |
| 預設完整回歸 | 104 項：103 通過、1 real-only skip（302.326s） |
| 真實 tmux 完整回歸 | 104 項全部通過（332.926s）；專用暫存 server／假的互動式 Worker |
| YAML 成功路徑補驗 | PyYAML 暫存 venv 1 項通過（1.263s）；預設缺依賴路徑於完整回歸檢查 |
| Skill 格式 | skill-creator quick_validate 通過 |
| 靜態檢查 | 8 份 Python 語法、runtime 可執行權限、22 份 Markdown 的 142 個本地 links/anchors／fences、git diff --check 通過 |

```sh
python3 tests/test_manager.py
MANAGER_TEST_REAL_TMUX=1 python3 tests/test_manager.py
```

Focused migration 18 項曾通過（71.528s）；其後補強非 object report 診斷、immutable inventory 檔案、destination mode intent 與操作文件；修正後 focused 18 項再通過（72.568s），損壞 namespace 清單查閱回歸 1 項通過（0.434s），最終以上述完整回歸為準。初輪完整回歸發現清單查閱會受旁邊的損壞 namespace 影響，已修正；同輪在執行中補入 inventory 檔案，造成已載入舊 helper 與新 CLI 格式不同，最終改由全新程序重跑兩套完整回歸。非 object／missing completion 的重點補驗 1 項通過（5.479s）。

## 限制與接續

Source-quiesced 是合作式 assertion，locks/tmux 檢查不能證明舊 LLM Session 或 detached children 不會再寫入。舊 controls 保留為 retired history，舊 report 路徑不會導向新的 namespace；不支援新舊 runtime 同時寫。保留 backup/journal/pins，沒有自動 rollback、cleanup、force 搬移或損壞修復。主 worktree、submodule worktree 與 unsupported layouts 仍拒絕。

下一步 MM-07：檢查完整 namespace／主控／整合／交付／migration 組合與文件一致性。MM-08／MVP-02 真實 Agent smoke test 仍未執行；SPEC-001 維持 Implementing。MM-05 已提交為 `a5521bb`；MM-06 提交以 `feat: add recoverable v1 manager migration` 識別，Git status/log 為準。
