# MM-08 — 真實 provider smoke test

日期：2026-10-12。狀態：Done；MM-08 與原 MVP-02 共用本輪真實 provider 證據。範圍：[SPEC-001 AC-14](../specs/001-multi-manager-isolation.md#10-驗收情境) 與 [MVP-02 原驗收](../progress.md#原-mvp-驗證缺口mvp-02--真實-worker-smoke-test)。Runtime 基線為已 commit/push 的 `c58cbf7`；本輪未修改 runtime／adapters。

## 結果與證據

真實 Codex 完成「啟動 → structured working/done → send → inbox ack → 修正 → 新 result/done → Manager review/verify/accept → 獨立整合/combined verify」。不是 fake provider，也不是只有 pane 文字或登入探測。

| 驗收 | 實際結果／證據 |
| --- | --- |
| 版本與原生權限 | Codex CLI 0.162.1，ChatGPT 登入，pane 實際顯示 gpt-6.1-sol／high；`workspace-write`／task/inbox/events add-dir 保留，沒有 bypass approvals/sandbox/hook trust。macOS 26.6.1、Python 3.9.6、Git 2.55.0、tmux 3.7b |
| 第一輪 structured completion | [initial report](mm08-evidence/initial-report.json)、[initial result](mm08-evidence/initial-result.md)、[task events](mm08-evidence/events.json)；Ada/Lin 2 項 unittest 通過；observed 是 verification，沒有直接 acceptance |
| 訊息與修正 | [correction](mm08-evidence/correction.json)、[inbox](mm08-evidence/inbox.json)、[final report](mm08-evidence/final-report.json)；message `4443d5f4ca3d4374b14561d319e52be5` current-attempt acknowledgment 為 true，同 session、attempt 1、assignment `7d95e5b2049647ecbf0fd2055fafe1ee`；新增 trim／blank error，4 項 unittest 通過 |
| 獨立驗收 | [Manager review](mm08-evidence/task-review.md)、[review clarification](mm08-evidence/review-note.md)、[verification](mm08-evidence/task-verification.json)、[accepted marker](mm08-evidence/accepted.json)；run `ead15e392ce04db8b10ff02b76397acc` 的 4 項 unittest 與獨立 exact-output/error assertions 均 exit 0、unchanged true；accepted/current 後 matching pane 已停止 |
| Manager 整合 | [combined review](mm08-evidence/integration-review.md)、[combined record](mm08-evidence/integration-verification.json)、[combined log](mm08-evidence/integration-unittest.log)；只刻意 copy 已 review 的兩檔、commit clean candidate `34b2d1553bd367f505dd36ad202aca5a2da66fa7`，run `01cc02cbc1ce4c85906733b59747b353` passed，最終 status eligible true |
| 隔離／保留 | [結果摘要與 hashes](mm08-results.json)；accepted source snapshot 在整合前後相符；主 checkout HEAD/index/staged/working/untracked files hashes、beta 同名 queued T001 與獨立 integration tree bytes/mtime/modes 均保留 |
| 第二 provider | Codex 這輪時 Claude Code 2.1.296 未登入、未啟動。登入後另以獨立 fixture 補跑同一 lifecycle 並通過，見下方 [Claude Code 第二 provider](#claude-code-第二-provider) |

[mm08-results.json](mm08-results.json) 記錄版本、identity、message、run IDs、candidate、preservation 與 21 個 artifact hashes；它是可重查的證據索引，不含 owner credential／原生 logs。Archived record 的絕對路徑仍指向原始 fixture，hash manifest 對應本目錄保存的 copies。

## Fixture、命令與停止條件

[mm08_provider_smoke.py](mm08_provider_smoke.py) 是需刻意執行的 real-provider fixture；`prepare` 只建暫存 repo，`spawn` 才會使用帳戶額度。Runtime 管理所有 worker lifecycle；`trust --confirm-trust` 僅在使用者明確同意且畫面/root/pane 相符後回應原生 trust。已確認 trust 不會重播 prompt input。`finish` 只在 accepted/combined eligible、所有 fixture Workers 不活躍且隔離核對通過後停止專用 tmux server，不刪 Git trees/state/evidence。

Fixture 在 `/private/tmp/mm08-real-provider-elquvjt2/repo with spaces`，含 alpha/beta 同名 T001、beta integration tree、dirty/staged/untracked 主 checkout；private owner credential 只保存在上層 `private/`，不給 Worker、不進 repository。Alpha 是這次唯一真實 Worker，beta 未啟動 provider。

首次遇到 Codex folder-trust，按 [manager protocol](../../../skills/manager/references/manager-protocol.md) 的「Do not auto-confirm a prompt」保留現場；使用者明確回覆「同意信任暫存 fixture」後，重新 inspect 並只信任該暫存 repository。決定由 Codex 原生機制保存；沒有變更全域 approval/sandbox 設定。Sandbox 的 tmux socket 存取限制依主機許可處理，未繞過原生 prompt。

```sh
python3 docs/manager-skill-design/reviews/mm08_provider_smoke.py prepare
# Use the fresh --run path returned by prepare; this completed run is historical.
python3 docs/manager-skill-design/reviews/mm08_provider_smoke.py spawn --run /private/tmp/mm08-real-provider-elquvjt2
python3 docs/manager-skill-design/reviews/mm08_provider_smoke.py inspect --run /private/tmp/mm08-real-provider-elquvjt2
# Only after explicit human confirmation of this fixture's native trust prompt:
python3 docs/manager-skill-design/reviews/mm08_provider_smoke.py trust --confirm-trust --run /private/tmp/mm08-real-provider-elquvjt2
# Wait for structured done and idle TUI, then send correction; wait for ack/new done.
python3 docs/manager-skill-design/reviews/mm08_provider_smoke.py correct --run /private/tmp/mm08-real-provider-elquvjt2
# Independently review real files and write review.md before verify/accept.
python3 docs/manager-skill-design/reviews/mm08_provider_smoke.py verify --run /private/tmp/mm08-real-provider-elquvjt2
# Write integration-review.md before reviewed transfer/commit/combined verification.
python3 docs/manager-skill-design/reviews/mm08_provider_smoke.py integrate --run /private/tmp/mm08-real-provider-elquvjt2
python3 docs/manager-skill-design/reviews/mm08_provider_smoke.py finish --run /private/tmp/mm08-real-provider-elquvjt2
```

Independent task checks 使用 `python3 -B -m unittest -v` 及 `python3 -B -c ...` exact-output/error assertions；combined checks 使用同一 4 項 unittest。`-B` 避免檢查額外建立 bytecode 改動 snapshot，沒有略過測試或放寬 acceptance。原 Manager review 曾把 bytecode 作為一般 scope 註記，實際 source 無 cache、git status 只有兩檔修改；另存 clarification，保留 immutable review/verification hashes。

本機 help 與 [official OpenAI CLI reference](https://learn.chatgpt.com/docs/developer-commands?surface=cli) 已核對 sandbox/add-dir/cd/no-alt-screen。第一輪 Worker 曾誤用 report 參數，CLI 明確拒絕後同 session 自行修正並 structured done；沒有修改 runtime 或把無效呼叫當成功。原始 pane/logs 與 commands.jsonl 留在 fixture，未直接複製到 repository。

## 最終驗證與邊界

- 真實 Worker 初版 2 項／修正版 4 項 tests、Manager 2 個 task checks、combined 1 個 check 通過；current acceptance 與 combined eligibility 再核對通過。
- 未帶 confirm 的 trust、已確認 trust 的重播各明確拒絕；21 份 artifact hashes 與 report/ack/acceptance/source proof identity 核對通過；15 份 Python 語法、29 份 Markdown／190 個本地 links/anchors／fences、66 個現行 CLI examples、skill 格式與 diff check 通過。
- Runtime/adapters 未修改，沿用 MM-07 最終 107 項預設／真實 tmux 回歸證據，沒有不必要重跑或把它當真實模型驗收。新增 helper 的 prepare/spawn/inspect/trust/correct/verify/integrate/finish 均在本輪實際執行。
- 專用 tmux server 已停止，原始 runtime/Git artifacts 留在暫存 fixture；21 個審查後的證據副本保存到 repository，credentials/raw native logs 不進 repository。未修改使用者產品專案、push fixture 或交付其 release target。

MM-08 與 MVP-02 為 Done，SPEC-001 為 Implemented。只驗證此主機版本的 Codex 與 Claude Code（後者僅 auto 權限模式）；其他版本/platform／權限模式不推論通過。既有 cooperative isolation、external ref/checkout race、forward-only migration 與 polling/no automatic wakeup 邊界不變。Phase 2 是後續候選，需另立 spec 與驗收，不因本輪完成自動啟動。

## Claude Code 第二 provider

同日補跑，fixture `/private/tmp/mm08-real-provider-kzecy5sk`（`prepare --agent claude`）。Runtime／adapters 仍為 `c58cbf7` 未修改；真實 Claude 完成「啟動 → structured done → send → inbox ack → 修正 → 新 done → Manager review/verify/accept → 獨立整合/combined verify → finish」。

| 驗收 | 實際結果／證據 |
| --- | --- |
| 版本與原生權限 | Claude Code 2.1.296，claude.ai（Pro）登入，pane 顯示 Opus 5.5／medium。Adapter 不帶權限旗標，worker 繼承使用者全域 `permissions.defaultMode: "auto"`，每個 Bash 呼叫顯示 `Allowed by auto mode classifier`；fixture／runtime 沒改設定，使用者明確同意以 auto mode 驗證。Default 逐步人工核准模式未驗證 |
| Folder trust | Claude 原生 trust 畫面預設游標是「No, exit」，所以 `trust` 指令只保留給 Codex，Claude 這邊會拒絕。使用者自行 attach 專用 socket 選「Yes, I trust this folder」 |
| 第一輪 structured completion | [initial report](mm08-evidence/claude/initial-report.json)、[initial result](mm08-evidence/claude/initial-result.md)、[task events](mm08-evidence/claude/events.json)；Ada/Lin 2 項 unittest 通過，Manager 在 worktree 重跑確認 |
| 訊息與修正 | [correction](mm08-evidence/claude/correction.json)、[inbox](mm08-evidence/claude/inbox.json)、[final report](mm08-evidence/claude/final-report.json)；message `319bdb539a4c4d08a24e3dafb5e8b3ae` 已 ack，同 session、attempt 1、assignment `74aab1e376264db0a29d85c3f0c36e22`；新增 trim／blank error，4 項 unittest 通過 |
| 獨立驗收 | [Manager review](mm08-evidence/claude/task-review.md)、[verification](mm08-evidence/claude/task-verification.json)、[accepted marker](mm08-evidence/claude/accepted.json)；run `210f6a8adbe342d4903e26b88b1a3a75` 的 unittest 與 exact-output/error assertions 均 exit 0、unchanged true，acceptance current，pane 已停止 |
| Manager 整合 | [combined review](mm08-evidence/claude/integration-review.md)、[combined record](mm08-evidence/claude/integration-verification.json)、[combined log](mm08-evidence/claude/integration-unittest.log)；只 copy 已 review 的兩檔，commit candidate `d92c9499fe8d98a5445c643fa39e9c6042e25bbf`，run `0482782b866b4528b774513186f8cf7e` passed，eligible true |
| 隔離／保留 | [結果摘要與 hashes](mm08-results-claude.json)；主 checkout HEAD/index/dirty/staged/untracked、beta queued T001 與 namespace tree 保留；finish 後專用 tmux server 停止 |

Worker 行為觀察：Claude transcript 只有 Bash 呼叫（包括寫檔），沒有 Agent/Task subagent；pane 的 `← 1 agent` 是 UI 指示，不是 worker 開的 subagent。輸入框的 `check your inbox for manager corrections` 是 Claude 的 prompt suggestion（dim ghost text），不是有人輸入的內容，所以 `send` 的 paste 不會被串接。第一輪 result.md 誠實記錄 inbox 為空；修正後另記非字串輸入會丟 AttributeError，這不在修正範圍內，review 接受。

Fixture 變更：[mm08_provider_smoke.py](mm08_provider_smoke.py) 新增 `prepare --agent {codex,claude}`（預設 codex，寫入 run.json），同時寫入內容相同的 `AGENTS.md`／`CLAUDE.md`；`trust` 只對 Codex 自動化。Runtime 沒有修改。
