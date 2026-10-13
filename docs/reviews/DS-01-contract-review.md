# DS-01 — DAG Scheduler 契約檢查

- 日期：2026-10-13。
- 範圍：基線 `50e8581` 的 source inspection、設計 walkthrough、reviewer核對與文件驗證；另用暫存 Git fixture檢查 ref pin機制，不是 scheduler runtime／provider驗收。
- 結果：初版 Ready 標記過早；reviewer 指出缺口後重新核對並修訂 [SPEC-002](../specs/002-dag-scheduler.md)，現為 Ready。[ADR-0007](../adr/0007-task-base-proof-and-launch-gates.md) Accepted，取代 ADR-0006；DS-01 文件完成，P2-01 runtime 尚未完成。

## 實作對照

| 現有程式／測試 | 觀察與契約影響 |
| --- | --- |
| `scripts/manager` 的 `register` | 依賴須已存在，base 即時解析，attempt 0／queued；採分階段註冊，不引入 task-edit |
| `load` | 現有 dependency metadata 檢查不是完整 cycle gate，也不要求 created_at；新 scheduler 檢查 cycle，timestamp 單項分類 |
| `launch`／`source_snapshot` | 已有 acceptance 指紋、live pane capacity，但 durable starting state 晚於 worktree／assignment；新契約將 intent 前移並分三層 gate |
| `reconcile` | Worker done 映為 verification，alive panes 與持久 state 分開；排程不能用 completion claim 自動解鎖 |
| `integration_status`／`combined_snapshot` | Delivery eligibility 綁目前 candidate／target 且拒絕 running operation；新 bind／launch 都獨立讀歷史 successful hash index與 current sources，保留 delivery gate |
| `main` 的 management lock flow | 現行 spawn 逐一 try-lock 全部 task，busy_tasks 供全圖 reconcile跳過；新 scheduler 每 candidate沿用並及時釋放，不取 integration operation lock |
| `tests/test_manager.py` 的 dependency／committed-base 測試 | 現行手動 spawn 可以在 dependency accepted 後沿用相同舊 base；scheduler 必須另要求明確成果證據，舊 API 行為維持 |
| 現有 dirty source／integration dependent-base／migration composition 測試 | 提供 DS-02／DS-04 fixture 模型，不能冒稱已驗證新 scheduler |

## Walkthrough

以下為逐項設計推演，不是執行測試結果。

| 情境 | 定案結果 |
| --- | --- |
| Root tasks A、B 可平行，C 依賴 A | A／B 符合 gate 可按排序啟動；C 需 accepted A 與匹配 base proof |
| A report done，tests 尚未 Manager accept | C blocked，不自動 accept |
| A accepted，但 C 在舊 HEAD 預先註冊 | 不自動換 base；bind mismatch，新 ID 從 verified candidate 註冊 |
| A 有 reviewed dirty code／untracked artifact | Manager 刻意整合 commit，combined review/checks 後 bind，不能只查 ancestry |
| C 依賴 A、B，proof 只有 A | Bind 拒絕缺來源；匯合任務不得只取一個 predecessor |
| Bind 後 source／review／record 被改 | Launch ineligible，保留歷史，不重算 hash 恢復資格；同 base可明確 rebind成功新 proof |
| Bind 前／後 integration branch／target 前進 | 同一歷史 task-base gate允許 bind／launch；原 delivery evidence 照常失效 |
| Capacity 1，兩 run 或 run/spawn 同時競爭 | 最後 registry gate 重新盤點；最多啟動一個，不使用舊預覽 reservation |
| Busy source verify 與獨立 root task | 依賴分支 skip，獨立 task 可前進；不等待長 checks 或刪鎖 |
| 現行 worktree 建好但 starting intent 未保存就中斷 | 舊殘留仍需診斷；新 launch在 worktree add之前保存 intent，不自動重用／重啟 |
| Intent 已保存，pane 結果尚未保存就中斷 | Reconcile 核對 identity；沒有 pane 不代表可再次 spawn |
| 前一個 task 成功後 takeover／provider error | 保留成功 Worker，停止後續 launch；partial／fenced 結果，不 rollback |
| Live orphan、done pane、等待問答 pane | 都佔 manager 額度，其他 manager 獨立 |
| Registry cycle 或破壞 namespace | 整次排程零 launch，保留資料 |

## Reviewer 核對與修訂

以下為現行 source核對與新契約決定，不是新 runtime行為測試。

| 點 | 判斷與現行證據 | 採取的修訂 |
| --- | --- | --- |
| 1 | 成立：integration_status（1440–1478）對照目前 candidate／target且拒絕 running；首次 bind的 gate比 launch嚴，限制歷史 proof的使用。不構成唯一無法恢復的死鎖，刻意恢復／重新驗證／重新規劃仍是選項 | Bind／launch使用同一 task-base proof，當前 tree／target與 running operation不決定歷史 proof資格 |
| 2 | 成立：launch（782–785）沿用有效現有 tree；assignment/status（797–798）先於 registry save（820）。Reconcile可使 attempt 0／next-report不符的 task failed；retry（1001–1024）是需 owner明確呼叫的既有恢復，不是自動 scheduler重啟 | 三層 gate、完整 artifacts、診斷優先於 not_queued；共用 intent早於 launch副作用，保留手動有效 tree相容性 |
| 3 | 成立：launch（757）全圖 reconcile；main（1995–2024）先對全 tasks try-lock／busy標記，新 spec原所需鎖範圍不足 | 每 candidate沿用全部 tasks nonblocking取鎖；reconcile不寫未持鎖 task |
| 4 | 成立，屬待實作契約的潛在阻塞：integration verify（1346–1400）只在 registry鎖內更新 metadata，長 checks在鎖外；integration operation lock由 main（1967）持有。歷史 verifications index仍保留 | Bind／launch在 registry讀 index，不取 integration operation lock；AC-08分別測長 task verify與長 combined verify |
| 5 | 合理的設計改進，不是現行 runtime錯誤 | 未開始且同 base／定義允許 expected-binding替換新 proof；完整舊歷史與 CAS衝突測試 |
| 6 | 成立：JSON中的 OID不是 Git可達性 ref，integration改寫後 candidate可能不再可達；實際 GC是否發生取決於其他 refs／reflog與保留時間，不是立即必然消失 | 固定 direct runtime pin、durable bind intent、expected-missing建立、錯／缺／symbolic pin gate及 GC驗收 |
| 7 | 成立：load required（308–310）沒有 created_at，migration task轉換保留原欄位，不保證它存在 | 缺／壞／無時區 timestamp單項 ineligible，UTC排序，不阻止獨立分支；AC-11新增 migrated missing timestamp |
| 8 | 成立：初版 RUN_ID混指 proof與 scheduler journal | 分別 VERIFICATION_ID／SCHEDULE_RUN_ID，另有 BINDING_ID／LAUNCH_ID |
| 9 | 成立：初版缺 reason映射／precedence，容量欄位說法不精確，outcome細節未定 | 定義 classification與 primary_reason；容量在 manager及task皆列；完整 outcome／exit code表 |
| 10 | 成立：初版未說明 binding generation用途；不應使既有 proof隨 owner到期 | Generation只稽核，takeover後新 owner沿用有效 binding；AC-10驗收 |
| 11 | 成立：舊 v2 load忽略新可選欄位，不認得 binding gate | 明列無法強制攔截舊 binary的風險，停止舊 writer只是營運前提 |
| 12 | 成立：source_snapshot（1322–1325）／fingerprint（1026起）讀 accepted worktree | 全部直接及額外 proof sources保留至下游 launch完成，retry／integration仍需要時繼續保留；本版無 cleanup |

Reviewer確認的現行 acceptance／capacity／先前註冊依賴／無 cycle gate描述均正確。`run`（57–59）設定 GIT_OPTIONAL_LOCKS=0，有助純讀 Git檢查避免 optional index refresh；不代表忽略其他讀取一致性競態。本文件原始 walkthrough仍為 14項，以上12項核對另列，不計作 runtime測試數。

## 驗證與接續

文件驗證結果見 [progress](../progress.md) 本次紀錄。目標 CLI 尚未加入現行 parser，因此只檢查新 spec 的連結／fences；現行 67 個 CLI examples 繼續由 maintained validator 檢查。

固定 ref的 Git primitive probe 證據已收進 repo：[首次結果](ds01-pin-probe/result.json) 記錄 Git 2.55.0與5項 assertions：expected-missing建立、同 OID既有 ref碰撞拒絕、integration ref改寫不動 pin、reflog expire／GC後 candidate可達、symbolic ref可檢出。首次執行的 inline script 沒有保存；[重建的可重跑 probe](../../tests/probe_ds01_pin.py) 使用相同 check 名稱，另加「未 pin 的 candidate 被 GC 清除」對照組，證明 GC 確實執行，[重跑結果](ds01-pin-probe/rerun-result.json) 6 項全部通過。重跑：`python3 -B tests/probe_ds01_pin.py`。只支持 pin設計的底層機制，不等於新 binding／launch故障恢復或 AC-06已通過。

第二輪 review 補了四項契約：launch intent stage 與結束狀態、retry 準備步驟納入 intent 且 history create-only、共用 gate 檢查 pending bind intent（`bind_needs_resume`）、帶 expect-binding 的同 proof 重播規則；見 SPEC-002 §5.1、§6.1、§6.2，以及 AC-05、AC-09。

DS-02 接續 binding／pin／rebind、歷史 proof重查與共用 launch intent／三層 gate；DS-03 接 scheduler status/run／journal／recovery；DS-04 逐項驗收 AC-01–AC-12，更新 runtime使用文件。既有完整回歸與真實 provider結果保持歷史基線，本輪沒有重新執行或延伸其能力宣稱。
