#!/bin/bash
# Download pinned, checksum-verified PHP CLI and ShellCheck binaries into
# .tools/ for hosts without system packages. scripts/check.sh uses them.
set -euo pipefail
cd "$(dirname "$(readlink -f "$0")")/.."
[ "$(uname -sm)" = 'Linux x86_64' ] || { echo 'Only Linux x86_64 binaries are pinned.' >&2; exit 1; }
TOOLS=.tools
mkdir -p "$TOOLS"
fetch() {
  local url="$1" sha256="$2" file="$3"
  curl -fsSL --retry 2 -o "$file" "$url"
  echo "$sha256  $file" | sha256sum -c --quiet - || { rm -f "$file"; exit 1; }
}
if [ ! -x "$TOOLS/php" ]; then
  fetch https://dl.static-php.dev/static-php-cli/common/php-8.4.11-cli-linux-x86_64.tar.gz \
    4d5f2b9c8cc3f2ed68c2792a2a01df08d57044c3b393d79e1f9f368302439589 "$TOOLS/php.tar.gz"
  tar -xzf "$TOOLS/php.tar.gz" -C "$TOOLS" php && rm -f "$TOOLS/php.tar.gz"
fi
if [ ! -x "$TOOLS/shellcheck" ]; then
  fetch https://github.com/koalaman/shellcheck/releases/download/v0.10.0/shellcheck-v0.10.0.linux.x86_64.tar.xz \
    6c881ab0698e4e6ea235245f22832860544f17ba386442fe7e9d629f8cbedf87 "$TOOLS/shellcheck.tar.xz"
  tar -xJf "$TOOLS/shellcheck.tar.xz" -C "$TOOLS" --strip-components=1 shellcheck-v0.10.0/shellcheck
  rm -f "$TOOLS/shellcheck.tar.xz"
fi
"$TOOLS/php" -v | head -1
"$TOOLS/shellcheck" --version | sed -n 2p
