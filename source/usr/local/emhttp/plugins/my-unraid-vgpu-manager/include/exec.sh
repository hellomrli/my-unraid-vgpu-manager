#!/bin/bash
# exec.sh - helper functions for the my-unraid-vgpu-manager plugin page

PLUGIN="my-unraid-vgpu-manager"
PLGCFG="/boot/config/plugins/${PLUGIN}"
SETTINGS="${PLGCFG}/settings.cfg"
EMHTTP="/usr/local/emhttp/plugins/${PLUGIN}"
RC="${EMHTTP}/scripts/rc.vgpu"
KERNEL_V="$(uname -r)"
VERSIONS_CACHE="/tmp/vgpu_driver"
CRON_LINE="${EMHTTP}/include/update-check.sh"

# refresh the cache of driver versions available for this kernel (throttled to 5 min)
update() {
  if [ -f "${VERSIONS_CACHE}" ]; then
    local age=$(( $(date +%s) - $(stat -c %Y "${VERSIONS_CACHE}") ))
    [ ${age} -lt 300 ] && return 0
  fi
  # asset names: nvidia-<driver version>-<kernel>-Unraid-1.txz -> field 2 is the version
  wget -T 15 -qO- "https://api.github.com/repos/hellomrli/my-vgpu-driver/releases/tags/${KERNEL_V}" 2>/dev/null \
    | jq -r '.assets[].name' 2>/dev/null \
    | grep '^nvidia-' | grep -E -v '\.md5$' \
    | cut -d '-' -f2 | sort -V | uniq | tail -10 > "${VERSIONS_CACHE}"
  if [ ! -s "${VERSIONS_CACHE}" ]; then
    modinfo -F version nvidia 2>/dev/null | head -1 > "${VERSIONS_CACHE}"
  fi
}

get_latest_version() {
  echo -n "$(tail -1 "${VERSIONS_CACHE}" 2>/dev/null)"
}

get_available_versions() {
  cat "${VERSIONS_CACHE}" 2>/dev/null
}

get_installed_version() {
  echo -n "$(modinfo -F version nvidia 2>/dev/null | head -1)"
}

get_selected_version() {
  echo -n "$(grep -m1 '^driver_version=' "${SETTINGS}" 2>/dev/null | cut -d '=' -f2)"
}

# download (if needed) and live-install a driver version; runs inside an openBox window
update_driver() {
  local want="${1:-latest}"
  sed -i "/^driver_version=/c\driver_version=${want}" "${SETTINGS}" 2>/dev/null
  if "${EMHTTP}/include/download.sh" "${want}"; then
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
  echo "-----------------------Installing NVIDIA vGPU driver...------------------------"
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
