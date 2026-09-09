# my-unraid-vgpu-manager

Unraid GPU 虚拟化管理插件，在一个设置页面管理 **NVIDIA vGPU** 和 **Intel i915 SR-IOV**。界面语言跟随 Unraid，提供驱动安装与更新、vGPU 设备与虚拟机绑定，以及 **Unraid 升级前的驱动预下载**。

## 安装与界面

在 Unraid 的 **Plugins → Install Plugin** 中填写：

```text
https://github.com/hellomrli/my-unraid-vgpu-manager/raw/master/my-unraid-vgpu-manager.plg
```

打开 **设置 → Unraid vGPU Manager**。保留原有三个标签页、紧凑表格和表单布局。Unraid 使用中文时显示简体中文，英文时显示英文；没有单独的语言切换控件，旧插件语言偏好不再生效。

| 标签页 | 内容 |
|---|---|
| 驱动管理 / Drivers | 驱动状态、可更新版本与更新按钮、安装 / 卸载、定时检查设置 |
| NVIDIA 显卡 / NVIDIA GPU | 驱动系列、授权、模块、unlock、vGPU 配置档、设备管理、虚拟机绑定 |
| Intel i915 SR-IOV | VF 数量、直通状态、启动参数 |

**首次安装插件不会自动安装 GPU 驱动。** 请在“驱动管理”中按需安装 NVIDIA 或 Intel 驱动；插件会记录用户选择安装的驱动，用于开机恢复和系统升级准备。卸载某个驱动会取消它的自动恢复和预下载。

## 驱动版本更新

“驱动状态”中发现更新时，会显示 **当前版本 → 可更新版本**，同时显示两边的构建号，并提供“更新驱动”按钮。NVIDIA 与 Intel 分别检查，同版本的新构建也能识别；NVIDIA 保持当前已安装的系列。

启用每天检查更新后，打开页面会异步获取或复用最近的检查结果，也可以点击“检查驱动更新”立即查询。这个检查只读取 Release 信息，不下载或安装驱动。检查设有 35 秒超时，网络或接口无响应时显示超时提示并恢复检查按钮；后台已有检查在运行时会提示稍后重试。检查失败会隐藏驱动状态中的旧更新按钮，不能据此判断驱动已是最新；安装完成、卸载驱动或更换内核后，旧更新提示失效。未启用的驱动不查询更新。

**2026.09.09a 修复了网页检查卡在 Unraid 认证阶段的问题。** 旧版直接提交 `FormData`，在实测主机上会因 multipart 请求而等待到超时，即使 GitHub 查询和检查脚本都能很快完成。新版检查与普通表单均使用 Unraid 常用的 URL 编码；从旧版本更新插件后重新打开管理页即可加载修复。

## Unraid 升级前的驱动准备

Unraid 更新写入启动盘后，插件读取 `/boot/bzimage` 中**实际准备启动的内核版本**，与当前 `uname -r` 比较。系统更新完成钩子会立即检查，另有每分钟一次的定时检查覆盖其他更新方式。通过 **Unraid 更新通知**进入准备选项，查看结果或重试；普通打开插件页面时不显示升级准备区域。重启完成后，旧通知也不会继续显示准备选项。

| 当前使用情况 | 更新 Unraid 时的行为 |
|---|---|
| 未启用任何 GPU 驱动 | 不查询、不下载驱动，需要时由用户手动安装 |
| 只启用了 NVIDIA vGPU | 只检查 / 下载新内核的 NVIDIA 驱动，Intel 不参与 |
| 只启用了 Intel i915 SR-IOV | 只检查 / 下载新内核的 Intel 驱动，NVIDIA 不参与 |
| 两者均启用 | 分别准备两个驱动，全部通过校验后才显示“已就绪” |
| 没有对应驱动包、网络错误或校验失败 | 提示“未就绪”，保留已有驱动包，方便检查或回退 |

- 默认开启“系统更新后自动准备已启用的驱动”，可在升级通知打开的准备选项中关闭。关闭后仍会提醒重启前同步驱动，但不自动下载，可在通知入口手动准备。此选项与“每天检查驱动更新”相互独立。
- NVIDIA 预下载**保持当前已安装的系列**，例如 535.x / 16.x 不会因升级系统而变成 580.x / 19.x。已固定的 NVIDIA 驱动版本也会被尊重，缺包时不会自动改用其他版本。
- 预下载只保存文件，**不替换当前运行内核的驱动、不重启系统**。确认 Unraid 更新完成且已启用的驱动全部就绪后，再重启。
- 新内核下会从本地已校验缓存恢复用户已启用的驱动，然后在 Docker / libvirt 和 VM 自启动前加载模块、恢复 vGPU。开机恢复不访问网络。
- 新旧内核、NVIDIA 两个系列和 Intel 的缓存互不删除。缓存会占用启动 U 盘空间，可在确认不再需要回退后手动清理旧内核目录。
- 缺包会每 30 分钟重试一次；已就绪缓存每小时复核。可随时点击“检查并下载已启用的驱动”立即重试。
- 这是重启前的准备和提醒，不会拦截 Unraid 的重启按钮。

通知入口使用启动镜像中检测到的目标内核，插件不根据 changelog 中的历史条目猜测内核版本。

## NVIDIA 支持与使用

驱动由 [my-nvidia-vgpu-driver](https://github.com/hellomrli/my-nvidia-vgpu-driver) 提供，使用 Merged 包，同时包含 vGPU 和宿主 CUDA / Docker 所需组件。

| 系列 | 当前包版本 | 选择建议 |
|---|---|---|
| 16.x | 535.309.01 | Pascal（P4 / P40 / P100 / P6 等）及需要 vgpu_unlock 的支持设备；16.x 已结束维护 |
| 19.x | 580.178.05 | 支持该分支的较新 GPU；新安装且硬件同时出现在两系列列表时，默认推荐 19.x |

硬件提示来自各分支 `vgpuConfig.xml` 的 PCI ID，**不是完整的 NVIDIA 认证或实机验证结论**。新架构可能还要求先启用 NVIDIA SR-IOV；本插件目前不自动运行 `sriov-manage`。项目已有的 Tesla P4 验证不能推导为其他 GPU 也已验证。

消费卡解锁只在 **16.x** 构建内包含内核补丁。上游 vgpu_unlock 支持 Maxwell / Pascal / Turing（GTX 9/10、RTX 20），RTX 30 属实验性支持，RTX 40 不支持；消费卡解锁仍需真机验证。原生支持 vGPU 的卡通常不需要 unlock。

使用步骤：

1. 在“驱动管理”选择系列并安装。首次安装可复用校验通过的本地包；“更新驱动”会查询 GitHub，包括驱动版本相同、构建号变大的更新。
2. 在“NVIDIA 显卡 → 授权与模块”设置授权服务器、端口和 FeatureType；P4 的 Q 系列档位通常用 `2`，B 系列用 `0`。FastAPI-DLS token 会在服务器或端口变化时重新获取。自签名 HTTPS 可选择不验证证书；有有效证书时建议启用验证。
3. 从可用配置档中选择显卡和显存档位，生成 UUID 并添加 vGPU。配置保存在启动盘，开机自动恢复。
4. 在“将 vGPU 绑定到虚拟机”中绑定目标 VM。写入的是持久配置，**需关闭虚拟机后重新启动**；在虚拟机内部重启不等同于冷启动。
5. 解绑运行中 VM 的设备后，页面仍会显示它的实际占用。必须关闭 VM 后才能完全释放；正在占用的设备不能删除或停止。
6. 更新或切换驱动系列前，停止使用 GPU 的 VM 和容器。普通更新按钮保持当前系列；需要切换时，在“授权与模块”选择并保存目标系列，再使用该处的切换按钮。切换宿主驱动分支时，还需核对 guest 驱动兼容性。

宿主 Docker GPU runtime 以合并方式配置，保留现有 `daemon.json` 的其他选项。若 Docker 已在运行，配置变化可能需要重启 Docker 服务后才被采用。`profile_override.toml` 的底层工具日志保持原始内容，方便排错。

## Intel i915 SR-IOV

使用 [strongtz/i915-sriov-dkms](https://github.com/strongtz/i915-sriov-dkms) 的配套构建。**不是所有“Intel 第 8 代及之后”的核显都支持 SR-IOV**；请核对上游支持的设备和内核。目标设备包括 Alder Lake-HX 的 UHD 770，实际可创建的 VF 数量以 `sriov_totalvfs` 为准。

1. 在“驱动管理”按需安装 Intel 驱动。
2. 在 Intel 页面设置 VF 数量。只有成功应用后才保存；重复应用相同数量不会重建 VF。
3. 在 BIOS / UEFI 开启 IOMMU，并将页面提供的参数加入当前 Unraid 启动项：

   ```text
   intel_iommu=on i915.enable_guc=3 i915.max_vfs=7 module_blacklist=xe
   ```

4. 将绑定到 `vfio-pci` 的 **VF** 分配给 VM，**不要直通 PF**。插件从 PF 的 `virtfn*` 链接识别 VF，支持不位于根总线的设备。

本版使用独立的 `my-unraid-vgpu-manager-i915.conf`，保留用户自己的模块配置和 `go` 脚本。旧版曾向 `i915.conf` 写入的 blacklist 没有所有权标记，卸载时不会擅自删除；如果以后不再使用 SR-IOV，请检查这些旧设置。

## 驱动缓存与来源

两个驱动仓库均按**完整内核版本**发布 Release tag，例如 `6.18.47-Unraid`：

- NVIDIA：[hellomrli/my-nvidia-vgpu-driver](https://github.com/hellomrli/my-nvidia-vgpu-driver)
  - `nvidia-535.309.01-6.18.47-Unraid-2.txz`
  - `nvidia-580.178.05-6.18.47-Unraid-1.txz`
- Intel：[hellomrli/my-i915-sriov-driver](https://github.com/hellomrli/my-i915-sriov-driver)
  - `i915-sriov-202608121-6.18.47-Unraid-1.txz`

缓存路径：`/boot/config/plugins/my-unraid-vgpu-manager/packages/<内核数字版本>/`。手动放置包时必须同时提供对应的 `.txz.md5`；插件按文件内容校验，不执行 checksum 文件内的路径。包名必须完整匹配内核和驱动系列。

若还没有新内核对应的包，可在驱动仓库运行构建工作流。插件不会把旧内核包强行安装到新内核，也不会声称下载失败的驱动已经更新。

卸载插件会移除界面、更新钩子与定时任务，保留用户设置和驱动缓存；已加载的驱动在重启后退出。卸载单个驱动后，其启用状态变为关闭。

## 开发与验证

```bash
# 修改源码或版本号后生成包，同时更新 .plg 的 MD5
python3 scripts/build-plugin.py

# PHP / Bash / JS / JSON / XML、隔离回归测试、包与源码一致性
./scripts/check.sh

# 浏览器交互验证（需要 Chrome / Chromium）
npm ci
python3 tests/browser_server.py
```

检查依赖：PHP CLI + SimpleXML、Python 3.9+、Node.js、ShellCheck、jq、bubblewrap、GNU coreutils（与 Unraid 一致；默认使用 uutils 的开发机需提供 `gnutimeout`）。回归测试在无网络、无宿主 GPU 的隔离文件系统中运行，不调用宿主的驱动管理命令。浏览器用同样的隔离文件系统和本地 HTTP 服务验证表单、跟随 Unraid 语言、驱动版本提示、通知入口、移动布局，以及无响应、超时后重试和迟到响应的处理。

本轮 review 的依据、修复清单和实机验证边界见 [REVIEW.md](REVIEW.md)。
