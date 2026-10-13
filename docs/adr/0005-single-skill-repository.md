# ADR-0005 — 單一 skill repository 與檔案分工

- 日期：2026-10-13
- 狀態：Accepted
- 任務：DOC-02

## 背景

原 repository 的定位是 agent-skillset，使用 `skills/<name>/` 收集多種 skill。Manager 現在有獨立 runtime、provider adapters、持久化狀態、遷移與驗收流程，且即將開始 Phase 2。使用者決定將 GitHub repository 改名為 `manager-skill`，讓它專門開發與發布 Manager。

## 決策

- 根目錄放置 `SKILL.md`、`agents/`、`scripts/`、`references/` 與 `templates/`，保持一份完整可安裝的 skill。Skill 名稱與 invocation 維持 `manager`。
- Runtime CLI 保持為 `scripts/manager`，helpers／adapters 保持在 `scripts/lib/`；本次只搬移，不改行為、狀態 schema 或 managed project 的 `.manager/{ID}/`。
- 行為測試、文件驗證、Git mechanism probe 與 opt-in real-provider fixture 集中到 `tests/`。安裝 payload 不需包含 tests 或設計文件。
- 設計、spec、ADR、task、progress 與驗收證據集中到 `docs/`。更新維護中的連結與命令；archived provider evidence 原文及 hashes 不變，保留其歷史絕對路徑。
- GitHub rename 由使用者處理；本輪不改 remote、本機 checkout 路徑或其他位置的已安裝 skill。

## 替代方案

保留 `skills/manager/` 可沿用集合型 repository 的目錄，但此 repo 已確定只維護一個 skill，額外層級不再提供分類用途。將 runtime 拆成另一個獨立發布的 package 會引入 skill／runtime 版本配對，本輪沒有這項需求。

## 代價與驗證

原 repository-relative 開發路徑需要更新；既有安裝仍需在選定版本下保留完整 runtime resources。歷史驗收記錄的絕對路徑不代表現行安裝位置。

以 skill validator、Markdown links／CLI example parser、完整行為回歸與只包含 runtime resources 的安裝副本驗證新結構。逐檔核對 runtime／adapters 與 archived evidence，避免把結構整理當成新的 provider 或 runtime 行為驗收。
