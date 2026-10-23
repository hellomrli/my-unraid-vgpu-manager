"""Regressions for the 2026-10-23 review, without host GPU or network access."""
import fcntl
import hashlib
import json
from pathlib import Path
import shutil
import unittest
import xml.etree.ElementTree as ET

from sandbox import Sandbox, BASE, PLUGIN, KERNEL, NEXT_KERNEL, REPO


class ReviewFixes(unittest.TestCase):
    def setUp(self):
        self.box = Sandbox()
        self.addCleanup(self.box.close)

    def assertOK(self, result):
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def cache(self, name):
        kernel = name.split('-')[-3]
        return self.box.root / f'boot/config/plugins/{PLUGIN}/packages/{kernel}' / name

    def prune(self):
        return self.box.shell(f'source {BASE}/include/common.sh; prune_cache')

    def conflict(self, name):
        path = self.box.root / 'var/log/plugins' / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.touch()

    def script(self, index=0, method=None):
        manifest = ET.parse(REPO / f'{PLUGIN}.plg').getroot()
        entries = [entry.findtext('INLINE') for entry in manifest.findall('FILE')
                   if entry.get('Run') == '/bin/bash' and entry.get('Method') == method]
        path = self.box.root / 'plugin-script.sh'
        path.write_text(entries[index])
        return self.box.run('/bin/bash', '/tmp/fixture/plugin-script.sh')

    def test_boot_recommendation_contains_only_iommu_options(self):
        self.box.settings(intel_installed='true')
        page = self.box.page()
        self.assertOK(page)
        self.assertIn('id="intel-boot-parameters">intel_iommu=on iommu=pt</pre>', page.stdout)
        self.assertNotIn('module_blacklist=xe', page.stdout)
        self.assertNotIn('i915.max_vfs=7', page.stdout)

    def test_boot_conflicts_are_detected_and_html_escaped(self):
        (self.box.root / 'cmdline').write_text('intel_iommu=on i915.enable_guc=0 i915.max_vfs=3 '
                                             'i915.xelp_enable_ccs=<script> module_blacklist=foo,xe iommu=pt')
        page = self.box.page()
        self.assertOK(page)
        self.assertIn('id="intel-boot-conflicts"', page.stdout)
        self.assertIn('i915.xelp_enable_ccs=&lt;script&gt;', page.stdout)
        self.assertIn('module_blacklist=foo,xe', page.stdout)
        (self.box.root / 'cmdline').write_text('intel_iommu=on module_blacklist=xen i915.unrelated=1')
        self.assertNotIn('id="intel-boot-conflicts"', self.box.page().stdout)

    def test_cache_prunes_obsolete_kernels_but_keeps_running_staged_and_rollback(self):
        rollback = '6.18.40-Unraid'
        obsolete = self.box.package(kernel='6.18.35-Unraid')
        retained = [self.box.package(), self.box.package(kernel=NEXT_KERNEL),
                    self.box.package(kernel=rollback)]
        self.box.settings(current_kernel=rollback)
        self.assertOK(self.box.rc('restore'))
        self.assertEqual(self.box.read_settings()['last_kernel'], rollback)
        self.assertOK(self.box.rc('restore'))
        self.assertEqual(self.box.read_settings()['last_kernel'], rollback)
        self.assertOK(self.prune())
        self.assertFalse(self.cache(obsolete).exists())
        for name in retained:
            self.assertTrue(self.cache(name).is_file(), name)

    def test_cache_keeps_latest_numeric_build_per_source_and_series(self):
        old, latest = [], []
        for source, version in [('nvidia', '535.309.01'), ('nvidia', '580.178.05'), ('i915', '20260916')]:
            old.append(self.box.package(source=source, version=version, build=2))
            latest.append(self.box.package(source=source, version=version, build=10))
        self.assertOK(self.prune())
        for name in old:
            for suffix in ('', '.md5', '.sha256'):
                self.assertFalse(Path(str(self.cache(name)) + suffix).exists())
        for name in latest:
            self.assertTrue(self.cache(name).is_file(), name)

    def test_cache_preserves_installed_driver_and_latest_pinned_build(self):
        installed = self.box.package(version='535.300.00')
        self.box.installed(installed)
        pin_old = self.box.package(build=1)
        pin_new = self.box.package(build=2)
        latest = self.box.package(version='535.310.00')
        self.box.settings(driver_version='535.309.01')
        self.assertOK(self.prune())
        self.assertFalse(self.cache(pin_old).exists())
        for name in (installed, pin_new, latest):
            self.assertTrue(self.cache(name).is_file(), name)

    def test_failed_update_does_not_delete_the_installed_cache(self):
        old = self.box.package()
        self.box.installed(old)
        self.box.package(build=2, remote=True)
        self.box.settings(nvidia_installed='true')
        self.box.state['fail_install'] = True
        self.box.write_state()
        self.assertNotEqual(self.box.helper('exec.sh', 'update_driver', '16', 'latest').returncode, 0)
        self.assertTrue(self.cache(old).is_file())

    def test_cache_does_not_prune_unknown_kernels_when_boot_image_is_unreadable(self):
        old = self.box.package(kernel='6.18.35-Unraid')
        (self.box.root / 'boot/bzimage').write_bytes(b'not a boot image')
        self.assertOK(self.prune())
        self.assertTrue(self.cache(old).is_file())

    def test_cache_prune_respects_an_active_reader(self):
        old = self.box.package(build=1)
        self.box.package(build=2)
        lock = self.box.root / f'boot/config/plugins/{PLUGIN}/.cache.lock'
        with lock.open('w') as file:
            fcntl.flock(file, fcntl.LOCK_SH)
            self.assertOK(self.prune())
            self.assertTrue(self.cache(old).is_file())
        self.assertOK(self.prune())
        self.assertFalse(self.cache(old).exists())

    def test_cache_keeps_explicitly_prepared_kernel_across_other_downloads(self):
        custom_kernel = '6.18.49-Unraid'
        custom = self.box.package(kernel=custom_kernel, remote=True)
        self.box.package()
        self.assertOK(self.box.helper('download.sh', 'nvidia', '16', 'latest', '--kernel', custom_kernel))
        self.assertOK(self.box.helper('download.sh', 'nvidia', '16'))
        self.assertTrue(self.cache(custom).is_file())

    def test_xe_config_excludes_only_managed_device_and_preserves_other_gpu(self):
        self.box.gpu('intel')
        other = self.box.gpu('intel', pci='0000:04:00.0', device='0xe20b')
        self.assertOK(self.box.shell(f'source {BASE}/scripts/rc.vgpu; intel_write_config'))
        config = (self.box.root / 'etc/modprobe.d/my-unraid-vgpu-manager-i915.conf').read_text()
        self.assertIn('options xe force_probe=!4680', config)
        self.assertNotIn('blacklist xe', config)
        self.assertNotIn('e20b', config)
        self.assertTrue(other.is_dir())

    def test_restore_migrates_existing_global_xe_blacklist_without_reinstalling(self):
        self.box.gpu('intel')
        self.box.installed(self.box.package(source='i915'))
        self.box.settings(intel_installed='true')
        for directory in ('boot/config/modprobe.d', 'etc/modprobe.d'):
            config = self.box.root / directory / f'{PLUGIN}-i915.conf'
            config.parent.mkdir(parents=True, exist_ok=True)
            config.write_text('blacklist i915\nblacklist xe\n')
        self.assertOK(self.box.rc('restore'))
        self.assertFalse(self.box.events('upgradepkg'))
        for directory in ('boot/config/modprobe.d', 'etc/modprobe.d'):
            config = (self.box.root / directory / f'{PLUGIN}-i915.conf').read_text()
            self.assertNotIn('blacklist xe', config)
            self.assertIn('options xe force_probe=!4680', config)

    def test_boot_ensure_does_not_hash_unrelated_cached_packages_for_pruning(self):
        self.box.gpu()
        self.box.installed(self.box.package())
        self.box.settings(nvidia_installed='true')
        old = self.box.package(build=2)
        self.box.package(build=3)
        self.assertOK(self.box.rc('ensure'))
        self.assertTrue(self.cache(old).is_file())
        self.assertOK(self.box.rc('restore'))
        self.assertFalse(self.cache(old).exists())

    def test_busy_stock_intel_first_install_is_staged_until_reboot(self):
        self.box.gpu('intel')
        self.box.package(source='i915')
        (self.box.root / 'sys/module/i915').mkdir()
        self.box.state['module_busy'] = True
        self.box.write_state()
        result = self.box.helper('exec.sh', 'install_intel')
        self.assertOK(result)
        self.assertIn('请重启', result.stdout)
        settings = self.box.read_settings()
        self.assertEqual(settings['intel_installed'], 'true')
        self.assertEqual(settings['intel_pending_reboot'], 'true')
        self.assertTrue((self.box.root / 'boot/config/modprobe.d/my-unraid-vgpu-manager-i915.conf').is_file())
        self.assertIn('id="intel-reboot-required"', self.box.page().stdout)
        self.box.read_state()
        self.box.state['module_busy'] = False
        self.box.write_state()
        shutil.rmtree(self.box.root / 'sys/module/i915')
        self.assertOK(self.box.rc('ensure'))
        self.assertEqual(self.box.read_settings()['intel_pending_reboot'], 'false')
        self.assertTrue((self.box.root / 'sys/module/i915/parameters/max_vfs').is_file())

    def test_busy_sriov_update_never_bypasses_occupancy(self):
        self.box.gpu('intel')
        old = self.box.package(source='i915')
        self.box.installed(old)
        self.box.package(source='i915', build=2, remote=True)
        self.box.settings(intel_installed='true')
        parameters = self.box.root / 'sys/module/i915/parameters'
        parameters.mkdir(parents=True)
        (parameters / 'max_vfs').write_text('7')
        self.box.state['module_busy'] = True
        self.box.write_state()
        self.assertNotEqual(self.box.helper('exec.sh', 'update_intel').returncode, 0)
        self.assertFalse(self.box.events('upgradepkg'))
        self.assertNotEqual(self.box.read_settings().get('intel_pending_reboot'), 'true')

    def test_busy_vf_does_not_allow_first_install_reboot_fallback(self):
        pf = self.box.gpu('intel')
        vf = pf.parent / '0000:03:00.1'
        (self.box.root / 'sys/kernel/iommu_groups/8').mkdir(parents=True)
        (vf / 'iommu_group').symlink_to('/sys/kernel/iommu_groups/8')
        self.box.package(source='i915')
        self.box.state['vf_busy'] = True
        self.box.write_state()
        self.assertNotEqual(self.box.helper('exec.sh', 'install_intel').returncode, 0)
        self.assertFalse(self.box.events('upgradepkg'))
        self.assertEqual(self.box.read_settings()['intel_installed'], 'false')

    def test_first_install_with_xe_defers_without_unloading_other_xe_devices(self):
        pf = self.box.gpu('intel')
        driver = self.box.root / 'sys/bus/pci/drivers/xe'
        driver.mkdir()
        (pf / 'driver').symlink_to('../../drivers/xe')
        (self.box.root / 'sys/module/xe').mkdir()
        self.box.package(source='i915')
        self.assertOK(self.box.helper('exec.sh', 'install_intel'))
        self.assertEqual(self.box.read_settings()['intel_pending_reboot'], 'true')
        self.assertFalse(any('xe' in event[1] for event in self.box.events('modprobe')))

    def test_api_sha256_is_verified_and_saved_for_offline_use(self):
        name = self.box.package(remote=True)
        digest = hashlib.sha256((self.box.root / 'remote' / name).read_bytes()).hexdigest()
        self.box.state['asset_digests'] = {name: 'sha256:' + digest}
        self.box.write_state()
        self.assertOK(self.box.helper('download.sh', 'nvidia', '16'))
        self.assertEqual(Path(str(self.cache(name)) + '.sha256').read_text().split()[0], digest)
        self.box.read_state()
        self.box.state['offline'] = True
        self.box.write_state()
        self.assertOK(self.box.helper('download.sh', 'nvidia', '16'))

    def test_bad_api_digest_rejects_package_even_if_md5_matches(self):
        name = self.box.package(remote=True)
        self.box.state['asset_digests'] = {name: 'sha256:' + '0' * 64}
        self.box.write_state()
        self.assertNotEqual(self.box.helper('download.sh', 'nvidia', '16').returncode, 0)
        self.assertFalse(self.cache(name).exists())

    def test_refresh_checks_api_digest_before_reusing_same_named_cache(self):
        name = self.box.package()
        self.box.package(remote=True)
        self.box.state['asset_digests'] = {name: 'sha256:' + '0' * 64}
        self.box.write_state()
        self.assertNotEqual(self.box.helper('download.sh', 'nvidia', '16', 'latest', '--refresh').returncode, 0)
        self.assertTrue(self.cache(name).exists())
        self.assertTrue(any('/releases/download/' in str(event) for event in self.box.events('curl')))

    def test_malformed_api_digest_is_not_silently_ignored(self):
        name = self.box.package(remote=True)
        self.box.state['asset_digests'] = {name: 'sha256:invalid'}
        self.box.write_state()
        self.assertNotEqual(self.box.helper('download.sh', 'nvidia', '16').returncode, 0)
        self.assertFalse(any('/releases/download/' in str(event) for event in self.box.events('curl')))

    def test_conflicting_plugins_block_download_and_runtime_changes(self):
        for name, source, helper, action in [
                ('nvidia-driver.plg', 'nvidia', 'install_nvidia', 'nvidia_install'),
                ('i915-sriov.plg', 'i915', 'install_intel', 'intel_install'),
                ('vgpu-driver.plg', 'nvidia', 'install_nvidia', 'nvidia_install')]:
            with self.subTest(plugin=name):
                self.conflict(name)
                package = self.box.package(source=source)
                result = self.box.helper('exec.sh', helper)
                self.assertNotEqual(result.returncode, 0)
                self.assertIn(name, result.stderr)
                self.assertNotEqual(self.box.rc(action, str(self.cache(package)).replace(str(self.box.root), '')).returncode, 0)
                self.assertFalse(self.box.events('curl'))
                self.assertFalse(self.box.events('upgradepkg'))
                self.assertFalse(self.box.events('modprobe'))
                (self.box.root / 'var/log/plugins' / name).unlink()

    def test_conflicting_plugin_blocks_boot_restore_only_for_its_stack(self):
        self.conflict('nvidia-driver.plg')
        self.box.settings(nvidia_installed='true', intel_installed='true')
        self.box.package()
        self.box.package(source='i915')
        self.assertNotEqual(self.box.rc('restore').returncode, 0)
        installs = self.box.events('upgradepkg')
        self.assertEqual(len(installs), 1)
        self.assertIn('i915-sriov-', installs[0][1][-1])

    def test_monitoring_plugin_does_not_block_driver_install(self):
        self.conflict('intel-gpu-top.plg')
        self.box.package(source='i915')
        self.assertOK(self.box.helper('exec.sh', 'install_intel'))

    def test_daemon_standard_streams_are_detached(self):
        self.box.gpu()
        self.box.package()
        self.box.settings(nvidia_license_server='dls.local')
        self.assertOK(self.box.helper('exec.sh', 'install_nvidia'))
        streams = self.box.read_state()['daemon_streams']
        self.assertEqual(set(streams), {'nvidia-vgpud', 'nvidia-vgpu-mgr', 'nvidia-gridd'})
        for daemon, descriptors in streams.items():
            self.assertEqual(descriptors, {'0': '/dev/null', '1': '/dev/null', '2': '/dev/null', '9': 'closed'}, daemon)

    def test_boot_defers_network_licensing_until_array_started(self):
        self.box.gpu()
        self.box.package()
        self.box.settings(nvidia_installed='true', nvidia_license_server='dls.local')
        self.box.state['offline'] = True
        self.box.write_state()
        self.assertOK(self.box.rc('ensure'))
        self.assertFalse(self.box.events('curl'))
        self.box.read_state()
        self.box.state['offline'] = False
        self.box.write_state()
        self.assertOK(self.box.rc('license_retry', '1'))
        self.assertTrue(self.box.events('curl'))

    def test_boot_reuses_saved_license_without_network(self):
        self.box.settings(nvidia_license_server='dls.local')
        self.assertOK(self.box.rc('nvidia_license'))
        shutil.rmtree(self.box.root / 'etc/nvidia')
        self.box.gpu()
        self.box.package()
        self.box.settings(nvidia_installed='true')
        self.box.read_state()
        self.box.state['processes'] = []
        self.box.state['offline'] = True
        self.box.write_state()
        calls = len(self.box.events('curl'))
        self.assertOK(self.box.rc('ensure'))
        self.assertEqual(len(self.box.events('curl')), calls)
        self.assertIn('nvidia-gridd', self.box.read_state()['processes'])

    def test_nvidia_uninstall_cleans_owned_config_and_preserves_other_runtimes(self):
        self.box.installed(self.box.package())
        self.box.settings(nvidia_installed='true', nvidia_license_server='dls.local')
        self.assertOK(self.box.rc('nvidia_license'))
        config = self.box.root / 'etc/docker/daemon.json'
        config.write_text(json.dumps({'runtimes': {'nvidia': {'path': '/usr/bin/nvidia-container-runtime'},
                                                  'custom': {'path': '/bin/custom'}},
                                      'default-runtime': 'nvidia', 'registry-mirrors': ['https://example.org']}))
        self.assertOK(self.box.rc('nvidia_uninstall'))
        data = json.loads(config.read_text())
        self.assertEqual(data['runtimes'], {'custom': {'path': '/bin/custom'}})
        self.assertNotIn('default-runtime', data)
        self.assertEqual(data['registry-mirrors'], ['https://example.org'])
        self.assertFalse((self.box.root / 'etc/nvidia/gridd.conf').exists())

    def test_nvidia_cleanup_does_not_remove_unmanaged_config(self):
        self.box.installed(self.box.package())
        config = self.box.root / 'etc/docker/daemon.json'
        config.write_text('{"runtimes":{"nvidia":{"path":"custom-runtime"}},"default-runtime":"nvidia"}')
        before = config.read_bytes()
        gridd = self.box.root / 'etc/nvidia/gridd.conf'
        gridd.parent.mkdir()
        gridd.write_text('# user-managed\nServerAddress=example.org\n')
        self.assertOK(self.box.rc('nvidia_uninstall'))
        self.assertEqual(json.loads(config.read_bytes()), json.loads(before))
        self.assertTrue(gridd.exists())

    def test_intel_ensure_sets_vf_count_once(self):
        result = self.box.shell(f'source {BASE}/scripts/rc.vgpu; intel_has_gpu() {{ return 0; }}; '
                                'intel_write_config() { return 0; }; '
                                'intel_set_vfs() { echo once >> /tmp/fixture/vf-calls; }; intel_do_ensure')
        self.assertOK(result)
        self.assertEqual((self.box.root / 'vf-calls').read_text(), 'once\n')

    def test_intel_uninstall_reloads_xe_as_well_as_i915(self):
        self.box.gpu('intel')
        self.box.installed(self.box.package(source='i915'))
        self.box.settings(intel_installed='true')
        self.assertOK(self.box.rc('intel_uninstall'))
        self.assertIn(['modprobe', ['xe']], self.box.events())

    def test_rate_limit_has_distinct_translated_update_status(self):
        self.box.installed(self.box.package())
        self.box.settings(nvidia_installed='true')
        self.box.state['rate_limited'] = True
        self.box.write_state()
        response = self.box.action('check_updates', refresh='true')
        self.assertOK(response)
        driver = json.loads(response.stdout)['updates']['drivers']['nvidia']
        self.assertEqual(driver['status'], 'rate_limited')
        self.assertIn('额度', driver['message'])
        result = self.box.helper('download.sh', 'nvidia', '16', 'latest', '--refresh')
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('额度', result.stderr)

    def test_plugin_package_migration_removes_only_exact_legacy_record(self):
        current = ET.parse(REPO / f'{PLUGIN}.plg').getroot().get('version')
        legacy = f'{PLUGIN}-2026.10.22'
        unrelated = 'my-unraid-other-plugin-2026.10.22'
        for name in (legacy, unrelated):
            (self.box.root / 'var/log/packages' / name).touch()
        directory = self.box.root / f'boot/config/plugins/{PLUGIN}'
        old = directory / f'{legacy}.txz'
        old.touch()
        archive = directory / f'{PLUGIN}-{current}-x86_64-1.txz'
        archive.touch()
        self.assertOK(self.script())
        self.assertEqual(self.box.events('removepkg'), [['removepkg', [legacy]]])
        self.assertTrue((self.box.root / 'var/log/packages' / unrelated).is_file())
        self.assertFalse(old.exists())
        self.assertTrue(archive.is_file())

    def test_failed_plugin_install_does_not_prune_old_archives(self):
        old = self.box.root / f'boot/config/plugins/{PLUGIN}/{PLUGIN}-2026.10.22.txz'
        old.touch()
        self.box.state['fail_install'] = True
        self.box.write_state()
        self.assertNotEqual(self.script().returncode, 0)
        self.assertTrue(old.is_file())

    def test_plugin_removal_explicitly_rebuilds_cron(self):
        update = self.box.root / 'local/sbin/update_cron'
        update.parent.mkdir(parents=True)
        update.write_text('#!/bin/bash\ntest ! -f /boot/config/plugins/' + PLUGIN + '/' + PLUGIN +
                          '.cron && touch /tmp/fixture/cron-rebuilt\n')
        update.chmod(0o755)
        (self.box.root / f'boot/config/plugins/{PLUGIN}/{PLUGIN}.cron').touch()
        self.assertOK(self.script(method='remove'))
        self.assertTrue((self.box.root / 'cron-rebuilt').exists())


if __name__ == '__main__':
    unittest.main()
