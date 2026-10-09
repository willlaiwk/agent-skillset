# MM-01 — 契約收斂檢查

- 日期：2026-10-09。
- 範圍：[SPEC-001](../specs/001-multi-manager-isolation.md) Q-01–Q-04；[ADR-0002](../adr/0002-manager-identity.md)／[ADR-0003](../adr/0003-isolated-integration.md)／[ADR-0004](../adr/0004-runtime-migration.md)。
- 結論：阻擋實作的契約已有 API、前置條件、失敗／恢復行為，可進入 MM-02；不是 v2 runtime 驗收。
- 基線：已讀 `skills/manager/scripts/manager` 的 init/load、launch/report、reconcile、verify/accept 與 main，以及現行 skill/protocol/reference。V1 使用 version 1、單 root namespace；status/peek 會 reconcile 寫入；verify 全程持 registry lock，report 使用 task report lock；accept 只接受隔離成果。

## 1. 契約 walkthrough（文件推演，未執行 v2 CLI）

| 情境 | 具體步驟 | 預期結果與對應契約 |
| --- | --- | --- |
| 兩 Session 同 ID | init alpha，owner released/gen 0；A、B 同時 claim；A 成功為 gen 1；B status 後試 send | registry 鎖序列化，只有一個 claim；B 可純查閱但無 token 不可 send。§3、§6.1；MM-02/MM-03 後續行為測試 |
| Compaction／失聯交接 | A 沿用 gen 1 credential；時間過期仍 active；B 明確 takeover expect 1 → gen 2；A send／release | Compaction 不需另 claim；不能依時間自動接管；舊 token 被拒絕。另一 takeover expect 1 也拒絕，不能接管新主控。§6.1 |
| 長 verify 與 report／交接 | A 以 gen 1 預留 T001 operation，放開 registry/report 鎖跑 checks；Worker report 更新；B takeover → gen 2；A checks exit 0 收尾 | Worker report 可寫；B 可管理其他 task，T001 管理寫入回 busy；A 重新核對 owner/snapshot，保存 fenced 診斷但不提交成功 verification，不能寫回舊整份 state。§6.2–6.3 |
| 完成 verification 後交接 | A verify 已提交成功；B takeover；B accept 前核對 unchanged report/result/review/tree | 已完成且未改動的 evidence 可用，不因 Session 改變要求無意義重跑；任何 snapshot 改變仍拒絕。與「舊長操作正在收尾」明確區分。§6.2 |
| 兩 manager 舊 target 競爭 | A/B 都 verify target X；A candidate XA 交付成功；B 拿 common gate，仍提供以 X 為基礎的 evidence | B 拒絕 stale target；釋放鎖後整合 XA、重新 verify，才可再交付。長 checks 不占 common gate。§7.2 |
| 外部 ref／checked-out target | final checks 後，外部 direct target OID 改變；或 inventory 顯示主 checkout／linked worktree 持有 target | expected old transaction 拒絕 OID 競爭；任何已 checkout target 預檢拒絕。External checkout／ref 類型切換需要合作維護區間，不宣稱 Git CAS 強制阻止。§7.2 |
| 交付收據前中斷 | durable intent 已寫，Git transaction 成功，但 JSON result 未寫；target 後又前進 | 同 transaction 的 receipt ref 證明已提交，可補記收據而不倒退 target；receipt 缺失／不符且 target 不再為 old 時 ambiguous，不憑 target==candidate 判定成功。§7.2 |
| Dirty legacy worktree | v1 T001 有 staged＋unstaged、untracked、ignored cache、已接受歷史；停止 writer，再 preview/hash/assertion | 完整 backup/index/object 保存；新 ref 指向原 HEAD，move＋switch 不重設內容；舊 ref 保留；accepted_history 可追溯但 eligibility=reverify_required，依賴 blocked。§8.1–8.3 |
| Legacy done 但 pane live | Worker report done，tmux pane/provider 仍活；或 Manager 無法確認舊 Session 停止 | migration 不自動 kill／不把 done 當退出；列出 blocker，先刻意退出／停止後重新 dry-run。Assertion 也不能略過 observed live blocker。§8.1 |
| Migration 半途／未知目的內容 | 一個 worktree 已 move，journal 尚未完成；resume 看見 new registration 且 snapshot 相符；另一 run 看見目的被外部修改 | 前者依 per-step intent 補記；後者停為 ambiguous，保留兩側/backup，不覆寫。Tombstone/完成標記之間中斷仍依 journal 恢復。§8.2 |
| Completed migration 重跑 | v2 owner 已 claim／task 有新 report；再次 migrate 同 root/目的 ID | 查證 completed journal/tombstone，回 no-op，不以舊 hash 覆蓋新 state，不重新清空資格。§8.2 |
| Legacy attempt 回報 | v1 attempt 1 搬成 snapshot/reporting disabled；舊 CLI 或舊 worker 再 report；v2 retry 建 attempt 2/new assignment | 無 selector／舊路由／disabled assignment 一律拒絕；新 report/ack 綁完整 launch identity，不把歷史 ack 當新收訊證據。§5、§8.3 |

## 2. 暫存 Git 實驗（已執行）

平台：macOS／POSIX；Python 3.9.6；Git 2.55.0。只在 Python TemporaryDirectory 的獨立 repository／linked worktrees 執行，不呼叫 provider、tmux 或 manager CLI，也不遷移真實專案。

可重跑：[mm01_git_primitives.py](mm01_git_primitives.py)；當次結果：[mm01-git-results.json](mm01-git-results.json)。從 repository root 執行：

```sh
python3 docs/manager-skill-design/reviews/mm01_git_primitives.py
```

八項 assertions 通過：

1. 同一 ref transaction 檢查 candidate、expected target 並建立 receipt。
2. 過期 old OID 使整個 transaction 失敗，receipt 不建立。
3. prepare 後未 commit、結束 stdin 時不更新 target/receipt。
4. Receipt 在 target 後續更新後仍保留。
5. Porcelain inventory 可辨識已 checkout target。
6. Linked worktree roots 解析至同 canonical common directory。
7. Dirty/staged/untracked/ignored/symlink 在 worktree move＋切至同 HEAD 新 branch 後保留。
8. 舊 branch 原值保留，新 branch checkout 與 registration 正確。

另外一項邊界探測發現：`update-ref --no-deref ... new old` 能將指向相同 old OID 的 symbolic ref 改成 direct ref（returncode 0）。因此 expected OID 不能當成 ref 類型不變的證明；已將外部類型切換與 checkout race 寫成 workflow 合作邊界，不誇稱原子保障。

機制依據：[Git update-ref](https://git-scm.com/docs/git-update-ref)、[Git worktree](https://git-scm.com/docs/git-worktree)。實驗是本機 Git primitive 證據，未測 manager 的 locking、journal、fencing 或 migration 實作。

## 3. 後續驗證責任

- MM-02：selector/schema／branch/tmux／launch identity／零寫入查閱／legacy 診斷。
- MM-03：claim 競爭、generation fencing、credential 發出中斷、長操作 report／收尾與例外釋鎖。
- MM-04/MM-05：source acceptance／combined snapshot、兩 root gate、stale target、checked-out/symbolic 拒絕、transaction receipt 與中斷故障注入。
- MM-06：完整 backup/object/index/ignored content、每階段 resume／ambiguous、tombstone、live writer 阻擋及歷史 gate 失效。
- MM-07/MM-08：整體 regression 與至少一個真實 provider smoke test。MVP-02 的原始真實 provider 缺口維持未驗證。

這些是待實作驗證責任；本輪沒有重跑 runtime 行為測試，也沒有驗收 AC-01–AC-14。
