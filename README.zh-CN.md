<p align="center">
  <img src="./source/usr/local/emhttp/plugins/my-unraid-vgpu-manager/images/large.png" width="200" alt="my-unraid-vgpu-manager 插件图标">
</p>

<h1 align="center">my-unraid-vgpu-manager</h1>

<p align="center">一个 Unraid 插件，在一个设置页面里管理 NVIDIA vGPU 与 Intel i915 SR-IOV：驱动安装与更新、vGPU 设备与虚拟机绑定，以及 Unraid 升级前的驱动预下载。</p>

<p align="center">
  <a href="./README.md">English</a> | <a href="./README.zh-CN.md">简体中文</a>
</p>

<p align="center">
  <a href="https://github.com/hellomrli/my-unraid-vgpu-manager/actions/workflows/check.yml"><img src="https://github.com/hellomrli/my-unraid-vgpu-manager/actions/workflows/check.yml/badge.svg" alt="校验工作流状态"></a>
  <a href="https://unraid.net/"><img src="https://img.shields.io/badge/Unraid-6.11.5%2B-orange" alt="需要 Unraid 6.11.5 或更新版本"></a>
</p>

## 这个插件解决什么

在 Unraid 上把一块显卡同时分给虚拟机和容器，通常意味着一串重复劳动：手工拼内核模块、为每一个驱动构建匹配精确的 Unraid 内核版本，系统一升级还得重来一遍。这个插件把这些事收在一个页面里完成——安装和更新驱动包、创建 vGPU 设备并绑定给虚拟机，以及在你重启进新内核之前把驱动准备好。

NVIDIA vGPU 与 Intel i915 SR-IOV 是两套独立的栈，驱动也来自两个仓库，插件按这个事实分别管理：各自有安装状态、各自的更新检查和各自的缓存。只有你明确启用的驱动才会被检查和准备。

## 核心亮点

| 亮点 | 说明 |
|---|---|
| 两套 GPU 栈同页管理 | 驱动管理、NVIDIA 显卡、Intel i915 SR-IOV 三个标签页同属一个设置入口，界面跟随 Unraid 自身语言，没有插件专用的语言切换控件 |
| NVIDIA 合并驱动 | 同一个包内同时包含 vGPU 宿主驱动与标准 NVIDIA 驱动，显卡既能给虚拟机用，也能给容器用（`--gpus all`），而不是只能二选一 |
| 两套驱动系列按硬件匹配 | 16.x LTS（535.309.01）面向 Pascal 世代（P4/P40/P100 等），19.x LTS（580.178.05）面向 T4 及更新型号；插件读取已安装型号后给出匹配的系列 |
| 驱动热更新 | 没有虚拟机占用 vGPU 时，新驱动包可直接装到当前运行的内核上，无需重启 |
| 升级前预下载 | 读取 `/boot/bzimage` 中实际准备启动的内核，只为已启用的驱动下载对应包；全程不安装包、不加载也不卸载模块 |
| 开机恢复不依赖网络 | 已启用的驱动与 vGPU 设备在每次开机时从本地已校验的包恢复，只靠启动盘也能带着 GPU 起来 |

## 架构

```text
┌────────────────────────────────────────────────────────────────────┐
│  Unraid 界面   设置 → Unraid vGPU 管理器                           │
│  驱动管理 ｜ NVIDIA 显卡 ｜ Intel i915 SR-IOV                      │
└───────────────┬────────────────────────────────────────────────────┘
               │
               ▼
┌────────────────────────────────────────────────────────────────────┐
│  PHP   web.php · actions.php · kernel.php                          │
└───────────────┬────────────────────────────────────────────────────┘
               │
               ▼
┌────────────────────────────────────────────────────────────────────┐
│  Shell   rc.vgpu · common.sh · download.sh                         │
│          update-check.sh · upgrade-check.sh                        │
└───────────────┬────────────────────────────────────┬───────────────┘
               │                                    │
               ▼                                    ▼
┌───────────────────────────┐      ┌─────────────────────────────────┐
│  /boot/config/plugins/    │      │  GitHub Release 资产            │
│    my-unraid-vgpu-manager/│      │  my-nvidia-vgpu-driver          │
│    packages/<kernel>/     │      │  my-i915-sriov-driver 构建      │
└───────────────┬───────────┘      └─────────────────────────────────┘
               │
               ▼
┌────────────────────────────────────────────────────────────────────┐
│  内核模块与 vGPU 设备 → 虚拟机、Docker（--gpus all）               │
└────────────────────────────────────────────────────────────────────┘
```

页面负责渲染界面，`kernel.php` 读取下次启动所用的内核，Shell 层承担所有涉及软件包与模块的动作。驱动包存放在启动盘的 `/boot/config/plugins/my-unraid-vgpu-manager/packages/<kernel>/`，开机恢复与升级前预下载都靠它避免重复下载。

## 使用示例

安装插件本身不会安装任何 GPU 驱动。一次完整的首次使用，都在 Unraid 界面里完成：

```text
# 1. Plugins -> Install Plugin，填入插件地址
https://github.com/hellomrli/my-unraid-vgpu-manager/raw/master/my-unraid-vgpu-manager.plg

# 2. 设置 → Unraid vGPU 管理器 → 驱动管理
#    选择与显卡匹配的系列并安装 NVIDIA 驱动。
#    首次安装可以复用本地已校验的包。

# 3. 驱动管理页按需启用每日更新检查。
#    检查只读取 Release 元数据，不下载也不安装任何东西。

# 4. NVIDIA 显卡 → 授权与模块
#    设置授权服务器、端口与 FeatureType，然后保存。

# 5. NVIDIA 显卡页选择显卡与配置档，生成 UUID，添加 vGPU。

# 6. NVIDIA 显卡页把设备绑定到目标虚拟机。
#    绑定是持久配置：关闭虚拟机后重新启动，
#    设备才会在一次真正的冷启动中挂上。
```

预期结果：vGPU 出现在设备列表里并带有配置档与 UUID，虚拟机启动时设备已挂载，且因为配置写在启动盘上，重启后依然存在。

动手前有两件事值得先知道：

- 运行中的虚拟机仍占用的设备会一直显示为被占用。需要先在虚拟机配置里解绑，再关闭虚拟机；占用中的设备无法删除或停止。
- 要切换 NVIDIA 驱动系列，先停掉所有使用该 GPU 的虚拟机与容器，在「授权与模块」里选择目标系列并保存，再用那里的切换按钮。普通的驱动更新会留在当前已安装的系列内。

## 快速安装

需要 Unraid 6.11.5 或更新版本，以及一块受支持的显卡。在 Unraid 界面里安装：

```text
Plugins -> Install Plugin
https://github.com/hellomrli/my-unraid-vgpu-manager/raw/master/my-unraid-vgpu-manager.plg
```

更新与卸载同样走 Unraid 的插件管理器。卸载会移除界面、更新钩子与定时任务，并调用 `rc.vgpu stop`，但不会强制关闭正在运行的虚拟机；你的设置与驱动缓存保留在启动盘上，重启后驱动退出。

## 快速开始

打开 **设置 → Unraid vGPU 管理器**，页面分为三个标签：

| 标签页 | 内容 |
|---|---|
| 驱动管理 | 驱动状态、可更新版本与更新按钮、安装与卸载、定时检查设置 |
| NVIDIA 显卡 | 驱动系列、授权、模块、unlock、vGPU 配置档、设备管理与虚拟机绑定 |
| Intel i915 SR-IOV | VF 数量、直通状态，以及需要添加的启动参数 |

NVIDIA 的最短路径是：在驱动管理页装上驱动，在「授权与模块」里设置授权服务器，从配置档列表添加 vGPU，再绑定给一台虚拟机。Intel 则是：装上驱动、设置 VF 数量、把页面给出的参数加入当前 Unraid 启动项，然后把 **VF**（不是 PF）直通给虚拟机。

驱动状态会把已安装版本与可用版本并排显示，并同时给出两边的构建号。启用每日检查后，打开页面就会查询或复用最近的结果；也可以按检查按钮立即查询。超过 35 秒没有应答会提示超时并恢复检查按钮，方便重试。

## 驱动系列与硬件

| 系列 | 当前包版本 | 选择建议 |
|---|---|---|
| 16.x | 535.309.01 | Pascal 世代（P4、P40、P100 等）以及需要 `vgpu_unlock` 的设备；16.x 已结束维护 |
| 19.x | 580.178.05 | 该分支支持的较新 GPU；新安装且硬件同时出现在两个系列列表时，推荐 19.x |

硬件提示来自各分支 `vgpuConfig.xml` 中的 PCI ID，它既不是 NVIDIA 的认证结论，也不代表真机验证过。较新的架构可能还要求先启用 NVIDIA SR-IOV，而本插件不会替你运行 `sriov-manage`。本仓库已验证的硬件仅限于 Tesla P4，不能因为它在 P4 上可用就推断其他型号同样可用。

消费卡解锁的内核补丁只构建在 16.x 系列里，因为它的 config magic 是 535 专属的。上游 `vgpu_unlock` 覆盖 Maxwell、Pascal 与 Turing（GTX 9/10、RTX 20 系列），RTX 30 属实验性支持，RTX 40 不支持。原生支持 vGPU 的卡（例如 P4）本来就不需要 unlock。

## Unraid 升级前的驱动准备

Unraid 把新系统写入启动盘后，插件读取 `/boot/bzimage` 中**实际准备启动的内核版本**，与当前 `uname -r` 比较。系统更新钩子会立即检查，另有每分钟一次的兜底覆盖其他更新方式。准备选项从 Unraid 的更新通知进入，普通打开插件页面时不显示。

| 当前启用的驱动 | 升级 Unraid 时的行为 |
|---|---|
| 未启用任何 GPU 驱动 | 不查询、不下载；需要时再手动安装 |
| 只启用 NVIDIA vGPU | 只为新内核检查并下载 NVIDIA 驱动，Intel 不参与 |
| 只启用 Intel i915 SR-IOV | 只为新内核检查并下载 Intel 驱动，NVIDIA 不参与 |
| 两者均启用 | 分别准备，全部通过校验后才报告就绪 |
| 缺包、网络错误或校验失败 | 报告未就绪，并保留已有驱动包，便于检查或回退 |

预下载保持当前已安装的 NVIDIA 系列，535.x 或 16.x 不会因为升级系统就变成 580.x 或 19.x；已固定的驱动版本同样被尊重，不会被悄悄替换。它只保存文件：当前运行的内核继续用原来的驱动，也不会触发重启。

## 缓存与包来源

两个驱动仓库都按**完整内核版本**发布 Release tag，例如 `6.18.47-Unraid`：

- NVIDIA：[hellomrli/my-nvidia-vgpu-driver](https://github.com/hellomrli/my-nvidia-vgpu-driver)
- Intel：[hellomrli/my-i915-sriov-driver](https://github.com/hellomrli/my-i915-sriov-driver)，基于 [strongtz/i915-sriov-dkms](https://github.com/strongtz/i915-sriov-dkms) 构建

驱动包缓存在 `/boot/config/plugins/my-unraid-vgpu-manager/packages/<kernel>/`。手动放置包时，需要同时提供对应的 `.txz.md5`；插件按文件内容校验，不执行也不信任 checksum 文件里写的路径。包名必须同时匹配内核与驱动系列。

如果新内核还没有对应的包，可以在驱动仓库里构建。插件不会把为其他内核构建的包装上去，也不会把下载失败说成驱动已更新。

## 开发与验证

```bash
# 修改源码或版本号后重建包，并刷新 .plg 的 MD5
python3 scripts/build-plugin.py

# PHP / Bash / JS / JSON / XML、隔离的生命周期回归测试、包与源码一致性
./scripts/check.sh

# 浏览器交互验证（需要 Chrome / Chromium）
npm ci
python3 tests/browser_server.py
```

检查依赖 PHP CLI（含 SimpleXML）、Python 3.9+、Node.js、ShellCheck、jq、bubblewrap 与 GNU coreutils，与 Unraid 自带的环境一致。回归测试在无网络、无宿主 GPU 的隔离文件系统中运行，从不调用宿主的驱动管理命令。浏览器测试用同一套隔离文件系统配合本地 HTTP 服务，覆盖表单、跟随 Unraid 语言、驱动版本提示、通知入口、移动布局，以及无响应、超时后重试和迟到响应的处理。

CI 在 `ubuntu-24.04` 上执行同样的命令，并把抓取到的界面截图作为工作流产物上传。

## 项目链接

| 主题 | 链接 |
|---|---|
| 修复记录与验证边界 | [REVIEW.md](REVIEW.md) |
| 插件清单与变更日志 | [my-unraid-vgpu-manager.plg](my-unraid-vgpu-manager.plg) |
| NVIDIA 驱动包 | [hellomrli/my-nvidia-vgpu-driver](https://github.com/hellomrli/my-nvidia-vgpu-driver) |
| Intel 驱动包 | [hellomrli/my-i915-sriov-driver](https://github.com/hellomrli/my-i915-sriov-driver) |
| Intel SR-IOV 上游 | [strongtz/i915-sriov-dkms](https://github.com/strongtz/i915-sriov-dkms) |

## 许可证

本项目基于 [GNU 通用公共许可证第 3 版](./LICENSE)发布。
