#!/bin/bash
set -euo pipefail
cd "$(dirname "$(readlink -f "$0")")/.."
for command in php python3 node shellcheck bwrap jq; do
  command -v "$command" >/dev/null || { echo "Required check tool is missing: $command" >&2; exit 1; }
done
while IFS= read -r -d '' file; do
  case "$file" in
    *.php|*.page) php -l "$file" >/dev/null ;;
    *.sh|*/rc.vgpu|*/event/*|*/post-hooks/*) bash -n "$file"; shellcheck -S warning -e SC1091 "$file" ;;
  esac
done < <(find source -type f -print0)
node --check source/usr/local/emhttp/plugins/my-unraid-vgpu-manager/include/ui.js
python3 - <<'PY'
import json,subprocess,tempfile,xml.etree.ElementTree as ET
from pathlib import Path
for file in Path('source').rglob('*.json'): json.loads(file.read_text())
manifest=ET.parse('my-unraid-vgpu-manager.plg').getroot()
for entry in manifest.findall('FILE'):
    if entry.get('Run') == '/bin/bash':
        with tempfile.NamedTemporaryFile(mode='w',suffix='.sh') as script:
            script.write(entry.findtext('INLINE').lstrip()); script.flush()
            subprocess.run(['bash','-n',script.name],check=True)
            subprocess.run(['shellcheck','-s','bash','-S','warning','-e','SC1091',script.name],check=True)
print('PHP, JavaScript, shell, JSON and plugin XML checks passed.')
PY
python3 -m unittest discover -s tests -p 'test_*.py' -v
python3 scripts/build-plugin.py --check
git diff --check
