# MM-02 — Namespace 與 worker 路由驗證

- 日期：2026-10-09–2026-10-10；起始 commit：`68cc99f`。
- 規格：[SPEC-001 §3–5](../specs/001-multi-manager-isolation.md#3-manager-身分與選擇契約)、AC-01–AC-05；[MM-02](../tasks.md#mm-02--namespace-與路由)。
- 實作：[CLI](../../../skills/manager/scripts/manager)、[namespace helper](../../../skills/manager/scripts/lib/namespace.py)、[行為測試](../../../skills/manager/scripts/test_manager.py)。
- 範圍：v2 ID/selector、state/path/branch/tmux、launch identity、report/inbox/ack、read-only inspection 與 runtime 使用說明。基本 owner claim/credential guard 是讓 namespace 生命週期可執行的 MM-03 前置；不宣稱完整 ownership/handoff 已驗收。

## 1. 行為與證據

| 驗收 | 已實作與檢查 |
| --- | --- |
| AC-01 | 無 selector 的 init 產生新 ID；4 個 CLI 並行建立互不相同的 state；同指定 ID 的並行 init 只有一個建立者；共用 exclude 不重複追加 |
| AC-02 | 指定 ID 接續不 claim/reconcile，保存 plan、task/attempt/owner 與檔案時間；拒絕不合法／reserved ID、symlink、損壞或身分／版本不符的 state，不覆寫資料 |
| AC-03 | 後續命令未給 selector 明確拒絕，不猜唯一 manager；managers/status/peek/events/inbox/owner status 不建檔或改 registry/ignore/index；persisted 與 observed state 分開 |
| AC-04 | Alpha/Beta 各有 T001 與獨立 branch/worktree/session/assignment；各自達 max_workers=1 仍可同時執行。Alpha send/ack/stop/retry/verify/accept/reconcile 不改 Beta 的 registry、report、inbox 或其他管理證據；Beta worker 仍活著 |
| AC-05 | Wrong manager/assignment/environment、舊 attempt/assignment、跨 manager 或舊訊息 ack 均拒絕，錯路由不寫目的 report/events；舊 worker inbox 被拒絕，歷史 ack 保留但標記 current_attempt=false；不接管 foreign/unmarked tmux metadata 或其他 manager worktree |

新行為使用真實暫存 Git repos 與 CLI subprocess，不只檢查命名字串。Fake tmux 支援多 session 與獨立 metadata/panes；real-tmux 模式以同一套 assertions 驗證實際 session 路由、paste、停止與 child environment。Fake provider 會輸出自己的 root hash/manager/task/attempt/assignment，確認 owner credential 環境變數未繼承。

其他覆蓋：主 checkout／dirty `.gitignore` 保留；沒有 runtime 的 linked checkout 純查閱不初始化；managers 逐項診斷 damaged/broken-symlink namespace；unsafe exclude/report path 不跟隨 symlink 寫到外部；unknown version 與浮點版本拒絕；現有 worker completion、verification fingerprint、timeout、dependency、retry、terminal quoting 與 provider routing 回歸。

## 2. 實際執行

平台：macOS／POSIX；Python 3.9.6；Git 2.55.0。所有 repo、worker binaries、tmux sockets 與 credential 都在測試自己的 TemporaryDirectory；cleanup 只管理自己的 artifacts/server。未呼叫模型/API、未變動真實專案資料或既有 tmux session。

```sh
python3 skills/manager/scripts/test_manager.py
MANAGER_TEST_REAL_TMUX=1 python3 skills/manager/scripts/test_manager.py
```

- 預設模式：35 項，34 通過／1 real-only 跳過，43.200 秒。
- 真實 tmux 模式：35 項全部通過，56.326 秒；執行已取得主機許可。
- YAML 設定補驗：使用暫存 PyYAML venv，單項成功路徑測試通過（1.169 秒）。
- Python 語法／runtime 可執行權限、18 份 Markdown 的 86 個本地連結／錨點、code fences 及 `git diff --check` 通過。

Skill 格式驗證使用 skill-creator 的 `quick_validate.py`。主機預設 Python 沒有 PyYAML，經主機許可只在 `/tmp/mm02-skill-validation` venv 安裝 PyYAML 6.0.3；不修改全域 Python。Validator 通過；另以該 interpreter 跑 YAML configuration 的行為測試，1 項通過。這個驗證 venv 是暫存工具，不是 runtime 新依賴；JSON 設定仍只需標準函式庫。

初次真實 tmux 執行因 sandbox 無法建立 socket 失敗；取得主機執行許可後可執行。測試也捕捉到兩項需修正的情況：

- `stop` 原先在 tmux identity 檢查前寫 marker；改為先驗證 session，不符合時不寫 stop marker。
- Real fake-worker 的啟動輸出可在讀取快照期間追加 log。管理資料快照明確排除 Worker 持續產生的 `log.txt`，仍比較所有 registry/report/inbox/evidence bytes 及修改時間，不把 Worker 輸出當查閱寫入。

## 3. 未完成能力與接續

- MM-03 已有 released owner、explicit claim、0600 credential、generation/token 檢查與 read-only owner status；尚無 release/takeover、交接 journal 恢復、長 verify 的 operation lock／鎖外 checks／收尾 fencing。Verify 仍全程持 per-manager registry lock；Worker report 用自己的 task lock，其他 manager namespace 可以繼續。
- MM-04–MM-06 的 integration/delivery/migration CLI 未提供，legacy 格式只診斷並保留；不能使用手動改 JSON／搬檔案替代 migration。
- 基本 claim 的一般行為已測，owner 競爭／中斷／失聯／fencing 的完整 AC-06 留給 MM-03。
- MM-07 的整體發布驗證與 MM-08/MVP-02 的真實 provider smoke test 尚未完成；fake provider 或真實 tmux 不等於真實 Agent 驗收。

接續 MM-03；SPEC-001 維持 Implementing，這份紀錄不宣稱 AC-06–AC-14 已完成。
