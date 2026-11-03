# User guide

[Back to installation and overview](../README.md)

## Architecture

```text
┌────────────────────────────────────────────────────────────────────┐
│  Unraid WebUI   Settings -> Unraid vGPU Manager                    │
│  Drivers  |  NVIDIA GPU  |  Intel SR-IOV                           │
└───────────────┬────────────────────────────────────────────────────┘
               │
               ▼
┌────────────────────────────────────────────────────────────────────┐
│  PHP   web.php - actions.php - kernel.php                          │
└───────────────┬────────────────────────────────────────────────────┘
               │
               ▼
┌────────────────────────────────────────────────────────────────────┐
│  Shell   rc.vgpu - common.sh - download.sh                         │
│          update-check.sh - upgrade-check.sh                        │
└───────────────┬────────────────────────────────────┬───────────────┘
               │                                    │
               ▼                                    ▼
┌───────────────────────────┐      ┌─────────────────────────────────┐
│  /boot/config/plugins/    │      │  GitHub Release assets          │
│    my-unraid-vgpu-manager/│      │  my-nvidia-vgpu-driver          │
│    packages/<kernel>/     │      │  my-i915-sriov-driver builds    │
└───────────────┬───────────┘      └─────────────────────────────────┘
               │
               ▼
┌────────────────────────────────────────────────────────────────────┐
│  Kernel modules and vGPU devices -> VMs, Docker (--gpus all)       │
└────────────────────────────────────────────────────────────────────┘
```

The page renders the interface, `kernel.php` reads the kernel staged for the next boot, and the shell layer owns everything that touches packages and modules. Packages live on the flash drive under `/boot/config/plugins/my-unraid-vgpu-manager/packages/<kernel>/`, which is what makes both boot restore and upgrade pre-staging work without re-downloading.

## Usage example

Installing the plugin does not install any driver. A full first run, from the Unraid WebUI:

```text
# 1. Plugins -> Install Plugin, and paste the plugin URL
https://github.com/hellomrli/my-unraid-vgpu-manager/raw/master/my-unraid-vgpu-manager.plg

# 2. Settings -> Unraid vGPU Manager -> Drivers
#    Pick the series that matches your card and install the NVIDIA driver.
#    The first install can reuse an already verified local package.

# 3. Drivers tab -> enable the daily update check if you want version notices.
#    Checking reads Release metadata only; it downloads and installs nothing.

# 4. NVIDIA GPU tab -> License & Modules
#    Set the license server, port and FeatureType, then save.

# 5. NVIDIA GPU tab -> pick a card and a profile, generate a UUID, add the vGPU.

# 6. NVIDIA GPU tab -> bind the device to a target VM.
#    The binding is persistent: shut the VM down and start it again
#    so the device is attached at a real cold boot.
```

Expected result: the vGPU appears in the device list with its profile and UUID, the VM starts with the device attached, and both survive a reboot because the configuration is stored on the flash drive.

Two behaviours are worth knowing before you start:

- A device that a running VM still holds keeps showing as occupied. Detach it from inside the VM's configuration, then shut the VM down; an attached device cannot be removed or stopped.
- To switch the NVIDIA driver series, stop every VM and container using the GPU, select the target series under License & Modules, and use the switch button there. A plain driver update stays on the installed series.

## Updates, removal and conflicts

Updating and removing the plugin use the same Unraid plugin manager. Removal deletes the interface, the update hooks and the scheduled checks, and calls `rc.vgpu stop` without force-stopping a running VM; your settings and the driver caches stay on the flash drive, and a reboot unloads the drivers.

Before installing a driver, uninstall other plugins managing the same stack and reboot. The manager rejects known conflicts such as Nvidia-Driver, i915-sriov and the old vgpu-driver plugin; monitoring-only plugins such as intel-gpu-top are not conflicts.

## Quick start

Open **Settings → Unraid vGPU Manager**. The page has three tabs:

| Tab | What it covers |
|---|---|
| Drivers | Driver status, available versions and update buttons, install and uninstall, and the scheduled check settings |
| NVIDIA GPU | Driver series, licensing, modules, unlock, vGPU profiles, device management and VM binding |
| Intel SR-IOV | i915/xe status, VF count, passthrough state and boot parameters |

For NVIDIA, the shortest path is: install a driver on the Drivers tab, set the license server under License & Modules, add a vGPU from the profile list, then bind it to a VM. For Intel, install the driver, set the VF count, add the parameters shown on the page to your active Unraid boot entry, and pass a **VF** (never the PF) through to the VM.

Only `intel_iommu=on iommu=pt` belongs in the recommended boot options. The plugin manages i915/xe `max_vfs`, `force_probe`, `xelp_enable_ccs` and i915 `enable_guc` through modprobe configuration. Remove duplicate options and both drivers from global boot blacklists, then reboot; the Intel tab reports conflicts. The opposite driver is excluded only for the managed PCI device ID, not globally unloaded or blacklisted. An i915 **first install** can defer activation when the stock driver is busy, without forcing console detachment. Updates to an enabled SR-IOV stack still abort when it is busy.

## Choosing i915 or xe

**i915 is the default and recommendation. xe is experimental.** Newer architecture or more upstream commits do not demonstrate better SR-IOV performance or stability on your hardware. Both packages come from the experimental [strongtz community port](https://github.com/strongtz/i915-sriov-dkms), not guaranteed production support. As of 2026-11-03, that port warns that its xe module does not support MTL/LNL; this is not a claim about mainline Linux xe support or a guarantee that i915 SR-IOV works on those platforms.

Choose a driver in **Drivers > Intel SR-IOV driver**. Existing installations and missing preferences remain on i915 (`intel_driver=i915`); plugin upgrades never silently opt users into xe.

1. A change (or a first xe install) downloads and verifies a separate package, keeps rollback cache, and writes next-boot configuration. It does **not** replace live packages, unload modules, stop workloads or change running VFs. If another kernel is already staged, its selected driver must also be cached before queuing the switch.
2. Disable automatic startup of GPU VMs/containers before experimenting. Reboot; activation runs locally before array startup, without network. A stored boot ID prevents plugin upgrades in the same boot from activating the pending choice. A failed driver start does not guarantee that Unraid cancels workload autostart.
3. Verify the actual loaded PF module and VF passthrough before starting GPU workloads. Driver choice and module-on-disk version are shown separately from the loaded module. Check `/var/log/my-unraid-vgpu-manager-boot.log` and `dmesg` on failure.
4. Cancel before reboot to keep the active driver without runtime changes. After an unsuccessful reboot, select i915 and reboot again to roll back; the pending request is retained on activation failure. Do not manually install both packages: they share `intel_sriov_compat` and must be mutually exclusive.

The legacy file name `/boot/config/modprobe.d/my-unraid-vgpu-manager-i915.conf` is retained for migration but manages either selected driver. Saving CCS/VF settings preserves the pending next-boot choice. Xe uses `force_probe=<device ID>` and `max_vfs`, not i915's `enable_guc`. Remove manual Intel `modprobe` commands from `/boot/config/go` before switching. The manager refuses a switch between identical PF device IDs because `force_probe` cannot select just one BDF; it never forcibly unbinds another driver or detaches the console.

Driver status compares the installed version with the available one and shows both build numbers. Enable the daily check to look for updates when the page opens, or press the check button to query immediately; a check that does not answer within 35 seconds is reported as timed out and the button comes back so you can retry.

## Driver updates and CCS0

After you confirm **Update driver**, the plugin downloads and verifies the package before identifying consumers from live VM mdev/PCI devices and Docker GPU requests, device mappings and mounts. It requests a normal VM shutdown and aborts after roughly two minutes without forcing power off. Containers use `docker stop --time 30` (Docker may kill them after that timeout). Unidentified host processes can still block module removal; the plugin does not kill them or stop the entire Docker/libvirt service. **Restart stopped VMs and containers manually afterwards**, including checking the log after a failed update. Scheduled checks and kernel pre-staging do not stop workloads.

The Intel tab has a separate **CCS0 switch**, **enabled by default** for i915/xe modules that advertise `xelp_enable_ccs`. Upstream defaults may differ (i915 defaults off since `2026.09.16`). Saving preserves a queued driver switch and does not change running VF counts or stop VMs. **Reboot or successfully reload a supported driver to apply it.** Unsupported modules do not receive the unknown parameter; the preference is retained for supported versions. Remove manually configured i915/xe CCS boot options instead of maintaining a second copy.

## Driver series and hardware

| Series | Package version | When to choose it |
|---|---|---|
| 16.x | 535.309.01 | Pascal cards (P4, P40, P100 and similar) and any device that needs `vgpu_unlock`; the 16.x line is past end of maintenance |
| 19.x | 580.178.05 | Newer GPUs that this branch supports; on a fresh install where the hardware appears in both lists, 19.x is the recommendation |

The hardware hint comes from the PCI IDs in each branch's `vgpuConfig.xml`. It is not an NVIDIA certification or a record of testing on real hardware: newer architectures may additionally require NVIDIA SR-IOV to be enabled first, and this plugin does not run `sriov-manage` for you. Verified hardware in this repository is limited to a Tesla P4; other cards should not be assumed to work because that one does.

The consumer-card unlock kernel patch is built into the 16.x series only, because its config magic is 535-specific. Upstream `vgpu_unlock` covers Maxwell, Pascal and Turing (GTX 9/10 and RTX 20 series), treats RTX 30 as experimental, and does not support RTX 40. Cards with native vGPU support, such as the P4, never need the unlock.

## Pre-staging drivers for an Unraid upgrade

After Unraid writes a new OS to the flash drive, the plugin reads the kernel version actually staged in `/boot/bzimage` and compares it with the running `uname -r`. The OS-update hook checks immediately and a five-minute fallback covers other update paths. The preparation options are reached from the Unraid update notification, not from the normal plugin page.

| What you have enabled | What an Unraid upgrade does |
|---|---|
| No GPU driver | Queries and downloads nothing; install a driver manually when you want one |
| NVIDIA vGPU only | Checks and downloads the NVIDIA driver for the new kernel; Intel takes no part |
| Intel SR-IOV only | Prepares the selected i915/xe package (pending choice takes precedence); NVIDIA takes no part |
| Both | Prepares both independently, and reports ready only after everything passes verification |
| Missing package, network error or checksum failure | Reports not ready and keeps the existing packages so you can inspect or roll back |

Pre-staging keeps the installed NVIDIA series, so a 535.x or 16.x install does not become 580.x or 19.x just because Unraid was upgraded, and a pinned driver version is respected rather than silently replaced. It only stores files: the running kernel keeps its driver and nothing reboots.

Boot restoration does not contact the license server: it reuses a saved token for the same endpoint when available. Missing tokens are requested in the background after the array starts, so a license server running in a local VM or container does not delay array startup.

## Cache and package sources

NVIDIA and i915 use the full kernel version as the Release tag, for example `6.18.58-Unraid`. Xe uses `xe-6.18.58-Unraid` in the same Intel repository:

- NVIDIA: [hellomrli/my-nvidia-vgpu-driver](https://github.com/hellomrli/my-nvidia-vgpu-driver)
- Intel: [hellomrli/my-i915-sriov-driver](https://github.com/hellomrli/my-i915-sriov-driver), built from [strongtz/i915-sriov-dkms](https://github.com/strongtz/i915-sriov-dkms)

Intel package names are `i915-sriov-<date>-<kernel>-<build>.txz` and `xe-sriov-<date>-<kernel>-<build>.txz`; caches and updates never substitute one for the other. Without a matching package for the selected kernel, selection fails safely and keeps the current driver.

The Intel build repository maintains only the deduplicated union of the current official stable kernel, current official beta/RC kernel (from their release notes), and ich777's latest preparation kernel. Historical assets remain available, but older kernels outside those sources stop receiving new driver builds. On 2026-11-03 the targets are `6.18.58-Unraid` (7.3.4 and 7.4.0-rc.2) and `6.18.60-Unraid` (ich777 preparation).

Packages are cached at `/boot/config/plugins/my-unraid-vgpu-manager/packages/<kernel>/`. If you place a package there by hand, add its `.txz.md5` next to it (a `.txz.sha256`, if present, must match too); the plugin verifies the file by content and does not execute or trust paths taken from the checksum file. A package name has to match both the kernel and the driver series.

Online downloads verify GitHub's upload-time SHA-256 asset digest and save it as `.txz.sha256` for offline restoration. Older releases without a digest retain MD5 and optional SHA-256 sidecar verification. Explicit refresh checks the API digest before reusing a same-named cached package. API quota exhaustion is reported separately from other network failures. These checks detect content changes; they are not publisher signatures.

Successful downloads, installations and explicit local restores prune obsolete cache entries. Retained kernels include the running kernel, the staged boot kernel, the previously recorded running kernel, `/boot/previous/bzimage` when readable, and the most recently prepared kernel. Each retained kernel keeps the newest verified build per driver and NVIDIA series, plus installed packages, the selected pinned version and the package just requested. Active downloads/installations hold a cache lock; failed updates do not delete the installed package. If the boot kernel cannot be read, cross-kernel pruning is skipped. Unknown files are not deleted. Boot-time `ensure` does not run this cleanup, avoiding extra USB reads on the array-start path.

The plugin itself uses Slackware-compatible names such as `my-unraid-vgpu-manager-2026.11.03-x86_64-1.txz`, verified by both MD5 and SHA-256 in the manifest. Unraid downloads this package from the repository's `packages/` directory using the `.plg` URL in the [README installation section](../README.md#install-the-plugin); the plugin does not need a GitHub Release. Installation migrates exact legacy package records and removes old plugin archives only after the new payload installs successfully.

If no package exists yet for a new kernel, build one in the driver repository. The plugin will not install a package built for a different kernel, and it does not report a failed download as an updated driver.

## Development and verification

```bash
# Rebuild the package and refresh the .plg MD5/SHA-256 after source/version changes
python3 scripts/build-plugin.py

# PHP / Bash / JS / JSON / XML, isolated lifecycle regressions, package consistency
./scripts/check.sh

# Browser interaction checks (needs Chrome or Chromium)
npm ci
python3 tests/browser_server.py
```

The checks need PHP CLI with SimpleXML, Python 3.9+, Node.js, ShellCheck, jq, bubblewrap and GNU coreutils, matching what Unraid ships. Regression tests run against an isolated filesystem with no network and no host GPU, and never invoke the host's driver management commands. The browser suite drives the same isolated filesystem over a local HTTP server and covers forms, the Unraid language handover, driver version notices, the notification entry point, the mobile layout, and the unresponsive, retry-after-timeout and late-response paths.

CI runs the same commands on `ubuntu-24.04` and uploads the interface screenshots it captures as a workflow artifact.

## Project links

| Topic | Link |
|---|---|
| Fix history and verification boundaries | [docs/REVIEW.md](REVIEW.md) |
| Plugin manifest and changelog | [my-unraid-vgpu-manager.plg](../my-unraid-vgpu-manager.plg) |
| NVIDIA driver packages | [hellomrli/my-nvidia-vgpu-driver](https://github.com/hellomrli/my-nvidia-vgpu-driver) |
| Intel driver packages | [hellomrli/my-i915-sriov-driver](https://github.com/hellomrli/my-i915-sriov-driver) |
| Intel SR-IOV upstream | [strongtz/i915-sriov-dkms](https://github.com/strongtz/i915-sriov-dkms) |

## License

Released under the [GNU General Public License v3.0](../LICENSE).
