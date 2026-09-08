#!/bin/bash
# download.sh nvidia <16|19> [version] [--kernel release] [--refresh]
# download.sh i915 [version] [--kernel release] [--refresh]
# Installs may use verified local packages. --refresh always consults GitHub.
set -o pipefail
source "$(dirname "$(readlink -f "$0")")/common.sh"

SOURCE="${1:-nvidia}"
[ $# -eq 0 ] || shift
SERIES=""
case "$SOURCE" in
  nvidia)
    SERIES="${1:-$(nvidia_series)}"
    case "$SERIES" in 16|19) ;; *) echo 'ERROR: expected series 16 or 19' >&2; exit 1 ;; esac
    [ $# -eq 0 ] || shift ;;
  i915) ;;
  *) echo 'ERROR: expected nvidia or i915' >&2; exit 1 ;;
esac
WANT=latest
if [ $# -gt 0 ] && [[ "$1" != --* ]]; then WANT="$1"; shift; fi
TARGET_KERNEL="$KERNEL_V"
REFRESH=false
while [ $# -gt 0 ]; do
  case "$1" in
    --kernel) [ $# -ge 2 ] || exit 1; TARGET_KERNEL="$2"; shift 2 ;;
    --refresh) REFRESH=true; shift ;;
    *) echo "ERROR: unknown argument $1" >&2; exit 1 ;;
  esac
done
valid_kernel "$TARGET_KERNEL" && valid_version "$WANT" || {
  echo 'ERROR: invalid kernel or driver version' >&2; exit 1;
}
PKGDIR="$(package_dir "$TARGET_KERNEL")"
mkdir -p "$PKGDIR" || exit 1
exec 7>"${PKGDIR}/.download-${SOURCE}-${SERIES}.lock"
flock -n 7 || { echo 'ERROR: this driver is already downloading' >&2; exit 1; }

if [ "$REFRESH" = false ]; then
  LOCAL_PKG="$(find_package "$SOURCE" "$TARGET_KERNEL" "$SERIES" "$WANT")"
  if [ -n "$LOCAL_PKG" ]; then
    bilingual "Using verified local package: ${LOCAL_PKG##*/}" "使用已校验的本地驱动包：${LOCAL_PKG##*/}"
    exit 0
  fi
fi

AVAIL="$(release_assets "$SOURCE" "$TARGET_KERNEL" "$SERIES" "$WANT")" || {
  bilingual 'ERROR: could not query GitHub. No driver has been installed or updated.' '错误：无法查询 GitHub，未安装或更新任何驱动。' >&2
  exit 1
}
PKG="$(printf '%s\n' "$AVAIL" | tail -1)"
[ -n "$PKG" ] || {
  bilingual "ERROR: no matching ${SOURCE} package for ${TARGET_KERNEL} (version ${WANT})." "错误：未找到适用于 ${TARGET_KERNEL} 的 ${SOURCE} 驱动包（版本 ${WANT}）。" >&2
  exit 1
}
if md5_ok "${PKGDIR}/${PKG}"; then
  bilingual "The requested package is already downloaded and verified: $PKG" "所需驱动包已下载并通过校验：$PKG"
  exit 0
fi
case "$SOURCE" in nvidia) REPO="$NVIDIA_REPO" ;; i915) REPO="$I915_REPO" ;; esac
DL_URL="https://github.com/${REPO}/releases/download/${TARGET_KERNEL}"
STAGE="$(mktemp -d "${PKGDIR}/.download.XXXXXX")" || exit 1
trap 'rm -rf -- "$STAGE"' EXIT
trap 'exit 1' HUP INT TERM
bilingual "Downloading $PKG. Wait for verification before rebooting." "正在下载 $PKG，请等待校验完成后再重启。"
if ! curl -fL --connect-timeout 15 --max-time 1800 --speed-time 60 --speed-limit 1024 \
     --retry 2 --output "${STAGE}/${PKG}" "${DL_URL}/${PKG}" ||
   ! curl -fsSL --connect-timeout 10 --max-time 30 --output "${STAGE}/${PKG}.md5" "${DL_URL}/${PKG}.md5" ||
   ! md5_ok "${STAGE}/${PKG}"; then
  bilingual "ERROR: download or checksum failed: $PKG" "错误：驱动包下载或校验失败：$PKG" >&2
  exit 1
fi
# Publish only complete files. Retain other drivers, branches, the running
# kernel, rollback kernels and pre-downloaded upgrade kernels.
mv -f -- "${STAGE}/${PKG}.md5" "${PKGDIR}/${PKG}.md5" &&
  mv -f -- "${STAGE}/${PKG}" "${PKGDIR}/${PKG}" || exit 1
sync -f "$PKGDIR" 2>/dev/null || sync
bilingual "Downloaded and verified: $PKG" "驱动包已下载并通过校验：$PKG"
