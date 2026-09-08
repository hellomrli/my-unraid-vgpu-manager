#!/bin/bash
# Allowlisted UI operations. Failures retain their exit status all the way to UI.
source "$(dirname "$(readlink -f "$0")")/common.sh"
RC="$EMHTTP/scripts/rc.vgpu"

configure_cron() {
  local tmp
  tmp="$(mktemp)" || return 1
  crontab -l 2>/dev/null | grep -Fv -- "$EMHTTP/include/update-check.sh" |
    grep -Fv -- "$EMHTTP/include/upgrade-check.sh" > "$tmp"
  if [ "$(setting update_check)" = true ]; then
    printf '17 9 * * * %s/include/update-check.sh >/dev/null 2>&1\n' "$EMHTTP" >> "$tmp"
  fi
  if [ "$(setting kernel_upgrade_check)" != false ]; then
    printf '* * * * * %s/include/upgrade-check.sh auto >>/var/log/%s-upgrade.log 2>&1\n' "$EMHTTP" "$PLUGIN" >> "$tmp"
  fi
  crontab "$tmp"
  local result=$?
  rm -f "$tmp"
  return "$result"
}

change_update_check() {
  case "${1:-}" in true|false) ;; *) return 1 ;; esac
  set_setting update_check "$1" && configure_cron
}

install_nvidia() {
  local series="${1:-$(nvidia_series)}" pkg
  series_prefix "$series" >/dev/null || return 1
  operation_lock || return 1
  "$EMHTTP/include/download.sh" nvidia "$series" latest || return 1
  pkg="$(find_package nvidia "$KERNEL_V" "$series")" || return 1
  set_setting nvidia_series "$series" && set_setting driver_version latest || return 1
  "$RC" nvidia_install "$pkg"
}

update_driver() {
  local series="${1:-$(nvidia_series)}" want="${2:-latest}" pkg
  series_prefix "$series" >/dev/null && valid_version "$want" || return 1
  [ "$(setting nvidia_installed)" = true ] || { echo 'ERROR: NVIDIA is not enabled'; return 1; }
  operation_lock || return 1
  "$EMHTTP/include/download.sh" nvidia "$series" "$want" --refresh || return 1
  pkg="$(find_package nvidia "$KERNEL_V" "$series" "$want")" || return 1
  set_setting nvidia_series "$series" && set_setting driver_version "$want" || return 1
  "$RC" nvidia_update "$pkg"
}

install_intel() {
  local pkg
  operation_lock || return 1
  "$EMHTTP/include/download.sh" i915 latest || return 1
  pkg="$(find_package i915 "$KERNEL_V")" || return 1
  "$RC" intel_install "$pkg"
}

update_intel() {
  local pkg
  [ "$(setting intel_installed)" = true ] || { echo 'ERROR: Intel is not enabled'; return 1; }
  operation_lock || return 1
  "$EMHTTP/include/download.sh" i915 latest --refresh || return 1
  pkg="$(find_package i915 "$KERNEL_V")" || return 1
  "$RC" intel_install "$pkg"
}

case "${1:-}" in
  configure_cron) configure_cron; exit $? ;;
  change_update_check) change_update_check "${2:-}"; exit $? ;;
  get_boot_kernel) exec php "$EMHTTP/include/kernel.php" ;;
  prepare_kernel) exec "$EMHTTP/include/upgrade-check.sh" prepare "${2:-}" ;;
  install_nvidia|update_driver|install_intel|update_intel)
    action="$1"; shift; "$action" "$@"; result=$? ;;
  uninstall_nvidia) "$RC" nvidia_uninstall; result=$? ;;
  uninstall_intel) "$RC" intel_uninstall; result=$? ;;
  restart_services) "$RC" restart; result=$? ;;
  apply_devices) "$RC" apply; result=$? ;;
  *) echo 'ERROR: unknown operation' >&2; exit 1 ;;
esac
if [ "$result" = 0 ]; then
  bilingual 'Operation completed. Close this window to refresh the status.' '操作完成，关闭窗口后刷新状态。'
else
  bilingual 'ERROR: operation failed. Check the messages above before retrying.' '错误：操作未完成，请查看上方日志后重试。' >&2
fi
exit "$result"
