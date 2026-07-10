# Shogun運用の残留リスクと次フェーズ必須TODO

更新日: 2026-07-10

本書はntfy listener standby基盤の完了時点で未解消のリスクと、エージェント本番起動
またはUI/スマホフェーズへ進む前に必要な作業を引き継ぐ。秘密値、Inbox本文、認証情報は
記載しない。

## 残留リスク

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

### 1.【高】`clear_command` のdefer→drop修正

special messageが取得時にread済み化され、busy時にdeferされた `clear_command` が
次周期に残らず、実質的にdropされる問題を解消する。

修正方針:

- 実送信成功後にreadへ更新する、または
- `deferred` 状態を導入して再試行可能にする

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
各項目は別タスク・別ブランチで実装し、テストとレビューを経て反映する。
