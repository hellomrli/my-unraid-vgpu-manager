#!/bin/bash
# Shared configuration, package matching and release lookup. No actions on source.
PLUGIN="my-unraid-vgpu-manager"
PLGCFG="/boot/config/plugins/${PLUGIN}"
SETTINGS="${PLGCFG}/settings.cfg"
EMHTTP="/usr/local/emhttp/plugins/${PLUGIN}"
KERNEL_V="$(uname -r)"
NVIDIA_REPO="hellomrli/my-nvidia-vgpu-driver"
I915_REPO="hellomrli/my-i915-sriov-driver"

setting() {
  grep -m1 "^${1}=" "${SETTINGS}" 2>/dev/null | cut -d '=' -f2-
}

# Lock the read/modify/write as well as the final rename. PHP uses the same lock.
set_setting() (
  local key="$1" value="$2" line found=0 tmp
  [[ "$key" =~ ^[a-z][a-z0-9_]*$ ]] || return 1
  [[ "$value" != *$'\n'* && "$value" != *$'\r'* ]] || return 1
  mkdir -p "$PLGCFG" || return 1
  exec 8>"${SETTINGS}.lock"
  flock -x 8 || return 1
  # Settings live on the flash drive. Skip the rewrite when nothing changes.
  if [ -f "$SETTINGS" ] && [ "$(grep -c "^${key}=" "$SETTINGS")" = 1 ] &&
     grep -qxF -- "${key}=${value}" "$SETTINGS"; then
    return 0
  fi
  tmp="$(mktemp "${PLGCFG}/.settings.XXXXXX")" || return 1
  if [ -f "$SETTINGS" ]; then
    while IFS= read -r line || [ -n "$line" ]; do
      if [[ "$line" == "$key="* ]]; then
        [ "$found" = 1 ] || printf '%s=%s\n' "$key" "$value"
        found=1
      else
        printf '%s\n' "$line"
      fi
    done < "$SETTINGS" > "$tmp"
  fi
  [ "$found" = 1 ] || printf '%s=%s\n' "$key" "$value" >> "$tmp"
  chmod 0644 "$tmp" 2>/dev/null || true
  mv -f "$tmp" "$SETTINGS"
)

valid_kernel() {
  [[ "$1" =~ ^[0-9]+([.][0-9]+){1,2}(-[A-Za-z0-9._+]+)*-Unraid$ ]]
}

valid_version() {
  [[ "$1" = latest || "$1" =~ ^[0-9]+([.][0-9]+)*$ ]]
}

# A version becomes a fixed-width, lexicographically comparable key. Dotted
# versions (535.309.01, 2026.09.16) and the legacy dot-stripped i915 date form
# (202608121) both map into the same six-field space, so mixed naming stays
# ordered and same-version rebuilds keep working.
#
# `sort -V` must not be used for this: it compares a digit run by numeric value,
# which ranked the 9-digit 202608121 above the newer 8-digit 20260916 and made
# every later i915 release look older than the installed one.
version_key() {
  local version="$1" rest part key='' index
  local -a fields=()
  [[ "$version" =~ ^[0-9]+([.][0-9]+)*$ ]] || return 1
  if [[ "$version" == *.* ]]; then
    IFS=. read -r -a fields <<< "$version"
  elif [ "${#version}" -ge 8 ]; then
    # Legacy i915 form: YYYYMMDD with an optional build counter appended.
    fields=("${version:0:4}" "${version:4:2}" "${version:6:2}")
    rest="${version:8}"
    [ -z "$rest" ] || fields+=("$((10#$rest))")
  else
    fields=("$version")
  fi
  for index in 0 1 2 3 4 5; do
    part="${fields[index]:-0}"
    key+="$(printf '%010d' "$((10#$part))")"
  done
  printf '%s\n' "$key"
}

# The package build counter is the last key field. Comparing it as text
# ranked -10 below -2, so the tenth rebuild would never be selected.
package_version_key() {
  local name="${1##*/}" rest key build
  case "$name" in
    nvidia-*) rest="${name#nvidia-}" ;;
    i915-sriov-*) rest="${name#i915-sriov-}" ;;
    *) return 1 ;;
  esac
  key="$(version_key "${rest%%-*}")" || return 1
  build="${name##*-}"; build="${build%.txz}"
  [[ "$build" =~ ^[0-9]{1,9}$ ]] || build=0
  printf '%s%010d\n' "$key" "$((10#$build))"
}

# Oldest-first ordering for package names or paths. Entries without a
# recognizable version sort first, so callers that keep the last match never
# mistake them for a driver.
sort_by_version() {
  local item base key
  while IFS= read -r item; do
    [ -n "$item" ] || continue
    base="${item##*/}"
    key="$(package_version_key "$base")" || key=''
    printf '%s\t%s\n' "$key" "$item"
  done | LC_ALL=C sort -t $'\t' -k1,1 -k2,2 -u | cut -f2-
}

series_prefix() {
  case "$1" in 16) echo 535 ;; 19) echo 580 ;; *) return 1 ;; esac
}

package_dir() {
  printf '%s/packages/%s\n' "$PLGCFG" "${1%%-*}"
}

# Match the COMPLETE kernel and numeric build, never a loose substring or .md5.
package_matches() {
  local name="$1" source="$2" kernel="$3" series="${4:-}" want="${5:-latest}"
  local prefix rest version build
  case "$source" in nvidia) prefix=nvidia ;; i915) prefix=i915-sriov ;; *) return 1 ;; esac
  [[ "$name" == "$prefix-"* ]] || return 1
  rest="${name#"$prefix-"}"
  version="${rest%%-*}"
  [[ "$version" =~ ^[0-9]+([.][0-9]+)*$ ]] || return 1
  if [ "$source" = nvidia ] && [ -n "$series" ]; then
    [[ "$version" == "$(series_prefix "$series")".* ]] || return 1
  fi
  [[ "$want" = latest || "$version" = "$want" ]] || return 1
  rest="${rest#*-}"
  [[ "$rest" == "$kernel-"* ]] || return 1
  build="${rest#"$kernel-"}"
  [[ "$build" =~ ^[0-9]+[.]txz$ ]]
}

checksum_ok() {
  local file="$1" kind="$2" length expected actual
  case "$kind" in md5) length=32 ;; sha256) length=64 ;; *) return 1 ;; esac
  expected="$(awk 'NR == 1 {print tolower($1)}' "${file}.${kind}")"
  [[ "$expected" =~ ^[0-9a-f]{$length}$ ]] || return 1
  actual="$("${kind}sum" -- "$file")" || return 1
  [ "${actual%% *}" = "$expected" ]
}

# Releases publish .md5 files. A .sha256 file, when the release provides one,
# must match as well.
package_ok() {
  local file="$1"
  [ -s "$file" ] && [ -f "${file}.md5" ] || return 1
  checksum_ok "$file" md5 || return 1
  [ ! -e "${file}.sha256" ] || checksum_ok "$file" sha256
}

find_package() {
  local source="$1" kernel="$2" series="${3:-}" want="${4:-latest}" file best=''
  # Walk oldest-first and keep the last verified match, so the newest package
  # wins without depending on `sort -V`'s treatment of the version field.
  while IFS= read -r file; do
    [ -n "$file" ] || continue
    package_matches "${file##*/}" "$source" "$kernel" "$series" "$want" || continue
    package_ok "$file" || continue
    best="$file"
  done < <(sort_by_version < <(printf '%s\n' "$(package_dir "$kernel")"/*.txz))
  [ -n "$best" ] || return 1
  printf '%s\n' "$best"
}

# The Slackware package database identifies rebuilds that modinfo cannot see.
installed_package() {
  local source="$1" kernel="${2:-$KERNEL_V}" db file name
  for db in /var/log/packages /var/lib/pkgtools/packages; do
    [ -d "$db" ] || continue
    for file in "$db"/*; do
      [ -f "$file" ] || continue
      name="${file##*/}.txz"
      package_matches "$name" "$source" "$kernel" || continue
      printf '%s\n' "$name"
    done
  done | sort_by_version | tail -1
}

nvidia_gpu_ids() {
  local dev
  for dev in /sys/bus/pci/devices/*; do
    [ "$(cat "$dev/vendor" 2>/dev/null)" = 0x10de ] || continue
    [ ! -L "$dev/physfn" ] || continue
    case "$(cat "$dev/class" 2>/dev/null)" in 0x03*) cat "$dev/device" ;; esac
  done | sort -u
}

nvidia_series_caps() {
  local ids
  ids="$(nvidia_gpu_ids)"
  jq -r --arg ids "$ids" '
    ($ids | split("\n") | map(select(length > 0))) as $gpus |
    if ($gpus | length) == 0 then "none" else
      . as $map | ["16", "19"] | map(. as $s |
        select(all($gpus[]; . as $id | $map[$s] | index($id) != null))) |
      if length == 2 then "both" elif length == 1 then .[0] else "none" end
    end' "$EMHTTP/include/gpu-series.json"
}

nvidia_series() {
  local selected
  selected="$(setting nvidia_series)"
  case "$selected" in 16|19) echo "$selected" ;; *)
    case "$(nvidia_series_caps)" in both|19) echo 19 ;; *) echo 16 ;; esac ;;
  esac
}

# OS upgrades keep the last installed series, even if the page's next-install
# preference has changed. An OS upgrade must not silently switch GPU branches.
nvidia_active_series() {
  local pkg version
  pkg="$(installed_package nvidia)"
  [ -n "$pkg" ] || pkg="$(setting nvidia_package)"
  case "$pkg" in nvidia-580.*) echo 19; return ;; nvidia-535.*) echo 16; return ;; esac
  version="$(cat /sys/module/nvidia/version 2>/dev/null)"
  case "$version" in 580.*) echo 19 ;; 535.*) echo 16 ;; *) nvidia_series ;; esac
}

release_assets() {
  local source="$1" kernel="$2" series="${3:-}" want="${4:-latest}" max_time="${5:-25}" repo data name
  valid_kernel "$kernel" && valid_version "$want" || return 1
  case "$source" in nvidia) repo="$NVIDIA_REPO" ;; i915) repo="$I915_REPO" ;; *) return 1 ;; esac
  data="$(curl -fsSL --connect-timeout 8 --max-time "$max_time" \
    "https://api.github.com/repos/${repo}/releases/tags/${kernel}")" || return 1
  jq -e '.assets | type == "array"' <<< "$data" >/dev/null 2>&1 || return 1
  while IFS= read -r name; do
    if package_matches "$name" "$source" "$kernel" "$series" "$want"; then printf '%s\n' "$name"; fi
  done < <(jq -r '.assets[]?.name // empty' <<< "$data") | sort_by_version
}

# Read [display] locale from Unraid's settings without starting PHP.
is_chinese() {
  local language
  language="$(awk -F= '
    /^[[:space:]]*\[/ { section = $0; gsub(/[][[:space:]]/, "", section); next }
    section == "display" {
      key = $1; gsub(/[[:space:]]/, "", key)
      if (key == "locale") { value = substr($0, index($0, "=") + 1); gsub(/^[[:space:]"]+|[[:space:]"]+$/, "", value); print value; exit }
    }' /boot/config/plugins/dynamix/dynamix.cfg 2>/dev/null)"
  case "$language" in [zZ][hH]*) return 0 ;; *) return 1 ;; esac
}

bilingual() {
  if is_chinese; then printf '%s\n' "$2"; else printf '%s\n' "$1"; fi
}

vgpu_notify() {
  /usr/local/emhttp/plugins/dynamix/scripts/notify -e "Unraid vGPU Manager" \
    -d "$1" -i "${2:-normal}" -l "${3:-/Settings/${PLUGIN}}"
}

# Logs under /var/log live in a small RAM filesystem. Keep the newest part.
trim_log() {
  local file="$1" limit="${2:-1048576}" size
  size="$(stat -c %s -- "$file" 2>/dev/null)" || return 0
  [ "$size" -gt "$limit" ] || return 0
  tail -c "$((limit / 2))" -- "$file" > "${file}.tmp" && cat -- "${file}.tmp" > "$file"
  rm -f -- "${file}.tmp"
}

# Serialize runtime actions, including PHP mdev/VM operations. The web helper
# holds this lock while invoking rc.vgpu and passes its inherited descriptor.
operation_lock() {
  if [ "${VGPU_LOCK_FD:-}" = 9 ] && [ -e /proc/self/fd/9 ] &&
     [ "$(readlink /proc/self/fd/9)" = "/var/lock/${PLUGIN}.lock" ]; then
    return 0
  fi
  exec 9>"/var/lock/${PLUGIN}.lock"
  if ! flock -n 9; then
    bilingual 'ERROR: another GPU operation is running. Try again after it finishes.' '错误：另一个 GPU 操作正在执行，请等待完成后重试。' >&2
    return 1
  fi
  export VGPU_LOCK_FD=9
}
