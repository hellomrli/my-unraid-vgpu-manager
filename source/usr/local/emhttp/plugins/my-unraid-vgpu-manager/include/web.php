<?php
$vgpu_plugin = 'my-unraid-vgpu-manager';
$vgpu_emhttp = "/usr/local/emhttp/plugins/$vgpu_plugin";
$vgpu_cfgdir = "/boot/config/plugins/$vgpu_plugin";
$vgpu_usercfg = '/boot/config/nvidia-vgpu';
$vgpu_rc = "$vgpu_emhttp/scripts/rc.vgpu";
require_once __DIR__.'/kernel.php';

function vgpu_settings() {
    global $vgpu_cfgdir;
    $settings = [];
    foreach (@file("$vgpu_cfgdir/settings.cfg", FILE_IGNORE_NEW_LINES) ?: [] as $line) {
        $parts = explode('=', $line, 2);
        if (count($parts) === 2 && preg_match('/^[a-z][a-z0-9_]*$/D', $parts[0])) $settings[$parts[0]] = $parts[1];
    }
    return $settings;
}
function vgpu_setting($key, $default = '') {
    return vgpu_settings()[$key] ?? $default;
}
function vgpu_write_file($file, $content) {
    $dir = dirname($file);
    if (!is_dir($dir) && !mkdir($dir, 0755, true)) throw new RuntimeException('Could not create the configuration directory.');
    $tmp = tempnam($dir, '.vgpu.');
    if ($tmp === false) throw new RuntimeException('Could not save the configuration.');
    try {
        if (file_put_contents($tmp, $content) !== strlen($content) || !rename($tmp, $file)) {
            throw new RuntimeException('Could not save the configuration.');
        }
        @chmod($file, 0644);
    } finally {
        if (is_file($tmp)) unlink($tmp);
    }
}
function vgpu_set_settings($values) {
    global $vgpu_cfgdir;
    foreach ($values as $key => $value) {
        if (!preg_match('/^[a-z][a-z0-9_]*$/D', $key) || !is_string($value) || preg_match('/[\r\n\x00]/', $value)) {
            throw new InvalidArgumentException('Invalid settings value.');
        }
    }
    if (!is_dir($vgpu_cfgdir) && !mkdir($vgpu_cfgdir, 0755, true)) throw new RuntimeException('Could not create the configuration directory.');
    $lock = fopen("$vgpu_cfgdir/settings.cfg.lock", 'c');
    if (!$lock || !flock($lock, LOCK_EX)) throw new RuntimeException('Could not lock the configuration.');
    try {
        $settings = array_merge(vgpu_settings(), $values);
        $lines = [];
        foreach ($settings as $key => $value) $lines[] = "$key=$value";
        vgpu_write_file("$vgpu_cfgdir/settings.cfg", implode("\n", $lines)."\n");
    } finally { flock($lock, LOCK_UN); fclose($lock); }
}
function vgpu_init_language() {
    global $locale, $display, $vgpu_language, $vgpu_translations;
    // Unraid's page locale takes precedence. Standalone POST requests use its
    // existing session or display settings, never a plugin/browser preference.
    if (!isset($locale) && !isset($_SESSION['locale']) && session_status() === PHP_SESSION_NONE &&
        isset($_COOKIE[session_name()]) && !headers_sent()) {
        @session_start(['read_and_close' => true]);
    }
    $config = @parse_ini_file('/boot/config/plugins/dynamix/dynamix.cfg', true, INI_SCANNER_RAW) ?: [];
    $unraid_locale = $locale ?? $_SESSION['locale'] ?? $display['locale'] ?? $config['display']['locale'] ?? '';
    $vgpu_language = strncasecmp((string)$unraid_locale, 'zh', 2) === 0 ? 'zh_CN' : 'en';
    $vgpu_translations = $vgpu_language === 'zh_CN' ? (json_decode(file_get_contents(__DIR__.'/zh_CN.json'), true) ?: []) : [];
}
function vgpu_t($message, $params = []) {
    global $vgpu_translations;
    $translated = $vgpu_translations[$message] ?? $message;
    foreach ($params as $key => $value) $translated = str_replace('{'.$key.'}', (string)$value, $translated);
    return $translated;
}
function vgpu_h($text) {
    return htmlspecialchars((string)$text, ENT_QUOTES | ENT_SUBSTITUTE, 'UTF-8');
}
function vgpu_e($message, $params = []) { return vgpu_h(vgpu_t($message, $params)); }
function vgpu_json($value) {
    return json_encode($value, JSON_HEX_TAG | JSON_HEX_AMP | JSON_HEX_APOS | JSON_HEX_QUOT | JSON_UNESCAPED_UNICODE | JSON_INVALID_UTF8_SUBSTITUTE);
}
function vgpu_read($file) { return trim((string)@file_get_contents($file)); }
function vgpu_uuid_valid($uuid) {
    return preg_match('/^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/iD', $uuid) === 1;
}
function vgpu_devices() {
    global $vgpu_cfgdir;
    $devices = [];
    foreach (@file("$vgpu_cfgdir/vgpu-devices.cfg", FILE_IGNORE_NEW_LINES | FILE_SKIP_EMPTY_LINES) ?: [] as $line) {
        $row = explode('|', $line);
        if (count($row) !== 3 || !vgpu_uuid_valid($row[0]) || !preg_match('/^[0-9a-f]{4}:[0-9a-f]{2}:[0-9a-f]{2}\.[0-7]$/iD', $row[1]) || !preg_match('/^nvidia-[0-9]+$/D', $row[2])) continue;
        $uuid = strtolower($row[0]);
        $devices[$uuid] = ['uuid' => $uuid, 'pci' => strtolower($row[1]), 'type' => $row[2], 'running' => is_dir("/sys/bus/mdev/devices/$uuid")];
    }
    return array_values($devices);
}
function vgpu_run($arguments, $lock = null) {
    $descriptors = [0 => ['pipe', 'r'], 1 => ['pipe', 'w'], 2 => ['redirect', 1]];
    $env = null;
    if ($lock !== null) { $descriptors[9] = $lock; $env = array_merge(getenv(), ['VGPU_LOCK_FD' => '9']); }
    $process = proc_open($arguments, $descriptors, $pipes, null, $env);
    if (!is_resource($process)) return ['code' => 1, 'output' => 'Could not start the operation.'];
    fclose($pipes[0]);
    $output = stream_get_contents($pipes[1]);
    fclose($pipes[1]);
    return ['code' => proc_close($process), 'output' => trim($output)];
}
function vgpu_command_text($args) { return vgpu_run($args)['output']; }
function vgpu_driver_updates($mode = 'status') {
    global $vgpu_emhttp;
    $result = vgpu_run(['/bin/bash', "$vgpu_emhttp/include/update-check.sh", $mode]);
    $state = json_decode($result['output'], true);
    if (!is_array($state) || !isset($state['drivers'])) throw new RuntimeException('Could not check driver updates. Try again.');
    foreach ($state['drivers'] as &$driver) {
        $labels = ['disabled'=>'Not enabled', 'unchecked'=>'Not checked', 'current'=>'No newer driver available',
            'missing'=>'Not installed for this kernel', 'pinned'=>'A fixed driver version is selected',
            'error'=>'Update check failed. Try again.'];
        $driver['message'] = vgpu_t($labels[$driver['status']] ?? 'Not checked');
        if ($driver['status'] === 'available') {
            $driver['message'] = vgpu_t('Update available: {current} → {latest}', [
                'current'=>vgpu_package_label($driver['current']), 'latest'=>vgpu_package_label($driver['latest'])]);
        }
    }
    unset($driver);
    return $state;
}
function vgpu_package_label($package) {
    if (preg_match('/^(?:nvidia|i915-sriov)-([0-9.]+)-.+-([0-9]+)\.txz$/D', $package, $match)) {
        return vgpu_t('{version} (build {build})', ['version'=>$match[1], 'build'=>$match[2]]);
    }
    return $package;
}
function vgpu_update_rows($updates, $sources = ['nvidia','i915']) {
    foreach (['nvidia'=>'NVIDIA vGPU', 'i915'=>'Intel i915 SR-IOV'] as $source=>$name) {
        if (!in_array($source, $sources, true)) continue;
        $driver = $updates['drivers'][$source];
        if ($driver['status'] === 'disabled') continue;
        $available = $driver['status'] === 'available';
        echo '<tr data-update-row="'.$source.'"><td>'.vgpu_h($name).' '.vgpu_e('Driver update').':</td><td colspan="3">';
        echo '<span data-update-message="'.$source.'" class="'.($available ? 'vgpu-warn' : 'vgpu-muted').'">'.vgpu_h($driver['message']).'</span> ';
        echo '<button type="button" data-update-button="'.$source.'" data-command="'.($source === 'nvidia' ? 'update_driver' : 'update_intel').'" data-series="'.vgpu_h($driver['series']).'"'.($available ? '' : ' hidden').'>'.vgpu_e('Update driver').'</button></td></tr>';
    }
}
function vgpu_vms() {
    $result = vgpu_run(['virsh', 'list', '--all', '--name']);
    return $result['code'] === 0 ? array_values(array_filter(explode("\n", $result['output']), 'strlen')) : [];
}
function vgpu_xml_mdevs($xml) {
    if ($xml === '') return [];
    $old = libxml_use_internal_errors(true);
    try {
        $document = simplexml_load_string($xml, 'SimpleXMLElement', LIBXML_NONET);
        if ($document === false) return [];
        $uuids = [];
        foreach ($document->xpath('/domain/devices/hostdev[@type="mdev"]/source/address/@uuid') as $uuid) {
            if (vgpu_uuid_valid((string)$uuid)) $uuids[] = strtolower((string)$uuid);
        }
        return $uuids;
    } finally { libxml_clear_errors(); libxml_use_internal_errors($old); }
}
function vgpu_csrf_token() {
    global $var;
    if (isset($var['csrf_token']) && is_string($var['csrf_token'])) return $var['csrf_token'];
    $state = @parse_ini_file('/var/local/emhttp/var.ini', false, INI_SCANNER_RAW) ?: [];
    return $state['csrf_token'] ?? '';
}
function vgpu_form_fields($action) {
    $token = vgpu_h(vgpu_csrf_token());
    // Unraid consumes csrf_token in local_prepend.php. Keep a separate token
    // for validation here, including when testing outside the Unraid web server.
    echo '<input type="hidden" name="vgpu_action" value="'.vgpu_h($action).'">';
    echo '<input type="hidden" name="csrf_token" value="'.$token.'">';
    echo '<input type="hidden" name="vgpu_token" value="'.$token.'">';
}
vgpu_init_language();
