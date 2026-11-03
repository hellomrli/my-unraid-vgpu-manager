# 使用指南

[返回安装入口与项目说明](../README.zh-CN.md)

## 架构

```text
┌────────────────────────────────────────────────────────────────────┐
│  Unraid 界面   设置 → Unraid vGPU 管理器                           │
│  驱动管理 ｜ NVIDIA 显卡 ｜ Intel SR-IOV                           │
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

## 更新、卸载与冲突

更新与卸载同样走 Unraid 的插件管理器。卸载会移除界面、更新钩子与定时任务，并调用 `rc.vgpu stop`，但不会强制关闭正在运行的虚拟机；你的设置与驱动缓存保留在启动盘上，重启后驱动退出。

安装驱动前，请卸载管理同一驱动的其他插件并重启。插件会拒绝 Nvidia-Driver、i915-sriov、旧 vgpu-driver 等已知冲突；仅监控 GPU 的 intel-gpu-top 不属于冲突插件。

## 快速开始

打开 **设置 → Unraid vGPU 管理器**，页面分为三个标签：

| 标签页 | 内容 |
|---|---|
| 驱动管理 | 驱动状态、可更新版本与更新按钮、安装与卸载、定时检查设置 |
| NVIDIA 显卡 | 驱动系列、授权、模块、unlock、vGPU 配置档、设备管理与虚拟机绑定 |
| Intel SR-IOV | i915/xe 状态、VF 数量、直通状态，以及需要添加的启动参数 |

NVIDIA 的最短路径是：在驱动管理页装上驱动，在「授权与模块」里设置授权服务器，从配置档列表添加 vGPU，再绑定给一台虚拟机。Intel 则是：装上驱动、设置 VF 数量、把页面给出的参数加入当前 Unraid 启动项，然后把 **VF**（不是 PF）直通给虚拟机。

推荐写入启动项的只有 `intel_iommu=on iommu=pt`。i915/xe 的 `max_vfs`、`force_probe`、`xelp_enable_ccs` 以及 i915 的 `enable_guc` 由插件的 modprobe 配置统一管理。请移除重复参数，并从全局启动黑名单中移除两种驱动，然后重启；Intel 标签页会提示冲突。插件仅对所管理的 PCI 设备 ID 排除另一驱动的探测，不全局卸载或禁用另一驱动。**首次安装 i915** 时仍可在原生驱动忙碌时延后激活，不强制解绑控制台；已启用 SR-IOV 栈的更新仍会在设备被占用时中止。

## 选择 i915 或 xe

**默认且推荐使用 i915；xe 为实验性驱动。** 架构较新或上游提交较多，不代表在你的 SR-IOV 场景中必然更快、更稳定。两个包均来自 [strongtz 社区的实验性移植](https://github.com/strongtz/i915-sriov-dkms)，不保证生产环境稳定性。截至 2026-11-03，该项目明确警告其 xe 模块不支持 MTL/LNL；不能把此限制推广为 Linux 主线 xe 的情况，也不保证这些平台能够使用 i915 SR-IOV。

在**驱动管理 > Intel SR-IOV 驱动**选择。已有安装和缺省配置保持 i915（`intel_driver=i915`），插件升级不会自动改用 xe。

1. 更换驱动或首次安装 xe 时，只下载、校验独立包并准备下次启动配置，保留回滚缓存；**不替换运行中的驱动包、不卸载模块、不停止虚拟机/容器，也不改变当前 VF**。若已准备另一个 Unraid 内核，其对应驱动也必须预先缓存，才能排队切换。
2. 测试前关闭相关 GPU 虚拟机/容器的自动启动，再重启。新驱动在重启后、阵列启动前从缓存离线激活。保存的 boot ID 可区分重启与同一次启动中的插件升级；后者不会提前执行切换。驱动失败不保证 Unraid 会取消工作负载自动启动。
3. 激活后核对实际加载的 PF 驱动和 VF 直通，再启动 GPU 工作负载。配置选择、磁盘模块与实际加载版本分别显示；失败时检查 `/var/log/my-unraid-vgpu-manager-boot.log` 和 `dmesg`。
4. 重启前可取消切换，保持运行中的驱动不变。重启后失败则选择 i915 并再次重启回滚；激活失败会保留待处理选择和缓存。不要手动同时安装两个包，它们共享 `intel_sriov_compat`，必须互斥。

配置文件沿用 `/boot/config/modprobe.d/my-unraid-vgpu-manager-i915.conf` 以兼容旧版，内容可以管理任一所选驱动。保存 CCS/VF 设置不会覆盖待重启的驱动选择。xe 使用 `force_probe=<设备 ID>` 和 `max_vfs`，不传入 i915 的 `enable_guc`。切换前请移除 `/boot/config/go` 中手动加载 Intel 驱动的命令。多个 PF 具有相同设备 ID 时，`force_probe` 无法仅指定一个 BDF，插件会拒绝切换；不会强制解绑其他驱动或控制台。

驱动状态会把已安装版本与可用版本并排显示，并同时给出两边的构建号。启用每日检查后，打开页面就会查询或复用最近的结果；也可以按检查按钮立即查询。超过 35 秒没有应答会提示超时并恢复检查按钮，方便重试。

## 驱动更新与 CCS0

点击“更新驱动”并确认后，插件先下载并校验，再根据活动 VM 的 mdev/PCI 设备和 Docker 的 GPU 请求、设备/目录映射识别相关工作负载。VM 正常关机，等待约两分钟仍未退出则中止，不强制断电；容器使用 `docker stop --time 30`（超时可能被 Docker 强制停止）。未识别出的宿主进程占用仍会阻止驱动卸载，不会强杀进程或停掉整个 Docker/libvirt 服务。已停止的 VM 和容器在更新后**需要手动启动**；失败时也请查看日志确认哪些已停止。定时检查和内核预下载不会停止工作负载。

Intel 标签页提供独立的 **CCS0 开关**，对支持 `xelp_enable_ccs` 的 i915/xe 模块**默认启用**；上游默认值可能不同，例如 i915 自 `2026.09.16` 起默认关闭。保存不会覆盖待重启的驱动选择、改变运行中的 VF 或停止虚拟机，**重启或成功重新加载支持该参数的驱动后生效**。不支持的模块不会收到未知参数，偏好仍保留供支持的版本使用。请移除启动项中手动配置的 i915/xe CCS 参数，避免两份配置冲突。

## 驱动系列与硬件

| 系列 | 当前包版本 | 选择建议 |
|---|---|---|
| 16.x | 535.309.01 | Pascal 世代（P4、P40、P100 等）以及需要 `vgpu_unlock` 的设备；16.x 已结束维护 |
| 19.x | 580.178.05 | 该分支支持的较新 GPU；新安装且硬件同时出现在两个系列列表时，推荐 19.x |

硬件提示来自各分支 `vgpuConfig.xml` 中的 PCI ID，它既不是 NVIDIA 的认证结论，也不代表真机验证过。较新的架构可能还要求先启用 NVIDIA SR-IOV，而本插件不会替你运行 `sriov-manage`。本仓库已验证的硬件仅限于 Tesla P4，不能因为它在 P4 上可用就推断其他型号同样可用。

消费卡解锁的内核补丁只构建在 16.x 系列里，因为它的 config magic 是 535 专属的。上游 `vgpu_unlock` 覆盖 Maxwell、Pascal 与 Turing（GTX 9/10、RTX 20 系列），RTX 30 属实验性支持，RTX 40 不支持。原生支持 vGPU 的卡（例如 P4）本来就不需要 unlock。

## Unraid 升级前的驱动准备

Unraid 把新系统写入启动盘后，插件读取 `/boot/bzimage` 中**实际准备启动的内核版本**，与当前 `uname -r` 比较。系统更新钩子会立即检查，另有每 5 分钟一次的兜底覆盖其他更新方式。准备选项从 Unraid 的更新通知进入，普通打开插件页面时不显示。

| 当前启用的驱动 | 升级 Unraid 时的行为 |
|---|---|
| 未启用任何 GPU 驱动 | 不查询、不下载；需要时再手动安装 |
| 只启用 NVIDIA vGPU | 只为新内核检查并下载 NVIDIA 驱动，Intel 不参与 |
| 只启用 Intel SR-IOV | 为新内核准备所选 i915/xe 包（待切换选择优先），NVIDIA 不参与 |
| 两者均启用 | 分别准备，全部通过校验后才报告就绪 |
| 缺包、网络错误或校验失败 | 报告未就绪，并保留已有驱动包，便于检查或回退 |

预下载保持当前已安装的 NVIDIA 系列，535.x 或 16.x 不会因为升级系统就变成 580.x 或 19.x；已固定的驱动版本同样被尊重，不会被悄悄替换。它只保存文件：当前运行的内核继续用原来的驱动，也不会触发重启。

启动恢复阶段不联网获取授权：服务端地址、端口和证书设置一致时复用已保存的令牌，缺少令牌则等阵列启动后在后台请求。本机 VM / 容器中的授权服务器不可达时，不会因此阻塞阵列启动。

## 缓存与包来源

NVIDIA 和 i915 使用**完整内核版本**作为 Release tag，例如 `6.18.58-Unraid`；xe 在同一个 Intel 仓库使用独立的 `xe-6.18.58-Unraid` tag：

- NVIDIA：[hellomrli/my-nvidia-vgpu-driver](https://github.com/hellomrli/my-nvidia-vgpu-driver)
- Intel：[hellomrli/my-i915-sriov-driver](https://github.com/hellomrli/my-i915-sriov-driver)，基于 [strongtz/i915-sriov-dkms](https://github.com/strongtz/i915-sriov-dkms) 构建

Intel 包名分别为 `i915-sriov-<日期>-<内核>-<构建号>.txz`、`xe-sriov-<日期>-<内核>-<构建号>.txz`，缓存及更新检查不会互相替代。找不到所选内核的匹配包时，选择会安全失败并保持现有驱动。

Intel 构建仓库只维护以下来源合并去重后的内核：当前正式版、当前公开 beta/RC（从对应 Release notes 读取内核），以及 ich777 的最新备编内核。旧资产继续保留，但退出这三个来源的历史内核不再更新驱动。2026-11-03 对应集合为 `6.18.58-Unraid`（正式版 7.3.4、测试版 7.4.0-rc.2）和 `6.18.60-Unraid`（ich777 备编）。

驱动包缓存在 `/boot/config/plugins/my-unraid-vgpu-manager/packages/<kernel>/`。手动放置包时，需要同时提供对应的 `.txz.md5`（如同时存在 `.txz.sha256`，也必须一致）；插件按文件内容校验，不执行也不信任 checksum 文件里写的路径。包名必须同时匹配内核与驱动系列。

在线下载校验 GitHub 上传时计算的 SHA-256 `digest`，并将其保存为 `.txz.sha256`，供离线恢复使用。旧资产没有 digest 时，仍兼容 MD5 与可选的 SHA-256 校验文件。显式刷新会先比对 API digest，再决定是否复用同名缓存；API 额度用尽会单独提示。这些检查可发现内容变化，但不等同于发布者签名。

成功下载、安装和显式本地恢复后会清理过时缓存。保留运行内核、待启动内核、记录的上一次运行内核、可读取的 `/boot/previous/bzimage` 内核，以及最近一次预下载的内核；各内核按驱动类型和 NVIDIA 系列保留最新的有效构建，同时保护已安装包、固定版本及本次请求的包。下载和安装期间持有缓存锁，更新失败不会删除已安装驱动的缓存。无法读取待启动内核时跳过跨内核清理；不删除无法识别的文件。开机 `ensure` 不额外执行此清理，避免阵列启动时增加 U 盘读取。

插件自身使用 `my-unraid-vgpu-manager-2026.11.03-x86_64-1.txz` 这样的 Slackware 规范包名，清单同时提供 MD5 / SHA-256。Unraid 通过 [README 安装入口](../README.zh-CN.md#安装插件)中的 `.plg` 地址，从仓库的 `packages/` 目录下载对应安装包，不需要插件 GitHub Release。安装时仅迁移精确匹配的旧包记录，并在新包安装成功后清理旧插件压缩包。

如果新内核还没有对应的包，可以在驱动仓库里构建。插件不会把为其他内核构建的包装上去，也不会把下载失败说成驱动已更新。

## 开发与验证

```bash
# 修改源码或版本号后重建包，并刷新 .plg 的 MD5 / SHA-256
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
| 修复记录与验证边界 | [docs/REVIEW.md](REVIEW.md) |
| 插件清单与变更日志 | [my-unraid-vgpu-manager.plg](../my-unraid-vgpu-manager.plg) |
| NVIDIA 驱动包 | [hellomrli/my-nvidia-vgpu-driver](https://github.com/hellomrli/my-nvidia-vgpu-driver) |
| Intel 驱动包 | [hellomrli/my-i915-sriov-driver](https://github.com/hellomrli/my-i915-sriov-driver) |
| Intel SR-IOV 上游 | [strongtz/i915-sriov-dkms](https://github.com/strongtz/i915-sriov-dkms) |

## 许可证

本项目基于 [GNU 通用公共许可证第 3 版](../LICENSE)发布。
