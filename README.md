# my-unraid-vgpu-manager

Unraid 插件：**统一管理 GPU 虚拟化** —— NVIDIA vGPU 与 Intel i915 SR-IOV，全部在一个设置页面中完成。

## 支持的 GPU（重要）

### NVIDIA vGPU —— 支持哪些显卡？

当前驱动基于 **NVIDIA vGPU 16.14（535.309.01）**，vGPU 能力来自 NVIDIA 官方的 vGPU 授权认证机制：

| 类别 | 支持情况 |
|---|---|
| **Tesla / 数据中心卡（vGPU 认证）** | ✅ **原生支持，无需解锁**。535 分支覆盖 Pascal（Tesla P4 / P6 / P40 / P100）、Volta（V100）、Turing（Tesla T4）等。**本项目实测验证的目标卡是 Tesla P4**。 |
| **Quadro / 专业卡（vGPU 认证）** | ✅ 原生支持（如 RTX A 系列、Quadro RTX 系列中带 vGPU 认证的型号）。 |
| **普通消费级游戏卡（GTX / RTX 游戏卡）** | ❌ **当前不支持**。详见下方说明。 |

**关于普通 RTX / GTX 游戏卡（例如 RTX 3060 / 3070 / 3080 / 3090 / 4070 / 4090 等）：**

- NVIDIA 通过软件限制屏蔽了消费级显卡的 vGPU 功能，这类卡**不在官方 vGPU 认证名单**里。
- 开源项目 [vgpu_unlock](https://github.com/mbilker/vgpu_unlock-rs) 可以绕过这一限制，但它的消费卡支持范围仅到 **Maxwell / Pascal / Turing**（GTX 9 / 10 系列、RTX 20 系列）；**Ampere（RTX 30 系列）是 work-in-progress，Ada Lovelace（RTX 40 系列）不支持**。
- **本插件页面上的 "vGPU unlock" 开关目前只是一个预留位，驱动包里尚未真正集成 vgpu_unlock-rs 的 hook 库（`libvgpu_unlock_rs.so`），因此该开关现阶段不会生效。**
- 结论：**如果你手里是普通 RTX 游戏卡（尤其是 30 / 40 系列），当前这套驱动无法给你提供 vGPU。** 请使用 vGPU 认证的 Tesla/专业卡（推荐 Tesla P4，性价比高且原生支持）。

### Intel i915 SR-IOV —— 支持哪些核显？

Intel 第 8 代及之后的核显（含 11–14 代酷睿 / Alder Lake / Raptor Lake 的 UHD/Iris Xe），使用 [strongtz i915-sriov-dkms](https://github.com/strongtz/i915-sriov-dkms) 驱动开启 SR-IOV。本项目的目标设备是 **Alder Lake-HX 的 UHD 770**。

---

## 功能一览

| | NVIDIA vGPU | Intel i915 SR-IOV |
|---|---|---|
| 驱动 | Merged 驱动（vGPU + 宿主机 CUDA/docker） | i915-sriov-dkms（strongtz） |
| 安装 | 页面按需安装 | 页面按需安装 |
| 管理 | License 设置、vGPU 设备（mdev）、绑定到 VM | VF 数量、vfio-pci 绑定、启动参数 |

**驱动不会自动安装**——只有在你确实需要 vGPU 时，才在插件页面点击安装。不使用 vGPU 的系统完全不受影响。

---

## 设置页面（三 tab 布局）

| Tab | 内容 |
|---|---|
| **① Drivers** | 驱动状态总览 + NVIDIA / Intel 驱动的安装、更新、卸载按钮 + 更新检查开关 |
| **② NVIDIA GPU** | License 服务器（FastAPI-DLS）、FeatureType、vGPU 设备（mdev）增删启停、**vGPU 绑定到 VM**、profile_override.toml |
| **③ Intel i915 SR-IOV** | VF 数量、vfio-pci 直通状态、启动参数提示 |

---

## 安装

在 Unraid 中添加插件 URL：

```
https://github.com/hellomrli/my-unraid-vgpu-manager/raw/master/my-unraid-vgpu-manager.plg
```

---

## 使用说明

### NVIDIA vGPU（Tesla P4 示例）

1. **安装驱动**：打开 **设置 → Unraid vGPU Manager → ① Drivers**，点击 *Install NVIDIA vGPU Driver*。安装完成后系统会自动加载驱动、启动 `nvidia-vgpud` / `nvidia-vgpu-mgr`。

2. **配置授权**（vGPU 需要 License）：切到 **② NVIDIA GPU → License & Modules**，填写 FastAPI-DLS 服务器地址与端口，FeatureType 选择 **2 - RTX Virtual Workstation (vDWS, Q-series)**（P4 的 Q 系列档位用 2；B 系列用 0）。插件会自动从 `https://<server>:<port>/-/client-token` 拉取授权 token 并启动 `nvidia-gridd`。

3. **创建 vGPU**：在 **② NVIDIA GPU → vGPU Devices** 选择 GPU 和性能档位（如 `nvidia-65` = P4-4Q，4GB 显存），生成 UUID 后点击 *Add vGPU*。vGPU 设备会在每次开机自动恢复。

4. **把 vGPU 绑定到虚拟机**：在 **② NVIDIA GPU → Attach vGPU to VM**，选择 vGPU 和目标 VM，点击 *Attach*。绑定写入 VM 的持久配置，**重启该 VM 后** vGPU 就会作为一块显卡出现在 VM 里。

   > **操作说明（重要）**：
   > - attach / detach 写的是 VM 持久配置，**不需要**先关闭 VM 就能操作。
   > - 但 mdev 不支持热插拔，**必须关机再开机**（不是重启）后，vGPU 才会出现在 VM 里（或才被彻底释放）。
   > - 一个 vGPU 同一时间只能绑定到一个 VM。

5. **宿主机同时用 GPU**：MERGED 驱动下，宿主机 docker 仍可通过 `--gpus all` 使用同一张 P4（docker 需已配置 nvidia 运行时，插件会处理）。

### Intel i915 SR-IOV

1. 在 **① Drivers** 点击 *Install Intel i915 SR-IOV Driver*。
2. 在 **③ Intel i915 SR-IOV** 设置 VF 数量，VFs 会自动绑定到 `vfio-pci`。
3. 把页面显示的启动参数加到 **设置 → Boot** 的 syslinux append 行。
4. 在 VM 里直通 VF（`00:02.1` / `00:02.2`…），**切勿直通 PF（`00:02.0`）**。

---

## 驱动来源

插件从两个独立项目下载驱动包（GitHub Actions 云编译），按当前内核版本匹配：

- NVIDIA：[hellomrli/my-nvidia-vgpu-driver](https://github.com/hellomrli/my-nvidia-vgpu-driver)
  - Release tag = 内核版本，资产 `nvidia-<版本>-<内核>-Unraid-<构建号>.txz`
- Intel：[hellomrli/my-i915-sriov-driver](https://github.com/hellomrli/my-i915-sriov-driver)
  - Release tag = 内核版本，资产 `i915-sriov-<版本>-<内核>-Unraid-<构建号>.txz`

如果当前内核还没有对应驱动包，在对应驱动仓库手动运行云编译工作流即可（接受任意 Unraid 内核版本）。

---

## 注意事项

- NVIDIA vGPU 设备（mdev）每次开机自动恢复
- vGPU 绑定到 VM 后需**关机再开机**生效（mdev 不能热插拔）
- 普通 RTX / GTX 游戏卡当前不支持 vGPU（见顶部"支持的 GPU"）
- Intel 直通时只能直通 **VF**（00:02.x），绝不能直通 PF（00:02.0）
