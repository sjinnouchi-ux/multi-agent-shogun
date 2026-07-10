# ntfy listener standby運用

現在のMVPでは外部投入経路を使わないため、listenerは停止状態を既定とする。
`config/settings.yaml` の `ntfy_listener.mode` は `disabled`、`systemd`、`legacy`
のいずれかで、未設定・不正値は `disabled` として扱う。`systemd` 指定時にunitが
停止していても旧方式へフォールバックしない。`systemctl` が存在しない環境で旧方式を
使う場合だけ、明示的に `legacy` を指定する。

## 再開・停止

再開前に次をすべて確認する。

- topicをローテーション済みであること
- 受信クライアントが準備済みであること
- inboxのpendingを処理する主体（UIまたはエージェント）が存在すること
- topicローテーション時は旧topicの未回収分を破棄するか、切替前に旧topicをdrainするかを決めること
- 再開初回はjournalを実機確認し、topic、token、password、メッセージ本文が出力されていないこと
- 再開初回はunitのrestart挙動を実機確認し、一時的な失敗で恒久的なfailed
  （start limit hit）にならないこと

再開手順:

```bash
loginctl enable-linger jinnouchi
systemctl --user enable --now shogun-ntfy-listener.service
```

再開初回の確認コマンド:

```bash
systemctl --user status shogun-ntfy-listener.service --no-pager
journalctl --user -u shogun-ntfy-listener.service --since "10 minutes ago" --no-pager
```

journalではtopic、token、password、メッセージ本文の実値が出力されていないことを確認する。
秘密値そのものを検索コマンドや報告書へ記載しない。unitに一時的な失敗が発生した場合は、
`systemctl --user status` で自動restartしていること、および `start-limit-hit` のまま
恒久的なfailedになっていないことを確認する。原因を解消してもfailed状態が残る場合は、
次のように失敗状態とstart-limitカウンタを解除してから再起動する。

```bash
systemctl --user reset-failed shogun-ntfy-listener.service
systemctl --user start shogun-ntfy-listener.service
systemctl --user status shogun-ntfy-listener.service --no-pager
```

`reset-failed` は設定不備や障害原因を修復するコマンドではない。先に原因を解消し、
状態・カウンタの解除用途に限って使用する。

停止手順:

```bash
systemctl --user disable --now shogun-ntfy-listener.service
```

unitの導入時は `deploy/systemd/shogun-ntfy-listener.service` を
`~/.config/systemd/user/` にコピーして `systemctl --user daemon-reload` のみ実施する。
standby準備ではenable/startしない。

## カーソルと重複排除

topic hashはTask 1とlistenerの双方で `lib/ntfy_state.sh` の共通関数を使い、
次の式に統一する。

```bash
printf '%s' "$topic" | sha256sum | awk '{print $1}'
```

これはtopicのUTF-8バイト列を末尾改行なしでSHA-256化した、小文字hex 64桁である。
topicそのものはstateへ保存しない。最終message IDとserver timeは
`status/ntfy_listener_state.yaml` にmode 0600で原子的に保存し、Git管理外とする。
再接続ではmessage ID（なければserver time）を `since` に使う。ntfy側の保持期間を
越えたメッセージは回収できないため、このカーソルは長期保管を保証しない。

自送信を示す `outbound` メッセージはInboxへ書かないが、カーソルは進める。
Inboxの既存 `id` フィールドをmessage IDとして使い、同じIDは二重登録しない。

## exit code方針

- ネットワーク断・stream切断: 内部再接続ループで吸収し、exitしない
- 設定不備・認証不備・state破損: fail closedでexit 1
- SIGTERM/SIGINT: 後始末のうえexit 0
- 上記以外の経路では意図的にexit 0にしない

systemdは `Restart=on-failure` のため、正常な停止シグナルでは再起動せず、障害時のみ
再起動する。連続失敗は200秒間に5回までに制限する。
