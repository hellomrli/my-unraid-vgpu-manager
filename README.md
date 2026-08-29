# my-unraid-vgpu-manager

Unraid 插件：**统一管理 GPU 虚拟化** —— NVIDIA vGPU 与 Intel i915 SR-IOV，全部在一个设置页面中完成。

## 支持的 GPU（重要）

### NVIDIA vGPU —— 双驱动系列，按硬件自动推荐

驱动仓库为每个 Unraid 内核**同时发布两个系列**的 Merged 驱动，插件会检测已安装的 GPU 型号（PCI 设备 ID 对照各分支 `vgpuConfig.xml`）并给出对应建议：

| 系列 | 驱动版本 | 分支状态 | 硬件范围 |
|---|---|---|---|
| **16.x** | 535.309.01 | vGPU 16.14 LTS（2026-07 EOL，末版） | Maxwell / Pascal / Volta / Turing / Ampere / Ada：**Tesla P4**、P6、P40、P100、V100、M60/M10、T4、Quadro RTX 6000/8000、A40、L40/L40S、RTX 6000 Ada 等 |
| **19.x** | 580.178.05 | vGPU 19.6 **现行 LTS**（支持到 2028-07） | **Turing T4 起**：Ampere（A40/A10）、Ada（L40/L40S/RTX 6000 Ada）、Blackwell（B 系列）。**不支持 Pascal/Maxwell** |

插件页面上的实际行为：

- **Pascal 卡（P4 / P40 / P100 / P6 等）** → 只提示安装 **16.x**（Pascal 从 17 分支起被 NVIDIA 移除，16.14 是这类卡的末版 vGPU 驱动）
- **T4 及之后的卡** → 显示系列选择器，**默认推荐 19.x**（现行 LTS）；同一张卡今后换 19.x 无需换卡
- **消费级 GeForce 游戏卡** → 不在 vGPU 支持列表，提示走 16.x + unlock（见下）；未检测到 NVIDIA GPU 时也可安装，插上卡后开机自动激活
- **License & Modules** 中可手动覆盖系列（`auto / 16 / 19`），两个系列的驱动包可在 U 盘共存，切换系列即切换安装源

> **宿主与 guest 版本配套**：升级宿主驱动时，VM 内的 guest 驱动需同步升级（NVIDIA 官方兼容矩阵：19.x/20.x 宿主只接受同分支及 19.x 的 guest 驱动）。

**关于普通 RTX / GTX 游戏卡（例如 RTX 3060 / 3070 / 3080 / 3090 / 4070 / 4090 等）：**

- NVIDIA 通过软件限制屏蔽了消费级显卡的 vGPU 功能，这类卡**不在官方 vGPU 认证名单**里。
- 本插件已内置开源 [vgpu_unlock](https://github.com/DualCoder/vgpu_unlock) / [vgpu_unlock-rs](https://github.com/mbilker/vgpu_unlock-rs) 的两层组件：**内核补丁**（`vgpu_unlock_hooks.c` + `kern.ld`，已适配 535.x）打进 `nvidia.ko`，**用户空间库**（`libvgpu_unlock_rs.so`）通过 `LD_PRELOAD` 注入守护进程。打开 NVIDIA GPU 页的 **vGPU unlock** 开关即可启用。
- ⚠️ **unlock 内核补丁只构建进 16.x 系列**（magic 值为 535 专属），消费卡用户请安装 16.x。
- 消费卡支持范围：**Maxwell / Pascal / Turing**（GTX 9 / 10 系列、RTX 20 系列）；**Ampere（RTX 30 系列）是 work-in-progress，Ada Lovelace（RTX 40 系列）不支持**。
- 稳妥起见仍推荐 vGPU 认证的 Tesla/专业卡（推荐 Tesla P4，原生支持、本项目实测验证）。

### Intel i915 SR-IOV —— 支持哪些核显？

Intel 第 8 代及之后的核显（含 11–14 代酷睿 / Alder Lake / Raptor Lake 的 UHD/Iris Xe），使用 [strongtz i915-sriov-dkms](https://github.com/strongtz/i915-sriov-dkms) 驱动开启 SR-IOV。本项目的目标设备是 **Alder Lake-HX 的 UHD 770**。

---

## 功能一览

| | NVIDIA vGPU | Intel i915 SR-IOV |
|---|---|---|
| 驱动 | Merged 驱动（vGPU + 宿主机 CUDA/docker），**16.x / 19.x 双系列按硬件推荐** | i915-sriov-dkms（strongtz） |
| 安装 | 页面按需安装（系列选择器） | 页面按需安装 |
| 管理 | License 设置、vGPU 设备（mdev）、绑定到 VM | VF 数量、vfio-pci 绑定、启动参数 |

**驱动不会自动安装**——只有在你确实需要 vGPU 时，才在插件页面点击安装。不使用 vGPU 的系统完全不受影响。

---

## 设置页面（三 tab 布局）

| Tab | 内容 |
|---|---|
| **① Drivers** | 驱动状态总览（含检测到的 GPU 型号与可用系列）+ NVIDIA / Intel 驱动的安装（带系列选择）、更新、卸载按钮 + 更新检查开关 |
| **② NVIDIA GPU** | 驱动系列设置、License 服务器（FastAPI-DLS）、FeatureType、vGPU 设备（mdev）增删启停、**vGPU 绑定到 VM**、profile_override.toml |
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

1. **安装驱动**：打开 **设置 → Unraid vGPU Manager → ① Drivers**。页面会显示检测到的 GPU 型号和支持的系列：
   - P4 上只会出现 *Install 16.x (535.309.01)*；
   - T4 及以后的卡会出现系列下拉框（19.x LTS 预选）。
   安装完成后系统会自动加载驱动、启动 `nvidia-vgpud` / `nvidia-vgpu-mgr`。

2. **配置授权**（vGPU 需要 License）：切到 **② NVIDIA GPU → License & Modules**，填写 FastAPI-DLS 服务器地址与端口，FeatureType 选择 **2 - RTX Virtual Workstation (vDWS, Q-series)**（P4 的 Q 系列档位用 2；B 系列用 0）。插件会自动从 `https://<server>:<port>/-/client-token` 拉取授权 token 并启动 `nvidia-gridd`。同一页的 **Driver series** 可随时改默认系列（auto = 跟随硬件检测）。

3. **创建 vGPU**：在 **② NVIDIA GPU → vGPU Devices** 选择 GPU 和性能档位（如 `nvidia-65` = P4-4Q，4GB 显存），生成 UUID 后点击 *Add vGPU*。vGPU 设备会在每次开机自动恢复。

4. **把 vGPU 绑定到虚拟机**：在 **② NVIDIA GPU → Attach vGPU to VM**，选择 vGPU 和目标 VM，点击 *Attach*。绑定写入 VM 的持久配置，**重启该 VM 后** vGPU 就会作为一块显卡出现在 VM 里。

   > **操作说明（重要）**：
   > - attach / detach 写的是 VM 持久配置，**不需要**先关闭 VM 就能操作。
   > - 但 mdev 不支持热插拔，**必须关机再开机**（不是重启）后，vGPU 才会出现在 VM 里（或才被彻底释放）。
   > - 一个 vGPU 同一时间只能绑定到一个 VM。

5. **宿主机同时用 GPU**：MERGED 驱动下，宿主机 docker 仍可通过 `--gpus all` 使用同一张卡（docker 需已配置 nvidia 运行时，插件会以合并方式写入配置，不覆盖已有 `daemon.json`）。

### Intel i915 SR-IOV

1. 在 **① Drivers** 点击 *Install Intel i915 SR-IOV Driver*。
2. 在 **③ Intel i915 SR-IOV** 设置 VF 数量，VFs 会自动绑定到 `vfio-pci`。
3. 把页面显示的启动参数加到 **设置 → Boot** 的 syslinux append 行。
4. 在 VM 里直通 VF（`00:02.1` / `00:02.2`…），**切勿直通 PF（`00:02.0`）**。

---

## 驱动来源

插件从两个独立项目下载驱动包（GitHub Actions 云编译），按当前内核版本匹配：

- NVIDIA：[hellomrli/my-nvidia-vgpu-driver](https://github.com/hellomrli/my-nvidia-vgpu-driver)
  - Release tag = 内核版本，每个 tag 下**双系列并存**：
    - 16.x：`nvidia-535.309.01-<内核>-Unraid-<构建号>.txz`
    - 19.x：`nvidia-580.178.05-<内核>-Unraid-<构建号>.txz`
  - 下载、更新检查、安装与热更新都按所选系列过滤，不会把 16.x 用户"升级"到 19.x
- Intel：[hellomrli/my-i915-sriov-driver](https://github.com/hellomrli/my-i915-sriov-driver)
  - Release tag = 内核版本，资产 `i915-sriov-<版本>-<内核>-Unraid-<构建号>.txz`

如果当前内核还没有对应驱动包，在对应驱动仓库手动运行云编译工作流即可（接受任意 Unraid 内核版本）。

---

## 注意事项

- NVIDIA vGPU 设备（mdev）每次开机自动恢复
- vGPU 绑定到 VM 后需**关机再开机**生效（mdev 不能热插拔）
- 两个系列不能同时加载，切换系列 = 卸载当前驱动后安装另一系列（或直接 Update Driver 切换）
- 普通 RTX / GTX 游戏卡需要 unlock 且**仅 16.x 支持**（见顶部"支持的 GPU"）
- Intel 直通时只能直通 **VF**（00:02.x），绝不能直通 PF（00:02.0）
