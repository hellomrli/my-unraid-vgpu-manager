# my-unraid-vgpu-manager

Unraid 插件：**统一管理 GPU 虚拟化** —— NVIDIA vGPU 与 Intel i915 SR-IOV，全部在一个设置页面中完成。

## 功能一览

| | NVIDIA vGPU | Intel i915 SR-IOV |
|---|---|---|
| 驱动 | Merged 驱动（vGPU + 宿主机 CUDA/docker） | i915-sriov-dkms（strongtz） |
| 安装 | 页面按需安装 | 页面按需安装 |
| 管理 | License 设置、解锁、vGPU 设备（mdev） | VF 数量、vfio-pci 绑定、启动参数 |

**驱动不会自动安装**——只有在你确实需要 vGPU 时，才在插件页面点击安装。不使用 vGPU 的系统完全不受影响。

## 驱动来源

插件从两个独立项目下载驱动包（GitHub Actions 云编译），按当前内核版本匹配：

- NVIDIA：[hellomrli/my-nvidia-vgpu-driver](https://github.com/hellomrli/my-nvidia-vgpu-driver)
  - Release tag = 内核版本，资产 `nvidia-<版本>-<内核>-Unraid-<构建号>.txz`
- Intel：[hellomrli/my-i915-sriov-driver](https://github.com/hellomrli/my-i915-sriov-driver)
  - Release tag = 内核版本，资产 `i915-sriov-<版本>-<内核>-Unraid-<构建号>.txz`

如果当前内核还没有对应驱动包，在对应驱动仓库手动运行云编译工作流即可（接受任意 Unraid 内核版本）。

## 安装

在 Unraid 中添加插件 URL：

```
https://github.com/hellomrli/my-unraid-vgpu-manager/raw/master/my-unraid-vgpu-manager.plg
```

然后打开 **设置 → Unraid vGPU Manager**：

1. **NVIDIA vGPU** —— 点击 *安装 NVIDIA vGPU 驱动*，设置 License 服务器（FastAPI-DLS 的 host:port），用页面显示的性能档位添加 vGPU 设备，把生成的 hostdev XML 附加到虚拟机。同一张 GPU 仍可通过 `--gpus all` 给 docker 使用。
2. **Intel i915 SR-IOV** —— 点击 *安装 Intel i915 SR-IOV 驱动*，设置 VF 数量，并把页面显示的启动参数加到 syslinux 的 append 行。

## 注意事项

- NVIDIA vGPU 设备（mdev）每次开机自动恢复
- 消费级 GPU 解锁默认关闭；Tesla P4 原生支持 vGPU（无需解锁）
- Intel 直通时只能直通 **VF**（00:02.x），绝不能直通 PF（00:02.0）
