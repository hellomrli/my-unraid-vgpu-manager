#!/usr/bin/env python3
"""Behavioral regressions against an isolated, networkless Unraid simulation."""
import fcntl
import hashlib
import json
from pathlib import Path
import select
import shutil
import subprocess
import time
import unittest
from sandbox import Sandbox, BASE, PLUGIN, KERNEL, NEXT_KERNEL, UUID


def vm_xml(uuid=UUID):
    return f'<domain><devices><hostdev type="mdev" mode="subsystem"><source><address uuid="{uuid}"/></source></hostdev></devices></domain>'

class Regressions(unittest.TestCase):
    def setUp(self): self.box=Sandbox()
    def tearDown(self): self.box.close()
    def assertOK(self, result): self.assertEqual(result.returncode,0,result.stdout+result.stderr)
    def load_upgrade(self): return json.loads((self.box.root/'var/tmp'/f'{PLUGIN}-upgrade.json').read_text())
    def action_json(self, action, **values):
        response=self.box.action(action,**values)
        self.assertOK(response)
        return json.loads(response.stdout)

    def test_auto_upgrade_skips_everything_when_not_enabled(self):
        self.box.package(remote=True,kernel=NEXT_KERNEL)
        self.box.gpu()
        self.assertOK(self.box.helper('upgrade-check.sh','auto'))
        self.assertFalse(self.box.events('curl'))
        self.assertFalse(self.box.events('upgradepkg'))
        self.assertFalse(self.box.events('notify'))

    def test_manual_prepare_does_not_enable_unused_drivers(self):
        self.assertOK(self.box.helper('upgrade-check.sh','prepare',NEXT_KERNEL))
        self.assertFalse(self.box.events('curl'))
        self.assertEqual(self.box.read_settings()['nvidia_installed'],'false')

    def test_nvidia_upgrade_downloads_only_nvidia_and_keeps_series(self):
        self.box.settings(nvidia_installed='true',nvidia_series='19',nvidia_package=f'nvidia-535.309.01-{KERNEL}-1.txz')
        old=self.box.package()
        new=self.box.package(kernel=NEXT_KERNEL,remote=True)
        self.box.package(version='580.178.05',kernel=NEXT_KERNEL,remote=True)
        self.box.package(source='i915',kernel=NEXT_KERNEL,remote=True)
        self.assertOK(self.box.helper('upgrade-check.sh','auto'))
        state=self.load_upgrade()
        self.assertEqual((state['status'],state['series'],state['intel']),('ready','16','disabled'))
        self.assertEqual(state['nvidia_package'],new)
        self.assertFalse(any('my-i915-sriov-driver' in str(e) for e in self.box.events('curl')))
        self.assertFalse(self.box.events('upgradepkg'))
        self.assertTrue((self.box.root/f'boot/config/plugins/{PLUGIN}/packages/6.18.44'/old).exists())

    def test_intel_upgrade_never_queries_nvidia_when_disabled(self):
        self.box.settings(intel_installed='true')
        new=self.box.package(source='i915',kernel=NEXT_KERNEL,remote=True)
        self.assertOK(self.box.helper('upgrade-check.sh','auto'))
        state=self.load_upgrade()
        self.assertEqual(state['intel_package'],new)
        self.assertEqual(state['nvidia'],'disabled')
        self.assertFalse(any('my-nvidia-vgpu-driver' in str(e) for e in self.box.events('curl')))

    def test_enabled_driver_missing_for_next_kernel_prevents_ready(self):
        self.box.settings(nvidia_installed='true',intel_installed='true')
        self.box.package(kernel=NEXT_KERNEL,remote=True)
        self.assertNotEqual(self.box.helper('upgrade-check.sh','auto').returncode,0)
        state=self.load_upgrade()
        self.assertEqual((state['status'],state['nvidia'],state['intel']),('missing','ready','missing'))
        self.assertTrue(self.box.events('notify'))
        self.assertFalse(self.box.events('upgradepkg'))

    def test_corrupt_cached_package_is_never_reported_ready_offline(self):
        self.box.settings(nvidia_installed='true')
        self.box.package(kernel=NEXT_KERNEL,corrupt=True)
        self.box.state['offline']=True; self.box.write_state()
        self.assertNotEqual(self.box.helper('upgrade-check.sh','prepare').returncode,0)
        self.assertEqual(self.load_upgrade()['status'],'missing')

    def test_repeat_auto_check_is_throttled(self):
        self.box.settings(nvidia_installed='true')
        self.box.package(kernel=NEXT_KERNEL,remote=True)
        self.assertOK(self.box.helper('upgrade-check.sh','auto'))
        calls=len(self.box.events('curl')); notices=len(self.box.events('notify'))
        self.assertOK(self.box.helper('upgrade-check.sh','auto'))
        self.assertEqual(len(self.box.events('curl')),calls)
        self.assertEqual(len(self.box.events('notify')),notices)

    def test_same_kernel_and_disabled_auto_setting_do_not_download(self):
        self.box.settings(nvidia_installed='true')
        self.box.boot_image(KERNEL)
        self.assertOK(self.box.helper('upgrade-check.sh','auto'))
        self.box.boot_image(NEXT_KERNEL)
        self.box.settings(kernel_upgrade_check='false')
        self.assertOK(self.box.helper('upgrade-check.sh','auto'))
        self.assertFalse(self.box.events('curl'))

    def test_invalid_boot_image_does_not_guess_from_changelog(self):
        self.box.settings(nvidia_installed='true')
        (self.box.root/'boot/bzimage').write_bytes(b'not a Linux image')
        (self.box.root/'boot/changes.txt').write_text('Linux kernel version 99.9.9\n')
        self.assertNotEqual(self.box.helper('upgrade-check.sh','prepare').returncode,0)
        self.assertFalse(self.box.events('curl'))

    def test_disabled_auto_preparation_still_notifies_without_downloading(self):
        self.box.settings(nvidia_installed='true',kernel_upgrade_check='false')
        self.box.package(kernel=NEXT_KERNEL,remote=True)
        self.assertOK(self.box.helper('upgrade-check.sh','auto'))
        self.assertFalse(self.box.events('curl'))
        self.assertEqual(self.load_upgrade()['status'],'missing')
        self.assertEqual(len(self.box.events('notify')),1)
        self.assertIn('?kernel_upgrade=1',str(self.box.events('notify')[0]))
        self.assertOK(self.box.helper('upgrade-check.sh','prepare'))
        self.assertEqual(self.load_upgrade()['status'],'ready')
        self.assertEqual(self.box.read_settings()['kernel_upgrade_check'],'false')

    def test_update_refresh_fetches_new_build_and_preserves_other_caches(self):
        old=self.box.package(build=1); self.box.installed(old)
        new=self.box.package(build=2,remote=True)
        other=self.box.package(source='i915'); upcoming=self.box.package(kernel=NEXT_KERNEL)
        self.box.settings(nvidia_installed='true')
        module=self.box.root/'sys/module/nvidia'; module.mkdir(); (module/'version').write_text('535.309.01')
        self.assertOK(self.box.helper('exec.sh','update_driver','16','latest'))
        self.assertEqual(self.box.read_settings()['nvidia_package'],new)
        self.assertTrue(self.box.events('curl'))
        self.assertEqual(len(self.box.events('upgradepkg')),1)
        for name,kernel in [(old,KERNEL),(other,KERNEL),(upcoming,NEXT_KERNEL)]:
            self.assertTrue((self.box.root/f'boot/config/plugins/{PLUGIN}/packages/{kernel.split("-")[0]}'/name).is_file())

    def test_update_network_failure_is_not_silently_old_package_success(self):
        self.box.package()
        self.box.settings(nvidia_installed='true')
        self.box.state['offline']=True; self.box.write_state()
        self.assertNotEqual(self.box.helper('exec.sh','update_driver','16','latest').returncode,0)
        self.assertFalse(self.box.events('upgradepkg'))
        self.assertFalse(self.box.events('modprobe'))

    def test_installation_failure_is_propagated_and_does_not_enable_driver(self):
        self.box.package(); self.box.state['fail_install']=True; self.box.write_state()
        result=self.box.helper('exec.sh','install_nvidia','16')
        self.assertNotEqual(result.returncode,0)
        self.assertEqual(self.box.read_settings()['nvidia_installed'],'false')
        self.assertEqual(len(self.box.events('upgradepkg')),1)
        self.assertFalse(self.box.events('depmod'))
        self.assertNotIn('操作完成',result.stdout)

    def test_install_cannot_fall_back_to_corrupt_cache(self):
        self.box.package(corrupt=True)
        self.box.state['offline']=True; self.box.write_state()
        self.assertNotEqual(self.box.helper('exec.sh','install_nvidia','16').returncode,0)
        self.assertFalse(self.box.events('upgradepkg'))

    def test_restore_requires_opt_in_and_uses_exact_boot_kernel(self):
        matching=self.box.package(); self.box.package(kernel=NEXT_KERNEL)
        self.assertOK(self.box.rc('restore'))
        self.assertFalse(self.box.events('upgradepkg'))
        self.box.settings(nvidia_installed='true')
        self.assertOK(self.box.rc('restore'))
        self.assertEqual(self.box.read_settings()['nvidia_package'],matching)
        self.assertFalse(self.box.events('curl'))

    def test_restore_rejects_wrong_kernel_only_cache(self):
        self.box.package(kernel=NEXT_KERNEL)
        self.box.settings(nvidia_installed='true')
        self.assertNotEqual(self.box.rc('restore').returncode,0)
        self.assertFalse(self.box.events('upgradepkg'))

    def test_download_rejects_non_assets_and_wrong_kernel_names(self):
        self.box.package(remote=True,kernel=NEXT_KERNEL)
        self.box.state['releases']['my-nvidia-vgpu-driver|'+KERNEL]=['nvidia-535.309.01-'+NEXT_KERNEL+'-99.txz','nvidia-535.309.01-'+KERNEL+'-99.txz.md5']
        self.box.write_state()
        self.assertNotEqual(self.box.helper('download.sh','nvidia','16','latest','--refresh').returncode,0)
        self.assertFalse(any('/releases/download/' in str(e) for e in self.box.events('curl')))

    def test_auto_series_recommends_19_only_when_supported(self):
        gpu=self.box.gpu(device='0x1eb8')
        self.box.settings(nvidia_series='auto')
        result=self.box.shell(f'source {BASE}/include/common.sh; nvidia_series_caps; nvidia_series')
        self.assertOK(result); self.assertEqual(result.stdout.splitlines(),['both','19'])
        (gpu/'device').write_text('0x1bb3')
        result=self.box.shell(f'source {BASE}/include/common.sh; nvidia_series')
        self.assertEqual(result.stdout.strip(),'16')

    def test_same_version_rebuild_notification_only_for_enabled_driver(self):
        installed=self.box.package(); self.box.installed(installed); self.box.package(build=2,remote=True)
        self.assertOK(self.box.helper('update-check.sh'))
        self.assertFalse(self.box.events('curl'))
        self.box.settings(nvidia_installed='true')
        self.assertOK(self.box.helper('update-check.sh'))
        self.assertEqual(len(self.box.events('notify')),1)
        self.assertFalse(self.box.events('upgradepkg'))

    def test_existing_persistent_binding_blocks_second_vm(self):
        (self.box.root/'sys/bus/mdev/devices'/UUID).mkdir()
        self.box.state['vms']={'VM A':{'state':'running','inactive':vm_xml(),'active':'<domain><devices/></domain>'},'VM B':{'state':'shut off','inactive':'<domain><devices/></domain>'}}
        self.box.write_state()
        result=self.box.rc('nvidia_attach_vm',UUID,'VM B')
        self.assertNotEqual(result.returncode,0)
        self.assertFalse(any(e[1][0]=='attach-device' for e in self.box.events('virsh')))

    def test_live_binding_remains_busy_after_persistent_detach(self):
        self.box.devices(); (self.box.root/'sys/bus/mdev/devices'/UUID).mkdir()
        self.box.state['vms']={'VM A':{'state':'running','inactive':'<domain><devices/></domain>','active':vm_xml()}}
        self.box.write_state()
        self.assertNotEqual(self.box.rc('nvidia_remove_device',UUID).returncode,0)
        self.assertFalse(self.box.events('mdevctl'))
        self.assertTrue((self.box.root/f'boot/config/plugins/{PLUGIN}/vgpu-devices.cfg').read_text().strip())

    def test_failed_device_stop_keeps_definition(self):
        self.box.devices(); (self.box.root/'sys/bus/mdev/devices'/UUID).mkdir()
        self.box.state['fail_stop']=True; self.box.write_state()
        self.assertNotEqual(self.box.rc('nvidia_remove_device',UUID).returncode,0)
        self.assertFalse(any(e[1][0]=='undefine' for e in self.box.events('mdevctl')))
        self.assertIn(UUID,(self.box.root/f'boot/config/plugins/{PLUGIN}/vgpu-devices.cfg').read_text())

    def test_intel_vfs_discovered_from_physical_function_links(self):
        self.box.gpu('intel',pci='0000:03:00.0')
        unrelated=self.box.root/'sys/bus/pci/devices/0000:04:00.1'; unrelated.mkdir()
        result=self.box.shell(f'source {BASE}/scripts/rc.vgpu; intel_sysfs_base; intel_vfs_pci')
        self.assertOK(result)
        self.assertEqual(result.stdout.splitlines(),['/sys/bus/pci/devices/0000:03:00.0','0000:03:00.1'])

    def test_unchanged_vf_count_does_not_recreate_devices(self):
        gpu=self.box.gpu('intel'); before=(gpu/'sriov_numvfs').stat().st_mtime_ns
        self.assertOK(self.box.rc('intel_set_vfs','1'))
        self.assertEqual((gpu/'sriov_numvfs').stat().st_mtime_ns,before)
        self.assertEqual(self.box.read_settings()['intel_vf_number'],'1')

    def test_vf_count_limits_do_not_overwrite_existing_setting(self):
        gpu=self.box.gpu('intel')
        self.assertNotEqual(self.box.rc('intel_set_vfs','8').returncode,0)
        self.assertEqual((gpu/'sriov_numvfs').read_text(),'1')
        self.assertEqual(self.box.read_settings()['intel_vf_number'],'7')

    def test_license_endpoint_change_refreshes_token(self):
        self.box.settings(nvidia_license_server='new.example',nvidia_license_port='443',nvidia_feature_type='2',nvidia_license_verify='true')
        folder=self.box.root/'etc/nvidia/ClientConfigToken'; folder.mkdir(parents=True)
        token=folder/'client_configuration_token.tok'; token.write_text('old-token')
        (self.box.root/'etc/nvidia/gridd.conf').write_text('ServerAddress=old.example\nServerPort=443\nFeatureType=2\n')
        self.assertOK(self.box.rc('nvidia_license'))
        self.assertEqual(token.read_text(),'new-client-configuration-token')
        self.assertNotIn('-k',self.box.events('curl')[0][1])

    def test_failed_license_request_preserves_token_and_runtime_config(self):
        self.box.settings(nvidia_license_server='new.example',nvidia_license_port='443')
        folder=self.box.root/'etc/nvidia/ClientConfigToken'; folder.mkdir(parents=True)
        token=folder/'client_configuration_token.tok'; token.write_text('old-token')
        conf=self.box.root/'etc/nvidia/gridd.conf'; conf.write_text('ServerAddress=old.example\nServerPort=443\n')
        old=conf.read_text(); self.box.state['offline']=True; self.box.write_state()
        self.assertNotEqual(self.box.rc('nvidia_license').returncode,0)
        self.assertEqual(conf.read_text(),old); self.assertEqual(token.read_text(),'old-token')

    def test_general_settings_do_not_disable_unlock(self):
        self.box.settings(unlock='true',nvidia_unlock='true')
        result=self.action_json('save_settings',update_check='false',kernel_upgrade_check='true')
        self.assertTrue(result['ok'],result)
        self.assertEqual(self.box.read_settings()['nvidia_unlock'],'true')
        self.assertEqual(self.box.read_settings()['unlock'],'true')

    def test_post_without_csrf_has_no_side_effect(self):
        result=self.action_json('save_settings',token='wrong',update_check='false')
        self.assertFalse(result['ok']); self.assertIn('令牌',result['message'])
        self.assertEqual(self.box.read_settings()['update_check'],'true')

    def test_invalid_license_input_cannot_inject_settings(self):
        result=self.action_json('save_nvidia',license_server='server\nnvidia_installed=true',license_port='443')
        self.assertFalse(result['ok']); self.assertEqual(self.box.read_settings()['nvidia_installed'],'false')
        result=self.action_json('save_nvidia',license_server='server',license_port='65536')
        self.assertFalse(result['ok'])

    def test_language_follows_unraid_and_ignores_plugin_preference(self):
        self.box.locale('en_US')
        result=self.action_json('save_settings',update_check='true')
        self.assertEqual(result,{'ok':True,'message':'Settings saved.'})
        self.box.settings(ui_language='en')
        self.box.locale('zh_CN')
        result=self.action_json('save_settings',update_check='true')
        self.assertEqual(result,{'ok':True,'message':'设置已保存。'})
        self.assertFalse(self.action_json('save_language',ui_language='en')['ok'])

    def test_language_uses_native_session_and_empty_english_locale(self):
        self.box.locale('zh_CN')
        result=self.box.run('php','-r',"$locale=''; $_SERVER['HTTP_ACCEPT_LANGUAGE']='zh-CN'; require '"+BASE+"/include/web.php'; echo $vgpu_language;")
        self.assertEqual(result.stdout,'en')
        result=self.box.run('php','-r',"$_SESSION=['locale'=>'en_US']; require '"+BASE+"/include/web.php'; echo $vgpu_language;")
        self.assertEqual(result.stdout,'en')
        self.box.settings(ui_language='en')
        result=self.box.shell(f"source {BASE}/include/common.sh; bilingual English 中文")
        self.assertEqual(result.stdout.strip(),'中文')

    def test_standalone_language_does_not_wait_on_native_session_lock(self):
        (self.box.root/'sessions').mkdir()
        setup="ini_set('session.save_path','/tmp/fixture/sessions'); session_id('vgpu-test-session'); "
        holder_code=setup+"session_start(); echo \"locked\\n\"; fflush(STDOUT); fgets(STDIN); session_write_close();"
        holder=subprocess.Popen(self.box.argv(['php','-r',holder_code]),stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True)
        try:
            self.assertTrue(select.select([holder.stdout],[],[],5)[0], 'Session holder did not start')
            self.assertEqual(holder.stdout.readline(),'locked\n')
            code=setup+"$_COOKIE[session_name()]='vgpu-test-session'; require '"+BASE+"/include/web.php'; echo $vgpu_language;"
            for configured,expected in [('zh_CN','zh_CN'),('','en')]:
                self.box.locale(configured)
                result=self.box.run('php','-r',code,timeout=3)
                self.assertOK(result); self.assertEqual(result.stdout,expected)
        finally:
            try: holder.communicate('\n',timeout=5)
            except subprocess.TimeoutExpired: holder.kill(); holder.communicate()

    def test_upgrade_panel_only_appears_from_notification_for_staged_update(self):
        self.box.settings(nvidia_installed='true')
        self.box.package(kernel=NEXT_KERNEL,remote=True)
        self.assertOK(self.box.helper('upgrade-check.sh','auto'))
        notices=self.box.events('notify')
        self.assertTrue(notices)
        self.assertTrue(all('?kernel_upgrade=1#kernel-upgrade-panel' in str(event) for event in notices))
        ordinary=self.box.page(); self.assertOK(ordinary)
        self.assertNotIn('id="kernel-upgrade-panel"',ordinary.stdout)
        self.assertNotIn('id="vgpu-language"',ordinary.stdout)
        linked=self.box.page(kernel_upgrade='1'); self.assertOK(linked)
        self.assertIn('id="kernel-upgrade-panel"',linked.stdout)
        self.box.boot_image(KERNEL)
        self.assertNotIn('id="kernel-upgrade-panel"',self.box.page(kernel_upgrade='1').stdout)
        self.box.boot_image(NEXT_KERNEL); self.box.settings(nvidia_installed='false')
        self.assertNotIn('id="kernel-upgrade-panel"',self.box.page(kernel_upgrade='1').stdout)

    def test_update_status_reports_versions_and_rebuilds_without_downloads(self):
        old_nv=self.box.package(); old_intel=self.box.package(source='i915')
        self.box.installed(old_nv); self.box.installed(old_intel)
        new_nv=self.box.package(version='535.310.00',remote=True)
        new_intel=self.box.package(source='i915',build=2,remote=True)
        self.box.package(version='580.178.05',remote=True)
        self.box.settings(nvidia_installed='true',intel_installed='true',nvidia_series='19')
        result=self.action_json('check_updates',refresh='true'); self.assertTrue(result['ok'],result)
        drivers=result['updates']['drivers']
        self.assertEqual((drivers['nvidia']['current'],drivers['nvidia']['latest'],drivers['nvidia']['series']),(old_nv,new_nv,'16'))
        self.assertEqual(drivers['i915']['latest'],new_intel)
        self.assertIn('535.309.01',drivers['nvidia']['message']); self.assertIn('535.310.00',drivers['nvidia']['message'])
        self.assertIn('构建 2',drivers['i915']['message'])
        self.assertFalse(self.box.events('upgradepkg'))
        self.assertFalse(any('/releases/download/' in str(event) for event in self.box.events('curl')))

    def test_i915_update_detected_when_the_newer_version_has_fewer_digits(self):
        # The i915 version is a dot-stripped upstream date: 2026.08.12.1 packs to
        # the 9-digit 202608121 while 2026.09.16 packs to the 8-digit 20260916.
        # `sort -V` compares a digit run by value, so the installed 202608121
        # outranked every later release and no update was ever reported.
        old=self.box.package(source='i915')
        self.box.installed(old)
        middle=self.box.package(source='i915',version='20260914',remote=True)
        new=self.box.package(source='i915',version='20260916',remote=True)
        self.box.settings(intel_installed='true')
        drivers=self.action_json('check_updates',refresh='true')['updates']['drivers']
        self.assertEqual(drivers['i915']['status'],'available')
        self.assertEqual(drivers['i915']['current'],old)
        self.assertEqual(drivers['i915']['latest'],new)
        self.assertNotEqual(drivers['i915']['latest'],middle)

    def test_intel_upgrade_downloads_the_newest_remote_version(self):
        # The release carries every version it ever built, so the 8-digit
        # 20260916 has to win over the 9-digit 202608121 rather than lose to it.
        self.box.settings(intel_installed='true')
        self.box.package(source='i915',kernel=NEXT_KERNEL,version='202608121',remote=True)
        self.box.package(source='i915',kernel=NEXT_KERNEL,version='20260914',remote=True)
        new=self.box.package(source='i915',kernel=NEXT_KERNEL,version='20260916',remote=True)
        self.assertOK(self.box.helper('upgrade-check.sh','auto'))
        self.assertEqual(self.load_upgrade()['intel_package'],new)

    def test_intel_upgrade_uses_the_newest_cached_package(self):
        # find_package() must pick the newest verified cache entry, otherwise an
        # update installs the older package that is already on the flash drive.
        self.box.settings(intel_installed='true')
        self.box.package(source='i915',kernel=NEXT_KERNEL,version='202608121')
        new=self.box.package(source='i915',kernel=NEXT_KERNEL,version='20260916')
        self.assertOK(self.box.helper('upgrade-check.sh','auto'))
        self.assertEqual(self.load_upgrade()['intel_package'],new)

    def test_installed_package_reports_the_newest_entry(self):
        self.box.package(source='i915')
        new=self.box.package(source='i915',version='20260916')
        self.box.installed(f'i915-sriov-202608121-{KERNEL}-1.txz')
        self.box.installed(new)
        result=self.box.shell(f'source {BASE}/include/common.sh; installed_package i915')
        self.assertOK(result)
        self.assertEqual(result.stdout.strip(),new)

    def test_update_status_invalidates_after_install_disable_or_kernel_change(self):
        old=self.box.package(); self.box.installed(old)
        new=self.box.package(build=2,remote=True)
        self.box.settings(nvidia_installed='true')
        self.assertOK(self.box.helper('update-check.sh','refresh'))
        self.box.installed(new)
        state=json.loads(self.box.helper('update-check.sh','status').stdout)
        self.assertEqual(state['drivers']['nvidia']['status'],'unchecked')
        state=json.loads(self.box.helper('update-check.sh','refresh').stdout)
        self.assertEqual(state['drivers']['nvidia']['status'],'current')
        self.box.settings(nvidia_installed='false')
        state=json.loads(self.box.helper('update-check.sh','status').stdout)
        self.assertEqual(state['drivers']['nvidia']['status'],'disabled')
        self.box.settings(nvidia_installed='true')
        self.box.state['kernel']=NEXT_KERNEL; self.box.write_state()
        state=json.loads(self.box.helper('update-check.sh','status').stdout)
        self.assertEqual(state['drivers']['nvidia']['status'],'missing')

    def test_update_status_offline_is_not_reported_as_current(self):
        self.box.installed(self.box.package()); self.box.package(build=2,remote=True)
        self.box.settings(nvidia_installed='true')
        self.assertOK(self.box.helper('update-check.sh','refresh'))
        self.box.state['offline']=True; self.box.write_state()
        result=self.action_json('check_updates',refresh='true')
        self.assertEqual(result['updates']['drivers']['nvidia']['status'],'error')

    def test_metadata_timeout_keeps_the_other_drivers_update_result(self):
        self.box.settings(nvidia_installed='true',intel_installed='true')
        self.box.installed(self.box.package()); self.box.installed(self.box.package(source='i915'))
        new_nv=self.box.package(build=2,remote=True)
        new_intel=self.box.package(source='i915',build=2,remote=True)
        self.box.state['metadata_delays']={'my-nvidia-vgpu-driver|'+KERNEL:30}; self.box.write_state()
        started=time.monotonic()
        result=self.action_json('check_updates',refresh='true')
        self.assertLess(time.monotonic()-started,20)
        self.assertTrue(result['ok'],result)
        self.assertEqual(result['updates']['drivers']['nvidia']['status'],'error')
        self.assertEqual(result['updates']['drivers']['i915']['latest'],new_intel)
        self.box.state['metadata_delays']={}; self.box.write_state()
        retry=self.action_json('check_updates',refresh='true')
        self.assertEqual(retry['updates']['drivers']['nvidia']['latest'],new_nv)
        self.assertFalse(self.box.events('upgradepkg'))
        self.assertFalse(any('/releases/download/' in str(event) for event in self.box.events('curl')))

    def test_update_deadline_kills_descendants_and_allows_retry(self):
        self.box.settings(nvidia_installed='true')
        self.box.installed(self.box.package()); latest=self.box.package(build=2,remote=True)
        self.box.state['hang_metadata']=True; self.box.write_state()
        # Retry in the same PHP process, before bubblewrap tears down children.
        # A leaked descendant would keep either the output pipe or lock open.
        code="""$_SERVER['REQUEST_METHOD']='POST'; $var=['csrf_token'=>'test-token'];
$_POST=['vgpu_action'=>'check_updates','vgpu_token'=>'test-token','refresh'=>'true'];
ob_start(); include '"""+BASE+"""/include/actions.php'; $first=json_decode(ob_get_clean(),true);
$state=json_decode(file_get_contents('/tmp/fixture/state.json'),true); unset($state['hang_metadata']);
file_put_contents('/tmp/fixture/state.json',json_encode($state));
echo vgpu_json(['first'=>$first,'retry'=>vgpu_driver_updates('refresh')]);"""
        started=time.monotonic()
        response=self.box.run('php','-r',code,timeout=40); self.assertOK(response)
        self.assertLess(time.monotonic()-started,38)
        result=json.loads(response.stdout)
        self.assertFalse(result['first']['ok']); self.assertIn('超时',result['first']['message'])
        self.assertEqual(result['retry']['drivers']['nvidia']['latest'],latest)
        self.assertFalse(result['retry'].get('busy'))
        self.assertFalse(self.box.events('upgradepkg'))

    def test_update_check_reports_busy_without_waiting_or_querying_again(self):
        self.box.settings(nvidia_installed='true')
        self.box.installed(self.box.package()); self.box.package(build=2,remote=True)
        self.assertTrue(self.action_json('check_updates',refresh='true')['ok'])
        calls=len(self.box.events('curl'))
        with (self.box.root/'var/lock'/f'{PLUGIN}-updates.lock').open('a') as lock:
            fcntl.flock(lock,fcntl.LOCK_EX)
            result=self.action_json('check_updates',refresh='true')
        self.assertTrue(result['ok']); self.assertTrue(result['updates']['busy'])
        self.assertEqual(len(self.box.events('curl')),calls)
        cached=json.loads(self.box.helper('update-check.sh','status').stdout)
        self.assertNotIn('busy',cached)

    def test_update_checks_respect_disabled_drivers_and_daily_setting(self):
        self.box.installed(self.box.package()); self.box.package(build=2,remote=True)
        result=self.action_json('check_updates',refresh='true')
        self.assertEqual(result['updates']['drivers']['nvidia']['status'],'disabled')
        self.assertFalse(self.box.events('curl'))
        self.box.settings(nvidia_installed='true',update_check='false')
        self.assertOK(self.box.helper('update-check.sh','check'))
        self.assertFalse(self.box.events('curl'))
        result=self.action_json('check_updates',refresh='true')
        self.assertEqual(result['updates']['drivers']['nvidia']['status'],'available')
        self.box.settings(update_check='true')
        calls=len(self.box.events('curl'))
        self.assertOK(self.box.helper('update-check.sh','check'))
        self.assertEqual(len(self.box.events('curl')),calls)

    def test_update_check_requires_csrf_before_querying_releases(self):
        self.box.installed(self.box.package()); self.box.settings(nvidia_installed='true')
        result=self.action_json('check_updates',token='invalid',refresh='true')
        self.assertFalse(result['ok']); self.assertFalse(self.box.events('curl'))

    def test_ui_helper_rejects_arbitrary_command_dispatch(self):
        result=self.box.helper('exec.sh','touch','/tmp/fixture/unexpected')
        self.assertNotEqual(result.returncode,0)
        self.assertFalse((self.box.root/'unexpected').exists())

    def test_boot_restores_packages_before_devices_and_is_idempotent(self):
        self.box.package(); self.box.package(source='i915')
        self.box.settings(nvidia_installed='true',intel_installed='true',intel_vf_number='1')
        self.box.gpu(); intel=self.box.gpu('intel'); self.box.devices()
        before=(intel/'sriov_numvfs').stat().st_mtime_ns
        self.assertOK(self.box.rc('ensure'))
        events=self.box.events()
        installs=[i for i,e in enumerate(events) if e[0]=='upgradepkg']
        starts=[i for i,e in enumerate(events) if e[0]=='mdevctl' and e[1][0]=='start']
        self.assertEqual(len(installs),2)
        self.assertTrue(starts and min(starts)>max(installs))
        self.assertFalse(self.box.events('curl'))
        self.assertOK(self.box.rc('ensure'))
        self.assertEqual(len(self.box.events('upgradepkg')),2)
        self.assertEqual((intel/'sriov_numvfs').stat().st_mtime_ns,before)

    def test_restart_nvidia_does_not_touch_intel_vfs(self):
        package=self.box.package(); self.box.installed(package)
        self.box.gpu(); intel=self.box.gpu('intel')
        self.box.settings(nvidia_installed='true',intel_installed='true')
        before=(intel/'sriov_numvfs').stat().st_mtime_ns
        self.assertOK(self.box.rc('restart'))
        self.assertEqual((intel/'sriov_numvfs').stat().st_mtime_ns,before)
        self.assertFalse(any('i915' in e[1] for e in self.box.events('modprobe')))

    def test_busy_nvidia_uninstall_retains_package_and_enabled_state(self):
        package=self.box.package(); self.box.installed(package)
        self.box.settings(nvidia_installed='true')
        module=self.box.root/'sys/module/nvidia'; module.mkdir(); (module/'version').write_text('535.309.01')
        self.box.state['module_busy']=True; self.box.write_state()
        self.assertNotEqual(self.box.rc('nvidia_uninstall').returncode,0)
        self.assertEqual(self.box.read_settings()['nvidia_installed'],'true')
        self.assertFalse(self.box.events('removepkg'))
        self.assertTrue((self.box.root/'var/log/packages'/package.removesuffix('.txz')).exists())

    def test_wrong_kernel_update_is_rejected_before_stopping_services(self):
        package=self.box.package(kernel=NEXT_KERNEL)
        filename=f'/boot/config/plugins/{PLUGIN}/packages/6.18.47/{package}'
        self.assertNotEqual(self.box.rc('nvidia_update',filename).returncode,0)
        self.assertFalse(self.box.events('modprobe'))
        self.assertFalse(self.box.events('killall'))
        self.assertFalse(self.box.events('upgradepkg'))

    def test_new_kernel_can_restore_prepared_driver_without_network(self):
        self.box.settings(nvidia_installed='true',nvidia_package=f'nvidia-535.309.01-{KERNEL}-1.txz',nvidia_series='19')
        package=self.box.package(kernel=NEXT_KERNEL,remote=True)
        self.assertOK(self.box.helper('upgrade-check.sh','prepare'))
        self.box.read_state(); self.box.state['kernel']=NEXT_KERNEL; self.box.state['offline']=True; self.box.write_state()
        calls=len(self.box.events('curl'))
        self.assertOK(self.box.rc('restore'))
        self.assertEqual(self.box.read_settings()['nvidia_package'],package)
        self.assertEqual(len(self.box.events('curl')),calls)

    def test_build_numbers_order_numerically_and_never_downgrade(self):
        # As text, -10 sorted below -2 and -9, so the tenth rebuild was never
        # chosen and an installed -10 was offered "-9" as an update.
        self.box.settings(nvidia_installed='true')
        for build in (2,9,10): self.box.package(build=build)
        result=self.box.shell(f'source {BASE}/include/common.sh; find_package nvidia {KERNEL} 16')
        self.assertOK(result); self.assertTrue(result.stdout.strip().endswith(f'{KERNEL}-10.txz'))
        self.box.installed(f'nvidia-535.309.01-{KERNEL}-10.txz')
        self.box.package(build=9,remote=True)
        drivers=self.action_json('check_updates',refresh='true')['updates']['drivers']
        self.assertEqual(drivers['nvidia']['status'],'current')
        (self.box.root/'var/log/packages'/f'nvidia-535.309.01-{KERNEL}-10').unlink()
        self.box.installed(f'nvidia-535.309.01-{KERNEL}-9.txz')
        newest=self.box.package(build=10,remote=True)
        drivers=self.action_json('check_updates',refresh='true')['updates']['drivers']
        self.assertEqual((drivers['nvidia']['status'],drivers['nvidia']['latest']),('available',newest))

    def test_page_opens_when_update_status_cannot_be_read(self):
        self.box.settings(nvidia_installed='true',intel_installed='true')
        (self.box.root/f'local/emhttp/plugins/{PLUGIN}/include/update-check.sh').write_text('#!/bin/bash\nexit 1\n')
        page=self.box.page(); self.assertOK(page)
        self.assertIn('id="driver-status-panel"',page.stdout)
        failed=json.loads((Path(__file__).resolve().parents[1]/f'source{BASE}/include/zh_CN.json').read_text())['Update check failed. Try again.']
        self.assertIn(failed,page.stdout)

    def test_saved_license_token_restores_licensing_offline_after_reboot(self):
        self.box.settings(nvidia_license_server='dls.local',nvidia_license_port='8443')
        self.assertOK(self.box.rc('nvidia_license'))
        saved=self.box.root/f'boot/config/plugins/{PLUGIN}/license/client_configuration_token.tok'
        self.assertEqual(saved.read_text(),'new-client-configuration-token')
        # Reboot: RAM contents are gone and the local license server is not up yet.
        shutil.rmtree(self.box.root/'etc/nvidia')
        self.box.read_state(); self.box.state['processes']=[]; self.box.state['offline']=True; self.box.write_state()
        self.assertOK(self.box.rc('nvidia_license'))
        self.assertEqual((self.box.root/'etc/nvidia/ClientConfigToken/client_configuration_token.tok').read_text(),'new-client-configuration-token')
        self.assertIn('nvidia-gridd',self.box.read_state()['processes'])
        # A token saved for another endpoint must not be reused.
        shutil.rmtree(self.box.root/'etc/nvidia'); self.box.settings(nvidia_license_port='443')
        self.assertNotEqual(self.box.rc('nvidia_license').returncode,0)

    def test_license_is_retried_after_startup(self):
        self.box.settings(nvidia_installed='true',nvidia_license_server='dls.local')
        module=self.box.root/'sys/module/nvidia'; module.mkdir(); (module/'version').write_text('535.309.01')
        self.box.state['offline']=True; self.box.write_state()
        self.assertNotEqual(self.box.rc('license_retry','2').returncode,0)
        self.box.read_state(); self.box.state['offline']=False; self.box.write_state()
        self.assertOK(self.box.rc('license_retry','2'))
        self.assertIn('nvidia-gridd',self.box.read_state()['processes'])
        calls=len(self.box.events('curl'))
        self.assertOK(self.box.rc('license_retry','2'))
        self.assertEqual(len(self.box.events('curl')),calls)

    def test_cron_is_published_through_update_cron(self):
        sbin=self.box.root/'local/sbin'; sbin.mkdir(parents=True)
        (sbin/'update_cron').write_text('#!/bin/bash\necho called >> /tmp/fixture/update_cron.log\n'); (sbin/'update_cron').chmod(0o755)
        plugins=self.box.root/'var/log/plugins'; plugins.mkdir(parents=True)
        (plugins/f'{PLUGIN}.plg').write_text('')
        (self.box.root/'crontab').write_text(f'0 1 * * * /usr/local/sbin/mover\n* * * * * {BASE}/include/upgrade-check.sh auto\n')
        self.assertOK(self.box.helper('exec.sh','configure_cron'))
        cron=(self.box.root/f'boot/config/plugins/{PLUGIN}/{PLUGIN}.cron').read_text()
        self.assertIn('include/update-check.sh',cron); self.assertIn('include/upgrade-check.sh auto',cron)
        self.assertEqual((self.box.root/'crontab').read_text(),'0 1 * * * /usr/local/sbin/mover\n')
        self.assertTrue((self.box.root/'update_cron.log').is_file())
        self.assertOK(self.box.helper('exec.sh','change_update_check','false'))
        self.assertNotIn('update-check.sh',(self.box.root/f'boot/config/plugins/{PLUGIN}/{PLUGIN}.cron').read_text())

    def test_intel_gpu_with_sriov_is_managed_when_several_exist(self):
        other=self.box.root/'sys/bus/pci/devices/0000:00:01.0'; other.mkdir(parents=True)
        for name,value in {'vendor':'0x8086','device':'0x56a0','class':'0x030000'}.items(): (other/name).write_text(value)
        self.box.gpu('intel',pci='0000:03:00.0')
        result=self.box.shell(f'source {BASE}/scripts/rc.vgpu; intel_pf_pci')
        self.assertOK(result); self.assertEqual(result.stdout.strip(),'0000:03:00.0')
        self.box.settings(intel_installed='true')
        page=self.box.page(); self.assertOK(page)
        self.assertIn('0000:03:00.0',page.stdout); self.assertNotIn('0000:00:01.0',page.stdout)

    def test_unchanged_setting_is_not_rewritten(self):
        path=self.box.root/f'boot/config/plugins/{PLUGIN}/settings.cfg'
        before=path.stat()
        self.assertOK(self.box.shell(f'source {BASE}/include/common.sh; set_setting update_check true'))
        after=path.stat()
        self.assertEqual((before.st_ino,before.st_mtime_ns),(after.st_ino,after.st_mtime_ns))
        self.assertOK(self.box.shell(f'source {BASE}/include/common.sh; set_setting update_check false'))
        self.assertEqual(self.box.read_settings()['update_check'],'false')

    def test_published_sha256_must_match(self):
        name=self.box.package()
        cache=self.box.root/f'boot/config/plugins/{PLUGIN}/packages/6.18.44'
        (cache/(name+'.sha256')).write_text('0'*64+'  '+name+'\n')
        lookup=f'source {BASE}/include/common.sh; find_package nvidia {KERNEL} 16'
        self.assertNotEqual(self.box.shell(lookup).returncode,0)
        (cache/(name+'.sha256')).write_text(hashlib.sha256((cache/name).read_bytes()).hexdigest()+'  '+name+'\n')
        self.assertOK(self.box.shell(lookup))
        remote=self.box.package(build=2,remote=True)
        (self.box.root/'remote'/(remote+'.sha256')).write_text('f'*64+'\n')
        self.assertNotEqual(self.box.helper('download.sh','nvidia','16','latest','--refresh').returncode,0)
        self.assertFalse((cache/remote).exists())
        (self.box.root/'remote'/(remote+'.sha256')).write_text(hashlib.sha256((self.box.root/'remote'/remote).read_bytes()).hexdigest()+'\n')
        self.assertOK(self.box.helper('download.sh','nvidia','16','latest','--refresh'))
        self.assertTrue((cache/remote).is_file()); self.assertTrue((cache/(remote+'.sha256')).is_file())

    def test_failed_series_switch_keeps_series_preference(self):
        self.box.installed(self.box.package())
        self.box.package(version='580.178.05',remote=True)
        self.box.settings(nvidia_installed='true',nvidia_series='16')
        self.box.state['fail_install']=True; self.box.write_state()
        self.assertNotEqual(self.box.helper('exec.sh','update_driver','19','latest').returncode,0)
        self.assertEqual(self.box.read_settings()['nvidia_series'],'16')

    def test_intel_uninstall_reloads_stock_driver(self):
        package=self.box.package(source='i915'); self.box.installed(package)
        self.box.gpu('intel'); self.box.settings(intel_installed='true')
        self.assertOK(self.box.rc('intel_uninstall'))
        events=self.box.events()
        removed=max(i for i,e in enumerate(events) if e[0]=='removepkg')
        self.assertTrue(any(e[0]=='modprobe' and e[1]==['i915'] for e in events[removed:]))
        self.assertEqual(self.box.read_settings()['intel_installed'],'false')

    def test_minute_check_reuses_kernel_of_unchanged_boot_image_and_trims_log(self):
        self.box.settings(nvidia_installed='true',kernel_upgrade_check='false')
        log=self.box.root/f'var/log/{PLUGIN}-upgrade.log'; log.write_bytes(b'x'*(3*1024*1024))
        state=self.box.root/'var/tmp'/f'{PLUGIN}-upgrade.json'
        self.assertOK(self.box.helper('upgrade-check.sh','auto'))
        self.assertLessEqual(log.stat().st_size,1024*1024)
        (self.box.root/f'local/emhttp/plugins/{PLUGIN}/include/kernel.php').write_text('<?php exit(1);\n')
        state.unlink()
        self.assertOK(self.box.helper('upgrade-check.sh','auto'))
        self.assertEqual(self.load_upgrade()['kernel'],NEXT_KERNEL)
        # A rewritten boot image is read again, never taken from the cache.
        time.sleep(0.01); self.box.boot_image(NEXT_KERNEL); state.unlink()
        self.assertOK(self.box.helper('upgrade-check.sh','auto'))
        self.assertFalse(state.exists())

if __name__ == '__main__': unittest.main(verbosity=2)
