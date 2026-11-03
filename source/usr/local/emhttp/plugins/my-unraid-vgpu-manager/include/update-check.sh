#!/bin/bash
# Release metadata only: no driver download or installation. Cache results for
# the status table and daily notifications, including same-version rebuilds.
source "$(dirname "$(readlink -f "$0")")/common.sh"
MODE="${1:-auto}"
case "$MODE" in auto|check|refresh|status) ;; *) exit 1 ;; esac
STATE="/var/tmp/${PLUGIN}-updates.json"
NV="$(setting nvidia_installed)"; INTEL="$(setting intel_installed)"
INTEL_DRIVER="$(intel_driver)" || exit 1
PENDING_INTEL="$(intel_pending_driver)" || exit 1
CURRENT_NV="$(installed_package nvidia)"; CURRENT_INTEL="$(installed_package "$INTEL_DRIVER")"
SERIES="$(nvidia_active_series)"; WANT="$(setting driver_version)"; WANT="${WANT:-latest}"
KEY="$(printf '%s|' "$KERNEL_V" "$NV" "$INTEL" "$CURRENT_NV" "$CURRENT_INTEL" "$SERIES" "$WANT" "$INTEL_DRIVER" "$PENDING_INTEL" | sha256sum | cut -d' ' -f1)"

initial_driver() {
  local enabled="$1" current="$2" series="$3" want="$4" status=unchecked
  if [ "$enabled" != true ]; then status=disabled
  elif [ -z "$current" ]; then status=missing
  elif [ "$want" != latest ]; then status=pinned; fi
  jq -cn --arg status "$status" --arg current "$current" --arg series "$series" \
    '{status:$status,current:$current,latest:"",series:$series}'
}
INTEL_STATE="$(initial_driver "$INTEL" "$CURRENT_INTEL" '' latest)"
if [ -n "$PENDING_INTEL" ]; then INTEL_STATE="$(jq -c '.status="switch_pending"' <<< "$INTEL_STATE")"; fi
BASE="$(jq -cn --arg key "$KEY" --arg kernel "$KERNEL_V" --arg source "$INTEL_DRIVER" \
  --argjson nvidia "$(initial_driver "$NV" "$CURRENT_NV" "$SERIES" "$WANT")" \
  --argjson intel "$INTEL_STATE" \
  '{key:$key,kernel:$kernel,checked_at:0,drivers:{nvidia:$nvidia,($source):$intel}}')" || exit 1
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
  if jq -e '.drivers[] | select(.status == "error" or .status == "rate_limited")' <<< "$CACHE" >/dev/null; then INTERVAL=300; fi
  if [[ "$LAST" =~ ^[0-9]+$ ]] && [ "$NOW" -ge "$LAST" ] && [ "$((NOW - LAST))" -lt "$INTERVAL" ]; then
    printf '%s\n' "$CACHE"; exit 0
  fi
fi
exec 7>"/var/lock/${PLUGIN}-updates.lock"
if ! flock -n 7; then
  [ "$MODE" = auto ] || jq -c '. + {busy:true}' <<< "$CACHE"
  exit 0
fi

check_driver() {
  local source="$1" series="$2" item current names latest status marker current_key latest_key
  item="$(jq -c --arg source "$source" '.drivers[$source]' <<< "$BASE")"
  status="$(jq -r '.status' <<< "$item")"
  marker="/var/tmp/${PLUGIN}-update-${source}"
  if [ "$status" != unchecked ]; then
    rm -f "$marker"
    printf '%s\n' "$item"; return
  fi
  current="$(jq -r '.current' <<< "$item")"
  status=error; latest=''
  # Leave time for both enabled drivers within the web request's 30s deadline.
  # curl diagnostics must not corrupt the JSON response or the other result.
  if names="$(release_assets "$source" "$KERNEL_V" "$series" latest 12 2>/dev/null)"; then
    latest="$(printf '%s\n' "$names" | tail -1)"
    if [ -n "$latest" ]; then
      status=current
      # Compare normalized version keys, never `sort -V` over the file names: the
      # i915 version field encodes a date, so the shorter newer number used to
      # lose against the longer older one and no update was ever reported.
      # The key includes the build counter, so only a strictly newer package
      # (including a same-version rebuild) counts. A different but older name
      # must never be offered, or "updating" would downgrade the driver.
      current_key="$(package_version_key "$current")" || current_key=''
      latest_key="$(package_version_key "$latest")" || latest_key=''
      if [ -n "$latest_key" ] && [[ "$latest_key" > "$current_key" ]]; then
        status=available
      fi
    fi
  elif [ "$?" = 2 ]; then
    status=rate_limited
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
  --arg source "$INTEL_DRIVER" --argjson nvidia "$(check_driver nvidia "$SERIES")" --argjson intel "$(check_driver "$INTEL_DRIVER" '')" \
  --argjson checked_at "$(date +%s)" \
  '$base | .checked_at=$checked_at | .drivers={nvidia:$nvidia,($source):$intel}')" || exit 1
TMP="$(mktemp "${STATE}.XXXXXX")" || exit 1
printf '%s\n' "$NEXT" > "$TMP" && chmod 0644 "$TMP" && mv -f "$TMP" "$STATE" || { rm -f "$TMP"; exit 1; }
if [ "$MODE" != auto ]; then printf '%s\n' "$NEXT"
else ! jq -e '.drivers[] | select(.status == "error" or .status == "rate_limited")' <<< "$NEXT" >/dev/null; fi
