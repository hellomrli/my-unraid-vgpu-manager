<?php
// CLI-only: stop GPU consumers for an explicitly requested driver update.
if (PHP_SAPI !== 'cli') { http_response_code(404); exit; }

function workload_command($args, $seconds = 20) {
    $command = implode(' ', array_map('escapeshellarg', array_merge(['timeout', '-k', '5', (string)$seconds], $args)));
    exec($command.' 2>&1', $lines, $code);
    if ($code !== 0) throw new RuntimeException(implode(' ', $args).': '.implode("\n", $lines));
    return implode("\n", $lines);
}
function workload_lines($text) {
    return array_values(array_filter(explode("\n", trim($text)), 'strlen'));
}
function workload_path_matches($path, $nodes) {
    $path = rtrim($path, '/');
    if ($path === '') return false;
    foreach ($nodes as $node) {
        if ($node === $path || strpos($node, $path.'/') === 0) return true;
        $real = realpath($path);
        if ($real !== false && $real === realpath($node)) return true;
    }
    return false;
}
try {
    $stack = $argv[1] ?? '';
    if (!in_array($stack, ['nvidia', 'intel'], true)) throw new RuntimeException('Invalid GPU stack');
    $pcis = array_slice($argv, 2);
    $uuids = [];
    foreach (glob('/sys/bus/mdev/devices/*') ?: [] as $device) {
        $real = realpath($device);
        foreach ($pcis as $pci) if (strpos($real ?: '', '/'.$pci.'/') !== false) $uuids[] = basename($device);
    }
    if ($stack === 'nvidia') {
        foreach (@file('/boot/config/plugins/my-unraid-vgpu-manager/vgpu-devices.cfg', FILE_IGNORE_NEW_LINES) ?: [] as $line) {
            $parts = explode('|', $line);
            if (count($parts) >= 2 && in_array($parts[1], $pcis, true)) $uuids[] = $parts[0];
        }
    }
    $nodes = [];
    foreach (glob('/sys/class/drm/*') ?: [] as $device) {
        if (!preg_match('/^(card[0-9]+|renderD[0-9]+)$/D', basename($device))) continue;
        $pci = basename(realpath($device.'/device') ?: '');
        if (in_array($pci, $pcis, true)) $nodes[] = '/dev/dri/'.basename($device);
    }
    if ($stack === 'nvidia') $nodes = array_merge($nodes, glob('/dev/nvidia*') ?: [], glob('/dev/nvidia-caps/*') ?: []);
    $vms = [];
    if (file_exists('/var/run/libvirt/libvirt-sock')) {
        foreach (workload_lines(workload_command(['virsh', 'list', '--name'])) as $vm) {
            $xml = workload_command(['virsh', 'dumpxml', '--domain', $vm]);
            if (stripos($xml, '<!DOCTYPE') !== false) throw new RuntimeException('Unexpected VM XML doctype');
            $document = simplexml_load_string($xml, 'SimpleXMLElement', LIBXML_NONET);
            if ($document === false) throw new RuntimeException('Cannot parse live VM XML: '.$vm);
            foreach ($document->xpath('/domain/devices/hostdev') as $device) {
                $address = $device->source->address;
                if (!$address) continue;
                $match = (string)$device['type'] === 'mdev' && in_array((string)$address['uuid'], $uuids, true);
                if ((string)$device['type'] === 'pci') {
                    $pci = sprintf('%04x:%02x:%02x.%x', hexdec((string)$address['domain']), hexdec((string)$address['bus']), hexdec((string)$address['slot']), hexdec((string)$address['function']));
                    $match = in_array($pci, $pcis, true);
                }
                if ($match) { $vms[] = $vm; break; }
            }
        }
    }
    $containers = [];
    if (file_exists('/var/run/docker.sock')) {
        foreach (workload_lines(workload_command(['docker', 'ps', '-q', '--no-trunc'])) as $id) {
            $data = json_decode(workload_command(['docker', 'inspect', $id]), true, 512, JSON_THROW_ON_ERROR);
            if (!isset($data[0]['HostConfig'])) throw new RuntimeException('Invalid Docker inspection: '.$id);
            $container = $data[0];
            $host = $container['HostConfig'];
            $match = false;
            foreach ($host['Devices'] ?? [] as $device) $match = $match || workload_path_matches($device['PathOnHost'] ?? '', $nodes);
            foreach ($container['Mounts'] ?? [] as $mount) $match = $match || workload_path_matches($mount['Source'] ?? '', $nodes);
            if ($stack === 'nvidia') {
                foreach ($host['DeviceRequests'] ?? [] as $request) {
                    $caps = array_merge([], ...($request['Capabilities'] ?? []));
                    if (($request['Driver'] ?? '') === 'nvidia' || (($request['Driver'] ?? '') === '' && in_array('gpu', $caps, true))) $match = true;
                }
                if (($host['Runtime'] ?? '') === 'nvidia') {
                    $visible = null;
                    foreach ($container['Config']['Env'] ?? [] as $env) if (strpos($env, 'NVIDIA_VISIBLE_DEVICES=') === 0) $visible = substr($env, 23);
                    if ($visible !== null && !in_array($visible, ['', 'void', 'none'], true)) $match = true;
                }
            }
            // Privileged access alone is not proof of GPU use; the unload check
            // will refuse any remaining consumers rather than stop unrelated apps.
            if ($match) $containers[$id] = $container['Name'] ?? $id;
        }
    }
    // Finish discovery before changing anything. Never stop whole host services.
    foreach ($vms as $vm) {
        echo 'Requesting shutdown of GPU VM: '.$vm."\n";
        workload_command(['virsh', 'shutdown', '--domain', $vm]);
        echo 'Shutdown requested; VM will not be automatically restarted: '.$vm."\n";
    }
    $deadline = microtime(true) + 120;
    while ($vms && microtime(true) < $deadline) {
        $active = workload_lines(workload_command(['virsh', 'list', '--name']));
        $vms = array_values(array_intersect($vms, $active));
        if ($vms) sleep(2);
    }
    if ($vms) throw new RuntimeException('VM shutdown timed out (no forced power-off): '.implode(', ', $vms));
    foreach ($containers as $id => $name) {
        echo 'Stopping GPU container: '.$name." (Docker may kill it after 30 seconds)\n";
        workload_command(['docker', 'stop', '--time', '30', $id], 40);
        echo 'Stopped; manually restart after updating: '.$name."\n";
        if (trim(workload_command(['docker', 'inspect', '--format', '{{.State.Running}}', $id])) !== 'false') throw new RuntimeException('Container is still running: '.$name);
    }
} catch (Throwable $error) {
    fwrite(STDERR, 'ERROR: GPU workload preparation failed. '.$error->getMessage()."\nSome workloads may already be stopped; check the messages above. No automatic restart is attempted.\n");
    exit(1);
}
