# MM-07 — 整體組合驗證與文件同步

日期：2026-10-12。範圍：[SPEC-001](../specs/001-multi-manager-isolation.md) AC-01–AC-14 的 deterministic 部分與現有單 manager 生命週期。只操作暫存 Git repository／獨立 tmux server／假的互動式 Worker；沒有呼叫真實 provider、模型/API、搬移使用者專案或 push。

## 組合驗證

[test_manager.py](../../tests/test_manager.py) 新增三項行為回歸，沿用原有全部測試：

| 測試 | 實際流程與結果 |
| --- | --- |
| `test_composition_migration_dependency_handoff_and_competing_delivery` | Dirty/staged/untracked/ignored v1 fixture 遷移，歷史 source 無法直接 combined verify；重新 review/verify/accept，保留 accepted dirty tree 並刻意轉入 integration commit；新依賴 task 從 integration base 收到成果，完成 correction/ack/再驗收；release/claim 後舊 credential 拒絕、新 owner 可重查已完成 proof；另一 manager 的同名 T001 先交付使 target 過期，拒絕舊 proof，真實 merge conflict 解決後重新驗證並交付 |
| `test_composition_migrated_long_checks_handoff_reports_capacity_and_delivery` | Migrated source 長 combined checks 中 takeover；failed task retry 改用 fake Claude、新 assignment report/ack，另一 manager 的同名 T002 用 fake Codex 並行；各 manager 上限 1、總量 2，超額啟動各自拒絕；跨 manager report 零寫入拒絕，另一 manager 可交付；舊 run fenced，reconcile 後新驗證與交付成功 |
| `test_migration_selector_examples_agree_and_conflicts_are_readonly` | Global／subcommand／同值雙 selector 的 dry-run 結果一致；衝突 selector 拒絕；source 與 Git bytes/mtime 零變更 |

第一項另核對使用者 staged/working/untracked files、主 HEAD/index、accepted source tree、v1 history、backup 與舊 ref 保留；交付 receipt/reconcile/重跑一致。遷移完成後再執行兩個 namespace 的 init/status/owner status/integration status/inbox/events/managers 與 migrate no-op，manager/Git bytes/mtime 不變。第二項核對原主 checkout/index 保留、長 checks 不持 common gate、report 不被阻塞、新 owner 不採用舊成功宣稱、另一 manager 活 Worker 保留。

## AC 證據對照

| 契約 | Deterministic 證據與邊界 |
| --- | --- |
| AC-01–AC-03 | [MM-02](MM-02-validation.md) 的 init/selector/損壞資料/純查閱回歸；本輪另核對 migrated＋fresh namespace 的查閱與完成 migration no-op |
| AC-04–AC-05 | MM-02 同名 task/send/stop/retry/ack 隔離與身份拒絕；本輪同名 T001 source/交付、同名 T002 report/new assignment/capacity 合用 |
| AC-06 | [MM-03](MM-03-validation.md) claim 競爭、長 verify/report、交接與中斷；本輪 migrated manager 的 release/claim、takeover/long integration fencing 與新 owner 重新驗證 |
| AC-07 | [MM-04](MM-04-validation.md) candidate/source/review/hash 失效及獨立整合；本輪遷移後 dirty accepted snapshot、新依賴 committed base、多 source combined checks、dirty 主 checkout 保留 |
| AC-08–AC-09 | [MM-05](MM-05-validation.md) transaction/receipt、checked-out target、不同 roots 共用 gate、external OID/SIGKILL；本輪 handoff 後競爭同 target、解 conflict/新 proof/交付，以及長檢查期間他人 delivery |
| AC-10–AC-12 | [MM-06](MM-06-validation.md) preview/hash/quiescence、完整 backup/Git move、phase/intent resume/tombstone/disabled assignment；本輪 migration 後全生命週期保留 backup/history/refs，completed rerun 零寫入 |
| AC-13 | MM-06 歷史資格失效與重新接受；本輪 historical source 拒絕 → fresh acceptance → dependency/integration/delivery |
| AC-14 | 每 manager 額度、fake Codex/Claude adapters、owner environment removal、原生 permission flags 的 deterministic 回歸；**真實 provider 新路由與管理生命週期尚未驗證，MM-08/MVP-02 保持 Todo** |

原單 manager init/spawn/report/questions/send/ack/correction/verify/accept/stop/retry/reconcile、timeout、fingerprint 與錯誤路徑全部留在完整回歸中；沒有以新案例取代舊 lifecycle 測試。

## 文件與介面核對

- 同步 SKILL、manager protocol、runtime reference、task template 與專案入口；worker protocol、escalation policy、adapter flags 經核對沿用。新增 [migration → acceptance → dependency → delivery 範例](../../references/runtime.md#continue-from-migrated-acceptance-to-dependent-work)，保留 private credential、disabled historical assignment、fresh review、committed candidate、expected-OID/receipt 與 checked-out target 拒絕。
- 明示現有註冊行為：task 註冊即解析固定 base；既有 queued task（含 migrated task）不能用 spawn 覆寫 base，目前沒有 task-edit API。需新 base 時先準備 integration commit，再以新 task ID 登錄，保留原任務與 history 並在 plan 記錄接續。這是既有實作限制的澄清，未增加 runtime API。
- 修正 spec 的 selector 文字：migrate 可同時提供兩處相同 ID，只有衝突值拒絕；runtime 行為未變。
- [validate_docs.py](../../tests/validate_docs.py) 可重跑所有維護中 Markdown 的本地 links/anchors/fences，以及 SKILL/reference/SPEC-001 shell 範例的真實 CLI parser。只驗語法，不執行範例或推論授權／semantic 成功；`design.md` 原 v1/未來 CLI sketches 保留，依其開頭聲明排除 parser 驗證。

## 執行證據

環境：macOS 26.6.1、Python 3.9.6、Git 2.55.0、tmux 3.7b；PyYAML 使用既有 `/tmp/mm02-skill-validation` venv，不新增全域依賴。

| 檢查 | 結果 |
| --- | --- |
| 預設完整回歸 | 107 項：106 通過、1 real-only skip（312.805s） |
| 真實 tmux 完整回歸 | 107 項全部通過（342.166s）；專用暫存 server／假的 Worker |
| YAML 成功路徑補驗 | 1 項通過（1.209s），預設缺依賴路徑由完整回歸涵蓋 |
| Skill 格式／UI YAML | skill-creator quick_validate、agents/openai.yaml 解析通過 |
| 靜態檢查 | 10 份 Python 語法、runtime 可執行權限、23 份 Markdown／160 個本地 links/anchors／fences、66 個現行 CLI 範例 parser、git diff --check 通過 |

```sh
python3 tests/test_manager.py
MANAGER_TEST_REAL_TMUX=1 python3 tests/test_manager.py
python3 tests/validate_docs.py
```

首輪 focused tests 誤在既有 migrated queued task 上指定新 base，runtime 正確拒絕覆寫定義；改為測拒絕與保留，再建立 fresh dependent task，並補上述文件限制。修正後此完整組合測試單獨通過（15.929s）。初次 focused real-tmux 在 sandbox 內無法建立 socket；依既有主機許可重跑完整專用 fixture，不繞過主機權限，不把環境限制算作 runtime 缺陷。

## 限制與接續

MM-07 deterministic 驗證完成，SPEC-001 維持 Implementing，下一步為 MM-08；至少一個真實 provider 需走完 selector/report/ack/correction/result/verify/accept 與 manager integration 隔離，另一 provider 按證據列出狀態。符合原 MVP-02 條件時共用同一證據關閉該缺口。

既有合作式 owner/quiescence/advisory locks、external checkout／same-OID ref-type race、submodule fingerprint 與 forward-only migration 邊界未改。沒有 task-edit、自動 scheduler/wakeup、migration rollback/cleanup 或內建 push/PR；沒有操作真實專案 runtime。
