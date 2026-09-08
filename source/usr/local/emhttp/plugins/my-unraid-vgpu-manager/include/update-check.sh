#!/bin/bash
# Daily notifications only, for enabled drivers. Includes same-version rebuilds.
source "$(dirname "$(readlink -f "$0")")/common.sh"
[ "$(setting update_check)" = true ] || exit 0
check_driver() {
  local source="$1" series="${2:-}" current latest names marker
  current="$(installed_package "$source")"
  [ -n "$current" ] || return 0
  names="$(release_assets "$source" "$KERNEL_V" "$series")" || return 1
  latest="$(printf '%s\n' "$names" | tail -1)"
  marker="/var/tmp/${PLUGIN}-update-${source}"
  if [ -n "$latest" ] && [ "$latest" != "$current" ] &&
     [ "$(printf '%s\n%s\n' "$current" "$latest" | sort -V | tail -1)" = "$latest" ]; then
    [ "$(cat "$marker" 2>/dev/null)" != "$latest|$current" ] || return 0
    vgpu_notify "$(bilingual "New $source driver package: $latest. Open vGPU Manager to update (installed: $current)." "发现新的 $source 驱动包：$latest。请打开 vGPU 管理页面更新（当前：$current）。")" &&
      printf '%s|%s\n' "$latest" "$current" > "$marker"
  else
    rm -f "$marker"
  fi
}
RESULT=0
if [ "$(setting nvidia_installed)" = true ] && [ "$(setting driver_version)" = latest ]; then
  check_driver nvidia "$(nvidia_active_series)" || RESULT=1
fi
if [ "$(setting intel_installed)" = true ]; then check_driver i915 || RESULT=1; fi
exit "$RESULT"
