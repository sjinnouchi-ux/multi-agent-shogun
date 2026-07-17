# Shogun運用の残留リスクと次フェーズ必須TODO

更新日: 2026-07-17

本書はntfy listener standby基盤とP0任務引き継ぎhardeningの実装・回帰確認時点で
未解消のリスクを引き継ぐ。秘密値、Inbox本文、認証情報は記載しない。

## P0で解消した項目

次のP0項目はdraft PRへ実装済みで、関連unit・integration・既存mock E2Eの回帰確認と
独立レビューを完了した。mainへ未マージの間は、各変更の導入可否をPR単位で判断する。

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

`clear_command` の配送時dropはP1であり、P0解消済みには含めない。

## 残留リスク

- CLI分類はterminal末尾のsanitized markerに基づく。判定不能時は `unknown` として
  fail-closedに送信を止めるため、未知のCLI表示変更は手動確認が必要になる。
- permission/login promptは自動承認せず、startup promptやinbox番号も送らない。
  P0では自動restartを行わないため、blocked状態の解消は利用者操作に依存する。
- deployment hostを必要とするBloom E2E 6件はSKIPであり、成功扱いにしていない。
  `make test-no-skip` も未実行である。
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

### 1.【高 / P1】`clear_command` のdefer→明示的drop修正

現在はbusy時など安全に配送できない `clear_command` がdeferされ、状態回復後に古い
commandが実行され得る。配送試行時点でready以外（busyを含む）なら後刻の再実行を
予定せず、fail-closedな明示的dropへ変更する。

修正方針:

- `delivery_blocked_reason` にsanitizedなdrop理由を記録する
- 送信元エージェントへ `watchdog_alert` を1回通知する
- 同一dropの無制限な重複alertを防ぎ、後から発行された新しいcommandは独立して扱う

### 2.【高】stale-busy 5分判定と正当な長考の分離

Claudeのidle flagが5分間更新されない場合、正当な長考中でも `/clear` 候補になる問題を
解消する。

修正方針:

- heartbeatまたはprogress timestampを導入する
- stale判定と長考を区別する
- stale判定の閾値を設定可能にする

### 3.【中】レート制限状態のwatcher接続

`scripts/ratelimit_check.sh` の結果を構造化してwatcherへ入力し、rate-limit silenceを
独立状態として扱う。reset時刻までは `/clear` を禁止する。

### 4.【中】状態別E2Eテスト追加

上記1〜3について、次の状態別E2Eテストを追加する。

- rate-limit
- long-thinking
- idle
- error

### 5.【低】UI/スマホフェーズ開始時の作業

- topicをローテーションする（B案: 旧backlog破棄）
- `docs/listener_standby.md` の手順に従ってlistenerを再開する
- 再開初回にjournal秘匿性とrestart挙動を実機確認する
- Windows起動時のWSL自動起動タスクを登録する（PowerShellスクリプトは別途指示）
- pending滞留の日次通知を実装する
- Drive Publisher失敗通知を実装する

## 変更管理

本書に記載した項目は引き継ぎ記録であり、このdocs PRでは機能変更を行わない。
P0解消項目の記載はPR #14〜#17へ依存する。残存項目は別タスク・別ブランチで実装し、
テストとレビューを経て反映する。
