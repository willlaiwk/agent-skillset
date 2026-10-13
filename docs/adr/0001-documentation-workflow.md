# ADR-0001 — 分開維護架構、功能規格、決策與任務

- 狀態：Accepted；僅採用本次文件管理方式，不代表接受其他 ADR 或完成 runtime。
- 日期：2026-10-08。
- 關聯：[文件入口](../README.md)、[任務清單](../tasks.md)。

## 背景

既有 `design.md` 是原始整體設計，含 MVP 與未實作願景；`progress.md` 同時承載實作現況、候選任務與交接。新增多 manager、整合與遷移後，如果所有內容都繼續塞進 design，容易混淆現在可用、目標行為與曾經討論的選項。

使用者要求先建立可持續維護 spec 調整、任務與 ADR 的文件方式，再開始實作。

## 決策

保留 design 作為架構基線及索引；功能契約放在 `specs/`；決策背景放在 `adr/`；開發任務集中 `tasks.md`；progress 專注現況與 Session 接續。目錄內 README 提供閱讀入口、狀態定義與調整流程。原有 runtime reference 繼續描述已實作介面。

初期不建立任務資料庫、逐項空白 task 檔案、獨立 changelog 或專用 documentation skill。以 Markdown 相對連結與 Git 追蹤即可。

## 替代方案

- 全部整併 design：入口少，但功能契約、歷史決策與待辦難以分辨。
- 每次討論另開一份無狀態文件：容易保留多份互相矛盾的規格。
- 立刻導入完整 RFC／PM 系統：成本超出目前單一 skill 的需要。

## 代價與後續

需要維護少量跨文件連結與狀態一致性。每份文件只有一種責任，progress 不複製 task board，ADR 不複製完整 spec。架構變動更新 design 摘要；功能細節仍只有 spec 一處。

決策變更以新 ADR 取代已接受 ADR；文件錯字可直接修正。這是維護約定，不增加使用者逐份核准文件的流程。
