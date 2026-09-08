<?php
require_once __DIR__.'/web.php';
header('Content-Type: application/json; charset=UTF-8');
header('Cache-Control: no-store');
function vgpu_post($key, $default = '') {
    $value = $_POST[$key] ?? $default;
    if (!is_string($value) || strpos($value, "\0") !== false) throw new InvalidArgumentException('Invalid form value.');
    return trim($value);
}
function vgpu_choice($key, $choices, $default = '') {
    $value = vgpu_post($key, $default);
    if (!in_array($value, $choices, true)) throw new InvalidArgumentException('Invalid form value.');
    return $value;
}
function vgpu_apply($args, $lock, $saved = false) {
    global $vgpu_rc;
    $result = vgpu_run(array_merge(['/bin/bash', $vgpu_rc], $args), $lock);
    if ($result['code'] !== 0) {
        $message = $saved ? 'Settings were saved, but applying them failed. {detail}' : 'Operation failed: {detail}';
        throw new RuntimeException(vgpu_t($message, ['detail' => $result['output']]));
    }
    return $result['output'];
}
$lock = null;
try {
    if (($_SERVER['REQUEST_METHOD'] ?? '') !== 'POST') { http_response_code(405); throw new RuntimeException('POST is required.'); }
    $token = vgpu_csrf_token();
    if ($token === '' || !hash_equals($token, vgpu_post('vgpu_token'))) {
        http_response_code(403);
        throw new RuntimeException('The page token expired. Refresh the page and try again.');
    }
    $action = vgpu_post('vgpu_action');
    if (!in_array($action, ['save_language','save_settings','save_nvidia','save_intel','save_override','add_device','start_device','stop_device','remove_device','attach_vm','detach_vm'], true)) {
        throw new InvalidArgumentException('Unknown operation.');
    }
    $lock = fopen('/var/lock/my-unraid-vgpu-manager.lock', 'c');
    if (!$lock || !flock($lock, LOCK_EX | LOCK_NB)) throw new RuntimeException('Another GPU operation is running. Try again after it finishes.');
    $message = '';
    switch ($action) {
        case 'save_language':
            vgpu_set_settings(['ui_language' => vgpu_choice('ui_language', ['auto', 'zh_CN', 'en'])]);
            vgpu_init_language();
            $message = vgpu_t('Language saved.');
            break;
        case 'save_settings':
            // General settings must not overwrite NVIDIA unlock/module options.
            vgpu_set_settings([
                'update_check' => vgpu_choice('update_check', ['true','false']),
                'kernel_upgrade_check' => vgpu_choice('kernel_upgrade_check', ['true','false'])
            ]);
            $result = vgpu_run(['/bin/bash', "$vgpu_emhttp/include/exec.sh", 'configure_cron'], $lock);
            if ($result['code'] !== 0) throw new RuntimeException('Settings were saved, but the scheduled checks could not be configured.');
            $message = vgpu_t('Settings saved.');
            break;
        case 'save_nvidia':
            $server = vgpu_post('license_server');
            $port = vgpu_post('license_port', '443');
            if ($server !== '' && (strlen($server) > 253 || !preg_match('/^(?:[A-Za-z0-9][A-Za-z0-9.-]*|\[[0-9a-fA-F:]+\])$/D', $server))) throw new InvalidArgumentException('Enter a license hostname or IP address without a URL, path or line break.');
            if (!ctype_digit($port) || strlen($port) > 5 || (int)$port < 1 || (int)$port > 65535) throw new InvalidArgumentException('The license port must be between 1 and 65535.');
            $series = vgpu_choice('driver_series', ['auto','16','19']);
            $unlock = vgpu_choice('unlock', ['true','false']);
            if ($series === '19' && $unlock === 'true') throw new InvalidArgumentException('vGPU unlock is only supported by the 16.x driver series.');
            $values = [
                'nvidia_license_server' => $server, 'nvidia_license_port' => (string)(int)$port,
                'nvidia_feature_type' => vgpu_choice('feature_type', ['0','1','2']),
                'nvidia_license_verify' => vgpu_choice('license_verify', ['true','false']),
                'nvidia_series' => $series, 'nvidia_unlock' => $unlock, 'unlock' => $unlock,
                'nvidia_load_uvm' => vgpu_choice('load_uvm', ['true','false']),
                'nvidia_load_modeset' => vgpu_choice('load_modeset', ['true','false']),
                'nvidia_load_drm' => vgpu_choice('load_drm', ['true','false'])
            ];
            if ($values['nvidia_load_drm'] === 'true' && $values['nvidia_load_modeset'] === 'false') throw new InvalidArgumentException('nvidia-drm requires nvidia-modeset. Enable both or disable DRM.');
            vgpu_set_settings($values);
            if (vgpu_setting('nvidia_installed') === 'true') vgpu_apply(['nvidia_license'], $lock, true);
            $message = vgpu_t('NVIDIA settings saved. Restart NVIDIA services after stopping GPU workloads to apply module or unlock changes.');
            break;
        case 'save_intel':
            $count = vgpu_post('vf_number');
            if (!ctype_digit($count) || strlen($count) > 2 || (int)$count > 63) throw new InvalidArgumentException('Enter a VF count between 0 and 63, within the GPU limit.');
            vgpu_apply(['intel_set_vfs', (string)(int)$count], $lock);
            $message = vgpu_t('Intel VF count applied and saved.');
            break;
        case 'save_override':
            $content = $_POST['override_content'] ?? '';
            if (!is_string($content) || strlen($content) > 65536 || strpos($content, "\0") !== false) throw new InvalidArgumentException('The profile override must be text, no larger than 64 KiB.');
            vgpu_write_file("$vgpu_usercfg/profile_override.toml", str_replace("\r", '', $content));
            $message = vgpu_t('Profile overrides saved. Restart NVIDIA services and cold-start the VM to apply them.');
            break;
        default:
            $uuid = strtolower(vgpu_post('uuid'));
            if (!vgpu_uuid_valid($uuid)) throw new InvalidArgumentException('Invalid vGPU UUID.');
            $commands = ['add_device'=>'nvidia_add_device','start_device'=>'nvidia_start_device','stop_device'=>'nvidia_stop_device','remove_device'=>'nvidia_remove_device','attach_vm'=>'nvidia_attach_vm','detach_vm'=>'nvidia_detach_vm'];
            $args = [$commands[$action], $uuid];
            if ($action === 'add_device') { $args[] = vgpu_post('pci'); $args[] = vgpu_post('mtype'); }
            if ($action === 'attach_vm' || $action === 'detach_vm') {
                $vm = vgpu_post('vm');
                if ($vm === '' || !in_array($vm, vgpu_vms(), true)) throw new InvalidArgumentException('Choose an existing virtual machine.');
                $args[] = $vm;
            }
            vgpu_apply($args, $lock);
            $message = in_array($action, ['attach_vm', 'detach_vm'], true)
                ? vgpu_t('VM configuration updated. Shut down and start the VM again for the change to take effect.')
                : vgpu_t('vGPU operation completed.');
    }
    echo vgpu_json(['ok' => true, 'message' => $message]);
} catch (Throwable $error) {
    if (http_response_code() < 400) http_response_code(400);
    echo vgpu_json(['ok' => false, 'message' => vgpu_t($error->getMessage())]);
} finally {
    if (is_resource($lock)) { flock($lock, LOCK_UN); fclose($lock); }
}
