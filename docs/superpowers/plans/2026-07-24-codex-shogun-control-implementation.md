# Codex-mediated Shogun Control Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Codex Desktopが、GitHubでレビュー・配備記録された固定profileだけを使って停止中のShogunを初回起動し、独立diagnosticsがhealthyの場合だけ既存承認済み入力経路へ新規taskを1回配送できるようにする。

**Architecture:** repo内では固定profile overlay、self-contained control snapshot source、独立consumer、tests、docsだけを実装する。reviewed main sourceをuser-local mode `0555` snapshotへ別checkpointで配備し、snapshot自身とCodex consumerの両方がGitHub mainの唯一のactive deployment recordを検証する。source merge、snapshot配備、deployment registry、Workspace/host policy、実起動、task配送を別checkpointに保つ。

**Tech Stack:** Bash、Python 3.10+ standard library、Bats、`unittest`、GNU Make、Git/GitHub、tmux、WSL2 Ubuntu、Claude Code CLI、OpenAI Codex CLI、PowerShell。

## Global Constraints

- 実装開始時と各deployment task開始時に、オンライン`workspace/main/codex/CODEX_DESKTOP_STARTUP.md`、`workspace/main/PROJECTS.md`、対象repositoryのdefault branch、`AGENTS.md`、Primary Docsを再取得する。
- Canonical repoは`https://github.com/sjinnouchi-ux/multi-agent-shogun`。設計baseは`52250dea0ba91316a87c1fa3c78703ce66c4259f`だが、実装branch作成時は最新`origin/main`を再取得し、設計specを含むことを確認する。
- 実装は`superpowers:using-git-worktrees`で作る専用worktree・branch `agent/codex-shogun-control`で行う。live path`/home/jinnouchi/multi-agent-shogun`を実装worktreeにしない。
- production control commandは次の完全token列だけである。

  ```text
  wsl.exe -d Ubuntu --cd /home/jinnouchi/multi-agent-shogun /home/jinnouchi/.local/libexec/shogun-codex-control start finance-planning-v1
  ```

- `wsl.exe`、`bash -lc`、`python3`、repo script、snapshot pathだけの短いprefixを許可しない。追加suffix、stdin payload、environment prefix、別profileはmutation前に拒否する。
- production snapshotは`/home/jinnouchi/.local/libexec/shogun-codex-control`のregular file一つ、owner`jinnouchi`、mode`0555`、最大1,048,576 bytes、symlink拒否である。
- control sourceはPython標準libraryだけをimportし、repo内module、plugin、dynamic config、local manifestをimportしない。
- snapshot自身が固定HTTPS host/pathからGitHub mainのcontrol work logを取得し、redirect、非200、oversize、marker/schema不正、active 0/複数、self hash不一致、runtime commit不一致をmutation前に拒否する。consumerも同じregistryを独立検証する。
- 固定profile以外のmodel設定を`config/settings.yaml`へ書かない。profile内容は`lib/cli_adapter.sh`とcontrol sourceのimmutable constantだけに置き、双方の一致をtestする。
- model mappingは次のexact値である。

  | Role | CLI | Model | Effort |
  | --- | --- | --- | --- |
  | shogun | claude | claude-opus-4-8 | high |
  | oometsuke | claude | claude-opus-4-8 | high |
  | karo | codex | gpt-5.6-terra | high |
  | gunshi | codex | gpt-5.6-sol | max |
  | ashigaru1-3 | codex | gpt-5.6-sol | high |
  | ashigaru4-7 | codex | gpt-5.6-terra | high |

- Codex CLIは`--model`とone-shot `-c model_reasoning_effort='"<effort>"'`で固定する。user/global configを書き換えない。
- FABLE 5はmodel IDではない。将軍の統括責務と大目付の独立監査責務はtask配送時のguardへ明記する。
- launcherは引数なしで一度だけ実行し、`-c`/`--clean`を渡さない。既存queue/dashboardをcontrol自身が読まず、削除・上書きしない。
- repository dirty、session存在、dependency不足、CLI不足、profile不一致ではstartしない。controlは`git clean`、stash、checkout、delete、package install、OAuth/login、permission承認を行わない。
- launcher開始後のtimeout、nonzero、partial readinessは`indeterminate`とし、controlはstop、kill、restart、repair、cleanupを行わない。
- stdoutはASCII JSON一件、stderrは空。task、queue、report、log、pane本文、秘密値、credential、command line、任意pathを含めない。
- source PR、snapshot配備、active deployment record PR、Workspace policy PR、host marker、persistent prefix approval、実起動、task配送に個別checkpointを置く。
- testはSKIP 1件以上を失敗とする。deployment hostの最終gateは`make test-no-skip`でtest count > 0、skip 0、exit 0である。
- `kakeibo-liff`、`mgmt-terminal`、Supabase、Cloud Run/IAM、LINE/LIFF、Google Sheets、freee、production deployはこの実装計画の変更対象外である。

## File Structure

### Shogun source PR

- Create `scripts/codex_shogun_control.py`: fixed CLI、self hash、GitHub registry、preflight、bounded launcher、readiness、sanitized JSON。
- Modify `lib/cli_adapter.sh`: marker一致時だけfixed profile overlayを返し、Codex effortをone-shot configへ反映。
- Modify `tests/unit/test_cli_adapter.bats`: profile mapping、unknown marker/role、normal path regression、command quoting。
- Create `tests/unit/test_codex_shogun_control.py`: pure unit、hostile registry、schema、preflight、timeout、leakage tests。
- Create `tests/unit/test_codex_shogun_control.bats`: Python unit、compile、suffix/stdio wrapper。
- Create `tests/integration/test_codex_shogun_control_start.py`: injected context、unique tmux socket、mock CLI/launcher integration。
- Create `tests/integration/test_codex_shogun_control_start.bats`: deployment-host integration wrapper。
- Create `tests/contract/codex_shogun_control_consumer.py`: GitHub provenance/process/JSONの独立fail-closed consumer。
- Create `tests/contract/test_codex_shogun_control_consumer.py`: hostile registry/output/process fixtures。
- Create `scripts/manage_codex_shogun_control_snapshot.py`: fixed control snapshot専用のinitial install/atomic rollback lifecycle helper。
- Create `tests/unit/test_manage_codex_shogun_control_snapshot.py`: owner/mode/hash/concurrency/TOCTOU/rollback tests。
- Create `docs/codex-shogun-control.md`: operator contract、deployment、rollback、non-goals。
- Create `docs/superpowers/plans/2026-07-24-codex-shogun-control-work-log.md`: marker付きschema-1 deployment registry。初期source PRではactive 0件。
- Modify `docs/github-boundary-operation.md`: controlはsource merge後もpolicy未有効、diagnostics healthy後だけtask intakeと明記。
- Modify `.gitignore`:上記exact Python/docs pathsだけをallowlist。
- Modify `Makefile`: control unit/contract/integrationを`test-no-skip`へ追加し、`codex`をhost prerequisiteへ追加。

### Post-source deployment PR

- Modify `docs/superpowers/plans/2026-07-24-codex-shogun-control-work-log.md`:唯一のactive recordを追加。

### Workspace policy PR

- Modify `workspace/codex/CODEX_DESKTOP_STARTUP.md`: marker付きcontrol例外。
- Modify `workspace/codex/CODEX_DESKTOP_CUSTOM_INSTRUCTIONS.md`:同一marker blockとverification bullets。
- Modify `workspace/codex/work_log.md`:sanitized enablement evidence。

### Host-only state

- Install `/home/jinnouchi/.local/libexec/shogun-codex-control`。
- Modify `C:\Users\jinnouchi\.codex\AGENTS.md`: marker blockのみ。
- Approve only the complete command token sequence。

---

### Task 1: Implement the immutable model profile overlay

**Files:**

- Modify: `lib/cli_adapter.sh` around `_cli_adapter_shell_quote()`, `get_cli_type()`, `build_cli_command()`, `get_agent_model()`, and `get_agent_effort()`
- Modify: `tests/unit/test_cli_adapter.bats` setup/teardown and a new control-profile section

**Interfaces:**

- Consumes: child-only `SHOGUN_CODEX_CONTROL_PROFILE`.
- Produces: `_cli_adapter_control_profile_value(field, agent_id)` returning exact `type|model|effort`; existing public functions keep their names and normal behavior.

- [ ] **Step 1: Write RED profile tests**

Add `unset SHOGUN_CODEX_CONTROL_PROFILE` to both setup and teardown. Add tests that source the adapter with deliberately conflicting settings and assert the fixed matrix wins:

```bash
@test "finance-planning-v1 returns the exact eleven-agent profile" {
    export SHOGUN_CODEX_CONTROL_PROFILE=finance-planning-v1
    load_adapter_with "${TEST_TMP}/settings_mixed.yaml"

    [ "$(get_cli_type shogun)" = claude ]
    [ "$(get_agent_model shogun)" = claude-opus-4-8 ]
    [ "$(get_agent_effort shogun)" = high ]
    [ "$(get_cli_type oometsuke)" = claude ]
    [ "$(get_agent_model oometsuke)" = claude-opus-4-8 ]
    [ "$(get_agent_effort oometsuke)" = high ]
    [ "$(get_cli_type karo)" = codex ]
    [ "$(get_agent_model karo)" = gpt-5.6-terra ]
    [ "$(get_agent_effort karo)" = high ]
    [ "$(get_cli_type gunshi)" = codex ]
    [ "$(get_agent_model gunshi)" = gpt-5.6-sol ]
    [ "$(get_agent_effort gunshi)" = max ]

    for id in ashigaru1 ashigaru2 ashigaru3; do
        [ "$(get_cli_type "$id")" = codex ]
        [ "$(get_agent_model "$id")" = gpt-5.6-sol ]
        [ "$(get_agent_effort "$id")" = high ]
    done
    for id in ashigaru4 ashigaru5 ashigaru6 ashigaru7; do
        [ "$(get_cli_type "$id")" = codex ]
        [ "$(get_agent_model "$id")" = gpt-5.6-terra ]
        [ "$(get_agent_effort "$id")" = high ]
    done
}

@test "control profile emits one-shot Codex reasoning config" {
    export SHOGUN_CODEX_CONTROL_PROFILE=finance-planning-v1
    load_adapter_with "${TEST_TMP}/settings_none.yaml"
    run build_cli_command gunshi
    [ "$status" -eq 0 ]
    [[ "$output" == *"--model gpt-5.6-sol"* ]]
    [[ "$output" == *"model_reasoning_effort=\"max\""* ]]
}

@test "unknown control profile and role fail closed" {
    export SHOGUN_CODEX_CONTROL_PROFILE=unknown
    load_adapter_with "${TEST_TMP}/settings_none.yaml"
    run get_cli_type shogun
    [ "$status" -ne 0 ]

    export SHOGUN_CODEX_CONTROL_PROFILE=finance-planning-v1
    run get_cli_type ashigaru8
    [ "$status" -ne 0 ]
}
```

- [ ] **Step 2: Run RED tests**

Run:

```bash
bats tests/unit/test_cli_adapter.bats --filter 'control profile|finance-planning-v1'
```

Expected: FAIL because the marker is not implemented and settings values win.

- [ ] **Step 3: Add the minimal fixed overlay**

Add this pure-shell helper before the public API and call it first from `get_cli_type()`, `get_agent_model()`, and `get_agent_effort()`:

```bash
_cli_adapter_control_profile_value() {
    local field="${1:-}"
    local agent_id="${2:-}"
    local profile="${SHOGUN_CODEX_CONTROL_PROFILE:-}"

    [[ -n "$profile" ]] || return 1
    [[ "$profile" == "finance-planning-v1" ]] || return 2

    case "${field}:${agent_id}" in
        type:shogun|type:oometsuke) printf '%s\n' claude ;;
        type:karo|type:gunshi|type:ashigaru[1-7]) printf '%s\n' codex ;;
        model:shogun|model:oometsuke) printf '%s\n' claude-opus-4-8 ;;
        model:karo|model:ashigaru[4-7]) printf '%s\n' gpt-5.6-terra ;;
        model:gunshi|model:ashigaru[1-3]) printf '%s\n' gpt-5.6-sol ;;
        effort:gunshi) printf '%s\n' max ;;
        effort:shogun|effort:oometsuke|effort:karo|effort:ashigaru[1-7])
            printf '%s\n' high
            ;;
        *) return 2 ;;
    esac
}
```

Use this exact entry pattern in each getter so an absent marker falls through, while any present invalid marker fails:

```bash
local control_value control_status
if control_value=$(_cli_adapter_control_profile_value type "$agent_id"); then
    printf '%s\n' "$control_value"
    return 0
else
    control_status=$?
    if [[ -n "${SHOGUN_CODEX_CONTROL_PROFILE:-}" ]]; then
        return "$control_status"
    fi
fi
```

Change only `type` to `model` or `effort` in the corresponding getter. In `build_cli_command()`, do not read `thinking` from settings when the control marker is active. For the Codex case only under the fixed marker, append a shell-quoted one-shot config:

```bash
if [[ -n "$effort" && "${SHOGUN_CODEX_CONTROL_PROFILE:-}" == "finance-planning-v1" ]]; then
    local reasoning_config
    reasoning_config=$(_cli_adapter_shell_quote "model_reasoning_effort=\"$effort\"")
    cmd="$cmd -c $reasoning_config"
fi
```

- [ ] **Step 4: Run GREEN and regression tests**

Run:

```bash
bats tests/unit/test_cli_adapter.bats --filter 'control profile|finance-planning-v1'
bats tests/unit/test_cli_adapter.bats
```

Expected: all selected and full adapter tests PASS, skip 0. Tests without the marker must retain their previous exact outputs.

- [ ] **Step 5: Commit the isolated overlay**

```bash
git add lib/cli_adapter.sh tests/unit/test_cli_adapter.bats
git commit -m "feat: add fixed Codex Shogun control profile"
```

### Task 2: Freeze the control CLI, registry, self-hash, and JSON schema

**Files:**

- Create: `scripts/codex_shogun_control.py`
- Create: `tests/unit/test_codex_shogun_control.py`
- Create: `tests/unit/test_codex_shogun_control.bats`
- Create: `docs/superpowers/plans/2026-07-24-codex-shogun-control-work-log.md`
- Modify: `.gitignore`

**Interfaces:**

- Produces: `Issue`, `CommandResult`, `ProfileEntry`, `DeploymentRecord`, `ControlContext`, `parse_argv()`, `calculate_source_sha256()`, `fetch_registry_bytes()`, `validate_deployment_registry()`, `build_failure_document()`, `validate_document()`, `render_document()`, `execute_control()`, `main()`.
- Consumer-visible exact top-level keys: `schema_version, generated_at, ok, action, profile, state, tool, repository, readiness, errors, warnings`.

- [ ] **Step 1: Allowlist only the new exact paths**

Add:

```gitignore
!scripts/codex_shogun_control.py
!scripts/manage_codex_shogun_control_snapshot.py
!tests/unit/test_codex_shogun_control.py
!tests/unit/test_manage_codex_shogun_control_snapshot.py
!tests/integration/test_codex_shogun_control_start.py
!tests/contract/codex_shogun_control_consumer.py
!tests/contract/test_codex_shogun_control_consumer.py
!docs/codex-shogun-control.md
```

Run `git check-ignore -v` for all eight paths. Expected: exit 1 and no output.

- [ ] **Step 2: Write RED CLI, self-hash, registry, and schema tests**

The first test module must load the source by path and cover these exact contracts:

```python
class CliContractTests(unittest.TestCase):
    def test_only_fixed_vector_is_accepted(self) -> None:
        self.assertEqual(
            module.parse_argv(("start", "finance-planning-v1")),
            "finance-planning-v1",
        )
        for argv in (
            (), ("start",), ("start", "other"),
            ("start", "finance-planning-v1", "extra"),
        ):
            with self.subTest(argv=argv), self.assertRaises(module.ArgumentRejected):
                module.parse_argv(argv)

    def test_profile_matrix_is_exact(self) -> None:
        self.assertEqual(tuple(module.PROFILE), module.AGENT_IDS)
        self.assertEqual(module.PROFILE["shogun"].model, "claude-opus-4-8")
        self.assertEqual(module.PROFILE["oometsuke"].model, "claude-opus-4-8")
        self.assertEqual(module.PROFILE["gunshi"].effort, "max")
        self.assertEqual(module.PROFILE["karo"].model, "gpt-5.6-terra")

    def test_failure_document_has_exact_order(self) -> None:
        document = module.build_failure_document("argument_rejected")
        self.assertEqual(tuple(document), module.TOP_LEVEL_KEYS)
        self.assertFalse(document["ok"])
        self.assertEqual(document["state"], "failed")
        module.validate_document(document)
```

Registry tests must reject duplicate JSON keys, wrong marker order/count, top-level key drift, record key drift, booleans in integer fields, non-lowercase SHA, wrong fixed URL/path/mode/profile/schema, active 0/multiple when `require_active=True`, redirect/non200/oversize fetches, source hash mismatch, and runtime commit mismatch.

- [ ] **Step 3: Run RED tests**

```bash
python3 -m unittest -v tests.unit.test_codex_shogun_control.CliContractTests
```

Expected: FAIL because the source does not exist.

- [ ] **Step 4: Implement the fixed constants and types**

Use these exact constants and immutable types:

```python
SCHEMA_VERSION = 1
TOOL_VERSION = "1.0.0"
PROFILE_NAME = "finance-planning-v1"
SNAPSHOT_PATH = Path("/home/jinnouchi/.local/libexec/shogun-codex-control")
RUNTIME_ROOT = Path("/home/jinnouchi/multi-agent-shogun")
REGISTRY_HOST = "raw.githubusercontent.com"
REGISTRY_PATH = (
    "/sjinnouchi-ux/multi-agent-shogun/main/docs/superpowers/plans/"
    "2026-07-24-codex-shogun-control-work-log.md"
)
MAX_SOURCE_BYTES = 1_048_576
MAX_REGISTRY_BYTES = 131_072
AGENT_IDS = (
    "shogun", "karo", "ashigaru1", "ashigaru2", "ashigaru3",
    "ashigaru4", "ashigaru5", "ashigaru6", "ashigaru7",
    "gunshi", "oometsuke",
)
TOP_LEVEL_KEYS = (
    "schema_version", "generated_at", "ok", "action", "profile", "state",
    "tool", "repository", "readiness", "errors", "warnings",
)
TOOL_KEYS = ("version", "deployment", "source_sha256")
REPOSITORY_KEYS = (
    "canonical_remote_present", "branch_state", "head_matches_runtime_commit",
    "tracked_changes", "untracked_changes",
)
READINESS_KEYS = (
    "sessions_present", "agents_observed", "panes_alive",
    "cli_ready", "watchers_ready",
)
DEPLOYMENT_KEYS = (
    "status", "source_repo", "source_commit", "source_path",
    "source_sha256", "runtime_commit", "deployed_at", "snapshot_path",
    "snapshot_mode", "contract_schema_version", "profile",
)

@dataclass(frozen=True, slots=True)
class ProfileEntry:
    cli: str
    model: str
    effort: str

@dataclass(frozen=True, slots=True)
class DeploymentRecord:
    source_commit: str
    source_sha256: str
    runtime_commit: str
```

`calculate_source_sha256()` must use `O_NOFOLLOW|O_CLOEXEC|O_NONBLOCK`, require regular file, effective-user ownership, exact mode`0555`, bounded read, and identical device/inode/size/mtime/mode before and after.

`fetch_registry_bytes()` must use `http.client.HTTPSConnection` with the fixed host/path, default TLS verification, fixed `GET`, timeout 3 seconds, status 200, no redirect handling, and `MAX_REGISTRY_BYTES+1` bounded read. It must not accept URL input.

- [ ] **Step 5: Create the inactive registry skeleton**

```markdown
# Codex Shogun Control Work Log

- State: source implementation not deployed
- Evidence boundary: no raw control JSON, pane, queue, report, log, task, or secret is recorded here

<!-- BEGIN CODEX_SHOGUN_CONTROL_DEPLOYMENTS_V1 -->
{"schema_version":1,"deployments":[]}
<!-- END CODEX_SHOGUN_CONTROL_DEPLOYMENTS_V1 -->
```

Unit validation allows active 0 for the source PR, while the production invocation and consumer require exactly one active record.

- [ ] **Step 6: Implement exact document invariants**

Use fixed enums:

```python
STATES = ("ready", "failed", "indeterminate")
BRANCH_STATES = ("main", "other", "detached", "unknown")
COMPONENTS = ("control", "source", "registry", "repository", "dependency", "tmux", "process", "launcher")
ERROR_CODES = (
    "argument_rejected", "source_rejected", "registry_untrusted",
    "boundary_rejected", "canonical_remote_missing", "runtime_commit_mismatch",
    "repository_dirty", "session_present", "dependency_unavailable",
    "cli_unavailable", "model_profile_invalid", "launcher_failed",
    "launcher_timeout", "command_output_limited", "session_missing",
    "agent_count_mismatch", "pane_dead", "cli_mismatch",
    "watcher_missing", "internal_error",
)
```

Required invariants:

- `ok` is true iff `state=ready`, errors empty, all readiness counts are `2,11,11,11,11`, repository is canonical/main/head-match/zero changes.
- `state=failed` means launcher was not invoked.
- any failure after launcher invocation returns `state=indeterminate`.
- issue arrays contain only `{code,component,agent}` fixed keys, are deduplicated, sorted, and bounded at 64.
- rendered bytes are one compact ASCII JSON object plus one LF; stderr remains empty.

- [ ] **Step 7: Run GREEN contract tests and commit**

```bash
python3 -m unittest -v tests.unit.test_codex_shogun_control.CliContractTests
python3 -m py_compile scripts/codex_shogun_control.py tests/unit/test_codex_shogun_control.py
git add .gitignore scripts/codex_shogun_control.py tests/unit/test_codex_shogun_control.py tests/unit/test_codex_shogun_control.bats docs/superpowers/plans/2026-07-24-codex-shogun-control-work-log.md
git commit -m "feat: freeze Shogun control contracts"
```

### Task 3: Add fail-closed repository, session, and dependency preflight

**Files:**

- Modify: `scripts/codex_shogun_control.py`
- Modify: `tests/unit/test_codex_shogun_control.py`

**Interfaces:**

- Produces: `BoundedRunner.run(argv, *, cwd, env, timeout)`, `collect_repository()`, `require_sessions_absent()`, `require_dependencies_ready()`, `build_launcher_environment()`.

- [ ] **Step 1: Write RED fake-runner tests**

Add table-driven tests for canonical remote, exact main branch, exact active runtime commit, tracked/untracked zero, absent target sessions, regular tracked launcher/dependency files, `.venv/bin/python3` with PyYAML, and Claude/Codex CLI version probes. Every negative case must assert the launcher fake was not called.

```python
def test_dirty_repository_blocks_before_launcher(self) -> None:
    runner = FakeRunner(repository(untracked_changes=1))
    rc, document = module.execute_control(
        ("start", module.PROFILE_NAME),
        context=fake_context(),
        runner=runner,
        registry_fetcher=valid_registry,
    )
    self.assertEqual(rc, 3)
    self.assertEqual(document["state"], "failed")
    self.assertIn("repository_dirty", issue_codes(document))
    self.assertEqual(runner.launcher_calls, 0)
```

- [ ] **Step 2: Run RED preflight tests**

```bash
python3 -m unittest -v tests.unit.test_codex_shogun_control.PreflightTests
```

Expected: FAIL because collectors are absent.

- [ ] **Step 3: Implement the bounded runner and repository checks**

The runner uses `subprocess.Popen(..., shell=False, stdin=DEVNULL, start_new_session=False)`, a fixed argv-template allowlist, per-stream limit 65,536 bytes, and per-command timeout 2 seconds. It may invoke only fixed absolute Git/tmux/pgrep/bash paths, the fixed repo venv Python path, and the resolved Claude/Codex binaries after ownership/type checks.

Repository commands are exact:

```text
/usr/bin/git rev-parse --show-toplevel
/usr/bin/git remote -v
/usr/bin/git symbolic-ref --quiet --short HEAD
/usr/bin/git rev-parse --verify HEAD
/usr/bin/git status --porcelain=v1 -z --untracked-files=no
/usr/bin/git ls-files --others --exclude-standard -z
/usr/bin/git ls-files -s -- shutsujin_departure.sh lib/cli_adapter.sh lib/cli_readiness.sh requirements.txt
```

Reject if cwd/top-level differs from fixed runtime root, canonical fetch remote is absent, branch is not`main`, HEAD differs from active`runtime_commit`, any status count is nonzero, or a fixed file is not a regular tracked blob. Output counts only, never names/diffs.

- [ ] **Step 4: Implement dependency checks without installation or login**

Exact probes:

```text
/home/jinnouchi/multi-agent-shogun/.venv/bin/python3 -I -c import yaml
(resolve_cli_path("claude"), "--version")
(resolve_cli_path("codex"), "--version")
/usr/bin/tmux -V
```

Validate the resolved CLI paths are regular non-symlink executable files outside the runtime repo. Validate all profile model/effort strings against immutable allowlists. Do not call OAuth/login, model chat, package manager, network provider API, or write any config.

`build_launcher_environment()` copies the existing process environment opaquely without enumerating or logging values, removes any inherited `SHOGUN_CODEX_CONTROL_PROFILE`, then adds exactly `SHOGUN_CODEX_CONTROL_PROFILE=finance-planning-v1`. It must not persist or print the environment.

- [ ] **Step 5: Run GREEN tests and commit**

```bash
python3 -m unittest -v tests.unit.test_codex_shogun_control.PreflightTests
python3 -m unittest -v tests.unit.test_codex_shogun_control
git add scripts/codex_shogun_control.py tests/unit/test_codex_shogun_control.py
git commit -m "feat: add Shogun control preflight"
```

### Task 4: Execute the fixed launcher once and prove sanitized readiness

**Files:**

- Modify: `scripts/codex_shogun_control.py`
- Modify: `tests/unit/test_codex_shogun_control.py`
- Create: `tests/integration/test_codex_shogun_control_start.py`
- Create: `tests/integration/test_codex_shogun_control_start.bats`

**Interfaces:**

- Produces: `run_fixed_launcher()`, `collect_readiness()`, `ReadinessSnapshot`.
- Consumes: successful Task 3 preflight and child-only profile environment.

- [ ] **Step 1: Write RED launcher-state tests**

Cover launcher called exactly once with:

```python
(
    "/usr/bin/bash",
    "/home/jinnouchi/multi-agent-shogun/shutsujin_departure.sh",
)
```

and no third argument. Assert fixed cwd, stdin closed, marker present, timeout 120 seconds, bounded output not returned. Add cases for nonzero, timeout, truncated output, one session only, agent count 10/12, dead pane, wrong CLI role, and watcher count 0/2. All post-invocation failures must be`indeterminate` and must not call cleanup/kill/restart.

- [ ] **Step 2: Run RED tests**

```bash
python3 -m unittest -v tests.unit.test_codex_shogun_control.LauncherTests
```

Expected: FAIL because launch/readiness functions are absent.

- [ ] **Step 3: Implement fixed launch and readiness projection**

After launcher exit 0, collect only fixed projections:

```text
/usr/bin/tmux list-sessions -F #{session_name}
/usr/bin/tmux list-panes -a -F <fixed enum projection of session_name,@agent_id,@agent_cli,pane_dead>
/usr/bin/pgrep -fc <fixed watcher pattern for each of 11 agents>
```

Expected mapping is Claude for`shogun,oometsuke` and Codex for the other nine. Require sessions exactly`shogun,multiagent`, agents exactly 11, all panes alive, and exactly one watcher per agent. Do not inspect pane title/content, command line, PID, queue, report, or log.

- [ ] **Step 4: Add an injected-context real tmux integration test**

The Python integration harness must create a unique tmux socket under a temporary directory, use a temporary fake runtime root and mock launcher, and call an imported test seam such as:

```python
context = dataclasses.replace(
    module.PRODUCTION_CONTEXT,
    runtime_root=temp_root,
    launcher=temp_root / "mock_launcher.sh",
    tmux_argv=("/usr/bin/tmux", "-L", socket_name),
)
```

The mock launcher creates exactly two isolated sessions and 11 sleep-based panes, sets only`@agent_id` and`@agent_cli`, and starts mock watcher processes using the fixed test context. It must never touch live`shogun`/`multiagent` sessions. Teardown may terminate only the unique test socket/process group it created.

- [ ] **Step 5: Run GREEN unit and integration tests**

```bash
python3 -m unittest -v tests.unit.test_codex_shogun_control.LauncherTests
bats tests/integration/test_codex_shogun_control_start.bats
```

Expected: PASS, tests > 0, skip 0, no live session names used.

- [ ] **Step 6: Commit**

```bash
git add scripts/codex_shogun_control.py tests/unit/test_codex_shogun_control.py tests/integration/test_codex_shogun_control_start.py tests/integration/test_codex_shogun_control_start.bats
git commit -m "feat: start fixed Shogun profile with bounded readiness"
```

### Task 5: Add the independent consumer, snapshot lifecycle, docs, and no-skip gate

**Files:**

- Create: `tests/contract/codex_shogun_control_consumer.py`
- Create: `tests/contract/test_codex_shogun_control_consumer.py`
- Create: `scripts/manage_codex_shogun_control_snapshot.py`
- Create: `tests/unit/test_manage_codex_shogun_control_snapshot.py`
- Create: `docs/codex-shogun-control.md`
- Modify: `docs/github-boundary-operation.md`
- Modify: `Makefile`

**Interfaces:**

- Consumer produces `ConsumerDecision(action, reason, fallback_allowed, document)` where every rejected decision has`action="stop_without_fallback"` and`fallback_allowed=False`.
- Lifecycle helper accepts only `install-initial --source <reviewed-blob>` or hash-gated rollback for the fixed control snapshot path; it is never persistently approved.

- [ ] **Step 1: Write RED hostile consumer tests**

Test GitHub fetch failure, redirect, marker missing/duplicate/reversed, duplicate JSON keys, active 0/multiple, key/type/order drift, hash mismatch, runtime commit mismatch, nonzero process, timeout >=120 seconds, stderr nonempty, empty/partial/multiple/non-ASCII JSON, nested schema drift, issue invariant drift, and`state!=ready`. Assert no fallback callback is invoked.

- [ ] **Step 2: Implement the consumer contract**

The consumer validates the raw GitHub main work log before returning the fixed command token tuple. It then validates process metadata and the entire nested output document, recomputes`ok/state` invariants, and compares`tool.source_sha256` with the sole active record. It must not execute shell, read live runtime files, or contain a raw-state fallback.

- [ ] **Step 3: Write RED snapshot lifecycle tests**

Cover fixed destination, user ownership, regular source/destination, mode`0555`, size limit, `O_NOFOLLOW`, same-directory atomic rename, fsync, concurrent first install, already-matching idempotence, wrong existing hash refusal, symlink refusal, pre-commit failure restoration, post-commit indeterminate classification, and exact temporary cleanup.

- [ ] **Step 4: Implement the fixed lifecycle helper**

Keep destination and temp prefix immutable:

```python
SNAPSHOT_PATH = Path("/home/jinnouchi/.local/libexec/shogun-codex-control")
INSTALL_TEMP_PREFIX = ".shogun-codex-control.install."
ROLLBACK_TEMP_PREFIX = ".shogun-codex-control.rollback."
```

Exit 0 means exact verified install/rollback; exit 3 means no committed change and exact cleanup; exit 4 means commit/cleanup/durability state is indeterminate and requires a new recovery task. Never use`sudo`, system directories, local manifest, or automatic retry.

- [ ] **Step 5: Extend the deployment-host gate**

Add`codex` to required commands and include the control integration wrapper:

```make
bats --formatter tap tests/*.bats tests/unit/ \
  tests/integration/test_codex_diagnostics_tmux.bats \
  tests/integration/test_codex_shogun_control_start.bats >"$$tap" 2>&1
```

Retain the existing test-count, exit, and skip-zero assertions.

- [ ] **Step 6: Write operator documentation**

Document the exact command, profile table, internal/external registry checks, result schema, no-clean/no-restart behavior, deployment order, active record schema, diagnostics-after-control gate, and rollback order. State explicitly that source merge alone grants no runtime permission.

- [ ] **Step 7: Run GREEN tests and commit**

```bash
python3 -m unittest -v tests.contract.test_codex_shogun_control_consumer
python3 -m unittest -v tests.unit.test_manage_codex_shogun_control_snapshot
python3 -m py_compile tests/contract/codex_shogun_control_consumer.py scripts/manage_codex_shogun_control_snapshot.py
make test
make lint
make check
git add tests/contract/codex_shogun_control_consumer.py tests/contract/test_codex_shogun_control_consumer.py scripts/manage_codex_shogun_control_snapshot.py tests/unit/test_manage_codex_shogun_control_snapshot.py docs/codex-shogun-control.md docs/github-boundary-operation.md Makefile
git commit -m "test: complete Shogun control trust boundary"
```

### Task 6: Verify and review the source implementation PR

**Files:** all Task 1-5 source-PR files only.

- [ ] Re-run online canonical discovery and rebase/merge only by the repository's approved non-destructive policy if`origin/main` advanced.
- [ ] Run full verification:

```bash
python3 -m unittest -v tests.unit.test_codex_shogun_control
python3 -m unittest -v tests.contract.test_codex_shogun_control_consumer
python3 -m unittest -v tests.unit.test_manage_codex_shogun_control_snapshot
bats tests/unit/test_cli_adapter.bats
bats tests/integration/test_codex_shogun_control_start.bats
make test
make lint
make check
git diff --check
git status --short --branch
```

Expected: all invoked tests pass, skip 0, no generated diff, no uncommitted files.

- [ ] Run the repository-pinned secret scan procedure and verify no task/queue/report/log/pane/credential fixture entered the diff.
- [ ] Use`superpowers:requesting-code-review` for an independent spec-compliance and security review. Fix findings with new tests before re-review.
- [ ] Push`agent/codex-shogun-control` and open a separate Draft PR against`main`. Do not merge the design PR and implementation PR as one commit.
- [ ] Obtain explicit user approval before merging the source PR. Source merge does not authorize snapshot placement or start.

### Task 7: Deploy the reviewed snapshot and register one active deployment

**Checkpoint:** Requires a new explicit user approval after source PR merge.

- [ ] On the real`jinnouchi` WSL2 Ubuntu boundary, re-fetch startup/PROJECTS/Shogun main and run the existing fixed diagnostics only through its approved command. Validate provenance/schema independently; report only sanitized enum/count status.
- [ ] If tracked or untracked count is nonzero, stop. Reconciliation is a separate explicit host-maintenance task; do not print names/content and do not auto-clean/stash/checkout/delete.
- [ ] Update the live runtime repo to the exact reviewed source merge commit only after it is clean and sessions are absent. Verify branch`main`, canonical remote, HEAD, fixed files, venv/PyYAML, Claude/Codex availability without login or install.
- [ ] Run`make test-no-skip` on the deployment host. Require tests > 0, skip 0, exit 0.
- [ ] Extract`main:scripts/codex_shogun_control.py` to a temporary regular blob, calculate its SHA-256 privately, and invoke the reviewed lifecycle helper`install-initial` for the fixed destination.
- [ ] Verify owner, mode`0555`, source/deployed hash match, exact argv rejection, stderr empty, ASCII schema. Do not start Shogun yet because no active registry exists.
- [ ] Create a new registry-only branch. Replace the empty array with exactly one active record using these exact ordered keys:

  Derive `SOURCE_COMMIT` from the merged source PR commit, `SOURCE_SHA256` from the verified reviewed blob, and `DEPLOYED_AT` from the successful host placement time in UTC seconds. Validate all three before rendering; do not accept operator-entered free text.

```json
{"schema_version":1,"deployments":[{"status":"active","source_repo":"https://github.com/sjinnouchi-ux/multi-agent-shogun","source_commit":"${SOURCE_COMMIT}","source_path":"scripts/codex_shogun_control.py","source_sha256":"${SOURCE_SHA256}","runtime_commit":"${SOURCE_COMMIT}","deployed_at":"${DEPLOYED_AT}","snapshot_path":"/home/jinnouchi/.local/libexec/shogun-codex-control","snapshot_mode":"0555","contract_schema_version":1,"profile":"finance-planning-v1"}]}
```

- [ ] Run the consumer registry validator, commit only the work log, open a separate PR, obtain review and explicit user approval, merge, then re-fetch raw GitHub main and verify sole active record/hash.

### Task 8: Enable Workspace and host policy with the exact command only

**Checkpoint:** Requires the Task 7 active record on GitHub main and a new explicit user approval.

- [ ] Create a clean Workspace branch from current`origin/main`; re-read its current instructions.
- [ ] Add the same marker block to`CODEX_DESKTOP_STARTUP.md` and the`Paste This Text` portion of`CODEX_DESKTOP_CUSTOM_INSTRUCTIONS.md`:

```markdown
<!-- BEGIN CODEX_SHOGUN_CONTROL_V1 -->
### Codex-mediated Shogun fixed control exception

Immediately before each invocation, fetch GitHub main raw
`https://raw.githubusercontent.com/sjinnouchi-ux/multi-agent-shogun/main/docs/superpowers/plans/2026-07-24-codex-shogun-control-work-log.md`, validate its single schema-version-1 registry and exactly one active deployment, and require its source SHA-256 to match the returned `tool.source_sha256`.

Only this complete command is eligible for persistent argv-prefix permission:

`wsl.exe -d Ubuntu --cd /home/jinnouchi/multi-agent-shogun /home/jinnouchi/.local/libexec/shogun-codex-control start finance-planning-v1`

The command may start only when repository/session/dependency preflight passes. It may not accept suffixes, stdin payloads, environment overrides, other profiles, stop, restart, repair, cleanup, task delivery, queue/report/log/pane reads, credential reads, or settings changes. A failure after launcher invocation is indeterminate and requires a new explicit recovery task.

After control exit 0 and complete schema validation, run the existing fixed read-only diagnostics independently. Task delivery remains forbidden unless diagnostics provenance/schema pass, recomputed `overall=healthy`, and the existing approved Shogun input route is confirmed.
<!-- END CODEX_SHOGUN_CONTROL_V1 -->
```

- [ ] Update`codex/work_log.md` with only PR/commit/hash-match/test-count/skip-count evidence.
- [ ] Verify the two policy blocks are byte-identical, marker count exactly one, and no existing prohibition was removed. Open and review a separate Workspace PR; obtain explicit user approval before merge.
- [ ] After raw Workspace main verification, prepare a candidate host`AGENTS.md` that inserts only the same marker block. Use same-handle compare-and-swap with durable backup/readback; preserve all bytes outside the marker. If stale or restore is not provable, stop with permission disabled.
- [ ] Request persistent approval for the complete token list only. Never request a shorter prefix.
- [ ] Open a fresh Codex task and confirm it can fetch the active registry and is still unable to run suffix/other-profile variants.

### Task 9: Start, independently diagnose, and deliver the approved Finance planning task once

**Checkpoint:** Requires Task 8 completion. Control success alone does not authorize delivery.

- [ ] Immediately fetch and validate the control registry, execute only the complete control command, privately validate exit 0, elapsed <120 seconds, stderr empty, ASCII JSON, exact schema/order/invariants, `state=ready`, and source-hash match. Do not publish raw JSON.
- [ ] Immediately fetch and validate the existing diagnostics registry, execute only the existing fixed diagnostics command, independently validate its full schema/invariants, and recompute`overall`.
- [ ] If diagnostics is not`healthy`, or approved task input route cannot be confirmed without raw queue/pane/log/report access, do not send. Report the sanitized blocker.
- [ ] If both gates pass, classify the user's Finance request as`new`, prepend the existing new-task guard plus this fixed role guard, and deliver exactly once through the already-approved input route:

```text
将軍はFABLE 5の統括責務を担い、大目付はFABLE 5の独立最終監査を担ってください。家老だけが交通整理・最終受入を行い、軍師は設計監査・矛盾分析・QC/RCA、足軽は割当済み分析作業を担当してください。今回は要件定義、設計監査、段階的実装計画のみです。コード、migration、データ、IAM、外部設定、deploy、import、OAuth/APIを変更しないでください。
```

- [ ] Record only a sanitized one-delivery receipt/status. Do not include task body, queue, report, log, pane, secret, personal identifier, customer name, amount, account/card number, office ID, or LINE identifier in the status report.
- [ ] If control returns`indeterminate`, do not retry, stop, restart, repair, or deliver. Request a separate recovery decision.

## Rollback Order

1. Revoke the complete command permission first and verify a fresh task cannot invoke it.
2. Remove only the host marker with the same-handle durable compare-and-swap procedure; keep permission disabled if state is uncertain.
3. Revert the Workspace policy PR through a reviewed PR and verify raw main.
4. Mark the failing control deployment superseded in a registry-only PR; do not leave multiple active records.
5. With explicit user selection of a prior reviewed record, run the hash-gated lifecycle helper. Exit 3 stops with old bytes verified; exit 4 is indeterminate and requires separate recovery.
6. Do not automatically stop live sessions. Session handling is a separate explicit operational task.
7. Re-enablement requires a new reviewed deployment and policy task.

## Spec Coverage Map

| Design requirement | Implementation task |
| --- | --- |
| Exact command/profile/suffix rejection | Tasks 1-2, 8 |
| Claude Opus 4.8 + GPT-5.6 Sol/Terra mapping | Task 1 |
| Child-only overlay; no settings persistence | Tasks 1, 3 |
| Self hash and dual GitHub registry validation | Tasks 2, 5, 7-9 |
| Clean main/runtime commit/dependency/session preflight | Task 3 |
| No auto clean/install/login/restart/repair | Global Constraints, Tasks 3-4, 9 |
| One launcher invocation, no clean mode | Task 4 |
| Two sessions/11 agents/readiness/watchers | Task 4 |
| Fixed ASCII JSON and leakage prevention | Tasks 2, 4-5 |
| Source/deploy/registry/policy/start checkpoints | Tasks 6-9 |
| Deployment-host no-skip gate | Tasks 5, 7 |
| Atomic user-local snapshot lifecycle | Tasks 5, 7 |
| Diagnostics healthy remains delivery gate | Tasks 8-9 |
| FABLE 5 task responsibility and one delivery | Task 9 |
| Ordered non-automatic rollback | Task 5 and Rollback Order |

## Self-Review Checklist

- [ ] Every design spec section maps to at least one task above.
- [ ] 未解決のplaceholder表現や実装者判断へ丸投げするstepが残っていない。
- [ ] `finance-planning-v1`, exact model IDs, effort values, paths, command tokens, registry keys, and JSON keys are consistent throughout.
- [ ] No step authorizes direct queue/report/log/pane/credential reads.
- [ ] No step combines source merge, deployment, policy enablement, start, and delivery into one approval.
- [ ] Implementation begins only after Draft PR #28 is reviewed and merged or otherwise explicitly selected as the execution base.
