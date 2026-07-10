#!/usr/bin/env bats

setup_file() {
    export PROJECT_ROOT="$(cd "$(dirname "$BATS_TEST_FILENAME")/../.." && pwd)"
    if [ -x "$PROJECT_ROOT/.venv/bin/python3" ]; then
        export PYTHON="$PROJECT_ROOT/.venv/bin/python3"
    else
        export PYTHON=python3
    fi
}

setup() {
    export TEST_TMPDIR="$(mktemp -d "$BATS_TMPDIR/drive_publisher.XXXXXX")"
    mkdir -p "$TEST_TMPDIR/artifacts/assets"
    printf '<h1>demo</h1>\n' > "$TEST_TMPDIR/artifacts/index.html"
    printf 'body{}\n' > "$TEST_TMPDIR/artifacts/assets/app.css"
    cat > "$TEST_TMPDIR/config.yaml" <<'EOF'
project_id: test-project
service_account: publisher@test-project.iam.gserviceaccount.com
drive_id: drive-root-id
projects_folder: "10_プロジェクト"
max_file_bytes: 1048576
EOF
    cat > "$TEST_TMPDIR/manifest.yaml" <<'EOF'
project: demo-project
artifact_id: cmd_123
source_tool: shogun
status: review
created_at: "2026-07-10T00:00:00+09:00"
files:
  - index.html
  - assets/app.css
review:
  result: pending
  reviewer: gunshi
EOF
}

teardown() {
    rm -rf "$TEST_TMPDIR"
}

run_dry() {
    run "$PYTHON" "$PROJECT_ROOT/scripts/drive_publisher.py" \
        --config "$TEST_TMPDIR/config.yaml" \
        --manifest "$TEST_TMPDIR/manifest.yaml" \
        --artifact-dir "$TEST_TMPDIR/artifacts" \
        --stage review \
        --gcloud-bin /does/not/exist \
        --dry-run
}

replace_in_file() {
    local path="$1"
    local old="$2"
    local new="$3"
    "$PYTHON" -c \
        'import pathlib,sys; p=pathlib.Path(sys.argv[1]); s=p.read_text(); old=sys.argv[2]; assert old in s; p.write_text(s.replace(old, sys.argv[3], 1))' \
        "$path" "$old" "$new"
}

delete_line_from_file() {
    local path="$1"
    local exact_line="$2"
    "$PYTHON" -c \
        'import pathlib,sys; p=pathlib.Path(sys.argv[1]); lines=p.read_text().splitlines(True); p.write_text("".join(line for line in lines if line.rstrip("\r\n") != sys.argv[2]))' \
        "$path" "$exact_line"
}

@test "drive publisher dry-run validates nested artifacts without authentication" {
    run_dry
    [ "$status" -eq 0 ]
    echo "$output" | grep -q '"status": "dry-run"'
    echo "$output" | grep -q '10_プロジェクト/demo-project/03_レビュー待ち/cmd_123'
    echo "$output" | grep -q 'assets/app.css'
}

@test "drive publisher rejects path traversal" {
    printf 'private\n' > "$TEST_TMPDIR/private.txt"
    replace_in_file "$TEST_TMPDIR/manifest.yaml" "  - index.html" "  - ../private.txt"
    run_dry
    [ "$status" -eq 2 ]
    echo "$output" | grep -q 'unsafe artifact path'
}

@test "drive publisher rejects secret-like filenames" {
    printf 'secret\n' > "$TEST_TMPDIR/artifacts/oauth_token.json"
    replace_in_file "$TEST_TMPDIR/manifest.yaml" "  - index.html" "  - oauth_token.json"
    run_dry
    [ "$status" -eq 2 ]
    echo "$output" | grep -q 'blocked secret-like artifact name'
}

@test "drive publisher rejects manifest stage mismatch" {
    run "$PYTHON" "$PROJECT_ROOT/scripts/drive_publisher.py" \
        --config "$TEST_TMPDIR/config.yaml" \
        --manifest "$TEST_TMPDIR/manifest.yaml" \
        --artifact-dir "$TEST_TMPDIR/artifacts" \
        --stage approved \
        --dry-run
    [ "$status" -eq 2 ]
    echo "$output" | grep -q 'does not match stage'
}

@test "drive publisher rejects approved stage without an approved review" {
    replace_in_file "$TEST_TMPDIR/manifest.yaml" "status: review" "status: approved"
    run "$PYTHON" "$PROJECT_ROOT/scripts/drive_publisher.py" \
        --config "$TEST_TMPDIR/config.yaml" \
        --manifest "$TEST_TMPDIR/manifest.yaml" \
        --artifact-dir "$TEST_TMPDIR/artifacts" \
        --stage approved \
        --dry-run
    [ "$status" -eq 2 ]
    echo "$output" | grep -q 'review.result=approved'
}

@test "drive publisher accepts approved stage only with complete approval evidence" {
    replace_in_file "$TEST_TMPDIR/manifest.yaml" "status: review" "status: approved"
    replace_in_file "$TEST_TMPDIR/manifest.yaml" "result: pending" "result: approved"
    printf '  approved_at: "2026-07-10T01:00:00+09:00"\n' >> "$TEST_TMPDIR/manifest.yaml"
    run "$PYTHON" "$PROJECT_ROOT/scripts/drive_publisher.py" \
        --config "$TEST_TMPDIR/config.yaml" \
        --manifest "$TEST_TMPDIR/manifest.yaml" \
        --artifact-dir "$TEST_TMPDIR/artifacts" \
        --stage approved \
        --dry-run
    [ "$status" -eq 0 ]
    echo "$output" | grep -q '04_承認済み成果物'
}

@test "drive publisher rejects approved stage without reviewer" {
    replace_in_file "$TEST_TMPDIR/manifest.yaml" "status: review" "status: approved"
    replace_in_file "$TEST_TMPDIR/manifest.yaml" "result: pending" "result: approved"
    delete_line_from_file "$TEST_TMPDIR/manifest.yaml" "  reviewer: gunshi"
    run "$PYTHON" "$PROJECT_ROOT/scripts/drive_publisher.py" \
        --config "$TEST_TMPDIR/config.yaml" \
        --manifest "$TEST_TMPDIR/manifest.yaml" \
        --artifact-dir "$TEST_TMPDIR/artifacts" \
        --stage approved \
        --dry-run
    [ "$status" -eq 2 ]
    echo "$output" | grep -q 'reviewer'
}

@test "drive publisher rejects approved stage without approved_at" {
    replace_in_file "$TEST_TMPDIR/manifest.yaml" "status: review" "status: approved"
    replace_in_file "$TEST_TMPDIR/manifest.yaml" "result: pending" "result: approved"
    run "$PYTHON" "$PROJECT_ROOT/scripts/drive_publisher.py" \
        --config "$TEST_TMPDIR/config.yaml" \
        --manifest "$TEST_TMPDIR/manifest.yaml" \
        --artifact-dir "$TEST_TMPDIR/artifacts" \
        --stage approved \
        --dry-run
    [ "$status" -eq 2 ]
    echo "$output" | grep -q 'approved_at'
}

@test "drive publisher refuses a live publish when the single-writer lock exists" {
    touch "$TEST_TMPDIR/publisher.lock"
    run "$PYTHON" "$PROJECT_ROOT/scripts/drive_publisher.py" \
        --config "$TEST_TMPDIR/config.yaml" \
        --manifest "$TEST_TMPDIR/manifest.yaml" \
        --artifact-dir "$TEST_TMPDIR/artifacts" \
        --stage review \
        --lock-file "$TEST_TMPDIR/publisher.lock"
    [ "$status" -eq 2 ]
    echo "$output" | grep -q 'another Drive publisher is running'
}

@test "drive publisher rejects symlink escape" {
    printf 'outside\n' > "$TEST_TMPDIR/outside.txt"
    ln -s "$TEST_TMPDIR/outside.txt" "$TEST_TMPDIR/artifacts/linked.txt"
    replace_in_file "$TEST_TMPDIR/manifest.yaml" "  - index.html" "  - linked.txt"
    run_dry
    [ "$status" -eq 2 ]
    echo "$output" | grep -q 'artifact escapes artifact directory'
}

@test "drive publisher rejects non-string gcloud_bin config" {
    printf '\ngcloud_bin: 123\n' >> "$TEST_TMPDIR/config.yaml"
    run_dry
    [ "$status" -eq 2 ]
    echo "$output" | grep -q 'gcloud_bin must be a string'
}

@test "drive publisher resolves gcloud as CLI then env then config then PATH" {
    run "$PYTHON" -c "import importlib.util; p='$PROJECT_ROOT/scripts/drive_publisher.py'; s=importlib.util.spec_from_file_location('publisher', p); m=importlib.util.module_from_spec(s); s.loader.exec_module(m); import os; os.environ.pop('GCLOUD_BIN', None); assert m.resolve_gcloud_bin('/cli/gcloud', '/config/gcloud') == '/cli/gcloud'; os.environ['GCLOUD_BIN']='/env/gcloud'; assert m.resolve_gcloud_bin(None, '/config/gcloud') == '/env/gcloud'; os.environ.pop('GCLOUD_BIN'); assert m.resolve_gcloud_bin(None, '/config/gcloud') == '/config/gcloud'; assert m.resolve_gcloud_bin(None, '') == 'gcloud'"
    [ "$status" -eq 0 ]
}
