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
record_running_kernel || exit 1
exec 5>"${PLGCFG}/.cache.lock"
flock -s 5 || exit 1
mkdir -p "$PKGDIR" || exit 1
exec 7>"${PKGDIR}/.download-${SOURCE}-${SERIES}.lock"
flock -n 7 || { echo 'ERROR: this driver is already downloading' >&2; exit 1; }

finish_download() {
  if [ "$TARGET_KERNEL" != "$KERNEL_V" ]; then set_setting prepared_kernel "$TARGET_KERNEL" || return 1; fi
  flock -u 7; exec 7>&-
  flock -u 5; exec 5>&-
  prune_cache "$TARGET_KERNEL" "$1"
}

if [ "$REFRESH" = false ]; then
  LOCAL_PKG="$(find_package "$SOURCE" "$TARGET_KERNEL" "$SERIES" "$WANT")"
  if [ -n "$LOCAL_PKG" ]; then
    bilingual "Using verified local package: ${LOCAL_PKG##*/}" "使用已校验的本地驱动包：${LOCAL_PKG##*/}"
    finish_download "$LOCAL_PKG"; exit $?
  fi
fi

AVAIL="$(release_assets "$SOURCE" "$TARGET_KERNEL" "$SERIES" "$WANT" 25 metadata)" || {
  result=$?
  [ "$result" = 2 ] || bilingual 'ERROR: could not query GitHub. No driver has been installed or updated.' '错误：无法查询 GitHub，未安装或更新任何驱动。' >&2
  exit 1
}
ASSET="$(printf '%s\n' "$AVAIL" | tail -1)"
PKG="${ASSET%%$'\t'*}"
DIGEST="${ASSET#*$'\t'}"; DIGEST="${DIGEST,,}"
[ "$DIGEST" != "$ASSET" ] || DIGEST=''
if [ -n "$DIGEST" ] && ! [[ "$DIGEST" =~ ^sha256:[0-9a-f]{64}$ ]]; then
  echo 'ERROR: invalid or unsupported GitHub asset digest' >&2; exit 1
fi
[ -n "$PKG" ] || {
  bilingual "ERROR: no matching ${SOURCE} package for ${TARGET_KERNEL} (version ${WANT})." "错误：未找到适用于 ${TARGET_KERNEL} 的 ${SOURCE} 驱动包（版本 ${WANT}）。" >&2
  exit 1
}
package_matches "$PKG" "$SOURCE" "$TARGET_KERNEL" "$SERIES" "$WANT" || {
  echo 'ERROR: invalid GitHub package metadata' >&2; exit 1;
}
if package_ok "${PKGDIR}/${PKG}" &&
   { [ -z "$DIGEST" ] || [ "$(sha256sum -- "${PKGDIR}/${PKG}" | cut -d' ' -f1)" = "${DIGEST#sha256:}" ]; }; then
  if [ -n "$DIGEST" ]; then
    checksum="$(mktemp "${PKGDIR}/.sha256.XXXXXX")" || exit 1
    printf '%s  %s\n' "${DIGEST#sha256:}" "$PKG" > "$checksum"
    mv -f "$checksum" "${PKGDIR}/${PKG}.sha256" || exit 1
  fi
  bilingual "The requested package is already downloaded and verified: $PKG" "所需驱动包已下载并通过校验：$PKG"
  finish_download "$PKG"; exit $?
fi
case "$SOURCE" in nvidia) REPO="$NVIDIA_REPO" ;; i915) REPO="$I915_REPO" ;; esac
DL_URL="https://github.com/${REPO}/releases/download/${TARGET_KERNEL}"
STAGE="$(mktemp -d "${PKGDIR}/.download.XXXXXX")" || exit 1
trap 'rm -rf -- "$STAGE"' EXIT
trap 'exit 1' HUP INT TERM
bilingual "Downloading $PKG. Wait for verification before rebooting." "正在下载 $PKG，请等待校验完成后再重启。"
# Background checks write to a log file; a progress meter would only fill it.
PROGRESS=()
[ "${VGPU_QUIET:-}" != 1 ] || PROGRESS=(--no-progress-meter)
if ! curl -fL "${PROGRESS[@]}" --connect-timeout 15 --max-time 1800 --speed-time 60 --speed-limit 1024 \
     --retry 2 --output "${STAGE}/${PKG}" "${DL_URL}/${PKG}" ||
   ! curl -fsSL --connect-timeout 10 --max-time 30 --output "${STAGE}/${PKG}.md5" "${DL_URL}/${PKG}.md5"; then
  bilingual "ERROR: download or checksum failed: $PKG" "错误：驱动包下载或校验失败：$PKG" >&2
  exit 1
fi
# GitHub computes this digest at upload time. Older releases may lack it;
# keep compatibility with their MD5 and optional SHA-256 sidecars.
if [ -n "$DIGEST" ]; then
  printf '%s  %s\n' "${DIGEST#sha256:}" "$PKG" > "${STAGE}/${PKG}.sha256"
else
  curl -fsSL --connect-timeout 10 --max-time 30 --output "${STAGE}/${PKG}.sha256" "${DL_URL}/${PKG}.sha256" >/dev/null 2>&1 ||
    rm -f -- "${STAGE}/${PKG}.sha256"
fi
if ! package_ok "${STAGE}/${PKG}"; then
  bilingual "ERROR: download or checksum failed: $PKG" "错误：驱动包下载或校验失败：$PKG" >&2
  exit 1
fi
# Publish only complete files, then prune obsolete verified builds/kernels.
rm -f -- "${PKGDIR}/${PKG}.sha256"
if [ -f "${STAGE}/${PKG}.sha256" ]; then mv -f -- "${STAGE}/${PKG}.sha256" "${PKGDIR}/${PKG}.sha256" || exit 1; fi
mv -f -- "${STAGE}/${PKG}.md5" "${PKGDIR}/${PKG}.md5" &&
  mv -f -- "${STAGE}/${PKG}" "${PKGDIR}/${PKG}" || exit 1
sync -f "$PKGDIR" 2>/dev/null || sync
bilingual "Downloaded and verified: $PKG" "驱动包已下载并通过校验：$PKG"
finish_download "$PKG"
