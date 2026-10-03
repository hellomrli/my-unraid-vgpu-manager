import json
import unittest
from sandbox import Sandbox, BASE, PLUGIN, UUID


class UpdateWorkloadsAndCCS(unittest.TestCase):
    def setUp(self):
        self.box = Sandbox()
        self.addCleanup(self.box.close)

    def assertOK(self, result):
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def socket(self, path):
        target = self.box.root / path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.touch()

    def workloads(self):
        return self.box.run('php', BASE + '/include/workloads.php', 'nvidia', '0000:01:00.0')

    def vm(self, name='GPU VM', active=True):
        xml = f'<domain><devices><hostdev type="mdev"><source><address uuid="{UUID}"/></source></hostdev></devices></domain>'
        self.box.state['vms'][name] = {'state': 'running', 'active': xml if active else '<domain><devices/></domain>', 'inactive': xml}
        cfg = self.box.root / f'boot/config/plugins/{PLUGIN}/vgpu-devices.cfg'
        cfg.write_text(f'{UUID}|0000:01:00.0|nvidia-65\n')
        self.socket('var/run/libvirt/libvirt-sock')

    def container(self, name='gpu', gpu=True):
        self.socket('var/run/docker.sock')
        self.box.state.setdefault('containers', {})[name] = {
            'Name': name, 'State': {'Running': True},
            'HostConfig': {'DeviceRequests': [{'Driver': 'nvidia', 'Capabilities': [['gpu']]}] if gpu else []},
            'Config': {'Env': []}, 'Mounts': []}

    def test_stops_only_live_gpu_consumers(self):
        self.vm(); self.vm('configured-only', active=False)
        self.container(); self.container('unrelated', False)
        self.box.write_state()
        self.assertOK(self.workloads())
        state = self.box.read_state()
        self.assertEqual(state['vms']['GPU VM']['state'], 'shut off')
        self.assertEqual(state['vms']['configured-only']['state'], 'running')
        self.assertFalse(state['containers']['gpu']['State']['Running'])
        self.assertTrue(state['containers']['unrelated']['State']['Running'])

    def test_failed_shutdown_aborts_before_containers(self):
        self.vm(); self.container()
        self.box.state['fail_shutdown'] = True; self.box.write_state()
        self.assertNotEqual(self.workloads().returncode, 0)
        self.assertFalse([e for e in self.box.events('docker') if e[1][0] == 'stop'])

    def test_discovery_failure_changes_nothing(self):
        self.vm(); self.container()
        self.box.state['fail_docker'] = True; self.box.write_state()
        self.assertNotEqual(self.workloads().returncode, 0)
        self.assertFalse([e for e in self.box.events('virsh') if e[1][0] == 'shutdown'])

    def test_container_stop_failure_propagated(self):
        self.container(); self.box.state['fail_docker_stop'] = True; self.box.write_state()
        self.assertNotEqual(self.workloads().returncode, 0)

    def test_nvidia_update_stops_workloads_before_installing(self):
        self.box.gpu(); self.vm(); self.container()
        old = self.box.package(); self.box.installed(old)
        self.box.package(build=2, remote=True)
        self.box.settings(nvidia_installed='true'); self.box.write_state()
        self.assertOK(self.box.helper('exec.sh', 'update_driver', '16', 'latest'))
        events = self.box.events()
        stop = next(i for i, e in enumerate(events) if e[0] == 'docker' and e[1][0] == 'stop')
        install = next(i for i, e in enumerate(events) if e[0] == 'upgradepkg')
        self.assertLess(stop, install)
        self.assertEqual(self.box.read_state()['vms']['GPU VM']['state'], 'shut off')

    def test_bad_package_never_stops_workloads(self):
        self.vm(); self.container(); self.box.write_state()
        self.assertNotEqual(self.box.rc('nvidia_update', '/bad.txz', 'stop-workloads').returncode, 0)
        self.assertFalse(self.box.events('virsh')); self.assertFalse(self.box.events('docker'))

    def test_intel_pci_vm_and_render_directory(self):
        self.box.gpu('intel')
        self.socket('var/run/libvirt/libvirt-sock'); self.container()
        xml = '<domain><devices><hostdev type="pci"><source><address domain="0x0000" bus="0x03" slot="0x00" function="0x0"/></source></hostdev></devices></domain>'
        self.box.state['vms']['Intel'] = {'state': 'paused', 'active': xml}
        drm = self.box.root / 'sys/class/drm/renderD128'; drm.mkdir(parents=True)
        (drm / 'device').symlink_to('/sys/bus/pci/devices/0000:03:00.0')
        self.box.state['containers']['gpu']['Mounts'] = [{'Source': '/dev/dri'}]
        self.box.write_state()
        result = self.box.run('php', BASE + '/include/workloads.php', 'intel', '0000:03:00.0')
        self.assertOK(result)
        self.assertFalse(self.box.read_state()['containers']['gpu']['State']['Running'])
        self.assertEqual(self.box.state['vms']['Intel']['state'], 'shut off')

    def test_unchanged_package_keeps_workloads_running(self):
        self.box.gpu(); self.container()
        package = self.box.package(); self.box.installed(package)
        self.box.settings(nvidia_installed='true')
        module = self.box.root / 'sys/module/nvidia'; module.mkdir()
        (module / 'version').write_text('535.309.01')
        self.box.write_state()
        self.assertOK(self.box.rc('nvidia_update', '', 'stop-workloads'))
        self.assertFalse(self.box.events('docker'))
        self.assertTrue(self.box.read_state()['containers']['gpu']['State']['Running'])

    def test_remaining_module_occupancy_blocks_install(self):
        self.box.gpu(); self.container()
        old = self.box.package(); self.box.installed(old)
        self.box.package(build=2, remote=True)
        self.box.settings(nvidia_installed='true')
        self.box.state['module_busy'] = True; self.box.write_state()
        module = self.box.root / 'sys/module/nvidia'; module.mkdir()
        (module / 'version').write_text('535.309.01')
        self.assertNotEqual(self.box.helper('exec.sh', 'update_driver', '16', 'latest').returncode, 0)
        self.assertFalse(self.box.events('upgradepkg'))

    def test_intel_update_stops_container_before_unloading(self):
        self.box.gpu('intel'); self.container()
        self.box.installed(self.box.package(source='i915'))
        self.box.package(source='i915', build=2, remote=True)
        self.box.settings(intel_installed='true')
        (self.box.root / 'sys/module/i915').mkdir()
        drm = self.box.root / 'sys/class/drm/renderD128'; drm.mkdir(parents=True)
        (drm / 'device').symlink_to('/sys/bus/pci/devices/0000:03:00.0')
        self.box.state['containers']['gpu']['HostConfig']['Devices'] = [{'PathOnHost': '/dev/dri/renderD128'}]
        self.box.write_state()
        self.assertOK(self.box.helper('exec.sh', 'update_intel'))
        events = self.box.events()
        stop = next(i for i, e in enumerate(events) if e[0] == 'docker' and e[1][0] == 'stop')
        unload = next(i for i, e in enumerate(events) if e[0] == 'modprobe' and e[1] == ['-r', 'i915'])
        self.assertLess(stop, unload)

    def test_legacy_nvidia_runtime_visibility(self):
        for name, visible in [('visible', 'all'), ('no-gpu', 'void')]:
            self.container(name, False)
            container = self.box.state['containers'][name]
            container['HostConfig']['Runtime'] = 'nvidia'
            container['Config']['Env'] = ['NVIDIA_VISIBLE_DEVICES=' + visible]
        self.box.write_state(); self.assertOK(self.workloads())
        state = self.box.read_state()['containers']
        self.assertFalse(state['visible']['State']['Running'])
        self.assertTrue(state['no-gpu']['State']['Running'])

    def test_ccs_save_does_not_unload_or_change_vfs(self):
        self.box.gpu('intel'); self.box.settings(intel_installed='true')
        self.box.state['ccs_supported'] = True; self.box.write_state()
        for value, number in [('true', '1'), ('false', '0')]:
            result = self.box.action('save_intel_ccs', xelp_enable_ccs=value)
            self.assertOK(result); self.assertTrue(json.loads(result.stdout)['ok'])
            config = self.box.root / 'boot/config/modprobe.d/my-unraid-vgpu-manager-i915.conf'
            self.assertIn('xelp_enable_ccs=' + number, config.read_text())
        self.assertFalse(self.box.events('modprobe'))
        self.assertEqual(self.box.read_settings()['intel_vf_number'], '7')

    def test_old_driver_keeps_ccs_intent_without_unknown_parameter(self):
        self.box.settings(intel_installed='true')
        result = self.box.action('save_intel_ccs', xelp_enable_ccs='true')
        self.assertTrue(json.loads(result.stdout)['ok'])
        self.assertIn('不支持 CCS', json.loads(result.stdout)['message'])
        config = self.box.root / 'etc/modprobe.d/my-unraid-vgpu-manager-i915.conf'
        self.assertNotIn('xelp_enable_ccs=', config.read_text())
        self.assertEqual(self.box.read_settings()['intel_xelp_enable_ccs'], 'true')

    def test_ccs_validation_and_csrf(self):
        for fields in [dict(xelp_enable_ccs='1'), dict(xelp_enable_ccs='true', token='invalid')]:
            self.assertFalse(json.loads(self.box.action('save_intel_ccs', **fields).stdout)['ok'])
        self.assertNotIn('intel_xelp_enable_ccs', self.box.read_settings())

    def test_ccs_load_default_off_and_enabled(self):
        self.box.state['ccs_supported'] = True; self.box.write_state()
        for enabled in [False, True]:
            self.box.settings(intel_xelp_enable_ccs='true' if enabled else 'false')
            self.assertOK(self.box.rc('intel_load'))
            if not enabled:
                self.assertOK(self.box.shell('rm -rf /sys/module/i915'))
        calls = [e[1] for e in self.box.events('modprobe') if e[1][0] == 'i915']
        self.assertIn('xelp_enable_ccs=0', calls[0]); self.assertIn('xelp_enable_ccs=1', calls[1])
