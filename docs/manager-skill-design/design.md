# Manager Skill — Design Document

**Status:** Architecture baseline（保留原始 Draft；實作狀態另行追蹤）<br>
**Target:** Codex / Claude Code  
**Runtime:** tmux + Git Worktree + Filesystem State  
**Goal:** 將任意 Coding Agent 轉化為可自主規劃、委派、監督、驗證與回報的 Engineering Manager

文件入口與維護方式見 [README](README.md)；實作現況見 [progress](progress.md)，開發任務見 [tasks](tasks.md)。本文件包含尚未實作的願景，不是目前 CLI 的使用手冊；已實作介面以 [runtime reference](../../skills/manager/references/runtime.md) 為準。

2026-10-09 完成 [SPEC-001：多 Manager 隔離、整合與遷移](specs/001-multi-manager-isolation.md) 的 MM-01 契約收斂（Ready，ADR-0002–0004 Accepted；未實作），涉及本文件第 7、11、18–19、23、25–26、30 節。採用持久 manager ID namespace、明確 owner generation/token 交接、各 manager 獨立整合工作樹、common-directory 短交付 gate 與 v1 遷移。首版 gate 僅支援未 checkout 本地分支 fast-forward；migration 保留歷史與舊 refs，採完整 backup/journal、資格重驗與 forward resume。原章節保留為 v1 架構基線；新功能以 SPEC-001 為行為契約，不在本文件複製細節。

---

## 1. Overview

Manager Skill 是一個可安裝至任意軟體專案的 Agent Skill。

啟用後，當前 Agent 不再只是直接執行使用者指令的 coding agent，而是成為專案的 **Manager / Primary Agent**。

使用者只需要與 Manager 溝通：

```text
User
 │
 ▼
Manager
```

Manager 負責理解需求、拆解工作、建立子任務、透過 tmux 啟動 Worker Agents、持續與 Worker 溝通、驗證成果、處理失敗與重新派工。

正常執行過程中的 Worker 溝通不應暴露給使用者。

只有以下情況才需要回報使用者：

- 需要產品或技術決策
- 缺少只有使用者能提供的資訊
- 需要特殊權限
- 即將執行高風險或不可逆操作
- 任務完成並通過驗證
- 多次自動恢復後仍無法完成

核心原則：

> **The user manages the Manager. The Manager manages everything else.**

---

## 2. Goals

Manager Skill 必須達成以下能力。

### 2.1 Single Point of Contact

使用者只與 Manager 溝通。

```text
User
  │
  ▼
Manager
  │
  ├── Worker A
  ├── Worker B
  └── Worker C
```

使用者不需要：

- 查看 Worker 狀態
- 回覆 Worker 問題
- 手動開 tmux
- 手動重新派工
- 手動整理 Worker output
- 判斷 Worker 是否真的完成

### 2.2 Autonomous Delegation

Manager 可以自行決定：

- 是否需要拆任務
- 任務如何拆解
- 哪些任務可以平行
- 哪些任務有 dependency
- 是否需要 research worker
- 是否需要 implementation worker
- 是否需要 verification worker
- Worker 使用 Codex 或 Claude Code

### 2.3 Autonomous Supervision

Worker 啟動後，Manager 仍然擁有任務。

Manager 必須：

```text
delegate
   ↓
observe
   ↓
answer worker questions
   ↓
review output
   ↓
request corrections
   ↓
verify
   ↓
accept
```

不能：

```text
delegate
   ↓
worker says "done"
   ↓
tell user "done"
```

Worker 的 `done` 只是「Worker 認為自己的工作完成」，不是「Manager 已確認需求完成」。

### 2.4 Cross-Agent Compatibility

Manager Skill 不應綁定特定 Agent implementation。

目標支援：

- Codex
- Claude Code
- 未來其他 CLI Coding Agents

因此 Skill 本身必須 vendor-neutral。

Provider-specific behavior 應封裝於 Adapter Layer。

### 2.5 Restart-Proof

Manager 的狀態不能只存在 LLM context。

以下情況都必須可以恢復：

- Context compaction
- Agent restart
- Terminal restart
- tmux reconnect
- Codex restart
- Claude Code restart

所有重要狀態必須持久化。

---

## 3. Non-Goals

第一版不需要實現：

- 完整 project management SaaS
- Web dashboard
- distributed execution
- cloud worker
- multi-user collaboration
- Jira / Linear integration
- Kubernetes worker scheduling
- long-term organizational memory

Manager Skill 首先是一個：

> **Local autonomous coding manager runtime.**

---

## 4. High-Level Architecture

```text
┌──────────────────────────────────────┐
│                 User                 │
│                                      │
│             "Implement X"            │
└──────────────────┬───────────────────┘
                   │
                   ▼
┌──────────────────────────────────────┐
│            Manager Agent             │
│                                      │
│ understand                           │
│ plan                                 │
│ delegate                             │
│ supervise                            │
│ review                               │
│ verify                               │
│ escalate                             │
└──────────────────┬───────────────────┘
                   │
                   ▼
┌──────────────────────────────────────┐
│          Manager Runtime             │
│                                      │
│ Task DAG                             │
│ State                                │
│ Events                               │
│ tmux                                 │
│ Git Worktrees                        │
│ Agent Adapters                       │
└─────────┬─────────────┬──────────────┘
          │             │
          ▼             ▼
┌─────────────────┐ ┌─────────────────┐
│ Worker T001     │ │ Worker T002     │
│ Codex           │ │ Claude Code     │
│ Worktree T001   │ │ Worktree T002   │
└─────────────────┘ └─────────────────┘
```

整體系統分為四層：

```text
Manager Skill
      ↓
Manager Runtime
      ↓
Agent Adapter
      ↓
Codex / Claude Code
```

---

## 5. Design Principle: Thin Skill, Deterministic Runtime

Manager Skill 不應該是一個巨大的 Prompt。

應採用：

> **Thin Skill + Deterministic Runtime**

Skill 負責：

- Manager role
- delegation policy
- supervision policy
- escalation policy
- verification policy

Runtime 負責：

- tmux
- process lifecycle
- task state
- filesystem state
- Worker messaging
- worktree
- events
- recovery

換句話說：

```text
SKILL.md
=
Policy / Behavior

manager CLI
=
Mechanism / Execution
```

Manager 不需要知道 tmux 的實作細節。

Manager 只需要使用穩定 API：

```bash
manager spawn
manager send
manager status
manager peek
manager stop
manager reconcile
```

---

## 6. Package Structure

建議 Skill 結構：

```text
manager/
├── SKILL.md
├── scripts/
│   ├── manager
│   ├── spawn-worker.sh
│   ├── send-worker.sh
│   ├── peek-worker.sh
│   ├── kill-worker.sh
│   ├── status.sh
│   └── lib/
│       ├── adapter.sh
│       ├── codex.sh
│       └── claude.sh
├── references/
│   ├── manager-protocol.md
│   ├── worker-protocol.md
│   └── escalation-policy.md
└── templates/
    └── task.md
```

其中：

- `SKILL.md`：定義 Manager 行為。
- `scripts/manager`：唯一公開 runtime interface。
- `scripts/lib/*`：實作 Agent-specific adapter。
- `references/*`：定義 Manager、Worker、Escalation protocol。
- `templates/*`：建立 Worker task prompt。

---

## 7. Project Runtime Directory

Manager 第一次在專案執行時建立：

```text
.manager/
├── state.json
├── events/
├── inbox/
├── tasks/
│   ├── T001/
│   │   ├── brief.md
│   │   ├── status.json
│   │   ├── result.md
│   │   └── log.txt
│   └── T002/
│       ├── brief.md
│       ├── status.json
│       ├── result.md
│       └── log.txt
└── worktrees/
    ├── T001/
    └── T002/
```

`.manager/` 預設加入 `.gitignore`。

Runtime state 不依賴 LLM conversation context。

---

## 8. Manager Configuration

專案可以提供：

```yaml
# .manager.yml

manager:
  max_workers: 4

agents:
  default: auto
  research: claude
  implementation: codex

git:
  isolation: worktree
  auto_commit: true
  auto_merge: false
  auto_push: false

verification:
  test: pnpm test
  typecheck: pnpm typecheck
  lint: pnpm lint

escalation:
  product_decisions: ask
  architecture: recommend_then_ask
  destructive_actions: always_ask
```

若沒有 `.manager.yml`，使用安全預設值。

---

## 9. Manager Responsibilities

Manager 是唯一負責最終 outcome 的 Agent。

Manager 的責任：

1. 理解使用者真正想達成的結果
2. 分析 repository
3. 找出既有 architecture / convention
4. 建立 execution plan
5. 建立 Task DAG
6. 指派 Worker
7. 監督 Worker
8. 回答 Worker 技術問題
9. Review Worker output
10. 要求 Worker 修正
11. 執行 independent verification
12. 整合各 Worker 結果
13. 必要時詢問使用者
14. 最終向使用者回報

Manager 不只是 scheduler。

Manager 是：

> **Owner of the outcome.**

---

## 10. Worker Responsibilities

Worker 是受 Manager 管理的執行 Agent。

Worker：

- 不直接對 User 負責
- 不應直接向 User 提問
- 不自行擴張 scope
- 不自行決定重大產品需求
- 必須回報 machine-readable status
- 必須提供 verification evidence

Worker 收到的 task brief 至少包含：

```text
Task ID
Objective
Context
Scope
Constraints
Acceptance Criteria
Allowed Files / Area
Dependencies
Expected Output
Verification Requirements
```

---

## 11. Worker Communication Protocol

Worker 不應依賴自然語言 terminal output 表示狀態。

不能讓 Manager 透過 `tmux capture-pane` 加 `grep "done"` 判斷任務是否完成。

Worker 必須更新：

```text
.manager/tasks/T001/status.json
```

---

## 12. Task State Machine

標準狀態：

```text
queued
  ↓
working
  ↓
needs_manager
  ↓
working
  ↓
verification
  ↓
done
```

完整集合：

```text
queued
working
needs_manager
needs_user
verification
done
failed
cancelled
```

---

## 13. Status Schema

工作中：

```json
{
  "task_id": "T001",
  "state": "working",
  "summary": "Implementing login validation",
  "question": null,
  "updated_at": "2026-10-07T10:00:00Z"
}
```

Worker 有問題：

```json
{
  "task_id": "T001",
  "state": "needs_manager",
  "summary": "Implementation blocked on empty-state behavior.",
  "question": {
    "type": "product",
    "text": "Should an empty search show recommendations or nothing?",
    "options": [
      "show_recommendations",
      "show_nothing"
    ]
  }
}
```

完成：

```json
{
  "task_id": "T001",
  "state": "done",
  "summary": "Implemented client and server validation.",
  "files_changed": [
    "src/login.ts",
    "src/login.test.ts"
  ],
  "tests": {
    "command": "pnpm test",
    "result": "passed"
  }
}
```

---

## 14. Manager vs Worker Questions

Worker 遇到問題時不能直接找 User。

```text
Worker question
      ↓
Manager
      ↓
Can Manager resolve it?
   │
 ┌─┴───────────────┐
 │                 │
YES                NO
 │                 │
 ▼                 ▼
answer Worker   Does it require
                user judgment?
                    │
                  YES
                    │
                    ▼
                   User
```

Manager 應先搜尋 source code、tests、README、specifications、architecture docs 與 previous implementation。

只有 repository 無法回答，而且不同選擇會影響產品行為時，Manager 才詢問 User。

---

## 15. Escalation Policy

Manager 的重要職責之一是：

> **Protect user attention.**

### AUTO

Manager 可以自行：

- 讀取檔案
- 搜尋程式碼
- 執行測試
- 修改 isolated worktree
- 在需求 scope 內 refactor
- 建立 commits
- retry Worker
- 回答 Worker 技術問題
- 啟動 research Worker
- 啟動 verification Worker

### ASK USER

以下情況應詢問 User：

- scope change
- product decision
- architecture decision with significant trade-off
- destructive migration
- external side effect
- credentials / secrets
- spending money
- production deployment
- irreversible operation
- repository policy 要求 approval 的 merge / push

### NEVER

Manager 不得：

- 不必要地將 secrets 傳給 Worker
- 刪除無關的使用者工作
- 未經允許 force push
- bypass safety boundary
- 把 Worker management 丟回給 User

---

## 16. User Notification Types

Manager 主動向 User 發訊息原則上只有四種類型：

1. **DECISION REQUIRED**：需要 User 做產品、scope 或重大技術決策，Manager 應附上選項與 recommendation。
2. **BLOCKED**：缺少只有 User 能提供的 credential、permission、external information 或 business context。
3. **COMPLETED**：需求完成且 Manager 已獨立驗證，回報完成內容、重要修改、verification 與 remaining caveats。
4. **FAILED**：只有在 reasonable autonomous recovery exhausted 後才回報，說明 failure reason、已嘗試的方法、blocker 與建議下一步。

---

## 17. Task DAG

Manager 不應只是建立 Todo List，而應建立 dependency-aware Task DAG。

例如：

```text
T001 Investigate auth architecture
          │
          ▼
T002 Implement backend
          │
     ┌────┴─────┐
     ▼          ▼
T003 UI      T004 Tests
     │          │
     └────┬─────┘
          ▼
     T005 Integration
```

Runtime 可以透過 DAG 找出 runnable tasks 並自動 spawn。

---

## 18. tmux Runtime

每個 Worker 使用獨立 tmux window / pane。

```text
manager-project
│
├── manager
├── mgr-T001
├── mgr-T002
└── mgr-T003
```

Worker process 可以是：

```text
mgr-T001 → codex
mgr-T002 → claude
mgr-T003 → codex
```

Manager 不直接操作 `tmux send-keys`，而是：

```bash
manager send T001 "Please cover the empty state."
```

由 Runtime 負責轉換成 tmux 操作。

---

## 19. Manager Runtime API

第一版 API：

```bash
manager init

manager spawn \
  --id T001 \
  --title "Implement login validation" \
  --agent auto \
  --brief .manager/tasks/T001/brief.md

manager send T001 "Please cover the empty state."

manager peek T001

manager status

manager stop T001

manager reconcile
```

未來可加入：

```bash
manager retry T001
manager verify T001
manager merge T001
manager events
manager graph
```

---

## 20. Agent Adapter

Runtime 提供統一 Agent abstraction：

```text
              Manager Runtime
                    │
             Agent Adapter API
                    │
          ┌─────────┴─────────┐
          ▼                   ▼
     CodexAdapter        ClaudeAdapter
          │                   │
          ▼                   ▼
        codex               claude
```

Manager Skill 完全不知道底層使用哪一個 Agent。

---

## 21. Agent Detection

`auto` mode 可以：

```bash
if command -v codex >/dev/null; then
    agent="codex"
elif command -v claude >/dev/null; then
    agent="claude"
else
    exit 1
fi
```

之後可以根據 task type routing：

```yaml
agents:
  research: claude
  implementation: codex
  review: claude
```

Manager 與 Worker 可以自由混用 Codex / Claude Code。

---

## 22. Persistent Worker Sessions

第一版建議 Worker 採用 persistent interactive session，而不是每次 message 都重新啟動 `codex exec` 或 `claude -p`。

原因是 Manager 的需求包含與 Worker 多輪互動。

```text
Manager
   │
   ▼
Worker T001
   │
   ├── implement
   │
Manager review
   │
   ├── "missing empty state"
   ▼
Worker continues
   │
Manager review
   │
   └── accepted
```

Persistent tmux session 可以自然保留 Worker context。

---

## 23. Git Worktree Isolation

不同 implementation Worker 不應直接修改同一 working tree。

每個 Task 建立獨立 worktree：

```text
.manager/worktrees/
├── T001/
├── T002/
└── T003/
```

例如：

```bash
git worktree add \
  ".manager/worktrees/T002" \
  -b "manager/T002"
```

完成流程：

```text
Worker implementation
        ↓
Worker commit
        ↓
Manager review
        ↓
Manager verification
        ↓
merge / cherry-pick
        ↓
remove worktree
```

---

## 24. Verification

Worker 宣稱 `done` 後，Manager 必須轉為 `verification`。

Manager 應自行：

```text
inspect diff
run tests
run typecheck
run lint
inspect acceptance criteria
```

只有成功後才能轉成 `done`。

如果失敗：

```text
verification
      ↓
worker correction
      ↓
verification
```

> **Worker completion is evidence, not truth.**

---

## 25. Recovery

Manager Runtime 必須支援：

```bash
manager reconcile
```

它應：

1. 讀 `.manager/state.json`
2. 找出現有 tmux sessions
3. 找出 worktrees
4. 讀取 task status
5. 找出 orphan workers
6. 找出 stale tasks
7. 修復 runtime state
8. 告知 Manager 目前有哪些 active / blocked tasks

Manager 可以自行 resume、answer 或 restart，而不需要 User 重新描述需求。

---

## 26. Event-Driven Supervision

MVP 可以先 polling，但長期應改成 event-driven。

Worker state change 時建立：

```text
.manager/events/T001-0004.json
```

例如：

```json
{
  "type": "worker.needs_manager",
  "task_id": "T001"
}
```

Runtime：

```text
Worker
  │
  ▼
Event
  │
  ▼
Watcher
  │
  ▼
Wake Manager
```

目的：

- 減少 polling
- 減少 token consumption
- 降低 latency
- 支援大量 Worker

---

## 27. Manager Skill Core Instruction

`SKILL.md` 的核心應保持簡潔：

```text
You are the user's sole project interface.

You own the requested outcome.

Understand the request.
Inspect the repository.
Plan the work.
Delegate appropriate tasks.
Supervise workers.
Answer worker questions when possible.
Review their work.
Request corrections when needed.
Independently verify completion.

Do not make the user manage workers.

Escalate only when:
- user judgment is genuinely required
- required information or permission is unavailable
- an irreversible/high-risk action requires approval
- the requested outcome has been verified
- autonomous recovery has been exhausted

Worker "done" does not mean task "done".
You must independently verify the result.
```

Skill 描述 policy；Runtime 實作 mechanism。

---

## 28. Example Execution

User：

```text
幫我把 login page 改成支援 Google OAuth，
要有 loading/error state 和 tests。
```

Manager 建立：

```text
T001 Research existing auth flow
T002 Implement OAuth integration
T003 Implement UI states
T004 Add tests
T005 Integration verification
```

Manager 依 DAG 執行並平行處理可獨立工作。

若 Worker 問：

```text
Should OAuth errors use toast or inline error?
```

Manager 先搜尋既有 UI convention。若發現其他 form 使用 inline error，Manager 直接回答 Worker，User 完全不被打擾。

最後完成 integration verification：

```text
pnpm test
pnpm typecheck
pnpm lint
Manager inspect diff
```

全部成功後才向 User 回報完成。

---

## 29. Security Model

Worker 預設遵守 least privilege。

Manager 應依 Task 判斷 required capability，只提供 minimum required access。

特別需要保護：

- API keys
- cloud credentials
- production credentials
- signing keys
- package publishing tokens
- SSH credentials

Research Worker 通常不需要任何 credential。

---

## 30. Concurrency

預設：

```yaml
manager:
  max_workers: 4
```

Manager 應考量 dependency、file overlap、token / compute cost、task size 與 integration complexity。

原則：

```text
independent + meaningful workload
           ↓
         parallel
```

而不是所有事情都 spawn agent。

---

## 31. MVP Scope

第一版只需要完成六個核心能力：

```text
spawn
send
status
verify
escalate
recover
```

MVP components：

```text
1 × SKILL.md
1 × manager CLI
2 × adapters
    ├── Codex
    └── Claude Code
3 × protocols
    ├── manager
    ├── worker
    └── escalation
filesystem state
tmux workers
git worktree isolation
```

---

## 32. Phase 2

MVP 穩定後加入：

- DAG Scheduler
- Event Watcher
- Automatic Verification
- Agent Routing
- Retry Policy

Automatic Verification 可根據 `package.json`、`Cargo.toml`、`go.mod`、`pyproject.toml`、`Makefile` 等推導 test、lint、typecheck、build。

Retry Policy 可採：

```text
attempt 1
   ↓
same Worker correction

attempt 2
   ↓
restart Worker with diagnosis

attempt 3
   ↓
different Agent

still failed
   ↓
Manager diagnosis
   ↓
User escalation
```

---

## 33. Phase 3

進一步可以加入：

- Worker Specialization
- Dynamic Planning
- Cost / Token Budget
- Project Knowledge

Worker specialization：

```text
researcher
implementer
reviewer
tester
security-reviewer
```

Project Knowledge 可維護於：

```text
.manager/knowledge/
```

記錄 architecture、conventions、discovered commands 與 recurring pitfalls。

---

## 34. Key Invariants

系統應始終維持：

1. **User never manages Workers.**
2. **Manager owns the outcome.**
3. **Worker done ≠ Task done.**
4. **Important state must survive context loss.**
5. **Parallel Workers must be isolated.**
6. **Provider-specific behavior stays behind adapters.**
7. **User attention is a scarce resource.**
8. **Manager resolves questions autonomously whenever repository context provides a safe answer.**
9. **Irreversible or high-impact decisions require appropriate approval.**

---

## 35. Success Criteria

Manager Skill 成功的標準不是：

> 能開很多 Agent。

而是：

> 使用者可以交付一個需求，之後不需要管理任何 Agent。

理想 UX：

```text
User:
做 X。

Manager:
開始處理。
```

中間只有真的需要決策時才詢問 User。

最後：

```text
Manager:
完成。

完成內容：
...

驗證：
...
```

責任模型：

```text
User
 │
 │ intent / decisions
 ▼
Manager
 │
 │ orchestration
 ▼
Workers
```

User 負責 **Intent + Decisions**。

Manager 負責 **Planning + Coordination + Quality**。

Workers 負責 **Execution**。

---

## 36. Final Architecture

```text
                     USER
                      │
              requirements /
                decisions
                      │
                      ▼
             ┌────────────────┐
             │    MANAGER     │
             │                │
             │ Plan           │
             │ Delegate       │
             │ Supervise      │
             │ Review         │
             │ Verify         │
             │ Escalate       │
             └───────┬────────┘
                     │
              Manager Runtime
                     │
        ┌────────────┼────────────┐
        │            │            │
        ▼            ▼            ▼
      State         tmux          Git
        │            │         Worktrees
        │            │            │
        └──────┬─────┴─────┬──────┘
               │           │
               ▼           ▼
          ┌─────────┐  ┌─────────┐
          │  Codex  │  │ Claude  │
          │ Worker  │  │ Worker  │
          └─────────┘  └─────────┘
```

最終產品應讓 Codex 或 Claude Code 在載入 Manager Skill 後，從 **Coding Agent** 轉變為 **Autonomous Engineering Manager**。

這三層責任邊界是整個 Manager Skill 最重要的設計基礎。
