#!/bin/bash
# exec.sh - helper functions for the my-unraid-vgpu-manager plugin page

PLUGIN="my-unraid-vgpu-manager"
PLGCFG="/boot/config/plugins/${PLUGIN}"
SETTINGS="${PLGCFG}/settings.cfg"
EMHTTP="/usr/local/emhttp/plugins/${PLUGIN}"
RC="${EMHTTP}/scripts/rc.vgpu"
KERNEL_V="$(uname -r)"
VERSIONS_CACHE_BASE="/tmp/vgpu_driver"
CRON_LINE="${EMHTTP}/include/update-check.sh"

# asset-name glob per driver series (the release carries both side by side)
nvidia_glob_for() {
  case "${1}" in
    19) echo "580." ;;
    *)  echo "535." ;;
  esac
}

versions_cache_for() {
  echo "${VERSIONS_CACHE_BASE}_$(nvidia_glob_for "$1" | tr -d '.')"
}

set_setting() {
  if grep -q "^${1}=" "${SETTINGS}" 2>/dev/null; then
    sed -i "s|^${1}=.*|${1}=${2}|" "${SETTINGS}"
  else
    echo "${1}=${2}" >> "${SETTINGS}"
  fi
}

# refresh the cache of driver versions available for this kernel + series
# (throttled to 5 min)
update() {
  local series="${1:-16}"
  local cache; cache="$(versions_cache_for "${series}")"
  if [ -f "${cache}" ]; then
    local age=$(( $(date +%s) - $(stat -c %Y "${cache}") ))
    [ ${age} -lt 300 ] && return 0
  fi
  local glob; glob="$(nvidia_glob_for "${series}")"
  # asset names: nvidia-<driver version>-<kernel>-Unraid-<b>.txz
  wget -T 15 -qO- "https://api.github.com/repos/hellomrli/my-nvidia-vgpu-driver/releases/tags/${KERNEL_V}" 2>/dev/null \
    | jq -r '.assets[].name' 2>/dev/null \
    | grep -F "nvidia-${glob}" | grep -E -v '\.md5$' \
    | cut -d '-' -f2 | sort -V | uniq | tail -10 > "${cache}"
  if [ ! -s "${cache}" ]; then
    modinfo -F version nvidia 2>/dev/null | head -1 > "${cache}"
  fi
}

get_latest_version() {
  local series="${1:-16}"
  echo -n "$(tail -1 "$(versions_cache_for "${series}")" 2>/dev/null)"
}

get_available_versions() {
  local series="${1:-16}"
  cat "$(versions_cache_for "${series}")" 2>/dev/null
}

get_installed_version() {
  echo -n "$(modinfo -F version nvidia 2>/dev/null | head -1)"
}

get_selected_version() {
  echo -n "$(grep -m1 '^driver_version=' "${SETTINGS}" 2>/dev/null | cut -d '=' -f2)"
}

# download (if needed) and live-install a driver version; runs inside an openBox window
update_driver() {
  local series="${1:-16}" want="${2:-latest}"
  sed -i "/^driver_version=/c\driver_version=${want}" "${SETTINGS}" 2>/dev/null
  set_setting nvidia_series "${series}"
  if "${EMHTTP}/include/download.sh" nvidia "${series}" "${want}"; then
    echo
    "${RC}" update
  else
    exit 1
  fi
}

restart_services() {
  echo "-----------------------Restarting vGPU services...------------------------------"
  "${RC}" restart
  echo
  "${RC}" status
  echo
  echo "----------------------------------DONE------------------------------------------"
}

apply_devices() {
  "${RC}" apply
}

change_update_check() {
  sed -i "/^update_check=/c\update_check=${1}" "${SETTINGS}"
  if [ "${1}" = "true" ]; then
    if ! crontab -l 2>/dev/null | grep -q "${CRON_LINE}"; then
      (crontab -l 2>/dev/null; echo "$((RANDOM % 59)) $(shuf -i 8-9 -n 1) * * * ${CRON_LINE} &>/dev/null 2>&1") | crontab -
    fi
  else
    crontab -l 2>/dev/null | grep -v "${CRON_LINE}" | crontab -
  fi
}

# --- on-demand driver install / uninstall (page buttons) ---

install_nvidia() {
  local series="${1:-16}"
  set_setting nvidia_series "${series}"
  echo "-----------------------Installing NVIDIA vGPU driver (series ${series})...-----------------------"
  "${EMHTTP}/include/download.sh" nvidia "${series}" latest || true
  "${RC}" nvidia_install
  echo
  "${RC}" status
  echo
  echo "----------------------------------DONE------------------------------------------"
}

uninstall_nvidia() {
  echo "-----------------------Uninstalling NVIDIA vGPU driver...----------------------"
  "${RC}" nvidia_uninstall
  echo
  echo "----------------------------------DONE------------------------------------------"
}

install_intel() {
  echo "-----------------------Installing Intel i915 SR-IOV driver...------------------"
  "${EMHTTP}/include/download.sh" i915 latest || true
  "${RC}" intel_install
  echo
  "${RC}" status
  echo
  echo "----------------------------------DONE------------------------------------------"
}

uninstall_intel() {
  echo "-----------------------Uninstalling Intel i915 SR-IOV driver...----------------"
  "${RC}" intel_uninstall
  echo
  echo "----------------------------------DONE------------------------------------------"
}

save_nvidia_settings() {
  # called from the page: persists license + module options, then applies them
  sed -i "/^nvidia_license_server=/c\nvidia_license_server=${1}" "${SETTINGS}" 2>/dev/null
  sed -i "/^nvidia_license_port=/c\nvidia_license_port=${2}" "${SETTINGS}" 2>/dev/null
  sed -i "/^nvidia_feature_type=/c\nvidia_feature_type=${3}" "${SETTINGS}" 2>/dev/null
  sed -i "/^nvidia_unlock=/c\nvidia_unlock=${4}" "${SETTINGS}" 2>/dev/null
  sed -i "/^nvidia_load_uvm=/c\nvidia_load_uvm=${5}" "${SETTINGS}" 2>/dev/null
  sed -i "/^nvidia_load_modeset=/c\nvidia_load_modeset=${6}" "${SETTINGS}" 2>/dev/null
  sed -i "/^nvidia_load_drm=/c\nvidia_load_drm=${7}" "${SETTINGS}" 2>/dev/null
  # apply the license immediately if the driver is running
  "${RC}" nvidia_license 2>/dev/null
}

save_intel_settings() {
  sed -i "/^intel_vf_number=/c\intel_vf_number=${1}" "${SETTINGS}" 2>/dev/null
  # hot-apply if i915 is loaded with SR-IOV
  "${RC}" intel_set_vfs "${1}" 2>/dev/null
}

"$@"
