"""An isolated Unraid filesystem with no host GPU access and no network."""
import hashlib
import io
import json
import os
from pathlib import Path
import shutil
import struct
import subprocess
import tarfile
import tempfile

REPO = Path(__file__).resolve().parents[1]
PLUGIN = 'my-unraid-vgpu-manager'
BASE = '/usr/local/emhttp/plugins/' + PLUGIN
KERNEL = '6.18.44-Unraid'
NEXT_KERNEL = '6.18.47-Unraid'
UUID = '12345678-1234-4234-8234-123456789abc'

class Sandbox:
    def __init__(self):
        self.temp = tempfile.TemporaryDirectory(prefix='vgpu-test-')
        self.root = Path(self.temp.name)
        for directory in ['boot/config/plugins/'+PLUGIN, 'sys/module', 'sys/bus/pci/devices', 'sys/bus/pci/drivers/vfio-pci', 'sys/bus/mdev/devices', 'var/log/packages', 'var/lib/pkgtools/packages', 'var/lock', 'var/tmp', 'var/run', 'etc/docker', 'etc/modprobe.d', 'local/emhttp/plugins/dynamix/scripts', 'bin', 'remote']:
            (self.root / directory).mkdir(parents=True, exist_ok=True)
        shutil.copytree(REPO/'source/usr/local/emhttp/plugins', self.root/'local/emhttp/plugins', dirs_exist_ok=True)
        shutil.copy(REPO/'tests/mock_command.py', self.root/'bin/mock')
        (self.root/'bin/mock').chmod(0o755)
        # /etc is isolated, so Debian alternatives symlinks need a direct target.
        (self.root/'bin/awk').symlink_to(Path(shutil.which('awk')).resolve())
        for cmd in ['uname','curl','upgradepkg','removepkg','modinfo','modprobe','rmmod','lsmod','pgrep','killall','nvidia-vgpud','nvidia-vgpu-mgr','nvidia-gridd','fuser','lspci','virsh','mdevctl','crontab','logger','notify','depmod','sleep','sync','nvidia-modprobe']:
            (self.root/'bin'/cmd).symlink_to('mock')
        (self.root/'local/emhttp/plugins/dynamix/scripts/notify').symlink_to('/tmp/fixture/bin/mock')
        # The notify double needs its own argv[0] name.
        (self.root/'local/emhttp/plugins/dynamix/scripts/notify').unlink()
        shutil.copy(REPO/'tests/mock_command.py', self.root/'local/emhttp/plugins/dynamix/scripts/notify')
        (self.root/'local/emhttp/plugins/dynamix/scripts/notify').chmod(0o755)
        (self.root/'etc/unraid-version').write_text('version="7.2.0"\n')
        (self.root/'sys/bus/pci/drivers/vfio-pci/bind').write_text('')
        self.state = {'kernel': KERNEL, 'releases': {}, 'vms': {}, 'processes': []}
        self.write_state()
        self.settings(nvidia_installed='false', intel_installed='false', nvidia_series='16', driver_version='latest', update_check='true', kernel_upgrade_check='true', ui_language='zh_CN', intel_vf_number='7')
        self.locale('zh_CN')
        self.boot_image(NEXT_KERNEL)
    def close(self): self.temp.cleanup()
    def write_state(self): (self.root/'state.json').write_text(json.dumps(self.state))
    def read_state(self): self.state = json.loads((self.root/'state.json').read_text()); return self.state
    def settings(self, **values):
        path=self.root/('boot/config/plugins/'+PLUGIN+'/settings.cfg')
        old=dict(line.split('=',1) for line in path.read_text().splitlines() if '=' in line) if path.exists() else {}
        old.update(values)
        path.write_text(''.join(k+'='+v+'\n' for k,v in old.items()))
    def read_settings(self):
        return dict(line.split('=',1) for line in (self.root/('boot/config/plugins/'+PLUGIN+'/settings.cfg')).read_text().splitlines() if '=' in line)
    def locale(self, language):
        path=self.root/'boot/config/plugins/dynamix/dynamix.cfg'
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text('[display]\nlocale="'+language+'"\n')
    def page(self, **query):
        (self.root/'query.json').write_text(json.dumps(query))
        code="$var=['csrf_token'=>'test-token']; $_GET=json_decode(file_get_contents('/tmp/fixture/query.json'),true); $source=file_get_contents('"+BASE+"/my-unraid-vgpu-manager.page'); eval('?>'.explode(\"---\\n\",$source,2)[1]);"
        return self.run('php','-r',code)
    def boot_image(self, kernel):
        data=bytearray(4096); data[0x202:0x206]=b'HdrS'; data[0x20e:0x210]=struct.pack('<H',0x100)
        version=(kernel+' (builder@test)\0').encode(); data[0x300:0x300+len(version)]=version
        (self.root/'boot/bzimage').write_bytes(data)
    def package(self, source='nvidia', kernel=KERNEL, version=None, build=1, remote=False, corrupt=False):
        version=version or ('535.309.01' if source=='nvidia' else '202608121')
        prefix='nvidia' if source=='nvidia' else 'i915-sriov'
        name=f'{prefix}-{version}-{kernel}-{build}.txz'
        buf=io.BytesIO()
        with tarfile.open(fileobj=buf, mode='w:xz') as archive:
            info=tarfile.TarInfo(f'lib/modules/{kernel}/{prefix}.ko'); info.size=4
            archive.addfile(info,io.BytesIO(b'test'))
        directory=self.root/'remote' if remote else self.root/('boot/config/plugins/'+PLUGIN+'/packages/'+kernel.split('-')[0])
        directory.mkdir(parents=True, exist_ok=True)
        payload=buf.getvalue(); (directory/name).write_bytes(payload)
        checksum=('0'*32 if corrupt else hashlib.md5(payload).hexdigest())
        (directory/(name+'.md5')).write_text(checksum+'  '+name+'\n')
        if remote:
            repo='my-nvidia-vgpu-driver' if source=='nvidia' else 'my-i915-sriov-driver'
            self.state['releases'].setdefault(repo+'|'+kernel,[]).extend([name, name+'.md5'])
            self.write_state()
        return name
    def installed(self, name):
        (self.root/'var/log/packages'/name.removesuffix('.txz')).write_text('installed\n')
        if name.startswith('nvidia-'): self.state['nvidia_disk_version']=name.split('-')[1]
        else: self.state['intel_disk_version']=name.removeprefix('i915-sriov-').split('-')[0]
        self.write_state()
    def gpu(self, vendor='nvidia', pci=None, device=None):
        pci=pci or ('0000:01:00.0' if vendor=='nvidia' else '0000:03:00.0')
        path=self.root/'sys/bus/pci/devices'/pci; path.mkdir(parents=True, exist_ok=True)
        (path/'vendor').write_text('0x10de' if vendor=='nvidia' else '0x8086')
        (path/'device').write_text(device or ('0x1bb3' if vendor=='nvidia' else '0x4680'))
        (path/'class').write_text('0x030000')
        if vendor=='nvidia':
            profile=path/'mdev_supported_types/nvidia-65'; profile.mkdir(parents=True,exist_ok=True)
            for name,value in {'available_instances':'2','name':'GRID P4-4Q','description':'framebuffer=4096M, num_heads=4, max_resolution=4096x2160, frl_config=60'}.items(): (profile/name).write_text(value)
        else:
            (path/'sriov_numvfs').write_text('1'); (path/'sriov_totalvfs').write_text('7')
            vf=pci[:-1]+'1'; vfpath=self.root/'sys/bus/pci/devices'/vf; vfpath.mkdir(exist_ok=True)
            (vfpath/'physfn').symlink_to('../'+pci)
            (path/'virtfn0').symlink_to('../'+vf)
            (vfpath/'driver_override').write_text('')
            (vfpath/'driver').symlink_to('../../drivers/vfio-pci')
        return path
    def devices(self, uuid=UUID):
        (self.root/('boot/config/plugins/'+PLUGIN+'/vgpu-devices.cfg')).write_text(f'{uuid}|0000:01:00.0|nvidia-65\n')
    def events(self, command=None):
        log=self.root/'events.jsonl'
        events=[json.loads(line) for line in log.read_text().splitlines()] if log.exists() else []
        return [e for e in events if command is None or e[0]==command]
    def argv(self, command, network=False):
        php=os.environ.get('VGPU_TEST_PHP', shutil.which('php') or '')
        if not php: raise RuntimeError('PHP CLI is required (set VGPU_TEST_PHP to its path).')
        # Mount extracted tools at the same path, or retain the system PHP
        # configuration after replacing /etc with the isolated fixture.
        extra=[]
        if php.startswith('/tmp/vgpu-review-tools/'):
            extra=['--ro-bind','/tmp/vgpu-review-tools','/tmp/vgpu-review-tools']
        elif Path('/etc/php').is_dir():
            extra=['--ro-bind','/etc/php','/etc/php']
        php_link=self.root/'bin/php'
        if not php_link.exists(): php_link.symlink_to(Path(php).resolve())
        return ['bwrap','--die-with-parent','--unshare-user','--unshare-pid','--unshare-ipc','--unshare-uts']+([] if network else ['--unshare-net'])+[
            '--ro-bind','/','/','--tmpfs','/tmp','--bind',str(self.root),'/tmp/fixture',
            '--bind',str(self.root/'boot'),'/boot','--bind',str(self.root/'sys'),'/sys',
            '--bind',str(self.root/'var'),'/var','--bind',str(self.root/'etc'),'/etc',*extra,
            '--bind',str(self.root/'local'),'/usr/local','--bind',str(self.root/'bin'),'/usr/sbin',
            '--dev','/dev','--proc','/proc','--chdir','/tmp/fixture',
            '--setenv','PATH','/tmp/fixture/bin:'+str(Path(php).parent)+':/usr/bin:/bin',
            '--setenv','LC_ALL','C',*command]
    def run(self, *command, check=False):
        result=subprocess.run(self.argv(list(command)),text=True,capture_output=True,timeout=35)
        if check and result.returncode: raise AssertionError(result.stdout+result.stderr)
        return result
    def rc(self, *args): return self.run('/bin/bash',BASE+'/scripts/rc.vgpu',*args)
    def helper(self, script, *args): return self.run('/bin/bash',BASE+'/include/'+script,*args)
    def shell(self, code): return self.run('/bin/bash','-c',code)
    def action(self, action, token='test-token', **fields):
        body={'vgpu_action':action,'vgpu_token':token,**fields}
        (self.root/'post.json').write_text(json.dumps(body))
        code="$_SERVER['REQUEST_METHOD']='POST'; $var=['csrf_token'=>'test-token']; $_POST=json_decode(file_get_contents('/tmp/fixture/post.json'),true); include '"+BASE+"/include/actions.php';"
        return self.run('php','-r',code)
