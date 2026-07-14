# Codex向けShogun読み取り専用診断ゲート 設計書

- 日付: 2026-07-14
- 状態: 設計方針再レビュー済み・ユーザー文書レビュー待ち
- 対象repo: `sjinnouchi-ux/multi-agent-shogun`、`sjinnouchi-ux/workspace`
- 対象version: v1
- 対象外: inbox wakeup不具合の根本改修、Shogun WebUI、runtime schema変更

## 1. 背景

Codex Desktopは現在、Shogunの秘密設定、tmux pane本文、生queue、生report、生ログを読み取らない。この境界は維持する必要があるが、session、watcher、runtime file、既知エラーの状態を横断して確認できず、障害の切り分けに時間がかかる。

CodexへWSL全体の読み取り権限を与える方式は採用しない。Shogun側で固定された診断メタデータだけを収集し、固定JSONだけを返すオンデマンドCLIを用意する。

初回設計レビューでは、queue/reportのfield解析を含む8種類のcollectorと、作業repo内の可変scriptを恒常許可する案に問題が見つかった。v1では範囲を削減し、次を設計原則とする。

1. 既存のwatcher、queue writer、launcher、agent status、WebUIを変更しない。
2. queue、task、report、statusは内容を読まず、存在と更新時刻等のfilesystem metadataだけを見る。
3. 診断実体は作業repoから直接実行せず、レビュー済みsnapshotをrepo外へ配置する。
4. 本文を読む例外は固定watcher log末尾の既知文字列集計だけとし、ログ行は出力しない。
5. v1で不足した項目は実績確認後に別specで追加する。

## 2. 目的

- CodexがShogunの主要な障害層を、raw本文や秘密値を取得せず区別できる。
- 恒常許可を単一の固定commandへ限定する。
- 診断追加が本体制御系へ波及しない依存方向を作る。
- 1足軽編成など可変編成を異常と誤判定しない。
- 2〜3時間規模のv1実装として完結させる。

## 3. 非目標

- Enter欠落、wakeup、handoff watchdogの根本改修を行わない。
- Shogunを起動、停止、再起動、修復しない。
- queue、task、report、status、log、Gitへ書き込まない。
- task ID、message ID、message type、本文、report statusを出力しない。
- tmux pane本文、scrollback、入力行、pane pathを取得しない。
- 任意path、任意session、任意agent、任意regex、任意shell commandを受け付けない。
- WebUI API、port、daemon、cacheを追加しない。
- debug raw mode、environment override、production path overrideを実装しない。
- 同一OS userが意図的に診断snapshotを書き換える攻撃を完全には防御しない。この残余リスクは§8.5で扱う。

## 4. 検討した方式

### 4.1 WSL全体を恒常的に読み取り可能にする

秘密設定、認証情報、業務本文へ到達できるため不採用。

### 4.2 既存`agent_status.sh`またはwatcherへ診断を追加する

既存`agent_status.sh`はpane本文からbusy/idleを判定し、watcherは本番配信と状態更新を担う。診断を追加すると本番制御と観測が結合するため不採用。

### 4.3 作業repo内のPythonを恒常許可する

固定commandでもentrypoint自体をShogun agentが変更でき、自己検査前に実行されるため不採用。

### 4.4 repo外の固定snapshotをオンデマンド実行する

レビュー済みsourceをuser-localの固定pathへ配置し、作業repoを観測対象として実行する。既存本体へ変更を入れず、作業branchから診断実体を分離できるため採用。

## 5. 構造

### 5.1 sourceとdeployment

Shogun repoへself-containedなsourceを置く。

- `scripts/codex_diagnostics.py`: CLI、sanitizer、collector、JSON serialization
- `tests/unit/test_codex_diagnostics.py`: Python単体・契約test
- `tests/unit/test_codex_diagnostics.bats`: 既存`make test`へ組み込むwrapper
- `tests/integration/test_codex_diagnostics_tmux.py`: WSL deployment hostのunique socket integration
- `tests/integration/test_codex_diagnostics_tmux.bats`: `test-no-skip`専用wrapper
- `docs/codex-diagnostics.md`: 利用、deployment、出力契約
- `docs/github-boundary-operation.md`: 信頼済みゲートの限定例外
- `docs/superpowers/plans/2026-07-14-codex-readonly-diagnostics-work-log.md`: source provenance、検証、deployment記録
- `Makefile`: skipを成功扱いしない`test-no-skip` target
- `.gitignore`: 上記新規fileだけを個別allowlist

Workspace repoでは次を同じcommitで同期する。

- `codex/CODEX_DESKTOP_STARTUP.md`: online正本の限定例外
- `codex/CODEX_DESKTOP_CUSTOM_INSTRUCTIONS.md`: bootstrap文面の同一規則
- `codex/work_log.md`: 判断、反映commit、deployment検証記録

Workspace main反映後、実PCの`C:\Users\jinnouchi\.codex\AGENTS.md`と`CODEX_DESKTOP_CUSTOM_INSTRUCTIONS.md`の`Paste This Text`をdiffし、今回追加する診断例外blockだけを一致させる。host側にのみ存在する、より厳しい認証境界その他の規則は保持し、今回のtaskで全文置換しない。既存driftの解消は別の明示承認taskとする。host設定はGit管理成果物ではなく、別PCやShogunへコピーしない。

Python codeは一fileだが、次の関数境界を維持する。

- CLI: argument完全一致とtop-level error処理
- command runner: absolute executable、timeout、出力上限
- path guard: 固定相対pathの安全なmetadata/open処理
- collector: repository、tmux、process、runtime source、log aggregate
- schema builder: 一箇所だけで出力を組み立てる

plugin、dynamic registration、base class、`sys.path`操作、repo内module importは作らない。

既存の`skills/shogun-agent-status/scripts/agent_status.sh`が採用している、引数なし、固定tmux format、未知値の破棄、repo helper非依存という安全原則を踏襲する。ただし同scriptを呼び出したり変更したりせず、両者の固定agent ID enumだけが一致する契約testを追加してdriftを検出する。

main反映後、sourceとSHA-256を確認し、次へsnapshotとして配置する。

```text
/home/jinnouchi/.local/libexec/shogun-codex-diagnostics
```

配置時はmode `0555`とし、source repo、source commit、source SHA-256、配置日時をShogun GitHub上の診断作業ログへ記録する。user-local manifestやcacheは作成しない。`sudo`とsystem directoryは使用しない。snapshot更新は通常診断とは別の明示的deployment作業とする。

診断JSONの`tool.source_sha256`は、実行中snapshot自身のsource bytesから算出した64文字の小文字16進SHA-256とする。これはruntime dataのhashではなく、GitHub上の診断作業ログと照合するためのsource provenanceである。

source hashは固定snapshot pathを`O_NOFOLLOW | O_CLOEXEC | O_NONBLOCK`で開き、`fstat`でregular fileかつmode `0555`であることを確認し、最大1,048,576 byteをstreaming hashする。read前後のdevice、inode、size、mtime nanoseconds、modeが一致しない、上限を超える、symlink、非regular file、mode不一致、read失敗のいずれかはcollector起動前にexit 3とし、`tool.source_sha256=null`の固定失敗JSONだけを返す。hash対象pathをargument、environment、cwd、runtime dataから組み立てない。

診断作業ログの固定path:

```text
docs/superpowers/plans/2026-07-14-codex-readonly-diagnostics-work-log.md
```

同fileは次のmarker pairを各1件だけ持ち、その間を一行JSONとする。

```text
<!-- BEGIN CODEX_DIAGNOSTICS_DEPLOYMENTS_V1 -->
{"schema_version":1,"deployments":[]}
<!-- END CODEX_DIAGNOSTICS_DEPLOYMENTS_V1 -->
```

各deployment recordは`status`、`source_repo`、`source_commit`、`source_path`、`source_sha256`、`deployed_at`、`snapshot_path`、`snapshot_mode`、`contract_schema_version`の9 fieldだけを持つ。`status`は`active | superseded`、`source_repo`は`https://github.com/sjinnouchi-ux/multi-agent-shogun`、`source_path`は`scripts/codex_diagnostics.py`、`snapshot_path`は`/home/jinnouchi/.local/libexec/shogun-codex-diagnostics`、commitは40文字小文字16進、SHA-256は64文字小文字16進、時刻はUTC RFC 3339 seconds、modeは文字列`0555`、contract schemaは整数`1`とする。初回deployment前は0件を許す。deployment後は`active`を必ず1件だけとし、更新時は旧activeを同じcommitで`superseded`へ変える。秘密値、診断JSON、runtime metadata、raw logは記録しない。

### 5.2 依存方向

```text
Codex Desktop
  -> 固定wsl.exe command
    -> user-local固定snapshot
      -> Shogun runtimeの読み取り専用metadata
```

Shogun本体から診断scriptを呼ばない。診断scriptから既存の更新系scriptを呼ばない。

### 5.3 恒常許可command

許可対象prefixは、次の全tokenを含む位置までとする。

```text
wsl.exe
-d
Ubuntu
--cd
/home/jinnouchi/multi-agent-shogun
/home/jinnouchi/.local/libexec/shogun-codex-diagnostics
summary
```

一行表記:

```text
wsl.exe -d Ubuntu --cd /home/jinnouchi/multi-agent-shogun /home/jinnouchi/.local/libexec/shogun-codex-diagnostics summary
```

これより短い`wsl.exe`、`bash -lc`、`python3`、repo内scriptを恒常許可しない。実行環境はprefix許可であるため後続argumentを形式上追加できるが、診断CLIが`summary`以外または追加argumentをcollector起動前にexit 2で拒否する。この二段階をv1の有効境界とする。

snapshotのshebangはabsolute interpreterとisolated modeを使用する。

```text
#!/usr/bin/python3 -I
```

## 6. v1 collector

### 6.1 共通enum

agent ID:

```text
shogun, karo, ashigaru1, ashigaru2, ashigaru3, ashigaru4,
ashigaru5, ashigaru6, ashigaru7, gunshi, oometsuke
```

CLI:

```text
claude, codex, copilot, kimi, opencode, cursor, antigravity, unknown
```

session:

```text
shogun, multiagent
```

tmuxから得た値はenum照合後にだけ出力する。path生成はtmux値を使わず、code内の固定mapだけを使う。

### 6.2 repository collector

`/usr/bin/git`をshellなしで実行する。`GIT_OPTIONAL_LOCKS=0`、`core.fsmonitor=false`、pager無効、固定timeout、最小environmentを使用する。

出力:

- `branch_class`: `main | shogun_namespace | codex_namespace | other | detached | invalid`
- `head`: 40文字lowercase SHA、取得不能時は`null`
- `dirty`: booleanまたは`null`
- `tracked_changes`: 0〜10000または`null`
- `untracked_changes`: 0〜10000または`null`
- `canonical_remote_present`: booleanまたは`null`

branch本文は出力しない。`main`完全一致、`shogun/`prefix、`codex/`prefix、その他の安全なbranch、detached、不正値へ分類する。分類前の安全判定では英数字開始、最大128文字、英数字、`.`, `_`, `/`, `-`だけを許し、`..`、`.lock`終端、先頭/末尾`/`を拒否する。remote名、remote URL、file名、diffも出力しない。Canonical repoはHTTPSまたはSSHの既知形式を`sjinnouchi-ux/multi-agent-shogun`へ正規化して確認する。

Canonical remoteがなければruntime fileを読まずexit 2とする。作業branch上でも診断できることが目的なので、runtime repoのHEADとremote mainの一致は要求しない。診断実体のtrustはrepo外snapshotで分離する。

Canonical remote確認command自体が失敗して境界を確定できない場合もruntime fileを開かずexit 2とする。Canonical boundary受理後のbranch、HEAD、status command失敗はexit 0の固定成功shapeを保ち、該当値を`null`または`invalid`、repositoryを利用不能、overallを`unavailable`、固定command errorをerrorsへ入れる。

repository commandが64 KiBまたは128 record上限に達した場合は部分countを返さず、該当countと`dirty`を`null`、固定code`command_output_limited`をerrorsへ入れる。`tracked_changes`と`untracked_changes`のschema上限10,000は有効なbounded command resultにだけ適用し、超過時は値を`null`、固定code`result_truncated`をerrorsへ入れる。

### 6.3 tmux collector

`/usr/bin/tmux list-sessions`と`list-panes`の固定formatだけを使う。`capture-pane`はcodeにもtestにも含めない。

sessionごとの出力:

- `name`: session enum
- `state`: `present | missing | error`
- `pane_count`: 0〜64または`null`
- `dead_pane_count`: 0〜64または`null`
- `unknown_agent_count`: 0〜64または`null`

agentごとの出力:

- `id`: agent enum
- `observed`: boolean
- `session`: session enumまたは`null`
- `pane_state`: `alive | dead | not_observed | error`
- `cli`: CLI enum

agent objectはenum順に常に11件返す。観測されないagentは`not_observed`とし、それだけで`degraded`にしない。これにより1足軽編成を正常に扱う。unknown agentの原文は出力せず、sessionごとの`unknown_agent_count`だけを返す。

同じagent IDを持つpaneが複数ある場合は一つを選ばず、該当agentを`pane_state=error`、全体を`degraded`とし、固定code`duplicate_agent_pane`を返す。

`shogun`は`shogun` session、それ以外のagentは`multiagent` sessionだけを正規配置とする。別sessionで観測した場合は該当agentを`pane_state=error`とし、固定code`agent_session_mismatch`を返す。CLI optionが欠落またはenum外の場合は`cli=unknown`とし、`unknown_cli_observed` warningだけを返す。

### 6.4 process collector

`/usr/bin/pgrep`へ固定patternを渡し、件数だけを取得する。

- watcher supervisor件数
- 観測済みagentごとのinbox watcher件数

PID、command line、environment、cwdは出力しない。agent patternはenumから固定mapで選び、tmux値や利用者入力を埋め込まない。実行argumentは`/usr/bin/pgrep -f -- <fixed-pattern>`に固定する。exit 0は返されたPID record数、exit 1は0件、その他は確認失敗として扱う。

固定pattern:

```text
(^|/)scripts/watcher_supervisor\.sh([[:space:]]|$)
(^|/)scripts/inbox_watcher\.sh[[:space:]]+<agent-enum>[[:space:]]
```

process state:

- supervisor: `healthy`=1、`missing`=0、`duplicate`=2以上、`unknown`=確認失敗
- agent watcher: `healthy`=1、`missing`=0、`duplicate`=2以上、`not_observed`=対象外

### 6.5 runtime source metadata collector

内容は開かず、固定pathの`lstat` metadataだけを取得する。

共通source:

| key | path |
|---|---|
| command_queue | `queue/shogun_to_karo.yaml` |
| dashboard | `dashboard.md` |

agent source:

| key | path | applicability |
|---|---|---|
| inbox | `queue/inbox/<agent>.yaml` | observed時required、未観測時optional |
| task | `queue/tasks/<agent>.yaml` | ashigaru1-7、gunshi、oometsukeはobserved時required。他はnot_applicable |
| report | §6.6のmap | ashigaru1-7、gunshi、oometsukeはoptional。他はnot_applicable |
| handoff_status | `status/handoff_watchdog/<agent>.yaml` | optional |
| watcher_log | `logs/inbox_watcher_<agent>.log` | observed時required、未観測時optional |

出力field:

- `applicability`: `required | optional | not_applicable`
- `state`: `present | missing | rejected | not_applicable | error`
- `modified_at`: UTC RFC 3339 secondsまたは`null`
- `size_class`: `empty | small | medium | large | null`

size class:

- `empty`: 0 byte
- `small`: 1〜65,536 byte
- `medium`: 65,537〜1,048,576 byte
- `large`: 1,048,577 byte以上

file名、正確なsize、内容、hashは出力しない。

symlink、非regular file、固定map外component、dir-FD境界違反は`state=rejected`と`source_rejected`へ変換する。通常のI/O失敗は`state=error`と`command_failed`へ変換する。required sourceではerrors、optional sourceではwarningsとし、raw path、errno、exception本文を出力しない。

### 6.6 report source map

globは使わない。

| agent | path |
|---|---|
| ashigaru1-7 | `queue/reports/<agent>_report.yaml` |
| gunshi | `queue/reports/gunshi_report.yaml` |
| oometsuke | `queue/reports/oometsuke_report.yaml` |
| shogun | not_applicable |
| karo | not_applicable |

task ID付きの別名reportが存在してもv1では列挙・探索しない。必要性が確認された場合に別specで扱う。

### 6.7 watcher log aggregate collector

対象は固定agent mapの`logs/inbox_watcher_<agent>.log`だけとする。安全に開けるregular fileについて末尾最大1,048,576 byteだけを読み、次のASCII固定substringを線形に数える。

| code | fixed substring |
|---|---|
| send_keys_failed_attempt | `send-keys nudge failed` |
| nudge_still_visible | `nudge text still visible in pane` |
| wakeup_retry_exhausted | `send-keys failed after` |
| wakeup_success_logged | `Wake-up sent to` |

`WARNING:`または`[ERROR]`を含み、上記codeに一致しない行は`unclassified_error_candidate`として件数だけを数える。通常行はunclassifiedへ含めない。

出力はagent ID、window=`tail_1048576_bytes`、各code件数、log fileの`modified_at`だけとする。ログ行、match内容、前後文脈、最終行、pathは出力しない。

## 7. 固定JSON契約

### 7.1 成功・degraded時

全fieldを必須とし、取得不能値は定義済み`null`またはenumで表す。配列順序はsession enum順、agent enum順、error code辞書順で固定する。

| top-level field | type | rule |
|---|---|---|
| schema_version | integer | 常に`1` |
| generated_at | stringまたはnull | UTC RFC 3339 seconds。literal fallbackだけ`null` |
| ok | boolean | collector完走時true、exit 2/3時false |
| overall | enum | `healthy | degraded | unavailable` |
| tool | object | version=`1.0.0`、deployment=`user_local_snapshot`、source_sha256=成功時64文字の小文字16進、exit 2/3時null |
| repository | objectまたはnull | 成功時§6.2の6 field、exit 2/3時null |
| sessions | array | 成功時2件、exit 2/3時0件 |
| processes | objectまたはnull | 成功時2 field、exit 2/3時null |
| global_sources | object | 成功時2 key、exit 2/3時0 key |
| agents | array | 成功時11件、exit 2/3時0件 |
| errors | array | 最大64件、固定objectのみ |
| warnings | array | 最大64件、固定objectのみ |

成功時repository object:

```json
{
  "branch_class": "main",
  "head": "0000000000000000000000000000000000000000",
  "dirty": false,
  "tracked_changes": 0,
  "untracked_changes": 0,
  "canonical_remote_present": true
}
```

完全なnested object契約。例では配列の先頭要素だけを示し、実出力件数は直後の規則に従う。

```json
{
  "sessions": [
    {
      "name": "shogun",
      "state": "present",
      "pane_count": 1,
      "dead_pane_count": 0,
      "unknown_agent_count": 0
    }
  ],
  "processes": {
    "watcher_supervisor_count": 1,
    "watcher_supervisor_state": "healthy"
  },
  "global_sources": {
    "command_queue": {
      "applicability": "required",
      "state": "present",
      "modified_at": "2026-07-14T00:00:00Z",
      "size_class": "small"
    },
    "dashboard": {
      "applicability": "optional",
      "state": "present",
      "modified_at": "2026-07-14T00:00:00Z",
      "size_class": "small"
    }
  },
  "agents": [
    {
      "id": "shogun",
      "observed": true,
      "session": "shogun",
      "pane_state": "alive",
      "cli": "claude",
      "watcher_count": 1,
      "watcher_state": "healthy",
      "sources": {
        "inbox": {
          "applicability": "required",
          "state": "present",
          "modified_at": "2026-07-14T00:00:00Z",
          "size_class": "small"
        },
        "task": {
          "applicability": "not_applicable",
          "state": "not_applicable",
          "modified_at": null,
          "size_class": null
        },
        "report": {
          "applicability": "not_applicable",
          "state": "not_applicable",
          "modified_at": null,
          "size_class": null
        },
        "handoff_status": {
          "applicability": "optional",
          "state": "missing",
          "modified_at": null,
          "size_class": null
        },
        "watcher_log": {
          "applicability": "required",
          "state": "present",
          "modified_at": "2026-07-14T00:00:00Z",
          "size_class": "medium"
        }
      },
      "log_events": {
        "window": "tail_1048576_bytes",
        "modified_at": "2026-07-14T00:00:00Z",
        "send_keys_failed_attempt": 0,
        "nudge_still_visible": 0,
        "wakeup_retry_exhausted": 0,
        "wakeup_success_logged": 1,
        "unclassified_error_candidate": 0
      }
    }
  ]
}
```

`sessions`は常に2件、`agents`は常に11件、`global_sources`は常に2 key、agent `sources`は常に5 key、`log_events`は常に上記7 fieldを持つ。整数は0以上、schema上限を超える場合は値を`null`にして`result_truncated`をerrorsへ入れる。取得不能の数値、timestamp、enumは各fieldで定義した`null`または`error`を使い、key自体を省略しない。

error/warning object:

```json
{
  "code": "watcher_missing",
  "component": "process",
  "agent": "ashigaru1"
}
```

- `code`: §7.3 enum
- `component`: `repository | tmux | process | source | log | diagnostic`
- `agent`: agent enumまたは`null`

自由記述fieldは持たない。配列最大数はerrors 64、warnings 64、agents 11、sessions 2とする。上限超過時は固定`result_truncated` errorへ置換する。

### 7.2 非0終了時

制御可能な失敗でもstdoutへ安全なJSON一件だけを出し、stderrは空にする。

```json
{
  "schema_version": 1,
  "generated_at": "2026-07-14T00:00:00Z",
  "ok": false,
  "overall": "unavailable",
  "tool": {
    "version": "1.0.0",
    "deployment": "user_local_snapshot",
    "source_sha256": null
  },
  "repository": null,
  "sessions": [],
  "processes": null,
  "global_sources": {},
  "agents": [],
  "errors": [
    {
      "code": "boundary_rejected",
      "component": "diagnostic",
      "agent": null
    }
  ],
  "warnings": []
}
```

終了code:

- `0`: JSON生成成功。`overall=degraded`または`unavailable`でも診断処理自体は成功
- `2`: argument、cwd、Canonical boundary等のpreflight拒否
- `3`: 安全なJSONを構築できない内部失敗

通常error pathは`Exception`をtop-levelで捕捉し、traceback、path、subprocess stdout/stderr、exception本文を伝播させない。内部command timeoutも固定error codeへ変換する。

JSON serialization自体が失敗した場合は、JSON libraryを再利用せず`os.write(1, FALLBACK_INTERNAL_ERROR)`で次の固定UTF-8 bytesを一度だけ書く。これがexit 3の最終contractである。

```json
{"schema_version":1,"generated_at":null,"ok":false,"overall":"unavailable","tool":{"version":"1.0.0","deployment":"user_local_snapshot","source_sha256":null},"repository":null,"sessions":[],"processes":null,"global_sources":{},"agents":[],"errors":[{"code":"internal_error","component":"diagnostic","agent":null}],"warnings":[]}
```

SIGINTとSIGTERMは出力開始前なら同じ固定bytesを返す。出力開始後のsignal、SIGKILL、WSL自体の起動失敗、外部timeoutによる強制終了ではJSONがない、または不完全な場合がある。

consumerはnon-JSON、空出力、不完全JSON、10秒超過を`diagnostic_process_failed`として扱い、raw fallbackを実行しない。

### 7.3 error/warning code enum

```text
argument_rejected
agent_session_mismatch
boundary_rejected
canonical_remote_missing
command_failed
command_output_limited
command_timeout
diagnostic_process_failed
diagnostic_provenance_untrusted
duplicate_agent_pane
duplicate_process
internal_error
pane_dead
required_source_missing
result_truncated
session_missing
source_rejected
unknown_agent_observed
unknown_cli_observed
watcher_missing
```

未定義codeを動的に生成しない。

errorsへ入れるcode:

```text
argument_rejected, agent_session_mismatch, boundary_rejected,
canonical_remote_missing,
command_failed, command_output_limited, command_timeout,
duplicate_agent_pane, duplicate_process, internal_error, pane_dead,
required_source_missing, result_truncated, session_missing, source_rejected,
watcher_missing
```

warningsへ入れるcode:

```text
source_rejected, unknown_agent_observed, unknown_cli_observed
```

`diagnostic_process_failed`と`diagnostic_provenance_untrusted`はconsumerだけが合成するcodeであり、正常に起動したCLI自身は出力しない。前者はprocess/JSON契約失敗、後者はGitHub active deployment recordまたはsource hashの信頼失敗に使う。optional source missingはerrors/warningsのどちらにも追加せず、source objectの`state=missing`だけで示す。required sourceの`source_rejected`はerrors、optional sourceの`source_rejected`はwarningsへ入れるがcodeは同じとする。

### 7.4 overall算出

- `unavailable`: `shogun`と`multiagent`が両方missing、またはrepository collectorが利用不能
- `degraded`: sessionが一方だけmissing、present sessionのdead pane、agent session不一致、supervisor異常、command queue異常、観測済みagentのwatcher異常、観測済みagentのrequired source異常、collector errorのいずれか
- `healthy`: 上記以外

未観測agentのsource欠落、optional source欠落、Shogun停止時のstale runtime fileは健康度を悪化させない。

## 8. セキュリティ境界

### 8.1 常時禁止

- token、OAuth code、認証JSON、`.env`
- `projects/*.yaml`、秘密設定、Secret Manager値
- browser session、keyring、SSH key
- pane本文、queue/task/report/status本文、log行
- 任意path、glob、regex、shell command

### 8.2 path guard

- runtime rootは固定commandのcwdとCanonical repo確認から決定し、引数やenvironmentで上書きできない。
- 相対pathはcode内の固定mapだけから選ぶ。
- agent IDは完全enumであり、正規表現だけをpath安全性に使わない。
- runtime rootをdirectory FDとして開き、全componentを`openat`相当のdir FDと`O_NOFOLLOW`で辿る。
- 親directory、leaf、magic link、repo外解決を拒否する。
- metadata取得後に`fstat`し、regular file以外を拒否する。
- logは上限+1 byteのbounded readを行い、上限超過分を読まない。

Linux kernelまたはPython runtimeで安全なdir FD traversalを実装できない場合、弱い`Path.resolve()`へfallbackせず該当sourceを`source_rejected`とする。

### 8.3 command runner

- executable: `/usr/bin/git`、`/usr/bin/tmux`、`/usr/bin/pgrep`だけ
- shell: 常にfalse
- timeout: commandごと2秒、全体10秒
- stdout/stderr: 各64 KiB、各128 recordまで
- environment: 固定`PATH=/usr/bin:/bin`、locale、Git read-only設定だけ
- pager、color、fsmonitor、optional lockを無効化
- subprocess stderrは解析・出力せず破棄する

### 8.4 値の保護

- allowlist fieldとenumを通過した値だけを出力する。
- free text、未知key、未知CLI、未知agentを原文で返さない。
- secret検出後のmaskを安全境界にしない。
- runtime file、log、command output等のraw bytes由来のhashやfingerprintを出力しない。`tool.source_sha256`だけは実行中の診断source自身を照合する固定例外とする。
- parse error、command error、path errorは固定codeだけへ変換する。

### 8.5 snapshotと残余リスク

作業repo内sourceを直接恒常許可しない。main反映済みsourceを確認後、repo外user-local pathへsnapshot配置し、mode `0555`とする。実行結果の`tool.source_sha256`をGitHub上の診断作業ログに記録したsource SHA-256と照合し、偶発的変更を検出する。user-local manifestやcacheは持たない。

Codex consumerは固定診断commandを実行する直前ごとに、GitHub `main`のraw診断作業ログを取得する。markerが各1件、JSONが固定schema、`active` recordが1件、recordのsource commitとsource SHA-256が有効であることを確認してからcommandを実行し、返った`tool.source_sha256`をactive recordと完全一致比較する。取得不能、recordなし、active複数、schema不一致、hash不一致では診断fieldを信頼せず`diagnostic_provenance_untrusted`として扱い、raw fallback、repo内source実行、直接runtime読取を行わない。

同一OS userはmodeを変更してsnapshotを置換できるため、これは悪意ある同一userに対する完全な実行sandboxではない。Shogunの既存規則はproject外変更を禁止しており、v1の目的はCodexの広い恒常権限と偶発的な本体変更を防ぐことである。

より強い境界が必要になった場合は、管理者所有binaryまたは別service accountによるlauncherを別specで設計する。v1では`sudo`、root-owned file、system serviceを導入しない。

### 8.6 運用規則の限定例外

`workspace/codex/CODEX_DESKTOP_STARTUP.md`、`workspace/codex/CODEX_DESKTOP_CUSTOM_INSTRUCTIONS.md`、Shogunの`docs/github-boundary-operation.md`へ、固定snapshotがallowlist metadataと固定log集計をlocal process内で取得することだけを限定例外として記載する。限定例外には、実行直前ごとのGitHub `main` active deployment record確認と`tool.source_sha256`照合を必須条件として同じ文面で含める。

Codexへ渡るのは固定JSONだけであり、`cat`、`grep`、YAML本文取得、log行取得、pane capture、別script実行は引き続き禁止する。

Workspaceとhost `AGENTS.md`の診断例外blockは、次の固定markerを各1件だけ持つ。

```text
<!-- BEGIN CODEX_SHOGUN_READONLY_DIAGNOSTICS_V1 -->
<!-- END CODEX_SHOGUN_READONLY_DIAGNOSTICS_V1 -->
```

既存block更新は開始・終了markerが各1件で正しい順序にある場合だけ許し、0件、複数、片側だけなら書き込まず停止する。今回のhost初回導入だけは汎用同期を使わず、main反映済みtemplateの固定Shogun禁止段落がhost側でもexactly 1 matchすることとmarker 0件を確認して、明示承認された`apply_patch`でその直後へblockを1回挿入する。変更前後でblock外bytesが完全一致すること、挿入後にmarker pairが各1件であることを検証する。host固有の既存規則や既存driftは変更しない。

## 9. テスト

### 9.1 argument・schema

- `summary`だけを受理する。
- 追加argument、別subcommandをcollector起動前にexit 2で拒否する。
- environment値を診断入力として採用せず、hostile environmentでもisolated modeと固定subprocess environmentによって結果契約が変わらない。
- 成功、degraded、preflight拒否、内部失敗の全JSONがschema契約を満たす。
- 成功時の`tool.source_sha256`が実行中source bytesのSHA-256と一致し、exit 2/3時はnullになる。
- consumer契約testはGitHub取得不能、marker/schema不正、active 0件、active複数、hash不一致をすべて`diagnostic_provenance_untrusted`へ変換し、raw fallbackしないことを確認する。
- stdoutはJSON一件、stderrは空である。
- 配列順序と上限が固定される。

### 9.2 漏洩防止

- branch、tmux option、process、file、log fixtureへtoken形式、OAuth code、改行、Unicode、顧客名を埋めても出力されない。
- paneへ秘密文字列を表示しても、`capture-pane`を使わず出力に現れない。
- remote名・URL、file名、PID、command line、正確なfile size、runtime dataのraw hashが出力されない。`tool.source_sha256`だけが64文字の小文字16進で出力される。
- exception、subprocess stderr、timeout内容が出力されない。

### 9.3 path・resource

- leaf symlink、親symlink、magic link、`..`、FIFO、socket、deviceを拒否する。
- metadata確認中の差し替えを模擬し、安全に拒否する。
- 1 MiB超のlogは末尾1 MiBだけを正常集計し、それ以前のmarkerを数えない。
- command 64 KiB超過、128 record超過を固定codeへ変換する。
- hostile `PATH`、`PYTHONPATH`、localeで実行してもabsolute executableとisolated modeが維持される。
- source hashは固定snapshot pathのregular file、mode `0555`、1,048,576 byte以下だけを受理し、symlink、非regular、mode違い、上限超過、read中metadata変化をcollector起動前に拒否する。

### 9.4 可変編成

- 1足軽編成を`healthy`または他の実障害だけに基づく状態として扱う。
- 未観測agent欠落を`degraded`にしない。
- unknown agent本文を返さず件数だけを返す。
- Shogun/Karoのtask/reportを`not_applicable`とする。

### 9.5 tmux integration

production CLIにはsession/socket overrideを追加しない。WSL deployment host専用integration testはunique tmux socket上に固定名`shogun`と`multiagent`を作り、socketを付与するcommand runnerをtest codeからだけ注入する。通常のunit/CI suiteは固定fixtureとfake runnerで同じparser契約を検証し、tmux未導入platformでskipを発生させない。unique socket testは`make test-no-skip`だけが明示実行し、実hostでtmux不足ならpreflight failureとする。

session検出とpane件数を先にassertし、その後に秘密文字列非漏洩をassertする。production sessionは使用しない。

### 9.6 回帰・Git追跡

- `python3 -m unittest tests/unit/test_codex_diagnostics.py`
- `bats tests/unit/test_codex_diagnostics.bats`
- `bats tests/integration/test_codex_diagnostics_tmux.bats`（`test-no-skip`内のWSL deployment host gate）
- `python3 -m py_compile scripts/codex_diagnostics.py tests/unit/test_codex_diagnostics.py`
- `make test-no-skip`
- `make lint`
- `make build`後のgenerated instruction diff 0
- gitleaks実行。CIに標準commandがない場合はversion固定した実行方法を実装計画で確定する
- `git check-ignore`で新規source、test、docsだけが追跡可能であることを確認する
- 近接した秘密path、log、status、project fileが新規に追跡可能にならないnegative test
- 診断作業ログのmarker pair各1件、一行JSON、固定field、active最大1件を静的testし、post-deployment gateではactive exactly 1件とdiagnostic hash一致を要求する

本タスクではinstruction templateとgenerated instructionを変更しない。既存checkoutで生じるEOL-only差分もstageしない。

`test-no-skip`は実deployment host用の受入targetである。最初にClaude、Bats、Python、tmux等の必須commandをpreflightし、不足時はskipせず非0終了する。その後root-levelとunit BatsをTAP formatterで実行し、一時出力に`# skip`が1件でもあれば非0終了する。通常のtest failure、timeout、formatter errorも非0のまま伝播し、skip件数を成功扱いしない。既存`make test`の意味は変更しない。

GitHub CIはClaude CLIを持たず、既存`test_cli_adapter.bats`に既知の条件付きskipがあるため、v1では`test-no-skip`をCIへ追加しない。CIの`make test`は通常回帰gateとして使うが、完了根拠のskip 0判定には使わない。完了判定はClaude導入済みの実WSL deployment hostで`make test-no-skip`が通ったことを必須とする。

## 10. 導入順序

1. Shogun専用branchでsource、test、docsを実装する。
2. Shogun PRで非結合性、漏洩防止、snapshot方式をレビューする。
3. PRをmainへ反映する。
4. WSL runtimeが停止している状態でmainを反映する。
5. main上sourceのSHA-256を確認し、user-local snapshotだけを配置する。
6. snapshotのmode、固定commandのJSON契約、`tool.source_sha256`とmain上source SHA-256の一致を確認する。
7. 最新Shogun mainからdeployment記録専用branchを作り、診断作業ログの旧activeを同commitで`superseded`へ変え、新recordを唯一の`active`として実測source commit、deployed bytes SHA-256、UTC配置日時、mode、schema versionとともに記録する。変更は同作業ログ一fileだけとする。
8. deployment記録PRをmainへ反映する。
9. GitHub raw `main`から診断作業ログを再取得し、marker、固定schema、唯一のactive record、source commit、source SHA-256を確認し、固定commandの`tool.source_sha256`と再照合する。
10. Workspace専用branchで共通起動手順、カスタム指示文面、作業ログへ限定例外を追加する。
11. Workspace PRをmainへ反映する。
12. 実PCのグローバル`AGENTS.md`へ§8.6の初回導入手順で診断例外blockだけを追加し、既存のより厳しいhost規則を保持する。
13. §5.3の全tokenを含む位置までのprefix許可を設定する。
14. 新しいCodex taskと現在taskの両方で、実行直前にGitHub active recordを確認してから固定commandを実行し、hash一致、固定schema、raw本文と秘密値が出力されないことを確認する。

Workspace規則を先に緩めない。Shogun source main反映、snapshot配置、契約test、deployment記録main反映、raw GitHub再確認の完了後にだけ例外を有効化する。

## 11. スパゲッティ化防止の合格条件

- 既存watcher、queue writer、launcher、agent status、WebUIの実装変更は0件。
- runtime schema変更は0件。
- production入口は固定command一つ、subcommand一つ、JSON schema一つ。
- 診断sourceはself-contained一fileで、既存runtime moduleをimportしない。
- collector間でraw textを渡さず、検証済み型または固定codeだけを渡す。
- collectorから別collectorを呼ばない。
- output field追加はschema test、漏洩test、docs更新を同じ変更に含める。
- raw mode、任意path、任意session、security feature flagを追加しない。
- 書き込み、自動修復、WebUI表示、queue/report内容解析は別specとする。

## 12. 受け入れ条件

1. repo外snapshotの固定command一つで診断JSONを取得できる。
2. CodexがGit、tmux metadata、process件数、runtime file freshness、既知log error件数を確認できる。
3. pane、queue、task、report、status、logの本文がstdout/stderrに現れない。
4. 任意path、任意command、追加argumentを指定できず、environment値を診断入力として採用しない。
5. 1足軽編成を欠損扱いしない。
6. 既存制御系codeとruntime schemaを変更しない。
7. 全testがunexpected skip 0で通る。
8. ShogunとWorkspaceが別branch・別PR・順序付きで反映される。
9. 恒常許可に§5.3より短いprefixを使わず、suffix追加はCLIがexit 2で拒否する。
10. Workspace main、カスタム指示文面、実PCグローバル`AGENTS.md`のmarker付き限定例外blockが一致し、host側のblock外bytesとより厳しい既存規則が変更されない。
11. 各診断実行の直前にGitHub mainの唯一のactive deployment recordを確認し、`tool.source_sha256`不一致時は診断fieldを信頼しない。

## 13. v2候補

運用実績で必要性を確認してから、content-free handoff statusのfield解析、unread件数、task status、report statusを検討する。これらはraw YAMLを開くため、source別schema、resource budget、allowlist、漏洩testを持つ別specとする。

自動修復、再起動、raw incident bundle、WebUI表示はv2にも自動的に含めない。
