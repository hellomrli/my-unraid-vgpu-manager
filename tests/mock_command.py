#!/usr/bin/python3
"""Deterministic hardware/package/network doubles, used only inside bubblewrap."""
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import sys
import xml.etree.ElementTree as ET

root = Path('/tmp/fixture')
state_file = root / 'state.json'
state = json.loads(state_file.read_text())
command = Path(sys.argv[0]).name
args = sys.argv[1:]
with (root / 'events.jsonl').open('a') as log:
    log.write(json.dumps([command, args]) + '\n')

def finish(code=0, output=''):
    state_file.write_text(json.dumps(state))
    if output:
        print(output)
    sys.exit(code)

def option(name, default=None):
    return args[args.index(name)+1] if name in args else default

def module(name):
    return Path('/sys/module') / name.replace('-', '_')

if command == 'uname':
    finish(output=state['kernel'])
if command == 'curl':
    url = next((v for v in reversed(args) if v.startswith('https://')), '')
    out = option('--output', option('-o'))
    if state.get('offline'):
        finish(22, 'simulated HTTP failure')
    if '/-/client-token' in url:
        payload = state.get('license_token', 'new-client-configuration-token').encode()
    elif 'api.github.com' in url:
        match = re.search(r'/repos/hellomrli/(.+)/releases/tags/(.+)$', url)
        key = '|'.join(match.groups()) if match else ''
        names = state.get('releases', {}).get(key)
        if names is None:
            finish(22, 'simulated 404: no release for kernel')
        payload = json.dumps({'assets': [{'name': n} for n in names]}).encode()
    else:
        filename = url.rsplit('/', 1)[-1]
        remote = root / 'remote' / filename
        if not remote.is_file():
            finish(22, 'simulated 404: missing asset')
        payload = remote.read_bytes()
    if out:
        Path(out).write_bytes(payload)
    else:
        sys.stdout.buffer.write(payload)
    finish()
if command == 'upgradepkg':
    if state.get('fail_install'):
        finish(1, 'simulated package installation failure')
    package = args[-1].split('%')[-1]
    name = Path(package).name.removesuffix('.txz')
    prefix = 'nvidia-' if name.startswith('nvidia-') else 'i915-sriov-'
    for old in Path('/var/log/packages').glob(prefix + '*'):
        old.unlink()
    (Path('/var/log/packages') / name).write_text('installed\n')
    if prefix == 'nvidia-': state['nvidia_disk_version'] = name.split('-')[1]
    else: state['intel_disk_version'] = name.removeprefix(prefix).split('-')[0]
    finish()
if command == 'removepkg':
    (Path('/var/log/packages') / args[-1]).unlink(missing_ok=True)
    finish()
if command == 'modinfo':
    driver = args[-1]
    version = state.get('nvidia_disk_version' if driver == 'nvidia' else 'intel_disk_version', '')
    if '-p' in args:
        finish(output='max_vfs: Maximum VFs')
    finish(0 if version else 1, version)
if command in ('modprobe', 'rmmod'):
    removing = '-r' in args or command == 'rmmod'
    names = [a for a in args if not a.startswith('-') and '=' not in a]
    for name in names:
        target = module(name)
        if removing:
            if state.get('module_busy') and name in ('nvidia', 'i915'):
                finish(1, 'simulated module is in use')
            if target.exists(): shutil.rmtree(target)
        else:
            target.mkdir(parents=True, exist_ok=True)
            if name == 'nvidia': (target / 'version').write_text(state.get('nvidia_disk_version', '535.309.01'))
            if name == 'i915':
                (target / 'parameters').mkdir(exist_ok=True)
                (target / 'parameters/max_vfs').write_text('7')
    finish()
if command == 'lsmod':
    finish(output='\n'.join(p.name + ' 123 0' for p in Path('/sys/module').iterdir()))
if command == 'pgrep':
    finish(0 if args[-1] in state.get('processes', []) else 1, '123' if args[-1] in state.get('processes', []) else '')
if command == 'killall':
    state['processes'] = [p for p in state.get('processes', []) if p not in args]
    finish()
if command in ('nvidia-vgpud', 'nvidia-vgpu-mgr', 'nvidia-gridd'):
    state.setdefault('processes', []).append(command)
    finish()
if command == 'fuser':
    finish(0 if state.get('vf_busy') else 1)
if command == 'lspci':
    finish(output=state.get('gpu_name', '0000:01:00.0 VGA compatible controller: NVIDIA Tesla P4'))
if command == 'virsh':
    vms = state.get('vms', {})
    if args[0] == 'list':
        finish(output='\n'.join(name for name, vm in vms.items() if '--all' in args or vm.get('state') in ('running', 'paused')))
    name = option('--domain', args[1] if len(args) > 1 else '')
    if name not in vms: finish(1, 'domain not found')
    vm = vms[name]
    if args[0] == 'domstate': finish(output=vm.get('state', 'shut off'))
    if args[0] == 'dumpxml':
        finish(output=vm.get('inactive' if '--inactive' in args else 'active', vm.get('inactive', '<domain><devices/></domain>')))
    if args[0] in ('attach-device', 'detach-device'):
        device = ET.parse(option('--file')).getroot()
        uuid = device.find('source/address').attrib['uuid']
        document = ET.fromstring(vm.get('inactive', '<domain><devices/></domain>'))
        devices = document.find('devices')
        if args[0] == 'attach-device': devices.append(device)
        else:
            for old in list(devices):
                address = old.find('source/address')
                if address is not None and address.get('uuid') == uuid: devices.remove(old)
        vm['inactive'] = ET.tostring(document, encoding='unicode')
        finish()
    finish(1)
if command == 'mdevctl':
    uuid = option('-u')
    if args[0] == 'define':
        if state.get('fail_define'): finish(1, 'define failed')
        state.setdefault('definitions', {})[uuid] = [option('-p'), option('--type')]
    if args[0] == 'start':
        if state.get('fail_start'): finish(1, 'start failed')
        (Path('/sys/bus/mdev/devices') / uuid).mkdir(parents=True, exist_ok=True)
    if args[0] == 'stop':
        if state.get('fail_stop'): finish(1, 'device is busy')
        target = Path('/sys/bus/mdev/devices') / uuid
        if target.exists(): target.rmdir()
    if args[0] == 'undefine': state.setdefault('definitions', {}).pop(uuid, None)
    finish()
if command == 'crontab':
    tab = root / 'crontab'
    if args == ['-l']: finish(0 if tab.exists() else 1, tab.read_text() if tab.exists() else '')
    tab.write_text(sys.stdin.read() if args == ['-'] else Path(args[0]).read_text())
    finish()
if command in ('logger', 'notify', 'depmod', 'sleep', 'sync', 'nvidia-modprobe'):
    finish()
finish(1, 'unimplemented test command: ' + command)
