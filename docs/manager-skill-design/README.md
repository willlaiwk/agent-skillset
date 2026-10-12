# Manager Skill — 規格、決策與開發入口

最後更新：2026-10-12。

這個目錄管理 manager skill 本身的設計與開發。使用 skill 管理產品專案時產生的 `.manager/` 是執行資料，兩者不共用任務狀態。

## 文件分工

| 文件 | 責任 | 更新時機 |
| --- | --- | --- |
| [design.md](design.md) | 整體目的、架構基線、核心原則與功能索引 | 整體架構或跨功能原則改變時 |
| [specs/](specs/001-multi-manager-isolation.md) | 每項功能的行為契約、範圍、驗收條件與未決問題 | 新功能或既有行為調整時 |
| [adr/](adr/0001-documentation-workflow.md) | 重要決策的背景、選項、理由與代價 | 做出或改變架構決策時 |
| [tasks.md](tasks.md) | 開發任務、依賴、狀態、完成條件與證據連結 | 任務拆解、開始、阻塞或驗收時 |
| [progress.md](progress.md) | 實作現況、驗證缺口與下一個 Session 的接續資訊 | 工作交接或實作狀態改變時 |
| [runtime reference](../../skills/manager/references/runtime.md) | 已發布 CLI 的實際使用方式與限制 | runtime 行為完成並驗證後 |

功能細節寫在一份 spec；`design.md` 保留架構摘要及連結。ADR 解釋「為什麼」，task 管理「接下來做什麼」，progress 記錄「現在做到哪裡」，避免四份文件複製同一套規則。

`design.md` 保留原始架構基線，包含尚未實作的願景。新增 spec 不代表功能已實作。判斷目前可用能力，先看 `progress.md` 與 runtime reference；判斷新功能目標行為，讀對應 spec 與 ADR。

## 功能與決策索引

| ID | 主題 | 狀態 | 相關任務／決策 |
| --- | --- | --- | --- |
| SPEC-001 | [多 manager 隔離、整合與舊格式遷移](specs/001-multi-manager-isolation.md) | Implemented；runtime／deterministic／真實 Codex／Claude 驗收完成 | MM-01–MM-08／MVP-02 Done |

| ID | 決策 | 狀態 |
| --- | --- | --- |
| ADR-0001 | [規格、ADR、任務與交接的文件分工](adr/0001-documentation-workflow.md) | Accepted；僅文件管理方式 |
| ADR-0002 | [以 manager ID 隔離執行資料與識別](adr/0002-manager-identity.md) | Accepted；namespace 與主控交接已實作 |
| ADR-0003 | [各 manager 獨立整合，共用交付入口](adr/0003-isolated-integration.md) | Accepted；獨立整合與共用本地交付已實作 |
| ADR-0004 | [遷移由 manager runtime 提供](adr/0004-runtime-migration.md) | Accepted；backup/journal、歷史資格失效及 forward resume 已實作 |

## 規格調整流程

1. 先讀現有 spec、ADR、task 與實作，辨識這次調整改變哪些行為及相容性。
2. 同一功能的修訂更新原 spec；新的獨立能力建立新 spec。ID 使用 `SPEC-001` 起依序遞增，已用 ID 不重複分配。
3. 影響資料格式、公開介面、恢復、隔離或授權邊界的選擇，建立 ADR；一般實作細節寫在 spec 或 task 即可。
4. spec 中列出需求、驗收條件、相容性與未決問題；更新 task 的依賴及受影響範圍。
5. 實作前收斂阻擋實作的未決問題。依使用者授權與 repository 政策決定即可，不額外引入逐份文件簽核流程。
6. 實作與驗證完成後更新 spec/task 狀態、runtime reference 和 progress。文件狀態不得先於實際證據宣稱完成。

Spec 狀態：`Draft → Ready → Implementing → Implemented`，取消或取代時使用 `Withdrawn`／`Superseded` 並連結替代文件。`Ready` 表示行為與驗收條件足以實作，仍不代表已授權部署、push 或其他外部操作。

## ADR 與任務的維護規則

ADR 使用 `Proposed`、`Accepted`、`Rejected`、`Superseded`。Accepted 表示採用設計，不表示 runtime 已實作。已接受的決策若要改變，建立新 ADR 並標記替代關係；不要改寫舊理由讓歷史消失。錯字、連結與實作結果的補充可直接修正並註明。

每份 ADR 至少記錄：日期／狀態、背景、決策、替代方案、代價、相關 spec/task。Spec 修訂記錄只列有意義的行為變更；完整 diff 由 Git 保存，不另外建立重複 changelog。

Task 狀態使用 `Todo`、`In progress`、`Blocked`、`Done`、`Cancelled`。每項 task 記錄目標、spec／ADR、依賴、完成條件、證據與接續資訊。拆出 task 詳細檔案僅在單項任務確實過大時進行，初期直接維護 `tasks.md`。

`progress.md` 保留實際驗證、已知限制與下一步摘要，連結 task，避免維護第二份 task board。完成需有結果與驗證證據；只有規劃、worker 宣稱完成或文件寫完，不代表 runtime 功能完成。

## 新 Session 的閱讀順序

1. 檢查 `git status --short` 與近期 commit，保留尚未提交的工作。
2. 讀 [progress.md](progress.md) 與 [tasks.md](tasks.md)，確認目前目標及最新使用者指示。
3. 只讀當前任務相關的 spec、ADR、`design.md` 章節與 skill/runtime 參考。
4. 接續後更新 task 與 progress；未跑的測試保持未驗證。

2026-10-12 完成 MM-08 真實 Codex report/ack/correction／獨立 acceptance／integration 隔離，證據及第二 provider 狀態見 [MM-08 validation](reviews/MM-08-validation.md)；原 MVP-02 共用證據結案，SPEC-001 Implemented。MM-07 的 [deterministic AC 對照](reviews/MM-07-validation.md) 與預設 107 項（106 通過、1 skip）／真實 tmux 107 項全通過，仍只對應假的 Worker。先前 migration／namespace／主控／整合／交付證據見 [MM-06](reviews/MM-06-validation.md)、[MM-02](reviews/MM-02-validation.md)、[MM-03](reviews/MM-03-validation.md)、[MM-04](reviews/MM-04-validation.md) 與 [MM-05](reviews/MM-05-validation.md)，設計定案見 [MM-01](reviews/MM-01-contract-review.md)。MM-07 提交 `c58cbf7` 已 push；MM-08 尚未 commit/push，Git status/log 為準。Phase 2 候選與接續見 [progress](progress.md)，啟動前另立 spec。
