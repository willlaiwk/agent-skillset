# DOC-02 — 單一 manager-skill repository 結構驗證

日期：2026-10-13。狀態：Done。依 [ADR-0005](../adr/0005-single-skill-repository.md) 與使用者指示調整 repository 結構；工作基線為已合併並推送 main 的 `77d55f4`。使用者要求先 commit/push 至 main，再自行進行 GitHub rename；提交狀態以 Git status/log 為準。

## 檔案分工與相容性

| 原位置 | 現在位置 |
| --- | --- |
| `skills/manager/SKILL.md` 與 `agents/`、`scripts/`、`references/`、`templates/` | Repository 根目錄；skill 名稱仍為 `manager` |
| `skills/manager/scripts/test_manager.py` | [tests/test_manager.py](../../tests/test_manager.py) |
| `docs/manager-skill-design/` | `docs/`；spec／ADR／task／progress／reviews 保留 |
| `reviews/mm07_validate.py` | [tests/validate_docs.py](../../tests/validate_docs.py) |
| `reviews/mm08_provider_smoke.py` | [tests/real_provider_smoke.py](../../tests/real_provider_smoke.py) |
| `reviews/mm01_git_primitives.py` | [tests/probe_git_primitives.py](../../tests/probe_git_primitives.py) |

Runtime CLI、helpers、adapters、skill instructions、UI metadata 與 task template 的內容不變。Runtime reference 只同步測試命令位置；開發工具調整 repository root／CLI 定位。文件檢查器納入根目錄 skill、references／templates／README，接受合法的 CLI `--help` 成功退出。

原 81 份 Git 追蹤檔案均能找到新位置，舊集合型 container 目錄已移除。13 份 skill/runtime payload files 逐檔對照 `77d55f4` 原值一致。兩份 MM-08 manifests 與全部 41 份 archived provider evidence 的 bytes／hashes 相符；保留歷史絕對路徑，不重寫原驗收內容。

## 實際驗證

| 檢查 | 結果 |
| --- | --- |
| 預設完整行為回歸 | 107 項：106 通過、1 real-only skip（375.486s） |
| 真實 tmux focused tests | `test_real_interactive_worker_receives_message`、`test_worker_done_requires_manager_verification` 均通過（3.314s）；專用暫存 server，假的 Worker |
| 獨立安裝 payload | 只複製 SKILL／agents／scripts／references／templates 到含空白的暫存 `manager` 目錄；completion／correction/ack／assignment/environment 三項既有 lifecycle tests 通過（5.100s），不依賴 docs／tests |
| Skill 格式／UI metadata | skill-creator `quick_validate.py` 與 `agents/openai.yaml` 解析通過；PyYAML 只安裝於暫存 validation dependency 目錄 |
| 文件與 CLI 範例 | 35 份 Markdown、233 個本地 links／anchors、fences 與 67 個 CLI examples 通過；從 repository root 與其他 cwd 都能執行 validator |
| Python／權限 | 11 份 Python 語法與 `scripts/manager` 可執行權限通過 |
| Git mechanism probe | 8 項 assertions 通過；symbolic-ref 邊界仍如原設計，只是 primitive probe，不能取代 runtime 驗收 |
| Real-provider helper | `--help` 與 `prepare --agent codex` 通過；fixture 記錄的新 runtime 路徑正確，沒有 spawn 或呼叫模型 |
| 搬移與來源保留 | 原 81 份檔案保留，13 份 payload files、兩份 manifests 與 41 份 evidence 原值相同 |
| Diff | `git diff --check` 通過；新檔案另檢查尾端空白 |

```sh
python3 -B tests/test_manager.py
python3 -B tests/validate_docs.py
MANAGER_TEST_REAL_TMUX=1 python3 -B tests/test_manager.py \
  ManagerTests.test_real_interactive_worker_receives_message \
  ManagerTests.test_worker_done_requires_manager_verification
python3 -B tests/probe_git_primitives.py
python3 -B tests/real_provider_smoke.py --help
```

真實 provider `prepare` 的暫存 fixture 為 `/private/tmp/mm08-real-provider-dafdiem7`；本輪沒有啟動 provider、處理 trust prompt 或改原生權限。先前完整真實 tmux／真實 Codex／Claude 驗收仍以各自日期的 [MM-07](MM-07-validation.md) 與 [MM-08](MM-08-validation.md) 為準，不將這次檔案搬移宣稱為新的真實模型驗收。

## 接續

使用者於 GitHub 將 repository 改名為 `manager-skill` 後，再核對／更新 origin URL。此調整未修改本機 checkout 目錄、其他已安裝 skill 副本、runtime schema 或任何產品專案的 `.manager/`。下一個功能候選仍為 P2-01，需先另立 spec。
