# Shogun運用の残留リスクと次フェーズ必須TODO

更新日: 2026-07-17

本書はntfy listener standby基盤とP0/P1-1任務引き継ぎhardeningの実装・回帰確認時点で
未解消のリスクを引き継ぐ。秘密値、Inbox本文、認証情報は記載しない。

## P0で解消した項目

次のP0項目はmainへ実装済みで、関連unit・integration・既存mock E2Eの回帰確認と
独立レビューを完了した。

- PR #14: Hookのcwd解決を `${CLAUDE_PROJECT_DIR:-.}` に統一し、裸の相対パスと
  `args` 使用をlintで検出する。oometsukeのPhase-3 `/clear` を抑止し、既存のkaro・
  gunshiと同じEscape+nudgeへフォールバックする。
- PR #15: `get_pane_cli_state` の7状態分類を追加し、blocked優先、positive marker優先、
  shell promptとshell processの両条件、test overrideの二重条件を実装する。
- PR #16: 起動・CLI切替時のreadiness確認を追加し、ready未達paneへstartup promptを
  送らず、CLI切替失敗時は設定をロールバックする。
- PR #17: inbox通知の集約入口へliveness guardを追加し、unsafe stateでは送信せず、
  `cli_state_at_notify` と `delivery_blocked_reason` だけを追加記録する。既存の
  busy/idle、idle flag、watcher throttle、self-watch、ack/receiptは維持する。

`clear_command` の配送時dropは次のP1-1項目であり、P0解消済みには含めない。

## P1-1で解消した項目

`clear_command` のbusy時defer表現と無通知dropを、配送試行時点の明示的dropへ変更した。

- CLI状態がready以外（busy、permission/login prompt、shell prompt、absent、unknownを
  含む）、既存busy判定がbusy、または必須キー送信が失敗した場合はread済みのterminal
  dropとし、後刻の再実行を予定しない。
- 対象messageの `cli_state_at_notify` と `delivery_blocked_reason` にsanitizedな状態・理由を
  記録する。
- 抽出時はlegacy/重複IDを一意なIDへ正規化するが、配送判断前のclearは未読のまま維持する。
  配送直前に60秒lease付きlocked claimを永続化し、複数watcherは稼働中claimを上書きしない。
  lease期限後の中断claimだけを `delivery_interrupted` のterminal dropとして回収するため、
  無通知消失や後刻の再送を行わない。
- `read: true` だけではclearをterminal扱いにしない。`clear_delivered_at` または明示的な
  `delivery_blocked_reason` がないclearは、readyならclaimして通常処理し、unsafeなら理由と
  alertを持つterminal dropへ確定する。
- 送信元エージェントへ本文やpane内容を含まない `watchdog_alert` を送る。alertは
  deterministicなsanitized refを使い、送信元Inboxの同一lock内で照合・appendするため、
  複数watcherから同時実行されても1件だけを生成する。
- alert書込みに失敗した場合はclear commandを再配送せず、pending alertだけを次周期で
  exponential backoff付きで最大3回再試行する。30秒leaseで同一dropの同時reserveを防ぎ、
  中断されたreserveはlease期限後に同じattemptとして回収する。恒久失敗時は `exhausted` を
  記録して停止する。
- drop metadataのInbox永続化に失敗した場合は、agent/message IDのSHA-256だけを持つ
  sanitized quarantine markerを先に永続化する。次周期にreadyへ変化しても古いclearは送らず、
  `state_persist_failed` のterminal drop記録を再試行する。
- alert後に発行された別IDの新しい `clear_command` は独立して扱い、readyなら通常配送する。

## 残留リスク

- CLI分類はterminal末尾のsanitized markerに基づく。判定不能時は `unknown` として
  fail-closedに送信を止めるため、未知のCLI表示変更は手動確認が必要になる。
- permission/login promptは自動承認せず、startup promptやinbox番号も送らない。
  P0では自動restartを行わないため、blocked状態の解消は利用者操作に依存する。
- deployment host受入ではPR-1a headの `make test-no-skip` が750件、P1最終stack headが
  847件、隔離tmuxとsanitized設定fixtureによるBloom E2Eが6件で、いずれもfail 0・
  skip 0だった。実運用設定・pane・queue・report・logは受入対象に含めていない。
- 送信元Inboxが恒久的に無効または書込み不能なclear drop alertは最大3回で
  `exhausted` となる。clear自体は再送しないため、sanitizedなterminal statusを確認して
  運用側で送信元経路を復旧する必要がある。
- `status/clear_drop_quarantine/` のmarkerはfail-closed証跡として自動削除しない。本文・送信元・
  message IDは保存せずhashだけだが、運用時は件数増加を永続化障害の兆候として確認する。
- 本番Shogunへの配置、切替、起動、停止、再起動は実施していない。P0の確認は隔離した
  clone/worktree、一時 `IDLE_FLAG_DIR`、sanitized fixtureだけで行った。
- P2のauto restartは対象外であり、未実装である。
- systemd実挙動は未検証。standby作業ではunitを意図的にstartしていないため、
  journalの秘匿性とrestart挙動は `docs/listener_standby.md` の再開初回チェックリストに
  従って実機確認する。
- watcher supervisorテストは `flock` をmock化している。実際の `flock` による排他制御の
  カバレッジはLinux実運用に依存する。
- 公開ntfy.shのキャッシュは約12時間である。`since` カーソルは短期の取りこぼし防止であり、
  長期休止中のメッセージを回収できる保証はない。
- topicローテーション時は旧backlogを破棄するB案を既定とする。

## 次フェーズ前の必須TODO

実タスクを投入する前に、次の優先度順で着手する。

### 1.【高】stale-busy 5分判定と正当な長考の分離

Claudeのidle flagが5分間更新されない場合、正当な長考中でも `/clear` 候補になる問題を
解消する。

修正方針:

- heartbeatまたはprogress timestampを導入する
- stale判定と長考を区別する
- stale判定の閾値を設定可能にする

### 2.【中】レート制限状態のwatcher接続

`scripts/ratelimit_check.sh` の結果を構造化してwatcherへ入力し、rate-limit silenceを
独立状態として扱う。reset時刻までは `/clear` を禁止する。

### 3.【中】状態別E2Eテスト追加

上記1〜2について、次の状態別E2Eテストを追加する。

- rate-limit
- long-thinking
- idle
- error

### 4.【低】UI/スマホフェーズ開始時の作業

- topicをローテーションする（B案: 旧backlog破棄）
- `docs/listener_standby.md` の手順に従ってlistenerを再開する
- 再開初回にjournal秘匿性とrestart挙動を実機確認する
- Windows起動時のWSL自動起動タスクを登録する（PowerShellスクリプトは別途指示）
- pending滞留の日次通知を実装する
- Drive Publisher失敗通知を実装する

## 変更管理

本書に記載した項目は引き継ぎ記録である。P0/P1-1解消項目は実装・テスト・レビューを
経てmainへ反映し、残存項目は別タスク・別ブランチで実装する。
