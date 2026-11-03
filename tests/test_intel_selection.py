import json
from pathlib import Path
import unittest

from sandbox import Sandbox, BASE, KERNEL, NEXT_KERNEL, PLUGIN


class IntelSelectionTests(unittest.TestCase):
    def setUp(self):
        self.box = Sandbox()
        self.addCleanup(self.box.close)
        self.box.boot_image(KERNEL)

    def ok(self, result):
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        return result

    def cache(self, name):
        kernel = name.split('-sriov-', 1)[1].split('-', 1)[1].rsplit('-', 1)[0]
        return f'/boot/config/plugins/{PLUGIN}/packages/{kernel.split("-")[0]}/{name}'

    def config(self, runtime=False):
        return self.box.root / ('etc/modprobe.d' if runtime else 'boot/config/modprobe.d') / f'{PLUGIN}-i915.conf'

    def enable(self, driver='i915'):
        name = self.box.package(source=driver, version='2026.10.28')
        self.box.installed(name)
        self.box.settings(intel_driver=driver, intel_installed='true', intel_vf_number='1', intel_package=name)
        self.box.gpu('intel')
        self.ok(self.box.rc('intel_load'))
        return name

    def queue(self, driver='xe'):
        name = self.box.package(source=driver, version='2026.11.01')
        self.ok(self.box.helper('exec.sh', 'switch_intel', driver))
        return name

    def test_missing_preference_defaults_to_i915_and_ui_explains_both(self):
        self.assertEqual(self.ok(self.box.shell(f'source {BASE}/include/common.sh; intel_driver')).stdout, 'i915\n')
        self.box.locale('en')
        page = self.ok(self.box.page()).stdout
        self.assertIn('value="i915" selected', page)
        for text in ('i915 (default, recommended)', 'xe (experimental)', 'xe is an experimental driver.', 'MTL/LNL', 'roll back'):
            self.assertIn(text, page)

    def test_invalid_driver_is_rejected_before_any_download_or_settings_change(self):
        before = self.box.read_settings()
        for driver in ('XE', '../xe', 'i915;id', 'nvidia', ''):
            self.assertNotEqual(self.box.helper('exec.sh', 'switch_intel', driver).returncode, 0)
            self.assertNotEqual(self.box.rc('intel_switch', driver, '/tmp/none').returncode, 0)
        self.assertEqual(self.box.read_settings(), before)
        self.assertFalse(self.box.events('curl'))
        self.assertFalse(self.box.events('upgradepkg'))

    def test_xe_uses_its_own_release_tag_cache_and_numeric_build_sort(self):
        self.box.package(source='i915', version='2026.12.01')
        self.box.package(source='xe', version='2026.11.01', build=2, remote=True)
        latest = self.box.package(source='xe', version='2026.11.01', build=10, remote=True)
        self.ok(self.box.helper('download.sh', 'xe'))
        urls = str(self.box.events('curl'))
        self.assertIn(f'/releases/tags/xe-{KERNEL}', urls)
        self.assertIn(f'/releases/download/xe-{KERNEL}/{latest}', urls)
        result = self.ok(self.box.shell(f'source {BASE}/include/common.sh; find_package xe {KERNEL}'))
        self.assertTrue(result.stdout.strip().endswith(latest))

    def test_queue_never_touches_live_modules_packages_vfs_or_workloads(self):
        old = self.enable()
        runtime = self.config(True).read_bytes()
        vf = self.box.root/'sys/bus/pci/devices/0000:03:00.0/sriov_numvfs'
        mtime = vf.stat().st_mtime_ns
        before = len(self.box.events())
        target = self.queue()
        events = self.box.events()[before:]
        self.assertFalse([e for e in events if e[0] in ('modprobe','upgradepkg','removepkg','docker','virsh')])
        self.assertEqual(vf.stat().st_mtime_ns, mtime)
        self.assertEqual(self.config(True).read_bytes(), runtime)
        settings = self.box.read_settings()
        self.assertEqual((settings['intel_driver'], settings['intel_pending_driver'], settings['intel_package']), ('i915','xe',old))
        self.assertEqual(settings['intel_pending_package'], target)
        config = self.config().read_text()
        self.assertIn('blacklist xe', config)
        self.assertIn('options i915 force_probe=!4680', config)
        self.assertIn('force_probe=4680', config)
        self.assertNotIn('enable_guc', config)
        self.assertNotIn('force_probe=*', config)

    def test_plugin_restore_in_same_boot_preserves_queued_driver(self):
        self.enable(); self.queue()
        before = len(self.box.events('upgradepkg'))
        self.ok(self.box.rc('restore')); self.ok(self.box.rc('ensure'))
        self.assertEqual(len(self.box.events('upgradepkg')), before)
        self.assertEqual(self.box.read_settings()['intel_driver'], 'i915')
        self.assertEqual(self.box.read_settings()['intel_pending_driver'], 'xe')
        self.assertIn('blacklist xe', self.config().read_text())
        self.assertIn('blacklist i915', self.config(True).read_text())

    def test_cancel_before_reboot_restores_boot_config_without_runtime_changes(self):
        self.enable(); self.queue()
        before = len(self.box.events())
        self.ok(self.box.helper('exec.sh', 'cancel_intel_switch'))
        events = self.box.events()[before:]
        self.assertFalse([e for e in events if e[0] in ('modprobe','upgradepkg','removepkg')])
        self.assertEqual(self.box.read_settings()['intel_pending_driver'], '')
        self.assertIn('blacklist i915', self.config().read_text())

    def test_choosing_current_driver_cancels_pending_switch(self):
        self.enable(); self.queue()
        self.ok(self.box.helper('exec.sh', 'switch_intel', 'i915'))
        self.assertEqual(self.box.read_settings()['intel_pending_driver'], '')

    def test_first_xe_install_is_only_opted_in_through_pending_until_reboot(self):
        self.box.package(source='xe'); self.box.gpu('intel')
        self.ok(self.box.helper('exec.sh', 'install_intel', 'xe'))
        self.ok(self.box.rc('restore')); self.ok(self.box.rc('ensure'))
        self.assertEqual(self.box.read_settings()['intel_installed'], 'false')
        self.assertFalse(self.box.events('upgradepkg'))
        self.assertFalse(self.box.events('modprobe'))
        self.ok(self.box.helper('exec.sh', 'cancel_intel_switch'))
        self.assertFalse(self.config().exists())

    def test_reboot_applies_offline_and_replaces_opposite_package_explicitly(self):
        old = self.enable(); target = self.queue()
        self.box.reboot(clear_packages=False)
        self.box.state['offline'] = True; self.box.write_state()
        before = len(self.box.events('curl'))
        self.ok(self.box.rc('ensure'))
        settings = self.box.read_settings()
        self.assertEqual((settings['intel_driver'], settings['intel_package'], settings['intel_pending_driver']), ('xe',target,''))
        self.assertFalse((self.box.root/'var/log/packages'/old.removesuffix('.txz')).exists())
        self.assertIn(old.removesuffix('.txz')+'%', self.box.events('upgradepkg')[-1][1][-1])
        self.assertEqual(len(self.box.events('curl')), before)
        calls = [e[1] for e in self.box.events('modprobe')]
        xe = next(args for args in calls if args[0] == 'xe')
        self.assertIn('force_probe=4680', xe)
        self.assertNotIn('enable_guc=3', xe)
        self.assertLess(calls.index(['intel_sriov_compat']), calls.index(xe))

    def test_first_xe_install_activates_after_real_reboot(self):
        self.box.gpu('intel'); self.box.package(source='xe')
        self.ok(self.box.helper('exec.sh', 'install_intel', 'xe'))
        self.box.reboot()
        self.ok(self.box.rc('ensure'))
        self.assertEqual(self.box.read_settings()['intel_driver'], 'xe')
        self.assertEqual(self.box.read_settings()['intel_installed'], 'true')

    def test_switch_back_to_i915_uses_i915_options_and_never_loads_xe(self):
        self.enable('xe'); self.queue('i915'); self.box.reboot()
        before = len(self.box.events())
        self.ok(self.box.rc('ensure'))
        calls = [e[1] for e in self.box.events()[before:] if e[0] == 'modprobe']
        self.assertTrue(any(args[0] == 'i915' and 'enable_guc=3' in args for args in calls))
        self.assertFalse(any('xe' in args for args in calls))
        self.assertIn('options xe force_probe=!4680', self.config().read_text())

    def test_failed_activation_retains_request_and_can_queue_rollback(self):
        old = self.enable(); self.queue(); self.box.reboot()
        self.box.state['fail_modprobe'] = ['xe']; self.box.write_state()
        self.assertNotEqual(self.box.rc('ensure').returncode, 0)
        self.assertEqual(self.box.read_settings()['intel_driver'], 'i915')
        self.assertEqual(self.box.read_settings()['intel_pending_driver'], 'xe')
        self.assertTrue((self.box.root/self.cache(old).lstrip('/')).exists())
        self.assertNotEqual(self.box.rc('intel_cancel_switch').returncode, 0)
        self.ok(self.box.helper('exec.sh', 'switch_intel', 'i915'))
        self.box.reboot()
        self.ok(self.box.rc('ensure'))
        self.assertEqual(self.box.read_settings()['intel_pending_driver'], '')
        self.assertEqual(self.box.read_settings()['intel_driver'], 'i915')

    def test_failed_package_install_does_not_commit_choice(self):
        self.enable(); self.queue(); self.box.reboot()
        self.box.state['fail_install'] = True; self.box.write_state()
        self.assertNotEqual(self.box.rc('ensure').returncode, 0)
        self.assertEqual(self.box.read_settings()['intel_driver'], 'i915')
        self.assertEqual(self.box.read_settings()['intel_pending_driver'], 'xe')

    def test_missing_or_corrupt_queued_package_never_falls_back_to_other_driver(self):
        self.enable(); target = self.queue(); self.box.reboot()
        (self.box.root/self.cache(target).lstrip('/')).write_bytes(b'corrupt')
        self.assertNotEqual(self.box.rc('ensure').returncode, 0)
        self.assertFalse(self.box.events('upgradepkg'))
        self.assertEqual(self.box.read_settings()['intel_pending_driver'], 'xe')

    def test_wrong_driver_owning_pf_aborts_without_unloading_it(self):
        self.enable(); self.queue(); self.box.reboot()
        driver = self.box.root/'sys/bus/pci/drivers/i915'; driver.mkdir(exist_ok=True)
        (self.box.root/'sys/bus/pci/devices/0000:03:00.0/driver').symlink_to('../../drivers/i915')
        before = len(self.box.events())
        self.assertNotEqual(self.box.rc('ensure').returncode, 0)
        self.assertFalse([e for e in self.box.events()[before:] if e[0] in ('modprobe','upgradepkg')])

    def test_pending_switch_suppresses_updates_and_keeps_cache_entries(self):
        old = self.enable(); target = self.queue()
        newest = self.box.package(source='xe', version='2026.11.02')
        self.ok(self.box.rc('restore'))
        for name in (old,target,newest): self.assertTrue((self.box.root/self.cache(name).lstrip('/')).is_file())
        state = json.loads(self.ok(self.box.helper('update-check.sh','refresh')).stdout)
        self.assertEqual(state['drivers']['i915']['status'], 'switch_pending')
        before = len(self.box.events('curl'))
        self.assertNotEqual(self.box.helper('exec.sh','update_intel').returncode, 0)
        self.assertEqual(len(self.box.events('curl')), before)

    def test_ccs_save_preserves_pending_boot_config_and_active_runtime_config(self):
        self.enable(); self.queue()
        self.box.read_state(); self.box.state['ccs_supported'] = True; self.box.write_state()
        self.ok(self.box.rc('intel_set_ccs','false'))
        self.assertIn('options xe max_vfs=1 xelp_enable_ccs=0', self.config().read_text())
        self.assertIn('options i915 enable_guc=3 max_vfs=1 xelp_enable_ccs=0', self.config(True).read_text())
        self.assertEqual(self.box.read_settings()['intel_pending_driver'], 'xe')

    def test_upgrade_prepares_pending_target_not_current_driver(self):
        self.enable(); self.queue()
        self.box.boot_image(NEXT_KERNEL)
        target = self.box.package(source='xe',kernel=NEXT_KERNEL, remote=True)
        self.ok(self.box.helper('upgrade-check.sh','prepare'))
        state = json.loads((self.box.root/f'var/tmp/{PLUGIN}-upgrade.json').read_text())
        self.assertEqual((state['intel_driver'],state['intel_package'],state['status']), ('xe',target,'ready'))
        self.box.reboot(kernel=NEXT_KERNEL)
        self.ok(self.box.rc('ensure'))
        self.assertEqual(self.box.read_settings()['intel_package'], target)

    def test_switch_requires_target_for_already_staged_boot_kernel(self):
        self.enable(); self.box.boot_image(NEXT_KERNEL)
        self.box.package(source='xe')
        self.assertNotEqual(self.box.helper('exec.sh','switch_intel','xe').returncode, 0)
        self.assertFalse(self.box.read_settings().get('intel_pending_driver'))

    def test_xe_update_checks_only_xe_release_and_displays_xe_row(self):
        self.enable('xe')
        target = self.box.package(source='xe',version='2026.11.01',remote=True)
        state = json.loads(self.ok(self.box.helper('update-check.sh','refresh')).stdout)
        self.assertEqual(state['drivers']['xe']['latest'],target)
        self.assertNotIn('i915',state['drivers'])
        page = self.ok(self.box.page()).stdout
        self.assertIn('data-update-row="xe"',page)
        self.assertNotIn('data-update-row="i915"',page)

    def test_both_driver_boot_conflicts_are_escaped_and_reported(self):
        (self.box.root/'cmdline').write_text('xe.force_probe=* i915.force_probe=!4680 xe.max_vfs=<bad> module_blacklist=i915')
        page = self.ok(self.box.page()).stdout
        self.assertIn('id="intel-boot-conflicts"',page)
        self.assertIn('xe.max_vfs=&lt;bad&gt;',page)

    def test_xe_package_cannot_coinstall_with_loaded_i915_compat(self):
        self.enable()
        target = self.box.package(source='xe')
        result = self.box.shell(f'source {BASE}/scripts/rc.vgpu; install_driver_package xe {self.cache(target)}')
        self.assertNotEqual(result.returncode,0)
        self.assertFalse(self.box.events('upgradepkg'))

    def test_switch_refuses_multiple_pfs_with_identical_device_id(self):
        self.enable()
        self.box.gpu('intel',pci='0000:04:00.0')
        self.box.package(source='xe')
        self.assertNotEqual(self.box.helper('exec.sh','switch_intel','xe').returncode,0)
        self.assertFalse(self.box.read_settings().get('intel_pending_driver'))
        self.assertFalse(self.box.events('upgradepkg'))

    def test_loading_rejects_both_community_packages_on_disk(self):
        self.enable()
        self.box.installed(self.box.package(source='xe'))
        before = len(self.box.events('modprobe'))
        self.assertNotEqual(self.box.rc('intel_load').returncode,0)
        self.assertEqual(len(self.box.events('modprobe')),before)

    def test_chinese_selector_recommends_i915_and_labels_xe_experimental(self):
        page = self.ok(self.box.page()).stdout
        self.assertIn('i915（默认，推荐）',page)
        self.assertIn('xe（实验性）',page)
        self.assertIn('xe 为实验性驱动，建议默认使用 i915。',page)

    def test_loaded_module_label_does_not_use_disk_version(self):
        self.enable()
        (self.box.root/'sys/module/i915/version').write_text('loaded-old-sriov')
        self.box.read_state(); self.box.state['intel_disk_version']='new-on-disk-sriov'; self.box.write_state()
        page = self.ok(self.box.page()).stdout
        self.assertIn('i915 loaded-old-sriov',page)
        self.assertIn('new-on-disk-sriov',page)
        self.assertNotIn('i915 new-on-disk-sriov',page)


if __name__ == '__main__':
    unittest.main()
