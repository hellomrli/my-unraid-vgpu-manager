#!/bin/bash
# Release metadata only: no driver download or installation. Cache results for
# the status table and daily notifications, including same-version rebuilds.
source "$(dirname "$(readlink -f "$0")")/common.sh"
MODE="${1:-auto}"
case "$MODE" in auto|check|refresh|status) ;; *) exit 1 ;; esac
STATE="/var/tmp/${PLUGIN}-updates.json"
NV="$(setting nvidia_installed)"; INTEL="$(setting intel_installed)"
CURRENT_NV="$(installed_package nvidia)"; CURRENT_INTEL="$(installed_package i915)"
SERIES="$(nvidia_active_series)"; WANT="$(setting driver_version)"; WANT="${WANT:-latest}"
KEY="$(printf '%s|%s|%s|%s|%s|%s|%s' "$KERNEL_V" "$NV" "$INTEL" "$CURRENT_NV" "$CURRENT_INTEL" "$SERIES" "$WANT" | sha256sum | cut -d' ' -f1)"

initial_driver() {
  local enabled="$1" current="$2" series="$3" want="$4" status=unchecked
  if [ "$enabled" != true ]; then status=disabled
  elif [ -z "$current" ]; then status=missing
  elif [ "$want" != latest ]; then status=pinned; fi
  jq -cn --arg status "$status" --arg current "$current" --arg series "$series" \
    '{status:$status,current:$current,latest:"",series:$series}'
}
BASE="$(jq -cn --arg key "$KEY" --arg kernel "$KERNEL_V" \
  --argjson nvidia "$(initial_driver "$NV" "$CURRENT_NV" "$SERIES" "$WANT")" \
  --argjson i915 "$(initial_driver "$INTEL" "$CURRENT_INTEL" '' latest)" \
  '{key:$key,kernel:$kernel,checked_at:0,drivers:{nvidia:$nvidia,i915:$i915}}')" || exit 1
cached_state() {
  jq -ce --arg key "$KEY" 'select(.key == $key and (.drivers | type) == "object")' "$STATE" 2>/dev/null || printf '%s\n' "$BASE"
}
CACHE="$(cached_state)"
if [ "$MODE" = status ]; then printf '%s\n' "$CACHE"; exit 0; fi
if [ "$MODE" != refresh ] && [ "$(setting update_check)" != true ]; then
  [ "$MODE" = auto ] || printf '%s\n' "$CACHE"
  exit 0
fi
# Page loads reuse recent metadata. The explicit check button always refreshes.
if [ "$MODE" = check ]; then
  LAST="$(jq -r '.checked_at // 0' <<< "$CACHE")"; NOW="$(date +%s)"
  INTERVAL=86400
  if jq -e '.drivers[] | select(.status == "error")' <<< "$CACHE" >/dev/null; then INTERVAL=300; fi
  if [[ "$LAST" =~ ^[0-9]+$ ]] && [ "$NOW" -ge "$LAST" ] && [ "$((NOW - LAST))" -lt "$INTERVAL" ]; then
    printf '%s\n' "$CACHE"; exit 0
  fi
fi
exec 7>"/var/lock/${PLUGIN}-updates.lock"
if ! flock -n 7; then
  [ "$MODE" = auto ] || printf '%s\n' "$CACHE"
  exit 0
fi

check_driver() {
  local source="$1" series="$2" item current names latest status marker
  item="$(jq -c --arg source "$source" '.drivers[$source]' <<< "$BASE")"
  status="$(jq -r '.status' <<< "$item")"
  marker="/var/tmp/${PLUGIN}-update-${source}"
  if [ "$status" != unchecked ]; then
    rm -f "$marker"
    printf '%s\n' "$item"; return
  fi
  current="$(jq -r '.current' <<< "$item")"
  status=error; latest=''
  if names="$(release_assets "$source" "$KERNEL_V" "$series")"; then
    latest="$(printf '%s\n' "$names" | tail -1)"
    if [ -n "$latest" ]; then
      status=current
      if [ "$latest" != "$current" ] && [ "$(printf '%s\n%s\n' "$current" "$latest" | sort -V | tail -1)" = "$latest" ]; then status=available; fi
    fi
  fi
  if [ "$status" = available ] && [ "$MODE" = auto ]; then
    if [ "$(cat "$marker" 2>/dev/null)" != "$latest|$current" ]; then
      vgpu_notify "$(bilingual "New $source driver package: $latest. Open vGPU Manager to update (installed: $current)." "发现新的 $source 驱动包：$latest。请打开 vGPU 管理页面更新（当前：$current）。")" >/dev/null &&
        printf '%s|%s\n' "$latest" "$current" > "$marker"
    fi
  elif [ "$status" = current ]; then rm -f "$marker"; fi
  jq -cn --arg status "$status" --arg current "$current" --arg latest "$latest" --arg series "$series" \
    '{status:$status,current:$current,latest:$latest,series:$series}'
}
NEXT="$(jq -cn --argjson base "$BASE" \
  --argjson nvidia "$(check_driver nvidia "$SERIES")" --argjson i915 "$(check_driver i915 '')" \
  --argjson checked_at "$(date +%s)" \
  '$base | .checked_at=$checked_at | .drivers={nvidia:$nvidia,i915:$i915}')" || exit 1
TMP="$(mktemp "${STATE}.XXXXXX")" || exit 1
printf '%s\n' "$NEXT" > "$TMP" && chmod 0644 "$TMP" && mv -f "$TMP" "$STATE" || { rm -f "$TMP"; exit 1; }
if [ "$MODE" != auto ]; then printf '%s\n' "$NEXT"
else ! jq -e '.drivers[] | select(.status == "error")' <<< "$NEXT" >/dev/null; fi
