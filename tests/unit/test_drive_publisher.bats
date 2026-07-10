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

@test "drive publisher dry-run validates nested artifacts without authentication" {
    run_dry
    [ "$status" -eq 0 ]
    echo "$output" | grep -q '"status": "dry-run"'
    echo "$output" | grep -q '10_プロジェクト/demo-project/03_レビュー待ち/cmd_123'
    echo "$output" | grep -q 'assets/app.css'
}

@test "drive publisher rejects path traversal" {
    printf 'private\n' > "$TEST_TMPDIR/private.txt"
    sed -i 's|  - index.html|  - ../private.txt|' "$TEST_TMPDIR/manifest.yaml"
    run_dry
    [ "$status" -eq 2 ]
    echo "$output" | grep -q 'unsafe artifact path'
}

@test "drive publisher rejects secret-like filenames" {
    printf 'secret\n' > "$TEST_TMPDIR/artifacts/oauth_token.json"
    sed -i 's|  - index.html|  - oauth_token.json|' "$TEST_TMPDIR/manifest.yaml"
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
    sed -i 's/status: review/status: approved/' "$TEST_TMPDIR/manifest.yaml"
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
    sed -i 's/status: review/status: approved/' "$TEST_TMPDIR/manifest.yaml"
    sed -i 's/result: pending/result: approved/' "$TEST_TMPDIR/manifest.yaml"
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
    sed -i 's/status: review/status: approved/' "$TEST_TMPDIR/manifest.yaml"
    sed -i 's/result: pending/result: approved/' "$TEST_TMPDIR/manifest.yaml"
    sed -i '/reviewer:/d' "$TEST_TMPDIR/manifest.yaml"
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
    sed -i 's/status: review/status: approved/' "$TEST_TMPDIR/manifest.yaml"
    sed -i 's/result: pending/result: approved/' "$TEST_TMPDIR/manifest.yaml"
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
    sed -i 's|  - index.html|  - linked.txt|' "$TEST_TMPDIR/manifest.yaml"
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
