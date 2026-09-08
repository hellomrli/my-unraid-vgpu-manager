<?php
// Read the version actually staged for the next boot, using the x86 Linux
// boot protocol's kernel_version pointer. Changelogs can contain old kernels.
function vgpu_boot_kernel($image = '/boot/bzimage') {
    $file = @fopen($image, 'rb');
    if (!$file) return '';
    try {
        if (fseek($file, 0x202) !== 0 || fread($file, 4) !== 'HdrS') return '';
        if (fseek($file, 0x20e) !== 0) return '';
        $pointer = fread($file, 2);
        if (strlen($pointer) !== 2) return '';
        $offset = unpack('v', $pointer)[1];
        if ($offset < 0x40 || fseek($file, 0x200 + $offset) !== 0) return '';
        $version = fread($file, 256);
        return preg_match('/^([0-9]+(?:\.[0-9]+){1,2}(?:-[A-Za-z0-9._+]+)*-Unraid)(?:\s|\x00)/', $version, $m) ? $m[1] : '';
    } finally {
        fclose($file);
    }
}

if (PHP_SAPI === 'cli' && realpath($_SERVER['SCRIPT_FILENAME'] ?? '') === __FILE__) {
    $kernel = vgpu_boot_kernel($argv[1] ?? '/boot/bzimage');
    if ($kernel === '') exit(1);
    echo $kernel, "\n";
}
