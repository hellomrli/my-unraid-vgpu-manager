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

md5_ok() {
  local file="$1" expected actual
  [ -s "$file" ] && [ -f "${file}.md5" ] || return 1
  expected="$(awk 'NR == 1 {print tolower($1)}' "${file}.md5")"
  [[ "$expected" =~ ^[0-9a-f]{32}$ ]] || return 1
  actual="$(md5sum -- "$file")" || return 1
  [ "${actual%% *}" = "$expected" ]
}

find_package() {
  local source="$1" kernel="$2" series="${3:-}" want="${4:-latest}" file
  while IFS= read -r file; do
    package_matches "${file##*/}" "$source" "$kernel" "$series" "$want" || continue
    if md5_ok "$file"; then printf '%s\n' "$file"; return 0; fi
  done < <(printf '%s\n' "$(package_dir "$kernel")"/*.txz | sort -Vr)
  return 1
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
  done | sort -Vu | tail -1
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
  local source="$1" kernel="$2" series="${3:-}" want="${4:-latest}" repo data name
  valid_kernel "$kernel" && valid_version "$want" || return 1
  case "$source" in nvidia) repo="$NVIDIA_REPO" ;; i915) repo="$I915_REPO" ;; *) return 1 ;; esac
  data="$(curl -fsSL --connect-timeout 8 --max-time 25 \
    "https://api.github.com/repos/${repo}/releases/tags/${kernel}")" || return 1
  jq -e '.assets | type == "array"' <<< "$data" >/dev/null 2>&1 || return 1
  while IFS= read -r name; do
    if package_matches "$name" "$source" "$kernel" "$series" "$want"; then printf '%s\n' "$name"; fi
  done < <(jq -r '.assets[]?.name // empty' <<< "$data") | sort -Vu
}

is_chinese() {
  local language
  language="$(setting ui_language)"
  if [ "$language" = auto ]; then
    language="$(sed -n 's/^locale="\{0,1\}\([^" ]*\)"\{0,1\}$/\1/p' /boot/config/plugins/dynamix/dynamix.cfg 2>/dev/null | head -1)"
    [ -n "$language" ] || language=en
  fi
  case "${language:-zh_CN}" in zh*) return 0 ;; *) return 1 ;; esac
}

bilingual() {
  if is_chinese; then printf '%s\n' "$2"; else printf '%s\n' "$1"; fi
}

vgpu_notify() {
  /usr/local/emhttp/plugins/dynamix/scripts/notify -e "Unraid vGPU Manager" \
    -d "$1" -i "${2:-normal}" -l "/Settings/${PLUGIN}"
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
