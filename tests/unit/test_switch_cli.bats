#!/usr/bin/env bats
# test_switch_cli.bats — switch_cli.sh ユニットテスト
# shogun-model-switch Skill テスト

# --- セットアップ ---

setup() {
    TEST_TMP="$(mktemp -d)"
    PROJECT_ROOT="$(cd "$(dirname "$BATS_TEST_FILENAME")/../.." && pwd)"
    RETAINED_SETTINGS_BACKUP=""
    RETAINED_RUNTIME_BACKUP_DIR=""

    # テスト用settings.yaml
    cat > "${TEST_TMP}/settings.yaml" << 'YAML'
cli:
  default: claude
  agents:
    karo:
      type: claude
      model: claude-sonnet-4-6
      thinking: true
    ashigaru1:
      type: claude
      model: claude-sonnet-4-6
      thinking: true
    ashigaru2:
      type: claude
      model: claude-sonnet-4-6
      thinking: false
    ashigaru3:
      type: codex
      model: gpt-5.3-codex-spark
    ashigaru5:
      type: claude
      model: claude-opus-4-6
      thinking: true
    gunshi:
      type: claude
      model: claude-opus-4-6
      thinking: true
YAML

    # cli_adapter.sh をロード（テスト用settings使用）
    export CLI_ADAPTER_SETTINGS="${TEST_TMP}/settings.yaml"
    source "${PROJECT_ROOT}/lib/cli_adapter.sh"
}

teardown() {
    if [[ -n "$RETAINED_SETTINGS_BACKUP" && "$RETAINED_SETTINGS_BACKUP" == /tmp/tmp.* ]]; then
        rm -f -- "$RETAINED_SETTINGS_BACKUP"
    fi
    if [[ -n "$RETAINED_RUNTIME_BACKUP_DIR" && "$RETAINED_RUNTIME_BACKUP_DIR" == /tmp/tmp.* ]]; then
        rm -f -- "$RETAINED_RUNTIME_BACKUP_DIR/runtime"
        rmdir -- "$RETAINED_RUNTIME_BACKUP_DIR" 2>/dev/null || true
    fi
    rm -rf "$TEST_TMP"
}

# =============================================================================
# resolve_pane テスト (switch_cli.sh 内の関数を直接テスト)
# =============================================================================

# resolve_pane は tmux に依存するため、関数定義のみ source して文字列生成テスト
load_resolve_pane() {
    # switch_cli.sh から resolve_pane のみ抽出（tmux コマンドはモック化）
    eval '
    resolve_pane() {
        local agent_id="$1"
        local pane_base="${MOCK_PANE_BASE:-0}"
        case "$agent_id" in
            shogun)     echo "shogun:main" ;;
            karo)       echo "multiagent:agents.$((pane_base + 0))" ;;
            ashigaru1)  echo "multiagent:agents.$((pane_base + 1))" ;;
            ashigaru2)  echo "multiagent:agents.$((pane_base + 2))" ;;
            ashigaru3)  echo "multiagent:agents.$((pane_base + 3))" ;;
            ashigaru4)  echo "multiagent:agents.$((pane_base + 4))" ;;
            ashigaru5)  echo "multiagent:agents.$((pane_base + 5))" ;;
            ashigaru6)  echo "multiagent:agents.$((pane_base + 6))" ;;
            ashigaru7)  echo "multiagent:agents.$((pane_base + 7))" ;;
            gunshi)     echo "multiagent:agents.$((pane_base + 8))" ;;
            *)          return 1 ;;
        esac
    }
    '
}

@test "resolve_pane: karo → multiagent:agents.0" {
    load_resolve_pane
    MOCK_PANE_BASE=0
    result=$(resolve_pane "karo")
    [ "$result" = "multiagent:agents.0" ]
}

@test "resolve_pane: ashigaru1 → multiagent:agents.1" {
    load_resolve_pane
    MOCK_PANE_BASE=0
    result=$(resolve_pane "ashigaru1")
    [ "$result" = "multiagent:agents.1" ]
}

@test "resolve_pane: ashigaru7 → multiagent:agents.7" {
    load_resolve_pane
    MOCK_PANE_BASE=0
    result=$(resolve_pane "ashigaru7")
    [ "$result" = "multiagent:agents.7" ]
}

@test "resolve_pane: gunshi → multiagent:agents.8" {
    load_resolve_pane
    MOCK_PANE_BASE=0
    result=$(resolve_pane "gunshi")
    [ "$result" = "multiagent:agents.8" ]
}

@test "resolve_pane: shogun → shogun:main" {
    load_resolve_pane
    MOCK_PANE_BASE=0
    result=$(resolve_pane "shogun")
    [ "$result" = "shogun:main" ]
}

@test "resolve_pane: unknown agent → return 1" {
    load_resolve_pane
    run resolve_pane "unknown"
    [ "$status" -eq 1 ]
}

@test "resolve_pane: pane_base=2 → offset applied" {
    load_resolve_pane
    MOCK_PANE_BASE=2
    result=$(resolve_pane "karo")
    [ "$result" = "multiagent:agents.2" ]
    result=$(resolve_pane "ashigaru3")
    [ "$result" = "multiagent:agents.5" ]
    result=$(resolve_pane "gunshi")
    [ "$result" = "multiagent:agents.10" ]
}

# =============================================================================
# settings.yaml 更新テスト（Python部分）
# =============================================================================

@test "update_settings: type変更でYAMLが正しく更新される" {
    # テスト用settings
    cp "${TEST_TMP}/settings.yaml" "${TEST_TMP}/settings_update.yaml"

    # Python直接実行でtype更新
    "${PROJECT_ROOT}/.venv/bin/python3" << PYEOF
import yaml

path = "${TEST_TMP}/settings_update.yaml"
with open(path, 'r') as f:
    data = yaml.safe_load(f) or {}

data['cli']['agents']['ashigaru1']['type'] = 'codex'
data['cli']['agents']['ashigaru1']['model'] = 'gpt-5.3-codex-spark'

with open(path, 'w') as f:
    yaml.dump(data, f, default_flow_style=False, allow_unicode=True)
PYEOF

    # 更新結果を検証
    export CLI_ADAPTER_SETTINGS="${TEST_TMP}/settings_update.yaml"
    source "${PROJECT_ROOT}/lib/cli_adapter.sh"

    result=$(get_cli_type "ashigaru1")
    [ "$result" = "codex" ]

    result=$(get_agent_model "ashigaru1")
    [ "$result" = "gpt-5.3-codex-spark" ]
}

@test "update_settings: model変更後にbuild_cli_commandが反映" {
    cp "${TEST_TMP}/settings.yaml" "${TEST_TMP}/settings_update2.yaml"

    "${PROJECT_ROOT}/.venv/bin/python3" << PYEOF
import yaml

path = "${TEST_TMP}/settings_update2.yaml"
with open(path, 'r') as f:
    data = yaml.safe_load(f) or {}

data['cli']['agents']['ashigaru1']['model'] = 'claude-opus-4-6'

with open(path, 'w') as f:
    yaml.dump(data, f, default_flow_style=False, allow_unicode=True)
PYEOF

    export CLI_ADAPTER_SETTINGS="${TEST_TMP}/settings_update2.yaml"
    source "${PROJECT_ROOT}/lib/cli_adapter.sh"

    result=$(build_cli_command "ashigaru1")
    [[ "$result" == *"claude-opus-4-6"* ]]
    [[ "$result" == *"--dangerously-skip-permissions"* ]]
}

@test "update_settings: thinking:false後のbuild_cli_commandにMAX_THINKING_TOKENS=0" {
    cp "${TEST_TMP}/settings.yaml" "${TEST_TMP}/settings_update3.yaml"

    "${PROJECT_ROOT}/.venv/bin/python3" << PYEOF
import yaml

path = "${TEST_TMP}/settings_update3.yaml"
with open(path, 'r') as f:
    data = yaml.safe_load(f) or {}

data['cli']['agents']['ashigaru1']['thinking'] = False

with open(path, 'w') as f:
    yaml.dump(data, f, default_flow_style=False, allow_unicode=True)
PYEOF

    export CLI_ADAPTER_SETTINGS="${TEST_TMP}/settings_update3.yaml"
    source "${PROJECT_ROOT}/lib/cli_adapter.sh"

    result=$(build_cli_command "ashigaru1")
    [[ "$result" == MAX_THINKING_TOKENS=0* ]]
}

# =============================================================================
# switch_cli.sh 引数パーステスト（--help, バリデーション）
# =============================================================================

@test "switch_cli.sh --help → usage表示 + exit 1" {
    run bash "${PROJECT_ROOT}/scripts/switch_cli.sh" --help
    [ "$status" -eq 1 ]
    [[ "$output" == *"Usage"* ]]
    [[ "$output" == *"opencode"* ]]
    [[ "$output" == *"openai/gpt-5.4-mini"* ]]
    [[ "$output" == *"--effort"* ]]
}

@test "switch_cli.sh -h → usage表示 + exit 1" {
    run bash "${PROJECT_ROOT}/scripts/switch_cli.sh" -h
    [ "$status" -eq 1 ]
    [[ "$output" == *"Usage"* ]]
}

@test "switch_cli.sh 引数なし → usage表示 + exit 1" {
    run bash "${PROJECT_ROOT}/scripts/switch_cli.sh"
    [ "$status" -eq 1 ]
    [[ "$output" == *"Usage"* ]]
}

@test "switch_cli.sh 不正type → エラー" {
    run bash "${PROJECT_ROOT}/scripts/switch_cli.sh" ashigaru1 --type invalid_cli
    [ "$status" -ne 0 ]
}

@test "switch_cli.sh 不正effort → エラー" {
    run bash "${PROJECT_ROOT}/scripts/switch_cli.sh" ashigaru1 --effort turbo
    [ "$status" -ne 0 ]
    [[ "$output" == *"Invalid effort"* ]]
}

@test "switch_cli validation: opencode type is accepted" {
    _cli_adapter_is_valid_cli "opencode"
    [ "$?" -eq 0 ]
}

@test "switch_cli validation: antigravity type and aliases are accepted" {
    _cli_adapter_is_valid_cli "antigravity"
    [ "$?" -eq 0 ]
    _cli_adapter_is_valid_cli "agy"
    [ "$?" -eq 0 ]
    _cli_adapter_is_valid_cli "gemini"
    [ "$?" -eq 0 ]
}

@test "switch_cli.sh provider-qualified model without --type on non-opencode agent → エラー" {
    run bash "${PROJECT_ROOT}/scripts/switch_cli.sh" ashigaru1 --model openai/gpt-5.4-mini
    [ "$status" -ne 0 ]
    [[ "$output" == *"provider-qualified model IDs are ambiguous without --type"* ]]
}

# =============================================================================
# get_model_display_name 統合テスト（switch_cli.sh が依存する表示名）
# =============================================================================

@test "display_name: 切替前後で表示名が正しく変わる" {
    # 元: Sonnet+T
    result=$(get_model_display_name "ashigaru1")
    [ "$result" = "Sonnet+T" ]

    # settings更新をシミュレート: Opus+T に
    cat > "${TEST_TMP}/settings_switched.yaml" << 'YAML'
cli:
  default: claude
  agents:
    ashigaru1:
      type: claude
      model: claude-opus-4-6
      thinking: true
YAML
    export CLI_ADAPTER_SETTINGS="${TEST_TMP}/settings_switched.yaml"
    source "${PROJECT_ROOT}/lib/cli_adapter.sh"

    result=$(get_model_display_name "ashigaru1")
    [ "$result" = "Opus+T" ]
}

@test "display_name: Codex → Claude切替で表示名更新" {
    # ashigaru3はCodex Spark
    result=$(get_model_display_name "ashigaru3")
    [ "$result" = "Spark" ]

    # Claude Sonnet+T に切替
    cat > "${TEST_TMP}/settings_codex_to_claude.yaml" << 'YAML'
cli:
  default: claude
  agents:
    ashigaru3:
      type: claude
      model: claude-sonnet-4-6
      thinking: true
YAML
    export CLI_ADAPTER_SETTINGS="${TEST_TMP}/settings_codex_to_claude.yaml"
    source "${PROJECT_ROOT}/lib/cli_adapter.sh"

    result=$(get_model_display_name "ashigaru3")
    [ "$result" = "Sonnet+T" ]
}

@test "display_name: thinking:false で +T が消える" {
    # ashigaru2は thinking:false
    result=$(get_model_display_name "ashigaru2")
    [ "$result" = "Sonnet" ]

    # ashigaru5は thinking:true
    result=$(get_model_display_name "ashigaru5")
    [ "$result" = "Opus+T" ]
}

# =============================================================================
# readiness transaction integration tests
# =============================================================================

setup_switch_cli_tmux_mock() {
    mkdir -p "$TEST_TMP/bin"
    export MOCK_TMUX_LOG="$TEST_TMP/tmux.log"
    : > "$MOCK_TMUX_LOG"

    cat > "$TEST_TMP/bin/tmux" <<'MOCK'
#!/usr/bin/env bash
printf '%s\n' "$*" >> "$MOCK_TMUX_LOG"

case "$1" in
    list-panes)
        echo '%1'
        ;;
    display-message)
        case "$*" in
            *'#{@agent_id}'*) echo ashigaru1 ;;
            *'#{pane_id}'*) echo '%1' ;;
            *'#{pane_current_command}'*) echo node ;;
            *'#{pane_title}'*) echo OldTitle ;;
        esac
        ;;
    show-options)
        case "$*" in
            *'@pane_state_override'*) echo "${MOCK_CLI_STATE:-unknown}" ;;
            *'@agent_cli'*) echo claude ;;
            *'@model_name'*) echo OldModel ;;
            *'@pane_base'*) echo 0 ;;
            *'pane-base-index'*) echo 0 ;;
        esac
        ;;
    set-option)
        if [[ "${MOCK_METADATA_FAIL_AT:-}" == model_name && "$*" == *'@model_name '* && "$*" != *'@model_name OldModel'* ]]; then
            exit 1
        fi
        if [[ "${MOCK_SIGNAL_AFTER_AGENT_CLI:-}" == 1 && "$*" == *'@agent_cli codex'* ]]; then
            kill -TERM "$PPID"
            sleep 0.1
        fi
        ;;
    capture-pane)
        echo '$'
        ;;
esac
exit 0
MOCK
    chmod +x "$TEST_TMP/bin/tmux"
}

setup_cp_restore_failure_mock() {
    cat > "$TEST_TMP/bin/cp" <<'MOCK'
#!/usr/bin/env bash
args=("$@")
dest="${args[${#args[@]}-1]}"
if [[ -n "${MOCK_CP_FAIL_DEST:-}" && "$dest" == "$MOCK_CP_FAIL_DEST" ]]; then
    exit 1
fi
exec /usr/bin/cp "$@"
MOCK
    chmod +x "$TEST_TMP/bin/cp"
}

setup_isolated_switch_project() {
    export ISOLATED_SWITCH_ROOT="$TEST_TMP/isolated-switch"
    mkdir -p "$ISOLATED_SWITCH_ROOT"/{scripts,lib,config,logs,.opencode/agents}
    cp "$PROJECT_ROOT/scripts/switch_cli.sh" "$ISOLATED_SWITCH_ROOT/scripts/"
    cp "$PROJECT_ROOT/lib/cli_adapter.sh" "$ISOLATED_SWITCH_ROOT/lib/"
    cp "$PROJECT_ROOT/lib/agent_registry.sh" "$ISOLATED_SWITCH_ROOT/lib/"
    cp "$PROJECT_ROOT/lib/agent_status.sh" "$ISOLATED_SWITCH_ROOT/lib/"
    cp "$PROJECT_ROOT/lib/cli_readiness.sh" "$ISOLATED_SWITCH_ROOT/lib/"
    cp "$TEST_TMP/settings.yaml" "$ISOLATED_SWITCH_ROOT/config/settings.yaml"
    ln -s "$PROJECT_ROOT/.venv" "$ISOLATED_SWITCH_ROOT/.venv"

    cat > "$ISOLATED_SWITCH_ROOT/.opencode/agents/ashigaru1.md" <<'MARKDOWN'
---
description: Sanitized readiness transaction fixture
mode: primary
---
fixture body
MARKDOWN
}

@test "switch_cli readiness failure restores settings and leaves pane metadata unchanged" {
    setup_switch_cli_tmux_mock
    cp "$TEST_TMP/settings.yaml" "$TEST_TMP/settings.before.yaml"

    run env \
        PATH="$TEST_TMP/bin:$PATH" \
        CLI_ADAPTER_SETTINGS="$TEST_TMP/settings.yaml" \
        SWITCH_CLI_LOG_FILE="$TEST_TMP/switch.log" \
        SHOGUN_TEST_MODE=1 \
        MOCK_CLI_STATE=unknown \
        SHOGUN_CLI_READINESS_TIMEOUT_SECONDS=0 \
        SHOGUN_CLI_READINESS_POLL_SECONDS=0 \
        SHOGUN_SWITCH_SHELL_POLL_SECONDS=0 \
        bash "$PROJECT_ROOT/scripts/switch_cli.sh" ashigaru1 \
            --type codex --model gpt-5.3-codex-spark

    [ "$status" -ne 0 ]
    cmp -s "$TEST_TMP/settings.before.yaml" "$TEST_TMP/settings.yaml"
    [[ "$output" == *"cli_readiness role=ashigaru1 state=unknown ready=false"* ]]
    [[ "$output" == *"cli_readiness overall=not_ready"* ]]
    ! grep -q 'set-option.*@agent_cli codex' "$MOCK_TMUX_LOG"
    ! grep -q 'set-option.*@model_name' "$MOCK_TMUX_LOG"
}

@test "switch_cli commits settings and pane metadata only after new CLI is ready" {
    setup_switch_cli_tmux_mock

    run env \
        PATH="$TEST_TMP/bin:$PATH" \
        CLI_ADAPTER_SETTINGS="$TEST_TMP/settings.yaml" \
        SWITCH_CLI_LOG_FILE="$TEST_TMP/switch.log" \
        SHOGUN_TEST_MODE=1 \
        MOCK_CLI_STATE=ready \
        SHOGUN_CLI_READINESS_TIMEOUT_SECONDS=0 \
        SHOGUN_CLI_READINESS_POLL_SECONDS=0 \
        SHOGUN_SWITCH_SHELL_POLL_SECONDS=0 \
        bash "$PROJECT_ROOT/scripts/switch_cli.sh" ashigaru1 \
            --type codex --model gpt-5.3-codex-spark

    [ "$status" -eq 0 ]
    [[ "$output" == *"cli_readiness role=ashigaru1 state=ready ready=true"* ]]
    [[ "$output" == *"cli_readiness overall=ready"* ]]
    grep -q 'set-option.*@agent_cli codex' "$MOCK_TMUX_LOG"
    grep -q 'set-option.*@model_name' "$MOCK_TMUX_LOG"

    readiness_probe_line=$(grep -n '@pane_state_override' "$MOCK_TMUX_LOG" | tail -1 | cut -d: -f1)
    metadata_commit_line=$(grep -n 'set-option.*@agent_cli codex' "$MOCK_TMUX_LOG" | head -1 | cut -d: -f1)
    [ "$readiness_probe_line" -lt "$metadata_commit_line" ]

    export CLI_ADAPTER_SETTINGS="$TEST_TMP/settings.yaml"
    source "$PROJECT_ROOT/lib/cli_adapter.sh"
    [ "$(get_cli_type ashigaru1)" = codex ]
}

@test "switch_cli metadata partial failure restores old metadata and settings" {
    setup_switch_cli_tmux_mock
    cp "$TEST_TMP/settings.yaml" "$TEST_TMP/settings.before.yaml"

    run env \
        PATH="$TEST_TMP/bin:$PATH" \
        CLI_ADAPTER_SETTINGS="$TEST_TMP/settings.yaml" \
        SWITCH_CLI_LOG_FILE="$TEST_TMP/switch.log" \
        SHOGUN_TEST_MODE=1 \
        MOCK_CLI_STATE=ready \
        MOCK_METADATA_FAIL_AT=model_name \
        SHOGUN_CLI_READINESS_TIMEOUT_SECONDS=0 \
        SHOGUN_CLI_READINESS_POLL_SECONDS=0 \
        SHOGUN_SWITCH_SHELL_POLL_SECONDS=0 \
        bash "$PROJECT_ROOT/scripts/switch_cli.sh" ashigaru1 \
            --type codex --model gpt-5.3-codex-spark

    [ "$status" -ne 0 ]
    cmp -s "$TEST_TMP/settings.before.yaml" "$TEST_TMP/settings.yaml"
    grep -q 'set-option.*@agent_cli codex' "$MOCK_TMUX_LOG"
    grep -q 'set-option.*@agent_cli claude' "$MOCK_TMUX_LOG"
    grep -q 'set-option.*@model_name OldModel' "$MOCK_TMUX_LOG"
    grep -q 'select-pane.*-T OldTitle' "$MOCK_TMUX_LOG"
    [[ "$output" != *"CLI switch complete"* ]]
}

@test "switch_cli TERM during metadata commit restores old metadata and settings" {
    setup_switch_cli_tmux_mock
    cp "$TEST_TMP/settings.yaml" "$TEST_TMP/settings.before.yaml"

    run env \
        PATH="$TEST_TMP/bin:$PATH" \
        CLI_ADAPTER_SETTINGS="$TEST_TMP/settings.yaml" \
        SWITCH_CLI_LOG_FILE="$TEST_TMP/switch.log" \
        SHOGUN_TEST_MODE=1 \
        MOCK_CLI_STATE=ready \
        MOCK_SIGNAL_AFTER_AGENT_CLI=1 \
        SHOGUN_CLI_READINESS_TIMEOUT_SECONDS=0 \
        SHOGUN_CLI_READINESS_POLL_SECONDS=0 \
        SHOGUN_SWITCH_SHELL_POLL_SECONDS=0 \
        bash "$PROJECT_ROOT/scripts/switch_cli.sh" ashigaru1 \
            --type codex --model gpt-5.3-codex-spark

    [ "$status" -ne 0 ]
    cmp -s "$TEST_TMP/settings.before.yaml" "$TEST_TMP/settings.yaml"
    grep -q 'set-option.*@agent_cli codex' "$MOCK_TMUX_LOG"
    grep -q 'set-option.*@agent_cli claude' "$MOCK_TMUX_LOG"
    grep -q 'set-option.*@model_name OldModel' "$MOCK_TMUX_LOG"
    grep -q 'select-pane.*-T OldTitle' "$MOCK_TMUX_LOG"
    [[ "$output" != *"CLI switch complete"* ]]
}

@test "switch_cli retains settings backup when rollback copy fails" {
    setup_switch_cli_tmux_mock
    setup_cp_restore_failure_mock

    run env \
        PATH="$TEST_TMP/bin:$PATH" \
        CLI_ADAPTER_SETTINGS="$TEST_TMP/settings.yaml" \
        SWITCH_CLI_LOG_FILE="$TEST_TMP/switch.log" \
        SHOGUN_TEST_MODE=1 \
        MOCK_CLI_STATE=unknown \
        MOCK_CP_FAIL_DEST="$TEST_TMP/settings.yaml" \
        SHOGUN_CLI_READINESS_TIMEOUT_SECONDS=0 \
        SHOGUN_CLI_READINESS_POLL_SECONDS=0 \
        SHOGUN_SWITCH_SHELL_POLL_SECONDS=0 \
        bash "$PROJECT_ROOT/scripts/switch_cli.sh" ashigaru1 \
            --type codex --model gpt-5.3-codex-spark

    [ "$status" -ne 0 ]
    RETAINED_SETTINGS_BACKUP=$(printf '%s\n' "$output" | sed -n 's/.*Failed to restore settings.*backup retained at \(\/tmp\/tmp\.[^ ]*\).*/\1/p' | tail -1)
    [[ "$RETAINED_SETTINGS_BACKUP" == /tmp/tmp.* ]]
    [ -f "$RETAINED_SETTINGS_BACKUP" ]
}

@test "switch_cli retains runtime backup when sidecar rollback copy fails" {
    setup_switch_cli_tmux_mock
    setup_cp_restore_failure_mock
    setup_isolated_switch_project
    local runtime_file="$ISOLATED_SWITCH_ROOT/.opencode/agents/ashigaru1-runtime.md"
    printf '%s\n' 'original sanitized runtime' > "$runtime_file"

    run env \
        PATH="$TEST_TMP/bin:$PATH" \
        CLI_ADAPTER_SETTINGS="$ISOLATED_SWITCH_ROOT/config/settings.yaml" \
        SWITCH_CLI_LOG_FILE="$TEST_TMP/switch.log" \
        SHOGUN_TEST_MODE=1 \
        MOCK_CLI_STATE=unknown \
        MOCK_CP_FAIL_DEST="$runtime_file" \
        SHOGUN_CLI_READINESS_TIMEOUT_SECONDS=0 \
        SHOGUN_CLI_READINESS_POLL_SECONDS=0 \
        SHOGUN_SWITCH_SHELL_POLL_SECONDS=0 \
        bash "$ISOLATED_SWITCH_ROOT/scripts/switch_cli.sh" ashigaru1 \
            --type opencode --model openai/gpt-5.4-mini --variant high

    [ "$status" -ne 0 ]
    RETAINED_RUNTIME_BACKUP_DIR=$(printf '%s\n' "$output" | sed -n 's/.*Failed to restore OpenCode runtime metadata.*backup retained at \(\/tmp\/tmp\.[^ ]*\).*/\1/p' | tail -1)
    [[ "$RETAINED_RUNTIME_BACKUP_DIR" == /tmp/tmp.* ]]
    [ -f "$RETAINED_RUNTIME_BACKUP_DIR/runtime" ]
}

@test "switch_cli readiness failure restores overwritten OpenCode runtime sidecar" {
    setup_switch_cli_tmux_mock
    setup_isolated_switch_project
    local runtime_file="$ISOLATED_SWITCH_ROOT/.opencode/agents/ashigaru1-runtime.md"
    printf '%s\n' 'original sanitized runtime' > "$runtime_file"
    cp "$runtime_file" "$TEST_TMP/runtime.before"
    cp "$ISOLATED_SWITCH_ROOT/config/settings.yaml" "$TEST_TMP/settings.before.yaml"

    run env \
        PATH="$TEST_TMP/bin:$PATH" \
        CLI_ADAPTER_SETTINGS="$ISOLATED_SWITCH_ROOT/config/settings.yaml" \
        SWITCH_CLI_LOG_FILE="$TEST_TMP/switch.log" \
        SHOGUN_TEST_MODE=1 \
        MOCK_CLI_STATE=unknown \
        SHOGUN_CLI_READINESS_TIMEOUT_SECONDS=0 \
        SHOGUN_CLI_READINESS_POLL_SECONDS=0 \
        SHOGUN_SWITCH_SHELL_POLL_SECONDS=0 \
        bash "$ISOLATED_SWITCH_ROOT/scripts/switch_cli.sh" ashigaru1 \
            --type opencode --model openai/gpt-5.4-mini --variant high

    [ "$status" -ne 0 ]
    cmp -s "$TEST_TMP/runtime.before" "$runtime_file"
    cmp -s "$TEST_TMP/settings.before.yaml" "$ISOLATED_SWITCH_ROOT/config/settings.yaml"
}

@test "switch_cli readiness failure restores OpenCode runtime sidecar deleted for empty variant" {
    setup_switch_cli_tmux_mock
    setup_isolated_switch_project
    local runtime_file="$ISOLATED_SWITCH_ROOT/.opencode/agents/ashigaru1-runtime.md"
    printf '%s\n' 'original sanitized runtime' > "$runtime_file"
    cp "$runtime_file" "$TEST_TMP/runtime.before"

    run env \
        PATH="$TEST_TMP/bin:$PATH" \
        CLI_ADAPTER_SETTINGS="$ISOLATED_SWITCH_ROOT/config/settings.yaml" \
        SWITCH_CLI_LOG_FILE="$TEST_TMP/switch.log" \
        SHOGUN_TEST_MODE=1 \
        MOCK_CLI_STATE=unknown \
        SHOGUN_CLI_READINESS_TIMEOUT_SECONDS=0 \
        SHOGUN_CLI_READINESS_POLL_SECONDS=0 \
        SHOGUN_SWITCH_SHELL_POLL_SECONDS=0 \
        bash "$ISOLATED_SWITCH_ROOT/scripts/switch_cli.sh" ashigaru1 \
            --type opencode --model openai/gpt-5.4-mini

    [ "$status" -ne 0 ]
    cmp -s "$TEST_TMP/runtime.before" "$runtime_file"
}
