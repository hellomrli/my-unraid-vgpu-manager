#!/usr/bin/env python3
"""Serve a simulated Unraid UI and run Playwright against the real plugin files."""
import json
import os
from pathlib import Path
import shutil
import socket
import subprocess
import sys
from sandbox import Sandbox, BASE, PLUGIN, UUID, NEXT_KERNEL

ROOT=Path(__file__).resolve().parents[1]

def main():
    box=Sandbox()
    process=None
    try:
        box.settings(nvidia_installed='true',intel_installed='true',intel_vf_number='1',unlock='true',nvidia_unlock='true')
        box.installed(box.package())
        box.installed(box.package(source='i915'))
        box.gpu(); box.gpu('intel'); box.devices()
        (box.root/'sys/bus/mdev/devices'/UUID).mkdir()
        (box.root/'sys/module/nvidia').mkdir(); (box.root/'sys/module/nvidia/version').write_text('535.309.01')
        (box.root/'sys/module/i915/parameters').mkdir(parents=True)
        (box.root/'sys/module/i915/parameters/max_vfs').write_text('7')
        box.state['processes']=['nvidia-vgpud','nvidia-vgpu-mgr']
        vm_name='Lab\'s "Windows 11" & 测试'
        box.state['vms']={vm_name:{'state':'running','inactive':f'<domain><devices><hostdev type="mdev"><source><address uuid="{UUID}"/></source></hostdev></devices></domain>','active':'<domain><devices/></domain>'}}
        box.package(kernel=NEXT_KERNEL,remote=True); box.package(source='i915',kernel=NEXT_KERNEL,remote=True)
        box.write_state()
        ready=box.helper('upgrade-check.sh','prepare')
        if ready.returncode: raise RuntimeError(ready.stdout+ready.stderr)
        router=box.root/'router.php'
        router.write_text('''<?php
$var = ['csrf_token'=>'test-token']; $display=['locale'=>'en_US'];
$path=parse_url($_SERVER['REQUEST_URI'],PHP_URL_PATH);
if ($path === '/favicon.ico') { http_response_code(204); exit; }
if (strpos($path, '/plugins/') === 0) {
    $file='/usr/local/emhttp'.$path;
    if (!is_file($file)) { http_response_code(404); exit; }
    if (substr($file,-4)==='.php') { include $file; exit; }
    header('Content-Type: '.(substr($file,-3)==='.js' ? 'application/javascript' : (substr($file,-4)==='.css' ? 'text/css' : 'application/octet-stream')));
    readfile($file); exit;
}
?><!doctype html><html><head><meta charset="UTF-8"><meta name="viewport" content="width=device-width, initial-scale=1"><title>Unraid vGPU Manager preview</title><style>
:root {--background-alt:#fff} body {background:#f4f5f6;color:#292b30;font:14px/1.6 Arial,"Noto Sans CJK SC",sans-serif;margin:0;padding:24px} button,input,select,textarea {font:inherit;color:inherit;border:1px solid #bdc2c8;border-radius:4px;padding:6px 9px;background:#fff} button {background:#f1f3f5} h2,h3 {font-weight:600} a {color:#22699c} @media(max-width:700px){body{padding:12px}}
</style></head><body><script>window.__openBoxCalls=[];function openBox(){window.__openBoxCalls.push(Array.from(arguments));}</script>
<?php $source=file_get_contents('/usr/local/emhttp/plugins/my-unraid-vgpu-manager/my-unraid-vgpu-manager.page'); eval('?>'.explode("---\\n",$source,2)[1]); ?>
</body></html>''')
        with socket.socket() as probe:
            probe.bind(('127.0.0.1',0)); port=probe.getsockname()[1]
        log=(box.root/'server.log').open('w')
        process=subprocess.Popen(box.argv(['php','-S',f'127.0.0.1:{port}','/tmp/fixture/router.php'],network=True),stdout=log,stderr=log)
        env=os.environ.copy()
        env.update(VGPU_TEST_URL=f'http://127.0.0.1:{port}/Settings/my-unraid-vgpu-manager',VGPU_FIXTURE=str(box.root),VGPU_VM_NAME=vm_name)
        result=subprocess.run(['node',str(ROOT/'tests/browser.cjs')],env=env)
        if result.returncode:
            print((box.root/'server.log').read_text(),file=sys.stderr)
            raise SystemExit(result.returncode)
    finally:
        if process is not None:
            process.terminate()
            try: process.wait(timeout=5)
            except subprocess.TimeoutExpired: process.kill(); process.wait()
        box.close()

if __name__=='__main__': main()
