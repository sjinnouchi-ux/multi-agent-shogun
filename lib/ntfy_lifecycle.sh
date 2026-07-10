#!/usr/bin/env bash
# Listener launch policy. Standby is the default; legacy launch is opt-in only.

ntfy_resolve_listener_mode() {
    local settings_file="${1:-}"
    local mode="${NTFY_LISTENER_MODE:-}"

    if [ -z "$mode" ] && [ -f "$settings_file" ]; then
        mode="$(awk '
            /^[[:space:]]*ntfy_listener:[[:space:]]*$/ { in_section=1; next }
            in_section && /^[^[:space:]#]/ { exit }
            in_section && /^[[:space:]]+mode:[[:space:]]*/ {
                value=$0
                sub(/^[[:space:]]+mode:[[:space:]]*/, "", value)
                sub(/[[:space:]#].*$/, "", value)
                gsub(/["\047]/, "", value)
                print value
                exit
            }
        ' "$settings_file")"
    fi

    case "$mode" in
        systemd|legacy|disabled) printf '%s\n' "$mode" ;;
        *) printf '%s\n' "disabled" ;;
    esac
}

ntfy_systemd_listener_active() {
    command -v systemctl >/dev/null 2>&1 || return 1
    systemctl --user is-active --quiet shogun-ntfy-listener.service
}

# fork-divergence: listener startup is disabled by default. If systemctl is
# unavailable, only an explicit mode=legacy may use the old background path.
ntfy_legacy_start_allowed() {
    local mode="${1:-disabled}"
    [ "$mode" = "legacy" ] || return 1
    ntfy_systemd_listener_active && return 1
    return 0
}
