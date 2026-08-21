# my-unraid-vgpu-manager

Unraid plugin for **unified management of GPU virtualization**: NVIDIA vGPU
and Intel i915 SR-IOV, all from one settings page.

## What it does

| | NVIDIA vGPU | Intel i915 SR-IOV |
|---|---|---|
| Driver | merged driver (vGPU + host CUDA/docker) | i915-sriov-dkms (strongtz) |
| Install | on-demand from the page | on-demand from the page |
| Manage | license, unlock, vGPU devices (mdev) | VF count, vfio-pci binding, boot params |

**Drivers are never installed automatically** - you choose Install from the
plugin page when you actually need vGPU. Systems that don't use vGPU stay
completely untouched.

## Driver sources

The plugin downloads driver packages built by two dedicated projects
(GitHub Actions cloud builds), keyed by the running kernel:

- NVIDIA: [hellomrli/my-vgpu-driver](https://github.com/hellomrli/my-vgpu-driver)
  - `nvidia-<ver>-<kernel>-Unraid-<b>.txz` from Release tag `<kernel>`
- Intel: [hellomrli/my-i915-sriov-driver](https://github.com/hellomrli/my-i915-sriov-driver)
  - `i915-sriov-<ver>-<kernel>-Unraid-<b>.txz` from Release tag `<kernel>`

If no package exists for your kernel yet, run the build workflow in the
corresponding driver repo (they accept any Unraid kernel release).

## Install

In Unraid, add the plugin URL:

```
https://github.com/hellomrli/my-unraid-vgpu-manager/raw/master/my-unraid-vgpu-manager.plg
```

Then open **Settings -> Unraid vGPU Manager**:

1. **NVIDIA vGPU** - click *Install NVIDIA vGPU Driver*, set your license
   server (FastAPI-DLS host:port), add vGPU devices with the profiles shown,
   and assign the generated hostdev XML to VMs. The same GPU stays usable for
   docker with `--gpus all`.
2. **Intel i915 SR-IOV** - click *Install Intel i915 SR-IOV Driver*, set the
   VF count, and add the boot parameters shown to the syslinux append line.

## Notes

- NVIDIA vGPU devices (mdev) are restored at every boot automatically.
- Unlocking consumer GPUs is optional and off by default; Tesla P4 is natively
  vGPU-capable (no unlock).
- For VMs, always passthrough Intel **VFs** (00:02.x), never the PF (00:02.0).
