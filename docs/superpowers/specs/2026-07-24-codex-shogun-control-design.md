# Codex-mediated Shogun Control Plane 設計

- 日付: 2026-07-24
- 状態: 設計承認済み・実装plan作成済み・実装前
- 対象リポジトリ: `sjinnouchi-ux/multi-agent-shogun`
- 設計base: `52250dea0ba91316a87c1fa3c78703ce66c4259f`
- 関連正本:
  - `docs/superpowers/specs/2026-07-14-codex-readonly-diagnostics-design.md`
  - `docs/codex-diagnostics.md`
  - `docs/github-boundary-operation.md`

## 1. 背景

Codex DesktopからShogunへtaskを配送するには、固定read-only診断の再計算結果が
`overall=healthy`でなければならない。現在のruntimeは、Shogun改修後に
`shogun`・`multiagent` tmux sessionを起動していないため、
診断はschema・provenance検証に成功しても`overall=unavailable`となる。

現行contractがCodexへ恒常許可するWSL操作は固定read-only診断だけであり、
起動、restart、repair、repo内script、短い`wsl.exe` prefix、settings変更は
禁止されている。任意shellを開放せず、レビュー済みの固定profileでShogunを
起動できる限定control planeを追加する。

## 2. 利用者決定

- 任意のWSL操作を許可する方式は採用しない。
- Git管理・PRレビュー・固定snapshot・GitHub deployment台帳を使う。
- Codexは承認済みprofileでの初回起動だけを実行できる。
- 将軍と大目付はClaude Opus 4.8を使い、task guardでFABLE 5責務を明示する。
- 家老、軍師、足軽はGPT-5.6 Sol/Terraを役割別に使う。
- 起動後も固定read-only診断が`healthy`でなければtaskを配送しない。

## 3. 目的

1. Codex Desktopが実Windows user `jinnouchi`のWSL2 `Ubuntu`上で、
   review済みShogun mainを承認済みprofileにより起動できる。
2. 恒常許可を単一の完全commandへ限定し、suffix、任意profile、任意path、
   shell文字列、environment override、stdin payloadを拒否する。
3. control source、deployment、実行結果をSHA-256と固定JSON schemaで照合する。
4. model profileを秘密設定へ保存せず、launcher process内部の固定overlayとして
   適用する。
5. task本文、生queue、生report、生ログ、pane本文、秘密設定をcontrol出力へ
   含めない。
6. control成功後に既存diagnosticsを独立実行し、`healthy`を配送gateとする。

## 4. 非目標

- 任意command、任意repo script、`bash -lc`、短い`wsl.exe` prefixの許可
- stop、restart、repair、kill、tmux attach、pane capture
- task本文のstdin・argv・一時file受渡し
- queue、report、dashboard、watcher log本文の読取または出力
- OAuth、token、認証JSON、`.env`、CLI credentialの読取・変更
- Shogun WebUI、queue schema、agent並列数、task lifecycleの変更
- control commandによるtask配送
- snapshot deploymentを設計PRまたは実装PRへ混在させること

## 5. 検討方式

### 5.1 短いWSL prefixを許可

不採用。任意command、path、environment、redirectへ到達でき、既存の秘密情報・
runtime境界を無効化する。

### 5.2 repo内launcherを直接恒常許可

不採用。working tree変更、branch drift、同一userによるsource差替えを
恒常許可の信頼境界へ持ち込む。

### 5.3 allowlist profileを固定snapshotから起動

採用。既存diagnosticsと同じく、review済みmain sourceをrepo外へmode `0555`で
配置し、実行直前にGitHub mainのactive deployment recordとsource SHA-256を
照合する。snapshotは固定profileだけを内部overlayとして設定し、review済み
runtime repoの固定launcherを起動する。

## 6. 構造

### 6.1 Production source

- `scripts/codex_shogun_control.py`
  - self hashとsnapshot trust検証
  - 固定GitHub Raw URLからactive deployment recordを独立取得・検証
  - argv・cwd・user・repository preflight
  - 固定profileの選択
  - 固定launcherのbounded実行
  - readiness判定
  - sanitized JSON生成
- `lib/cli_adapter.sh`
  - 固定environment markerが存在するlauncher process内だけで
    allowlist role/model overlayを返す
  - 通常起動時は既存`config/settings.yaml`契約を変更しない
- `tests/unit/test_codex_shogun_control.py`
  - pure unit・fake runner・schema・漏洩防止
- `tests/unit/test_cli_adapter.bats`
  - profile overlayと通常経路の回帰
- `tests/integration/test_codex_shogun_control_start.py`
  - injected context・unique tmux socket・mock CLI起動harness
- `tests/integration/test_codex_shogun_control_start.bats`
  - deployment host専用wrapper
- `tests/contract/codex_shogun_control_consumer.py`
  - GitHub registry・process・JSONの独立fail-closed validator
- `tests/contract/test_codex_shogun_control_consumer.py`
  - provenance、schema、timeout、stderr、suffix、hash mismatch test
- `scripts/manage_codex_shogun_control_snapshot.py`
  - fixed snapshot initial install・hash-gated atomic rollback
- `tests/unit/test_manage_codex_shogun_control_snapshot.py`
  - owner・mode・hash・concurrency・TOCTOU・rollback test
- `docs/codex-shogun-control.md`
  - 利用、境界、deployment、rollback
- `docs/superpowers/plans/2026-07-24-codex-shogun-control-work-log.md`
  - source/deployment registry。runtime内容は記録しない

### 6.2 Installed snapshot

固定path:

`/home/jinnouchi/.local/libexec/shogun-codex-control`

条件:

- effective user `jinnouchi`所有
- regular file
- mode `0555`
- 1,048,576 bytes以下
- symlink拒否
- 実行前後のdevice、inode、size、mtime、mode一致
- GitHub main active deployment recordのSHA-256とself hash一致

### 6.3 完全command

`wsl.exe -d Ubuntu --cd /home/jinnouchi/multi-agent-shogun /home/jinnouchi/.local/libexec/shogun-codex-control start finance-planning-v1`

恒常許可prefixは上記の全tokenを含む位置までとする。snapshot CLIは
`start finance-planning-v1`以外、引数不足、追加suffixをcollector・mutation前に
exit 2で拒否する。stdinは閉じ、task payloadを受け取らない。

## 7. 固定profile

`finance-planning-v1`はsource内のimmutable constantとし、外部YAMLや
environmentからprofile内容を読まない。

| Role | CLI | Model | Reasoning / effort | Responsibility |
| --- | --- | --- | --- | --- |
| shogun | claude | claude-opus-4-8 | high | FABLE 5統括、利用者指示の分解 |
| oometsuke | claude | claude-opus-4-8 | high | FABLE 5独立最終監査 |
| karo | codex | gpt-5.6-terra | high | 交通整理、dashboard、最終受入 |
| gunshi | codex | gpt-5.6-sol | max | 設計監査、矛盾分析、QC/RCA |
| ashigaru1-3 | codex | gpt-5.6-sol | high | 現状、要件、architectureの主要分析 |
| ashigaru4-7 | codex | gpt-5.6-terra | high | migration比較、test、rollback、privacy、PR差分 |

FABLE 5はmodel IDではないため、controlはClaude model割当だけを強制する。
Codex consumerはtask配送時に、将軍と大目付のFABLE 5責務をtask guardへ
明記する。task guardに秘密値、顧客名、金額、識別子を含めない。

## 8. 起動preflight

mutation前に次をすべて満たす。

1. argvが完全一致する。
2. effective user、WSL distribution、cwdが固定値と一致する。
3. runtime repoのcanonical remoteが`sjinnouchi-ux/multi-agent-shogun`である。
4. branchが`main`で、HEADがcontrol active deployment recordの
   `runtime_commit`と一致する。
5. tracked・untracked changeが0件である。pathやdiffは出力しない。
6. `shogun`・`multiagent` sessionが両方存在しない。
7. 固定launcherと依存tracked filesがHEAD blobと一致する。
8. 必要CLIとmodel IDのreadiness preflightが成功し、launcherがPython
   venv作成やpackage installを必要としない。
9. profile overlay以外のenvironment overrideを受け取らない。
10. task queue、report、pane本文、credentialを読まない。

sessionが一つでも存在する場合はstartを拒否し、restartへ昇格しない。
repository dirty時は固定codeだけを返し、path・file名・内容を出力しない。
repository dirty状態の同定・解消は、pathや内容をCodexへ出力しない別の
明示host maintenance taskで行う。controlは`git clean`、stash、checkout、
deleteを実行せず、解消されるまでstartを拒否する。

## 9. profile適用

control processは固定marker
`SHOGUN_CODEX_CONTROL_PROFILE=finance-planning-v1`をlauncher子processへだけ
渡す。ユーザー環境、`config/settings.yaml`、shell profile、tmux global
environmentへ永続化しない。

`lib/cli_adapter.sh`はmarkerが完全一致する場合だけ§7のmappingを返す。
unknown profile、role欠落、model欠落は起動前に拒否する。通常の
`shutsujin_departure.sh`実行にはmarkerがないため既存挙動を維持する。

## 10. 実行と成功条件

1. preflight成功後、固定launcherを引数なしで一度だけ起動する。
   `-c`・`--clean`を渡さず、既存queue・dashboard維持契約を使う。
   control自身はその内容を読まない。
2. launcher stdout/stderrはcontrol内部でbounded captureし、外へ中継しない。
3. 起動timeoutは120秒。timeout時はkill・restart・repairを行わない。
4. readinessは2 session、11 agent、pane alive、各CLI ready marker、
   watcher readyをcontent-free enum/countで確認する。
5. 全条件成功時だけexit 0、`state=ready`を返す。
6. 部分起動、timeout、CLI/model unavailableはexit 3、
   `state=failed`または`state=indeterminate`を返す。
7. controlは失敗後にcleanup、stop、restart、settings rollbackを行わない。
   部分起動は新しい明示recovery taskを要求する。
8. control成功後、Codexは固定read-only diagnosticsを別processとして実行し、
   provenance・完全schema・再計算`overall=healthy`を要求する。

## 11. 出力契約

stdoutはASCII JSON一件、stderrは空とする。top-level key順は固定する。

- `schema_version`
- `generated_at`
- `ok`
- `action`
- `profile`
- `state`
- `tool`
- `repository`
- `readiness`
- `errors`
- `warnings`

自由文、path、branch本文、command、environment、task、queue、report、log、
pane、credentialは含めない。issue code、component、roleは固定enumとし、
重複を除去してsortする。

## 12. Consumer gate

control snapshotとCodex consumerは各実行直前に、それぞれGitHub main rawの
control work logを独立取得し、marker pair各1件、schema version 1、exact keys、
active deployment 1件、source commit、runtime commit、source SHA-256、
snapshot path、modeを検証する。snapshotはactive recordのruntime commitを
runtime repo HEADと比較し、consumerはreturned source hashを再照合する。

次のいずれかは`control_provenance_untrusted`としてcommandを実行しない。

- GitHub取得失敗
- marker/schema不正
- active 0件または複数
- source/runtime commit不正
- source hash不一致

commandはexit 0、120秒未満、stderr空、ASCII JSON一件、完全schema、
`state=ready`を必須とする。失敗時にraw output、repo script、queue、pane、
logへfallbackしない。

control成功だけではtask配送しない。直後の既存diagnosticsが
`overall=healthy`となり、既存承認済みtask入力経路を確認できた場合だけ、
新規task guard付き依頼を1回配送する。

## 13. Deployment順序

1. design specを専用branch・Draft PRでレビューする。
2. 承認済みspecから実装planを作る。
3. TDDでsource、consumer、unit、integration、漏洩testを実装する。
4. 実装PRを独立レビューし、mainへmergeする。
5. deployment hostで`make test-no-skip`を実行し、test>0、skip=0、
   exit 0を要求する。
6. reviewed main blobだけをlifecycle helperでsnapshotへ初回配置する。
7. owner、mode、source/deployed SHA-256、suffix拒否、stderr空、
   JSON schemaを検証する。
8. deployment record専用branch・PRで唯一のactive recordをmainへ記録する。
9. GitHub raw mainからregistryを再取得し、snapshot self hashと照合する。
10. Workspaceとhostの安全契約へ完全commandの限定例外を追加する。
11. 完全prefixだけを承認する。
12. 新しいCodex taskでprovenance、control、diagnostics、task intakeを再検証する。

Workspace規則をsource merge、snapshot配置、deployment registry main反映より
先に緩めない。snapshot配置とhost/Workspace policy変更は実装PRとは別の
明示承認taskとする。policy変更対象は実装planでcanonical pathを再確認し、
少なくとも`workspace/codex/CODEX_DESKTOP_STARTUP.md`と、このGitHub境界を
適用するcanonical `AGENTS.md`を個別PRで扱う。各記述は完全commandだけを許可し、
短い`wsl.exe`、`bash -lc`、repo script prefixを追加しない。

## 14. Rollback

1. 完全command permissionを先に撤回する。
2. hostとWorkspaceのcontrol例外をrevertする。
3. control deployment recordを無効化する。
4. reviewed lifecycle helperで固定snapshotを削除または明示版へ戻す。
5. 実行中sessionを自動停止しない。
6. profile markerはlauncher子process限定で永続化しないため、settings復元は不要。
7. rollback結果が不確定なら自動retryせず、新しいrecovery taskを要求する。

## 15. テスト計画

- exact argv、suffix、stdin、environment、cwd、user、branch、commit拒否
- canonical remote、dirty repo、session存在、partial session拒否
- profile全11 roleのCLI/model/effort完全一致
- profile markerなしの通常起動non-regression
- unknown profile・unknown role・missing model拒否
- launcher stdout/stderr、秘密形式、非ASCII、path、task本文の漏洩防止
- timeout、partial readiness、CLI unavailable、model unavailable
- JSON exact keys/order、enum、count、issue sort、ASCII
- registry marker、exact schema、active 0/1/複数、hash mismatch
- snapshot symlink、owner、mode、size、TOCTOU、deployment/rollback
- unique tmux socketによる2 session・11 agent integration
- `make test`回帰
- deployment host `make test-no-skip`でtest>0、skip=0、exit 0

## 16. 受入条件

1. 短い`wsl.exe`、`bash -lc`、repo script prefixを許可しない。
2. production control sourceはrepo外mode `0555` snapshot一つである。
3. 完全commandは承認済みprofile一つだけを起動できる。
4. stop、restart、repair、task delivery、任意payloadを実行できない。
5. 通常launcherのsettings契約に回帰がない。
6. model profileはsettings、credential store、Git外fileへ永続化されない。
7. control出力に秘密値、task、queue、report、log、pane本文がない。
8. provenance不信、process失敗、schema不正でfail closedする。
9. control成功後もdiagnostics `healthy`を配送gateとして維持する。
10. source merge、deployment、policy変更、起動、task配送が別checkpointである。
