#!/usr/bin/env bash
# ============================================================
# Instruction File Build System
# ============================================================
# Combines instruction parts into complete instruction files
# for each role and CLI combination.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT_DIR="$(dirname "$SCRIPT_DIR")"
PARTS_DIR="$ROOT_DIR/instructions"
OUTPUT_DIR="$ROOT_DIR/instructions/generated"

mkdir -p "$OUTPUT_DIR"

echo "=== Instruction File Build System ==="
echo "Building instruction files..."

# Function: opencode_build_python
# Description: Returns the Python interpreter used for build-time YAML parsing.
# Arguments: none
# Returns: path to python3 on success, 1 on error
opencode_build_python() {
    if [[ -x "$ROOT_DIR/.venv/bin/python3" ]]; then
        echo "$ROOT_DIR/.venv/bin/python3"
    elif command -v python3 &>/dev/null; then
        command -v python3
    else
        return 1
    fi
}

# Function: get_build_ashigaru_ids
# Description: Returns ashigaru agent IDs discovered from settings.yaml or queue/task files.
# Arguments: none
# Returns: space-separated ashigaru IDs on success, fallback list otherwise
get_build_ashigaru_ids() {
    local settings_file="$ROOT_DIR/config/settings.yaml"
    local python_bin
    python_bin=$(opencode_build_python 2>/dev/null || true)

    if [[ -n "$python_bin" && -f "$settings_file" ]]; then
        local result
        result=$("$python_bin" - "$settings_file" "$ROOT_DIR" <<'PYEOF'
import sys
from pathlib import Path
import yaml

settings_file = sys.argv[1]
root_dir = Path(sys.argv[2])
try:
    with open(settings_file, encoding='utf-8') as fh:
        data = yaml.safe_load(fh) or {}
    cli_agents = (data.get('cli') or {}).get('agents') or {}
    model_agents = data.get('models') or {}

    ashigaru = {
        str(agent_id)
        for agent_id in cli_agents
        if str(agent_id).startswith('ashigaru')
    }
    ashigaru.update(
        str(agent_id)
        for agent_id in model_agents
        if str(agent_id).startswith('ashigaru')
    )

    if not ashigaru:
        task_dir = root_dir / 'queue' / 'tasks'
        if task_dir.exists():
            ashigaru.update(path.stem for path in task_dir.glob('ashigaru*.yaml'))

    ashigaru = list(ashigaru)
    ashigaru.sort(key=lambda agent_id: int(str(agent_id).replace('ashigaru', '')) if str(agent_id).replace('ashigaru', '').isdigit() else 999)
    print(' '.join(ashigaru))
except Exception:
    pass
PYEOF
        )
        if [[ -n "$result" ]]; then
            echo "$result"
            return 0
        fi
    fi

    echo "ashigaru1 ashigaru2 ashigaru3 ashigaru4 ashigaru5 ashigaru6 ashigaru7"
}

# Function: normalize_generated_markdown
# Description: Normalizes generated markdown so diff hygiene does not depend on source file line endings.
normalize_generated_markdown() {
    local output_path="$1"
    local tmp_path="${output_path}.tmp.$$"

    [ -f "$output_path" ] || return 0

    awk '{ sub(/\r$/, ""); sub(/[ \t]+$/, ""); print }' "$output_path" > "$tmp_path"
    mv "$tmp_path" "$output_path"
}

# ============================================================
# Helper function: Build a complete instruction file
# ============================================================
build_instruction_file() {
    local cli_type="$1"
    local role="$2"
    local output_filename="$3"
    local output_path="$OUTPUT_DIR/$output_filename"
    local original_file="$ROOT_DIR/instructions/${role}.md"

    echo "Building: $output_filename (CLI: $cli_type, Role: $role)"

    # Extract YAML front matter from original file
    if [ -f "$original_file" ]; then
        awk '/^---$/{if(++n==2) {print "---"; exit} if(n==1) next} n==1' "$original_file" > "$output_path"
        echo "" >> "$output_path"
    else
        # Minimal YAML front matter
        cat > "$output_path" <<EOFYAML
---
role: $role
version: "3.0"
cli_type: $cli_type
---

EOFYAML
    fi

    # Append role-specific content
    cat "$PARTS_DIR/roles/${role}_role.md" >> "$output_path"

    # Append common sections
    echo "" >> "$output_path"
    cat "$PARTS_DIR/common/protocol.md" >> "$output_path"
    echo "" >> "$output_path"
    cat "$PARTS_DIR/common/task_flow.md" >> "$output_path"
    echo "" >> "$output_path"
    cat "$PARTS_DIR/common/forbidden_actions.md" >> "$output_path"

    # Append CLI-specific tools section
    echo "" >> "$output_path"
    case "$cli_type" in
        claude)
            cat "$PARTS_DIR/cli_specific/claude_tools.md" >> "$output_path"
            ;;
        codex)
            cat "$PARTS_DIR/cli_specific/codex_tools.md" >> "$output_path"
            ;;
        copilot)
            cat "$PARTS_DIR/cli_specific/copilot_tools.md" >> "$output_path"
            ;;
        kimi)
            cat "$PARTS_DIR/cli_specific/kimi_tools.md" >> "$output_path"
            ;;
        opencode)
            cat "$PARTS_DIR/cli_specific/opencode_tools.md" >> "$output_path"
            ;;
    esac

    if [[ "$cli_type" == "opencode" ]]; then
        normalize_generated_markdown "$output_path"
    fi

    echo "  ✅ Created: $output_filename"
}

# Build Claude Code instruction files
build_instruction_file "claude" "shogun" "shogun.md"
build_instruction_file "claude" "karo" "karo.md"
build_instruction_file "claude" "ashigaru" "ashigaru.md"
build_instruction_file "claude" "gunshi" "gunshi.md"

# Build Codex instruction files
build_instruction_file "codex" "shogun" "codex-shogun.md"
build_instruction_file "codex" "karo" "codex-karo.md"
build_instruction_file "codex" "ashigaru" "codex-ashigaru.md"
build_instruction_file "codex" "gunshi" "codex-gunshi.md"

# Build Copilot instruction files
build_instruction_file "copilot" "shogun" "copilot-shogun.md"
build_instruction_file "copilot" "karo" "copilot-karo.md"
build_instruction_file "copilot" "ashigaru" "copilot-ashigaru.md"
build_instruction_file "copilot" "gunshi" "copilot-gunshi.md"

# Build Kimi K2 instruction files
build_instruction_file "kimi" "shogun" "kimi-shogun.md"
build_instruction_file "kimi" "karo" "kimi-karo.md"
build_instruction_file "kimi" "ashigaru" "kimi-ashigaru.md"
build_instruction_file "kimi" "gunshi" "kimi-gunshi.md"

# Build OpenCode instruction files
build_instruction_file "opencode" "shogun" "opencode-shogun.md"
build_instruction_file "opencode" "karo" "opencode-karo.md"
build_instruction_file "opencode" "ashigaru" "opencode-ashigaru.md"
build_instruction_file "opencode" "gunshi" "opencode-gunshi.md"

# ============================================================
# AGENTS.md generation (Codex auto-load file)
# ============================================================
# Codex CLIはリポジトリルートのAGENTS.mdを自動読み込みする。
# CLAUDE.mdを正本とし、Claude固有部分をCodex固有に置換して生成。
generate_agents_md() {
    local output_path="$ROOT_DIR/AGENTS.md"
    local claude_md="$ROOT_DIR/CLAUDE.md"

    echo "Generating: AGENTS.md (Codex auto-load)"

    if [ ! -f "$claude_md" ]; then
        echo "  ⚠️  CLAUDE.md not found. Skipping AGENTS.md generation."
        return 1
    fi

    # Normalize line endings to LF to keep tracked auto-load files stable across platforms.
    sed \
        -e 's|CLAUDE\.md|AGENTS.md|g' \
        -e 's|CLAUDE\.local\.md|AGENTS.override.md|g' \
        -e 's|instructions/shogun\.md|instructions/generated/codex-shogun.md|g' \
        -e 's|instructions/karo\.md|instructions/generated/codex-karo.md|g' \
        -e 's|instructions/ashigaru\.md|instructions/generated/codex-ashigaru.md|g' \
        -e 's|instructions/gunshi\.md|instructions/generated/codex-gunshi.md|g' \
        -e 's|~/.claude/|~/.codex/|g' \
        -e 's|\.claude\.json|.codex/config.toml|g' \
        -e 's|\.mcp\.json|config.toml (mcp_servers section)|g' \
        -e 's|Claude Code|Codex CLI|g' \
        -e 's|## /clear Recovery|## /new Recovery|g' \
        -e 's|Forbidden after /clear|Forbidden after /new|g' \
        -e 's|pre-/clear memory|pre-/new memory|g' \
        -e 's|lost on /clear)|lost on /new)|g' \
        -e 's|(/new or /clear)|(`/new`)|g' \
        -e 's|sends `/clear` + Enter via send-keys|sends `/new` + Enter via send-keys（/clear→/new自動変換）|g' \
        -e 's|`/clear` sent (max once per 5 min)|スキップ（Codexは`/clear`不可）|g' \
        -e 's|escalation sends `/clear` (~4 min)|next nudge escalation or task reassignment|g' \
        -e 's|delivers `/clear` to the agent|delivers `/new` to the agent（/clear→/new自動変換）|g' \
        -e 's|`/clear` wipes old context|`/new` wipes old context|g' \
        "$claude_md" | tr -d '\r' > "$output_path"

    echo "  ✅ Created: AGENTS.md"
}

# ============================================================
# copilot-instructions.md generation (Copilot auto-load file)
# ============================================================
# GitHub Copilot CLIは .github/copilot-instructions.md を自動読み込みする。
# CLAUDE.mdを正本とし、Claude固有部分をCopilot固有に置換して生成。
generate_copilot_instructions() {
    local github_dir="$ROOT_DIR/.github"
    local output_path="$github_dir/copilot-instructions.md"
    local claude_md="$ROOT_DIR/CLAUDE.md"

    echo "Generating: .github/copilot-instructions.md (Copilot auto-load)"

    if [ ! -f "$claude_md" ]; then
        echo "  ⚠️  CLAUDE.md not found. Skipping copilot-instructions.md generation."
        return 1
    fi

    mkdir -p "$github_dir"

    # Normalize line endings to LF to keep tracked auto-load files stable across platforms.
    sed \
        -e 's|CLAUDE\.md|copilot-instructions.md|g' \
        -e 's|CLAUDE\.local\.md|copilot-instructions.local.md|g' \
        -e 's|instructions/shogun\.md|instructions/generated/copilot-shogun.md|g' \
        -e 's|instructions/karo\.md|instructions/generated/copilot-karo.md|g' \
        -e 's|instructions/ashigaru\.md|instructions/generated/copilot-ashigaru.md|g' \
        -e 's|instructions/gunshi\.md|instructions/generated/copilot-gunshi.md|g' \
        -e 's|~/.claude/|~/.copilot/|g' \
        -e 's|\.claude\.json|.copilot/config.json|g' \
        -e 's|\.mcp\.json|.copilot/mcp-config.json|g' \
        -e 's|Claude Code|GitHub Copilot CLI|g' \
        "$claude_md" | tr -d '\r' > "$output_path"

    echo "  ✅ Created: .github/copilot-instructions.md"
}

# ============================================================
# Kimi K2 auto-load files generation
# ============================================================
# Kimi K2 CLIは agents/default/agent.yaml + system.md を自動読み込みする。
# CLAUDE.mdを正本とし、Claude固有部分をKimi固有に置換して生成。
generate_kimi_instructions() {
    local agents_dir="$ROOT_DIR/agents/default"
    local system_md_path="$agents_dir/system.md"
    local agent_yaml_path="$agents_dir/agent.yaml"
    local claude_md="$ROOT_DIR/CLAUDE.md"

    echo "Generating: agents/default/system.md + agent.yaml (Kimi auto-load)"

    if [ ! -f "$claude_md" ]; then
        echo "  ⚠️  CLAUDE.md not found. Skipping Kimi auto-load generation."
        return 1
    fi

    mkdir -p "$agents_dir"

    # Generate system.md (CLAUDE.md → Kimi版)
    # Normalize line endings to LF to keep tracked auto-load files stable across platforms.
    sed \
        -e 's|CLAUDE\.md|agents/default/system.md|g' \
        -e 's|CLAUDE\.local\.md|agents/default/system.local.md|g' \
        -e 's|instructions/shogun\.md|instructions/generated/kimi-shogun.md|g' \
        -e 's|instructions/karo\.md|instructions/generated/kimi-karo.md|g' \
        -e 's|instructions/ashigaru\.md|instructions/generated/kimi-ashigaru.md|g' \
        -e 's|instructions/gunshi\.md|instructions/generated/kimi-gunshi.md|g' \
        -e 's|~/.claude/|~/.kimi/|g' \
        -e 's|\.claude\.json|.kimi/config.json|g' \
        -e 's|\.mcp\.json|.kimi/mcp.json|g' \
        -e 's|Claude Code|Kimi K2 CLI|g' \
        "$claude_md" | tr -d '\r' > "$system_md_path"

    echo "  ✅ Created: agents/default/system.md"

    # Generate agent.yaml (Kimi agent definition)
    cat > "$agent_yaml_path" <<'EOFYAML'
# Kimi K2 Agent Configuration
# Auto-generated by build_instructions.sh — do not edit manually
name: multi-agent-shogun
description: "Kimi K2 CLI agent for multi-agent-shogun system"
model: moonshot-k2.5
system_prompt_file: system.md
tools:
  - file_read
  - file_write
  - shell_exec
  - web_search
EOFYAML

    echo "  ✅ Created: agents/default/agent.yaml"
}

# ============================================================
# OpenCode agent definition files generation
# ============================================================
# OpenCode reads .opencode/agents/<name>.md and uses the YAML
# frontmatter + body as a built-in system prompt.  This replaces
# the former --prompt bootstrap approach.  Permissions are
# expanded from config/opencode-permissions.yaml at build time
# so that OPENCODE_CONFIG_CONTENT is no longer needed at launch.

# Function: generate_opencode_agents
# Description: Generates .opencode/agents/*.md files with role frontmatter and OpenCode-specific rules.
# Arguments: none
# Returns: 0 on success, 1 if generation is skipped or unavailable
generate_opencode_agents() {
    local agents_dir="$ROOT_DIR/.opencode/agents"
    local permissions_file="$ROOT_DIR/config/opencode-permissions.yaml"
    local python_bin

    echo "Generating: .opencode/agents/*.md (OpenCode agent definitions)"

    if [ ! -f "$permissions_file" ]; then
        echo "  ⚠️  config/opencode-permissions.yaml not found. Skipping OpenCode agent generation."
        return 1
    fi

    mkdir -p "$agents_dir"

    python_bin=$(opencode_build_python) || {
        echo "  ⚠️  python3 not found. Skipping OpenCode agent generation."
        return 1
    }

    # Agent ID → role mapping
    local agent_ids
    agent_ids="shogun karo gunshi $(get_build_ashigaru_ids)"

    for agent_id in $agent_ids; do
        # Determine role (all ashigaru share the same role template)
        local role=""
        case "$agent_id" in
            ashigaru*) role="ashigaru" ;;
            *)         role="$agent_id" ;;
        esac

        # Determine role title for description
        local role_title=""
        case "$agent_id" in
            shogun)
                role_title="Shogun — strategic oversight and command issuance"
                ;;
            karo)
                role_title="Karo — task decomposition, assignment, and coordination"
                ;;
            gunshi)
                role_title="Gunshi — strategic analysis and quality control"
                ;;
            ashigaru*)
                local ashigaru_number="${agent_id#ashigaru}"
                role_title="Ashigaru ${ashigaru_number} — front-line execution"
                ;;
        esac

        # Generate permission YAML via the same Python logic used in cli_adapter.sh
        local permission_yaml
        if ! permission_yaml=$("$python_bin" - "$permissions_file" "$agent_id" <<'PYEOF'
import json, sys, yaml

permissions_file = sys.argv[1]
agent_id = sys.argv[2]

def role_for_agent(agent_id: str) -> str:
    if agent_id.startswith('ashigaru'):
        return 'ashigaru'
    if agent_id in {'shogun', 'karo', 'gunshi'}:
        return agent_id
    return ''

def expand(pattern: str) -> str:
    return pattern.replace('{agent_id}', agent_id)

def build_rule(deny_patterns, allow_patterns):
    deny = []
    allow = []
    seen = set()
    for pattern in deny_patterns or []:
        expanded = expand(pattern)
        if expanded not in seen:
            seen.add(expanded)
            deny.append(expanded)
    for pattern in allow_patterns or []:
        expanded = expand(pattern)
        if expanded not in seen:
            seen.add(expanded)
            allow.append(expanded)
    rule = {}
    for pattern in deny:
        rule[pattern] = 'deny'
    for pattern in allow:
        rule[pattern] = 'allow'
    return rule

with open(permissions_file, encoding='utf-8') as fh:
    config = yaml.safe_load(fh) or {}

role = role_for_agent(agent_id)
roles = config.get('roles') or {}
role_cfg = roles.get(role) or {}

common_edit_deny = list((config.get('common') or {}).get('edit_deny') or [])
read_rule = build_rule(role_cfg.get('read_deny'), role_cfg.get('read_allow'))
edit_rule = build_rule(common_edit_deny + list(role_cfg.get('edit_deny') or []), role_cfg.get('edit_allow'))

permission = {
    '*': 'allow',
    'question': role_cfg.get('question', 'deny'),
    'read': read_rule,
    'edit': edit_rule,
    'write': edit_rule,
    'patch': edit_rule,
    'list': read_rule,
    'glob': read_rule,
    'grep': read_rule,
}

# Output as YAML (indented) for embedding in frontmatter
print(yaml.dump({'permission': permission}, default_flow_style=False, allow_unicode=True).rstrip())
PYEOF
        ); then
            echo "  ❌ Failed to generate OpenCode permissions for ${agent_id}" >&2
            return 1
        fi

        local output_path="$agents_dir/${agent_id}.md"

        # Write YAML frontmatter
        cat > "$output_path" <<FRONTMATTER
---
description: "${role_title}"
mode: primary
# Auto-generated by build_instructions.sh — do not edit manually.
# Source: instructions/roles/${role}_role.md + instructions/common/* + instructions/cli_specific/opencode_tools.md
${permission_yaml}
---

FRONTMATTER

        # Append role-specific content (same pipeline as build_instruction_file)
        {
            cat "$PARTS_DIR/roles/${role}_role.md"

            echo ""
            cat <<EOF
## Identity Anchor

This generated file belongs to exactly one agent.

- Canonical agent_id: \`${agent_id}\`
- Canonical tmux check: \`tmux display-message -t "\$TMUX_PANE" -p '#{@agent_id}'\`
- Proceed only if the tmux value matches the canonical agent_id.
- If you have not confirmed this yet, confirm it before reading inbox/task files.

EOF

            # Append common sections
            echo ""
            cat "$PARTS_DIR/common/protocol.md"
            echo ""
            cat "$PARTS_DIR/common/task_flow.md"
            echo ""
            cat "$PARTS_DIR/common/forbidden_actions.md"

            # Append OpenCode-specific tools section
            echo ""
            cat "$PARTS_DIR/cli_specific/opencode_tools.md"
        } >> "$output_path"

        normalize_generated_markdown "$output_path"

        echo "  ✅ Created: .opencode/agents/${agent_id}.md"
    done
}

# Generate CLI auto-load files
generate_agents_md
generate_copilot_instructions
generate_kimi_instructions
generate_opencode_agents

echo ""
echo "=== Build Complete ==="
echo "Output directory: $OUTPUT_DIR"
echo ""
echo "Generated instruction files:"
ls -lh "$OUTPUT_DIR"/*.md
echo ""
echo "CLI auto-load files:"
[ -f "$ROOT_DIR/AGENTS.md" ] && ls -lh "$ROOT_DIR/AGENTS.md"
[ -f "$ROOT_DIR/.github/copilot-instructions.md" ] && ls -lh "$ROOT_DIR/.github/copilot-instructions.md"
[ -f "$ROOT_DIR/agents/default/system.md" ] && ls -lh "$ROOT_DIR/agents/default/system.md"
[ -f "$ROOT_DIR/agents/default/agent.yaml" ] && ls -lh "$ROOT_DIR/agents/default/agent.yaml"
echo ""
echo "OpenCode agent definitions:"
ls -lh "$ROOT_DIR/.opencode/agents/"*.md 2>/dev/null || echo "  (none)"
