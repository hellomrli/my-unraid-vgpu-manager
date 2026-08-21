#!/bin/bash
# update-check.sh - daily cron job: check whether a newer driver build exists
# for an INSTALLED driver and notify the user. It NEVER downloads or installs
# anything - the user decides from the plugin page (Install button).

PLUGIN="my-unraid-vgpu-manager"
PLGCFG="/boot/config/plugins/${PLUGIN}"
SETTINGS="${PLGCFG}/settings.cfg"
KERNEL_V="$(uname -r)"

notify() {
  /usr/local/emhttp/plugins/dynamix/scripts/notify -e "Unraid vGPU Manager" -d "$1" -i "${2:-normal}" -l "/Settings/${PLUGIN}"
}

# only auto-check when the user follows the latest version
SET_DRV_V="$(grep -m1 '^driver_version=' "${SETTINGS}" 2>/dev/null | cut -d '=' -f2)"
[ "${SET_DRV_V}" = "latest" ] || exit 0

# check one driver repo; only notify when that driver is actually installed
check_repo() {
  local repo="$1" prefix="$2" installed="$3"
  [ -n "${installed}" ] || return 0
  local latest
  latest="$(wget -T 15 -qO- "https://api.github.com/repos/${repo}/releases/tags/${KERNEL_V}" 2>/dev/null \
    | jq -r '.assets[].name' 2>/dev/null \
    | grep "^${prefix}-" | grep -E -v '\.md5$' \
    | cut -d '-' -f2 | sort -V | uniq | tail -1)"
  if [ -n "${latest}" ] && [ "${latest}" != "${installed}" ]; then
    notify "New ${prefix} driver v${latest} available (installed: ${installed}). Open Settings -> Unraid vGPU Manager and click Install to download and install it."
  fi
}

# installed version: nvidia from modinfo, i915 from the installed package name
I915_PKG="$(ls "${PLGCFG}/packages/${KERNEL_V%%-*}/"i915-sriov-*.txz 2>/dev/null | head -1)"
check_repo "hellomrli/my-nvidia-vgpu-driver" "nvidia"     "$(modinfo -F version nvidia 2>/dev/null | head -1)"
check_repo "hellomrli/my-i915-sriov-driver"  "i915-sriov" "$(basename "${I915_PKG}" 2>/dev/null | cut -d '-' -f2)"
