#!/bin/bash
# download.sh [nvidia|i915] [version] - make sure the requested driver packages
# for the running kernel are present on the flash drive.
# Called from the .plg on boot/install and from the plugin page before an update.
#
# Two independent sources:
#   nvidia - NVIDIA vGPU merged driver from hellomrli/my-nvidia-vgpu-driver (tag = kernel)
#   i915   - Intel i915 SR-IOV driver from hellomrli/my-i915-sriov-driver (tag = kernel)
#
# LOCAL-FIRST behaviour: a package placed manually in
#   /boot/config/plugins/my-unraid-vgpu-manager/packages/<kernel-major>/
# is used as-is (no download). GitHub is only consulted when no local package
# exists - and if GitHub is unreachable the local package is still used.

PLUGIN="my-unraid-vgpu-manager"
PLGCFG="/boot/config/plugins/${PLUGIN}"
SETTINGS="${PLGCFG}/settings.cfg"
KERNEL_V="$(uname -r)"
PKGDIR="${PLGCFG}/packages/${KERNEL_V%%-*}"
NVIDIA_REPO="hellomrli/my-nvidia-vgpu-driver"
I915_REPO="hellomrli/my-i915-sriov-driver"

# pick source: first arg is nvidia (default) or i915
SRC="${1:-nvidia}"
[ "${SRC}" = "i915" ] || SRC="nvidia"
shift 2>/dev/null || true

WANT="${1:-$(grep -m1 '^driver_version=' "${SETTINGS}" 2>/dev/null | cut -d '=' -f2)}"
[ -n "${WANT}" ] || WANT="latest"

mkdir -p "${PKGDIR}"

md5_ok() {
  [ -f "${1}" ] && [ -f "${1}.md5" ] || return 1
  [ "$(md5sum "${1}" | awk '{print $1}')" = "$(awk '{print $1}' "${1}.md5")" ]
}

# nvidia: packages named nvidia-<ver>-<kernel>-Unraid-1.txz, Release tag = kernel
nvidia_source() {
  DL_URL="https://github.com/${NVIDIA_REPO}/releases/download/${KERNEL_V}"
  API_URL="https://api.github.com/repos/${NVIDIA_REPO}/releases/tags/${KERNEL_V}"
  PATTERN='^nvidia-'
  LOCAL_PKG="$(ls "${PKGDIR}"/nvidia-*.txz 2>/dev/null | sort -V | tail -1)"
}

# i915: packages named i915-sriov-<ver>-<kernel>-Unraid-<b>.txz.
# The Release tag is NOT the bare kernel; find the newest release whose assets
# contain an i915-sriov-<...>-<kernel>-Unraid-*.txz.
i915_source() {
  API_URL="https://api.github.com/repos/${I915_REPO}/releases"
  PATTERN="i915-sriov-.*-${KERNEL_V}-Unraid-"
  # newest release matching this kernel (releases are listed newest-first)
  PKG="$(wget -T 15 -qO- "${API_URL}?per_page=20" 2>/dev/null \
    | jq -r --arg kv "${KERNEL_V}" '[.[] | .tag_name as $t | .assets[].name | select(startswith("i915-sriov-") and contains("-" + $kv + "-") and endswith(".txz")) | {tag: $t, name: .}] | .[0] | "\(.tag)|\(.name)"' 2>/dev/null)"
  if [ -n "${PKG}" ]; then
    I915_TAG="${PKG%%|*}"
    I915_PKG="${PKG#*|}"
    DL_URL="https://github.com/${I915_REPO}/releases/download/${I915_TAG}"
    API_URL="https://api.github.com/repos/${I915_REPO}/releases/tags/${I915_TAG}"
  fi
  LOCAL_PKG="$(ls "${PKGDIR}"/i915-*.txz 2>/dev/null | sort -V | tail -1)"
}

case "${SRC}" in
  nvidia) nvidia_source ;;
  i915)   i915_source ;;
esac

# Local-first: if a package for this kernel already exists on the flash drive,
# verify it and use it without touching the network.
if [ -n "${LOCAL_PKG}" ] && [ "${WANT}" = "latest" ]; then
  if md5_ok "${LOCAL_PKG}"; then
    echo "-------Using local ${SRC} package $(basename "${LOCAL_PKG}") (checksum OK)-------"
    exit 0
  else
    echo "-----WARNING: local ${SRC} package $(basename "${LOCAL_PKG}") failed checksum, re-downloading-----"
  fi
fi

# list of available package assets for this kernel (may be empty when offline)
if [ "${SRC}" = "nvidia" ]; then
  AVAIL="$(wget -T 15 -qO- "${API_URL}" | jq -r '.assets[].name' 2>/dev/null | grep "${PATTERN}" | grep -E -v '\.md5$' | sort -V)"
else
  # i915: use the release found above (if any)
  AVAIL=""
  [ -n "${I915_PKG}" ] && AVAIL="${I915_PKG}"
fi

if [ -z "${AVAIL}" ]; then
  if [ -n "${LOCAL_PKG}" ]; then
    echo "---Can't reach GitHub, using local ${SRC} package $(basename "${LOCAL_PKG}")---"
    exit 0
  fi
  echo
  echo "-----ERROR - ERROR - ERROR - ERROR - ERROR - ERROR - ERROR - ERROR - ERROR------"
  echo "----No ${SRC} driver package found for kernel ${KERNEL_V} and no local copy exists----"
  echo "---Check your internet connection, or wait for a build for this kernel to be---"
  echo "---------------published, then reinstall/update the plugin.--------------------"
  exit 1
fi

# packages are named <vendor>-<driver version>-<kernel>-Unraid-1.txz
if [ "${WANT}" = "latest" ]; then
  PKG="$(echo "${AVAIL}" | tail -1)"
else
  PKG="$(echo "${AVAIL}" | grep -- "-${WANT}-" | sort -V | tail -1)"
  if [ -z "${PKG}" ]; then
    echo "---Requested driver v${WANT} not found for this kernel, falling back to latest---"
    PKG="$(echo "${AVAIL}" | tail -1)"
    sed -i '/^driver_version=/c\driver_version=latest' "${SETTINGS}" 2>/dev/null
  fi
fi
PKG_V="$(echo "${PKG}" | sed -E 's/^(nvidia|i915-sriov)-([0-9.]+).*/\2/')"

if md5_ok "${PKGDIR}/${PKG}"; then
  echo "-------${SRC} driver package v${PKG_V} already downloaded, checksum OK-------"
else
  echo
  echo "+==============================================================================="
  echo "| Downloading ${SRC} driver package v${PKG_V} for kernel ${KERNEL_V}"
  echo "| Please don't close this window until it is finished!"
  echo "+==============================================================================="
  echo
  rm -f "${PKGDIR}/${PKG}" "${PKGDIR}/${PKG}.md5"
  if wget -q --show-progress --progress=bar:force:noscroll -O "${PKGDIR}/${PKG}" "${DL_URL}/${PKG}" &&
     wget -q -O "${PKGDIR}/${PKG}.md5" "${DL_URL}/${PKG}.md5" &&
     md5_ok "${PKGDIR}/${PKG}"; then
    echo
    echo "----------Successfully downloaded ${SRC} driver package v${PKG_V}----------"
  else
    rm -f "${PKGDIR}/${PKG}" "${PKGDIR}/${PKG}.md5"
    echo
    echo "-----ERROR - ERROR - ERROR - ERROR - ERROR - ERROR - ERROR - ERROR - ERROR------"
    echo "-------Download or checksum of ${SRC} driver package v${PKG_V} failed!----------------"
    if [ -n "${LOCAL_PKG}" ]; then
      echo "---------Keeping existing local package $(basename "${LOCAL_PKG}")---------"
      exit 0
    fi
    exit 1
  fi
fi

# remove packages for other kernels and older builds for this kernel
for d in "${PLGCFG}/packages/"*/; do
  [ "${d}" = "${PKGDIR}/" ] || rm -rf "${d}"
done
for f in "${PKGDIR}"/*; do
  case "$(basename "${f}")" in
    "${PKG}"|"${PKG}.md5") ;;
    *) rm -f "${f}" ;;
  esac
done
exit 0
