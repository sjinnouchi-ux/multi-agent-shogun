#!/usr/bin/env bats

setup() {
    export PROJECT_ROOT="$(cd "$(dirname "$BATS_TEST_FILENAME")/../.." && pwd)"
    export TEST_ROOT="$BATS_TEST_TMPDIR/case"
    export INSTALL_ROOT="$TEST_ROOT/install"
    mkdir -p "$INSTALL_ROOT" "$TEST_ROOT/work" "$TEST_ROOT/bin"
    cp -R "$PROJECT_ROOT/skills/shogun-agent-status" "$INSTALL_ROOT/"
    cp -R "$PROJECT_ROOT/skills/shogun-screenshot" "$INSTALL_ROOT/"
}

write_safe_png() {
    local target="$1"
    printf '%s' 'iVBORw0KGgoAAAANSUhEUgAAAAQAAAAECAIAAAAmkwkpAAAAFElEQVR4nGP4z8DAwMDAxAADCBYAOI8CBYz2rSgAAAAASUVORK5CYII=' \
        | base64 --decode > "$target"
}

selected_identity() {
    "$INSTALL_ROOT/shogun-screenshot/scripts/capture_local.sh" --input "$1" \
        | python3 -c 'import json, sys; print(json.load(sys.stdin)["identity"])'
}

install_fake_pillow() {
    mkdir -p "$TEST_ROOT/fake-pillow/PIL"
    cat > "$TEST_ROOT/fake-pillow/PIL/__init__.py" <<'PY'
import os
import warnings


class DecompressionBombWarning(RuntimeWarning):
    pass


class DecompressionBombError(Exception):
    pass


class _FakeImage:
    def __init__(self):
        self.size = tuple(
            int(value) for value in os.environ.get("FAKE_IMAGE_SIZE", "4,4").split(",")
        )

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def load(self):
        return None

    def crop(self, _box):
        return self

    def copy(self):
        return self

    def resize(self, size, _resampling):
        self.size = size
        return self

    def save(self, stream, format=None):
        del format
        stream.write(b"fake-encoded-image\n")


class Image:
    MAX_IMAGE_PIXELS = None
    DecompressionBombWarning = DecompressionBombWarning
    DecompressionBombError = DecompressionBombError

    class Resampling:
        LANCZOS = object()

    @staticmethod
    def open(_stream):
        bomb = os.environ.get("FAKE_PILLOW_BOMB")
        if bomb == "warning":
            warnings.warn("decompression bomb", DecompressionBombWarning)
        if bomb == "error":
            raise DecompressionBombError("decompression bomb")
        return _FakeImage()


class _Drawer:
    def rectangle(self, *_args, **_kwargs):
        return None


class ImageDraw:
    @staticmethod
    def Draw(_image):
        return _Drawer()
PY
}

@test "installed agent-status ignores repository helpers and emits only the allowlisted schema" {
    mkdir -p "$TEST_ROOT/hostile/.git" "$TEST_ROOT/fake-root/scripts"

    cat > "$TEST_ROOT/bin/git" <<'EOF'
#!/usr/bin/env bash
: > "$SENTINEL"
exit 99
EOF
    cat > "$TEST_ROOT/fake-root/scripts/agent_status.sh" <<'EOF'
#!/usr/bin/env bash
: > "$HELPER_SENTINEL"
exit 99
EOF
    cat > "$TEST_ROOT/bin/tmux" <<'EOF'
#!/usr/bin/env bash
printf '%s\n' "$*" >> "$TMUX_TRACE"
[[ "$#" -eq 4 ]]
[[ "$1" == "list-panes" ]]
[[ "$2" == "-a" ]]
[[ "$3" == "-F" ]]
[[ "$4" == '#{@agent_id}|#{pane_dead}|#{?@current_task,busy,available}' ]]
printf '%s\n' \
    'shogun|0|available' \
    'karo|0|busy' \
    'ashigaru1|1|busy' \
    'intruder|0|available'
EOF
    chmod +x "$TEST_ROOT/bin/git" "$TEST_ROOT/bin/tmux" \
        "$TEST_ROOT/fake-root/scripts/agent_status.sh"

    run env \
        PATH="$TEST_ROOT/bin:$PATH" \
        SENTINEL="$TEST_ROOT/git-called" \
        HELPER_SENTINEL="$TEST_ROOT/helper-called" \
        TMUX_TRACE="$TEST_ROOT/tmux-trace" \
        SHOGUN_ROOT="$TEST_ROOT/fake-root" \
        MULTI_AGENT_SHOGUN_DIR="$TEST_ROOT/fake-root" \
        bash -c 'cd "$1" && exec "$2"' _ \
        "$TEST_ROOT/hostile" \
        "$INSTALL_ROOT/shogun-agent-status/scripts/agent_status.sh"

    [ "$status" -eq 0 ]
    [ ! -e "$TEST_ROOT/git-called" ]
    [ ! -e "$TEST_ROOT/helper-called" ]
    [ "$(wc -l < "$TEST_ROOT/tmux-trace")" -eq 1 ]

    expected='{"agent_id":"shogun","role":"shogun","coarse_availability":"available"}
{"agent_id":"karo","role":"karo","coarse_availability":"busy"}
{"agent_id":"ashigaru1","role":"ashigaru","coarse_availability":"offline"}
{"agent_id":"ashigaru2","role":"ashigaru","coarse_availability":"unknown"}
{"agent_id":"ashigaru3","role":"ashigaru","coarse_availability":"unknown"}
{"agent_id":"ashigaru4","role":"ashigaru","coarse_availability":"unknown"}
{"agent_id":"ashigaru5","role":"ashigaru","coarse_availability":"unknown"}
{"agent_id":"ashigaru6","role":"ashigaru","coarse_availability":"unknown"}
{"agent_id":"ashigaru7","role":"ashigaru","coarse_availability":"unknown"}
{"agent_id":"gunshi","role":"gunshi","coarse_availability":"unknown"}
{"agent_id":"oometsuke","role":"oometsuke","coarse_availability":"unknown"}'
    [ "$output" = "$expected" ]
}

@test "agent-status rejects caller-selected panes before invoking tmux" {
    cat > "$TEST_ROOT/bin/tmux" <<'EOF'
#!/usr/bin/env bash
: > "$TMUX_SENTINEL"
exit 99
EOF
    chmod +x "$TEST_ROOT/bin/tmux"

    run env PATH="$TEST_ROOT/bin:$PATH" TMUX_SENTINEL="$TEST_ROOT/tmux-called" \
        "$INSTALL_ROOT/shogun-agent-status/scripts/agent_status.sh" 'multiagent:agents.0'

    [ "$status" -eq 64 ]
    [ ! -e "$TEST_ROOT/tmux-called" ]
}

@test "installed local-image selector requires one explicit regular non-symlink image" {
    write_safe_png "$TEST_ROOT/selected.png"
    write_safe_png "$TEST_ROOT/work/newer.png"
    touch -d '2035-01-01 00:00:00' "$TEST_ROOT/work/newer.png"
    printf 'not an image\n' > "$TEST_ROOT/not-image.png"
    ln -s "$TEST_ROOT/selected.png" "$TEST_ROOT/link.png"

    run bash -c 'cd "$1" && exec "$2" --input "$3"' _ \
        "$TEST_ROOT/work" \
        "$INSTALL_ROOT/shogun-screenshot/scripts/capture_local.sh" \
        "$TEST_ROOT/selected.png"
    [ "$status" -eq 0 ]
    selected_path="$(printf '%s' "$output" | python3 -c 'import json, sys; print(json.load(sys.stdin)["path"])')"
    identity="$(printf '%s' "$output" | python3 -c 'import json, sys; print(json.load(sys.stdin)["identity"])')"
    [ "$selected_path" = "$TEST_ROOT/selected.png" ]
    [[ "$identity" =~ ^sha256:[0-9a-f]{64}$ ]]

    run "$INSTALL_ROOT/shogun-screenshot/scripts/capture_local.sh"
    [ "$status" -eq 64 ]

    run "$INSTALL_ROOT/shogun-screenshot/scripts/capture_local.sh" --input "$TEST_ROOT/link.png"
    [ "$status" -ne 0 ]

    run "$INSTALL_ROOT/shogun-screenshot/scripts/capture_local.sh" --input "$TEST_ROOT/not-image.png"
    [ "$status" -ne 0 ]

    run "$INSTALL_ROOT/shogun-screenshot/scripts/capture_local.sh" --input "$TEST_ROOT/work"
    [ "$status" -ne 0 ]
}

@test "installed trim and mask helpers reject input equal to output without touching the original" {
    write_safe_png "$TEST_ROOT/original.png"
    before="$(sha256sum "$TEST_ROOT/original.png" | awk '{print $1}')"
    identity="$(selected_identity "$TEST_ROOT/original.png")"

    run python3 "$INSTALL_ROOT/shogun-screenshot/scripts/trim_image.py" \
        --input "$TEST_ROOT/original.png" \
        --input-identity "$identity" \
        --output "$TEST_ROOT/original.png" \
        --crop '0,0,2,2'
    [ "$status" -ne 0 ]
    [[ "$output" == *"input and output must differ"* ]]
    [ "$(sha256sum "$TEST_ROOT/original.png" | awk '{print $1}')" = "$before" ]

    run python3 "$INSTALL_ROOT/shogun-screenshot/scripts/mask_sensitive.py" \
        --input "$TEST_ROOT/original.png" \
        --input-identity "$identity" \
        --output "$TEST_ROOT/original.png" \
        --regions '0,0,2,2'
    [ "$status" -ne 0 ]
    [[ "$output" == *"input and output must differ"* ]]
    [ "$(sha256sum "$TEST_ROOT/original.png" | awk '{print $1}')" = "$before" ]
}

@test "installed trim and mask helpers refuse every pre-existing output" {
    write_safe_png "$TEST_ROOT/input.png"
    write_safe_png "$TEST_ROOT/existing.png"
    existing_before="$(sha256sum "$TEST_ROOT/existing.png" | awk '{print $1}')"
    identity="$(selected_identity "$TEST_ROOT/input.png")"

    run python3 "$INSTALL_ROOT/shogun-screenshot/scripts/trim_image.py" \
        --input "$TEST_ROOT/input.png" \
        --input-identity "$identity" \
        --output "$TEST_ROOT/existing.png" \
        --crop '0,0,2,2'
    [ "$status" -ne 0 ]
    [[ "$output" == *"output already exists"* ]]
    [ "$(sha256sum "$TEST_ROOT/existing.png" | awk '{print $1}')" = "$existing_before" ]

    run python3 "$INSTALL_ROOT/shogun-screenshot/scripts/mask_sensitive.py" \
        --input "$TEST_ROOT/input.png" \
        --input-identity "$identity" \
        --output "$TEST_ROOT/existing.png" \
        --regions '0,0,2,2'
    [ "$status" -ne 0 ]
    [[ "$output" == *"output already exists"* ]]
    [ "$(sha256sum "$TEST_ROOT/existing.png" | awk '{print $1}')" = "$existing_before" ]
}

@test "installed trim and mask helpers require and verify the selector identity" {
    write_safe_png "$TEST_ROOT/selected.png"
    identity="$(selected_identity "$TEST_ROOT/selected.png")"

    run python3 "$INSTALL_ROOT/shogun-screenshot/scripts/trim_image.py" \
        --input "$TEST_ROOT/selected.png" \
        --output "$TEST_ROOT/no-identity.png" \
        --crop '0,0,2,2'
    [ "$status" -ne 0 ]
    [[ "$output" == *"--input-identity"* ]]
    [ ! -e "$TEST_ROOT/no-identity.png" ]

    run python3 "$INSTALL_ROOT/shogun-screenshot/scripts/trim_image.py" \
        --input "$TEST_ROOT/selected.png" \
        --input-identity 'not-a-valid-identity-☃' \
        --output "$TEST_ROOT/malformed-identity.png" \
        --crop '0,0,2,2'
    [ "$status" -ne 0 ]
    [[ "$output" == *"input identity mismatch"* ]]
    [[ "$output" != *"Traceback"* ]]
    [ ! -e "$TEST_ROOT/malformed-identity.png" ]

    mv "$TEST_ROOT/selected.png" "$TEST_ROOT/original-selected.png"
    write_safe_png "$TEST_ROOT/selected.png"

    run python3 "$INSTALL_ROOT/shogun-screenshot/scripts/trim_image.py" \
        --input "$TEST_ROOT/selected.png" \
        --input-identity "$identity" \
        --output "$TEST_ROOT/swapped-trim.png" \
        --crop '0,0,2,2'
    [ "$status" -ne 0 ]
    [[ "$output" == *"input identity mismatch"* ]]
    [ ! -e "$TEST_ROOT/swapped-trim.png" ]

    run python3 "$INSTALL_ROOT/shogun-screenshot/scripts/mask_sensitive.py" \
        --input "$TEST_ROOT/selected.png" \
        --input-identity "$identity" \
        --output "$TEST_ROOT/swapped-mask.png" \
        --regions '0,0,2,2'
    [ "$status" -ne 0 ]
    [[ "$output" == *"input identity mismatch"* ]]
    [ ! -e "$TEST_ROOT/swapped-mask.png" ]
}

@test "installed mask helper rejects ineffective regions and unsafe preview output" {
    write_safe_png "$TEST_ROOT/input.png"
    identity="$(selected_identity "$TEST_ROOT/input.png")"
    install_fake_pillow

    run env PYTHONPATH="$TEST_ROOT/fake-pillow" \
        python3 "$INSTALL_ROOT/shogun-screenshot/scripts/mask_sensitive.py" \
        --input "$TEST_ROOT/input.png" \
        --input-identity "$identity" \
        --output "$TEST_ROOT/zero-area.png" \
        --regions '1,1,1,3'
    [ "$status" -ne 0 ]
    [[ "$output" == *"region 1 has zero area"* ]]
    [ ! -e "$TEST_ROOT/zero-area.png" ]

    run env PYTHONPATH="$TEST_ROOT/fake-pillow" \
        python3 "$INSTALL_ROOT/shogun-screenshot/scripts/mask_sensitive.py" \
        --input "$TEST_ROOT/input.png" \
        --input-identity "$identity" \
        --output "$TEST_ROOT/outside.png" \
        --regions '10,10,12,12'
    [ "$status" -ne 0 ]
    [[ "$output" == *"region 1 does not overlap the image"* ]]
    [ ! -e "$TEST_ROOT/outside.png" ]

    run env PYTHONPATH="$TEST_ROOT/fake-pillow" \
        python3 "$INSTALL_ROOT/shogun-screenshot/scripts/mask_sensitive.py" \
        --input "$TEST_ROOT/input.png" \
        --input-identity "$identity" \
        --output "$TEST_ROOT/preview.png" \
        --regions '0,0,2,2' \
        --preview
    [ "$status" -ne 0 ]
    [[ "$output" == *"preview output is forbidden"* ]]
    [ ! -e "$TEST_ROOT/preview.png" ]
}

@test "installed trim and mask helpers atomically refuse concurrent output creation" {
    write_safe_png "$TEST_ROOT/input.png"
    identity="$(selected_identity "$TEST_ROOT/input.png")"
    printf 'protected\n' > "$TEST_ROOT/protected.txt"
    install_fake_pillow

    cat > "$TEST_ROOT/race_driver.py" <<'PY'
import importlib.util
import os
from pathlib import Path
import sys

script_dir = Path(sys.argv[1])
tool = sys.argv[2]
attack = sys.argv[3]
input_path = Path(sys.argv[4])
identity = sys.argv[5]
output_path = Path(sys.argv[6])
protected_path = Path(sys.argv[7])
sys.path.insert(0, str(script_dir))

import safe_image_io

real_link = safe_image_io.os.link

def racing_link(*args, **kwargs):
    if attack == "file":
        output_path.write_bytes(b"attacker-created\n")
    else:
        output_path.symlink_to(protected_path)
    return real_link(*args, **kwargs)

safe_image_io.os.link = racing_link
spec = importlib.util.spec_from_file_location(tool, script_dir / f"{tool}.py")
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)

arguments = [
    "--input", str(input_path),
    "--input-identity", identity,
    "--output", str(output_path),
]
if tool == "trim_image":
    arguments += ["--crop", "0,0,2,2"]
else:
    arguments += ["--regions", "0,0,2,2"]

raise SystemExit(module.main(arguments))
PY

    for tool in trim_image mask_sensitive; do
        for attack in file symlink; do
            output_path="$TEST_ROOT/${tool}-${attack}.png"
            run env PYTHONPATH="$TEST_ROOT/fake-pillow" \
                python3 "$TEST_ROOT/race_driver.py" \
                "$INSTALL_ROOT/shogun-screenshot/scripts" \
                "$tool" "$attack" "$TEST_ROOT/input.png" "$identity" \
                "$output_path" "$TEST_ROOT/protected.txt"
            [ "$status" -ne 0 ]
            [[ "$output" == *"output already exists"* ]]
            if [ "$attack" = file ]; then
                [ "$(cat "$output_path")" = "attacker-created" ]
            else
                [ -L "$output_path" ]
                [ "$(cat "$output_path")" = "protected" ]
            fi
            [ "$(cat "$TEST_ROOT/protected.txt")" = "protected" ]
            [ -z "$(find "$TEST_ROOT" -maxdepth 1 -name ".${tool}-${attack}.png.tmp-*" -print -quit)" ]
        done
    done
}

@test "installed selector enforces its input byte budget before and during reads" {
    write_safe_png "$TEST_ROOT/oversized.png"
    truncate -s 67108865 "$TEST_ROOT/oversized.png"

    run "$INSTALL_ROOT/shogun-screenshot/scripts/capture_local.sh" \
        --input "$TEST_ROOT/oversized.png"
    [ "$status" -ne 0 ]
    [[ "$output" == *"input exceeds the 67108864-byte limit"* ]]

    write_safe_png "$TEST_ROOT/growing.png"
    cat > "$TEST_ROOT/growing_read.py" <<'PY'
from pathlib import Path
import sys

script_dir = Path(sys.argv[1])
input_path = Path(sys.argv[2])
sys.path.insert(0, str(script_dir))
import safe_image_io

safe_image_io.MAX_INPUT_BYTES = 128
chunks = [input_path.read_bytes(), b"x" * 64, b"x" * 64, b""]

def growing_read(_descriptor, _size):
    return chunks.pop(0)

safe_image_io.os.read = growing_read
try:
    safe_image_io.read_image_snapshot(input_path)
except safe_image_io.ScreenshotSafetyError as exc:
    print(exc)
    raise SystemExit(0)
raise SystemExit("unbounded read was accepted")
PY

    run python3 "$TEST_ROOT/growing_read.py" \
        "$INSTALL_ROOT/shogun-screenshot/scripts" "$TEST_ROOT/growing.png"
    [ "$status" -eq 0 ]
    [[ "$output" == *"input exceeds the 128-byte limit"* ]]
}

@test "installed trim and mask helpers reject excessive dimensions and pixels" {
    write_safe_png "$TEST_ROOT/input.png"
    identity="$(selected_identity "$TEST_ROOT/input.png")"
    install_fake_pillow

    run env PYTHONPATH="$TEST_ROOT/fake-pillow" FAKE_IMAGE_SIZE='16385,1' \
        python3 "$INSTALL_ROOT/shogun-screenshot/scripts/trim_image.py" \
        --input "$TEST_ROOT/input.png" \
        --input-identity "$identity" \
        --output "$TEST_ROOT/too-wide.png" \
        --crop '0,0,2,1'
    [ "$status" -ne 0 ]
    [[ "$output" == *"maximum dimension is 16384 pixels"* ]]
    [ ! -e "$TEST_ROOT/too-wide.png" ]

    run env PYTHONPATH="$TEST_ROOT/fake-pillow" FAKE_IMAGE_SIZE='8000,5001' \
        python3 "$INSTALL_ROOT/shogun-screenshot/scripts/mask_sensitive.py" \
        --input "$TEST_ROOT/input.png" \
        --input-identity "$identity" \
        --output "$TEST_ROOT/too-many-pixels.png" \
        --regions '0,0,2,2'
    [ "$status" -ne 0 ]
    [[ "$output" == *"maximum pixel count is 40000000"* ]]
    [ ! -e "$TEST_ROOT/too-many-pixels.png" ]

    run env PYTHONPATH="$TEST_ROOT/fake-pillow" \
        python3 "$INSTALL_ROOT/shogun-screenshot/scripts/trim_image.py" \
        --input "$TEST_ROOT/input.png" \
        --input-identity "$identity" \
        --output "$TEST_ROOT/oversized-resize.png" \
        --crop '0,0,2,2' \
        --resize '8000,5001'
    [ "$status" -ne 0 ]
    [[ "$output" == *"maximum pixel count is 40000000"* ]]
    [ ! -e "$TEST_ROOT/oversized-resize.png" ]
}

@test "installed trim and mask helpers fail on Pillow decompression bomb signals" {
    write_safe_png "$TEST_ROOT/input.png"
    identity="$(selected_identity "$TEST_ROOT/input.png")"
    install_fake_pillow

    for tool in trim_image mask_sensitive; do
        for bomb in warning error; do
            output_path="$TEST_ROOT/${tool}-${bomb}-bomb.png"
            if [ "$tool" = trim_image ]; then
                run env PYTHONPATH="$TEST_ROOT/fake-pillow" FAKE_PILLOW_BOMB="$bomb" \
                    python3 "$INSTALL_ROOT/shogun-screenshot/scripts/trim_image.py" \
                    --input "$TEST_ROOT/input.png" \
                    --input-identity "$identity" \
                    --output "$output_path" \
                    --crop '0,0,2,2'
            else
                run env PYTHONPATH="$TEST_ROOT/fake-pillow" FAKE_PILLOW_BOMB="$bomb" \
                    python3 "$INSTALL_ROOT/shogun-screenshot/scripts/mask_sensitive.py" \
                    --input "$TEST_ROOT/input.png" \
                    --input-identity "$identity" \
                    --output "$output_path" \
                    --regions '0,0,2,2'
            fi
            [ "$status" -ne 0 ]
            [[ "$output" == *"Pillow decompression bomb"* ]]
            [ ! -e "$output_path" ]
        done
    done
}

@test "screenshot skill assigns routing selection processing and review to distinct roles" {
    skill="$PROJECT_ROOT/skills/shogun-screenshot/SKILL.md"
    run grep -F 'Karo routes' "$skill"
    [ "$status" -eq 0 ]
    run grep -F 'Ashigaru alone selects and processes' "$skill"
    [ "$status" -eq 0 ]
    run grep -F 'Gunshi and Oometsuke review' "$skill"
    [ "$status" -eq 0 ]
    run grep -F 'Never delete or overwrite the user original' "$skill"
    [ "$status" -eq 0 ]
    run grep -F -- '--input' "$skill"
    [ "$status" -eq 0 ]
    run grep -F 'Select every intermediate output again before using it as a new input' "$skill"
    [ "$status" -eq 0 ]
    run grep -F '64 MiB (67,108,864 bytes)' "$skill"
    [ "$status" -eq 0 ]
    run grep -F '16,384 pixels per dimension and 40,000,000 total pixels' "$skill"
    [ "$status" -eq 0 ]
    run grep -F 'including requested resize dimensions' "$skill"
    [ "$status" -eq 0 ]
}
