#!/bin/bash
# Prepare only opted-in drivers for the kernel staged on the Unraid flash drive.
# Called after an OS update, once per minute as a fallback, and from the UI.
# This script NEVER installs packages or loads/unloads modules.
set -o pipefail
source "$(dirname "$(readlink -f "$0")")/common.sh"
MODE="${1:-auto}"
STATE="/var/tmp/${PLUGIN}-upgrade.json"
NOTICE_URL="/Settings/${PLUGIN}?kernel_upgrade=1#kernel-upgrade-panel"
case "$MODE" in auto|prepare) ;; *) exit 1 ;; esac
AUTO_DOWNLOAD=true
[ "$MODE" != auto ] || [ "$(setting kernel_upgrade_check)" != false ] || AUTO_DOWNLOAD=false

NV="$(setting nvidia_installed)"
INTEL="$(setting intel_installed)"
# A cached package or detected GPU is not opt-in. Do not even query GitHub.
if [ "$NV" != true ] && [ "$INTEL" != true ]; then
  rm -f "$STATE"
  [ "$MODE" = auto ] || bilingual 'No GPU drivers are enabled. Install a driver manually first.' '尚未启用 GPU 驱动，请先按需手动安装。'
  exit 0
fi

TARGET="${2:-$(php "$EMHTTP/include/kernel.php" 2>/dev/null)}"
if ! valid_kernel "$TARGET"; then
  [ "$MODE" = auto ] && exit 0
  bilingual 'ERROR: cannot read the next boot kernel. Enter its full release, for example 6.18.47-Unraid.' '错误：无法读取下次启动的内核，请填写完整版本，例如 6.18.47-Unraid。' >&2
  exit 1
fi
if [ "$TARGET" = "$KERNEL_V" ]; then
  rm -f "$STATE"
  [ "$MODE" = auto ] || bilingual "The boot image uses the running kernel $KERNEL_V; no new kernel package is needed." "启动镜像与当前内核同为 $KERNEL_V，无需为新内核预下载驱动。"
  exit 0
fi

exec 6>"/var/lock/${PLUGIN}-upgrade.lock"
flock -n 6 || { [ "$MODE" = auto ] && exit 0; echo 'ERROR: kernel driver preparation is already running' >&2; exit 1; }
SERIES="$(nvidia_active_series)"
WANT="$(setting driver_version)"
[ -n "$WANT" ] || WANT=latest
valid_version "$WANT" || exit 1
KEY="$(printf '%s|%s|%s|%s|%s|%s' "$TARGET" "$NV" "$INTEL" "$SERIES" "$WANT" "$AUTO_DOWNLOAD" | sha256sum | cut -d' ' -f1)"
NOW="$(date +%s)"
if [ "$MODE" = auto ] && [ -s "$STATE" ]; then
  OLD_KEY="$(jq -r '.key // empty' "$STATE" 2>/dev/null)"
  OLD_STATUS="$(jq -r '.status // empty' "$STATE" 2>/dev/null)"
  LAST="$(jq -r '.checked_at // 0' "$STATE" 2>/dev/null)"
  if [ "$KEY" = "$OLD_KEY" ]; then
    # Retry missing packages at most every 30 minutes. Ready states are checked
    # hourly, so a manually removed or damaged cache does not stay ready forever.
    INTERVAL=1800
    [ "$OLD_STATUS" != ready ] || INTERVAL=3600
    if [[ "$LAST" =~ ^[0-9]+$ ]] && [ "$NOW" -ge "$LAST" ] && [ "$((NOW - LAST))" -lt "$INTERVAL" ]; then exit 0; fi
  else
    OLD_STATUS=""
  fi
fi

NSTATUS=disabled; ISTATUS=disabled; NPKG=""; IPKG=""
[ "$NV" != true ] || NSTATUS=pending
[ "$INTEL" != true ] || ISTATUS=pending
save_state() {
  local tmp
  tmp="$(mktemp "${STATE}.XXXXXX")" || return 1
  jq -n --arg key "$KEY" --arg kernel "$TARGET" --arg current "$KERNEL_V" \
    --arg status "$1" --arg nvidia "$NSTATUS" --arg intel "$ISTATUS" \
    --arg nvidia_package "$NPKG" --arg intel_package "$IPKG" --arg series "$SERIES" --arg wanted_version "$WANT" \
    --argjson checked_at "$(date +%s)" \
    '{key:$key,kernel:$kernel,current_kernel:$current,status:$status,nvidia:$nvidia,intel:$intel,
      nvidia_package:$nvidia_package,intel_package:$intel_package,series:$series,wanted_version:$wanted_version,checked_at:$checked_at}' > "$tmp" &&
    chmod 0644 "$tmp" && mv -f "$tmp" "$STATE"
}
if [ "$AUTO_DOWNLOAD" = true ]; then
  save_state downloading || exit 1
  MESSAGE="$(bilingual "New boot kernel $TARGET detected. Preparing enabled GPU drivers; wait for the result before rebooting." "检测到下次启动内核 $TARGET，正在准备已启用的 GPU 驱动，请等待结果后再重启。")"
  echo "$MESSAGE"
  # Do not repeat the progress notification during a successful periodic recheck.
  [ "${OLD_STATUS:-}" = ready ] || vgpu_notify "$MESSAGE" warning "$NOTICE_URL"
else
  save_state pending || exit 1
fi

RESULT=0
if [ "$NV" = true ] && [ "$(setting nvidia_installed)" = true ]; then
  if { [ "$AUTO_DOWNLOAD" = false ] || "$EMHTTP/include/download.sh" nvidia "$SERIES" "$WANT" --kernel "$TARGET"; } &&
     NPKG="$(find_package nvidia "$TARGET" "$SERIES" "$WANT")"; then
    NPKG="${NPKG##*/}"; NSTATUS=ready
  else NSTATUS=missing; RESULT=1; fi
else
  NSTATUS=disabled
fi
if [ "$INTEL" = true ] && [ "$(setting intel_installed)" = true ]; then
  if { [ "$AUTO_DOWNLOAD" = false ] || "$EMHTTP/include/download.sh" i915 latest --kernel "$TARGET"; } &&
     IPKG="$(find_package i915 "$TARGET")"; then
    IPKG="${IPKG##*/}"; ISTATUS=ready
  else ISTATUS=missing; RESULT=1; fi
else
  ISTATUS=disabled
fi
if [ "$RESULT" = 0 ]; then
  save_state ready || exit 1
  MESSAGE="$(bilingual "GPU driver packages for $TARGET are downloaded and verified. Reboot after the Unraid update completes; the enabled drivers will be restored locally." "$TARGET 对应的 GPU 驱动包已下载并校验。确认 Unraid 更新完成后即可重启，已启用的驱动会从本地恢复。")"
  echo "$MESSAGE"
  [ "${OLD_STATUS:-}" = ready ] || vgpu_notify "$MESSAGE" normal "$NOTICE_URL"
else
  save_state missing || exit 1
  status_zh() { case "$1" in ready) echo 已就绪 ;; disabled) echo 未启用 ;; *) echo 未就绪 ;; esac; }
  MESSAGE="$(bilingual "GPU drivers for $TARGET are NOT ready (NVIDIA: $NSTATUS, Intel: $ISTATUS). Check the vGPU Manager before rebooting; GPU features may be unavailable on the new kernel." "$TARGET 的 GPU 驱动尚未就绪（NVIDIA：$(status_zh "$NSTATUS")，Intel：$(status_zh "$ISTATUS")）。请在重启前打开 vGPU 管理页面检查，否则新内核下可能无法使用 GPU 功能。")"
  echo "$MESSAGE" >&2
  [ "${OLD_STATUS:-}" = missing ] || vgpu_notify "$MESSAGE" alert "$NOTICE_URL"
fi
# Disabling automatic downloads still leaves a notification entry to prepare
# manually. Missing local packages are expected in this notification-only mode.
[ "$AUTO_DOWNLOAD" != false ] || exit 0
exit "$RESULT"
