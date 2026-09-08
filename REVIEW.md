# 项目审查与修复记录

审查日期：2026-09-08。本报告记录 **2026.09.08** 版本的修复、验证结果和后续事项。

## 审查依据

- 目标仓库：[hellomrli/my-unraid-vgpu-manager](https://github.com/hellomrli/my-unraid-vgpu-manager)。审查开始时，本地 HEAD 与 GitHub `master` 均为 `b7d2f4b9ac46f98afaa53e20bb4fc469cc7fceac`。
- 已对照 GitHub 发布的插件清单、驱动下载来源和插件安装包；原发布包的文件内容与当时的源码一致。本轮同时更新源码、插件包和清单校验值，避免只改源码而安装到旧程序。
- 对照 Unraid WebGUI 源码确认了系统更新 post-hook 参数、`starting` 事件与 Docker / libvirt 启动顺序，以及原生 CSRF 处理方式。
- 已核对 NVIDIA / Intel 配套仓库的 Release 命名：两者均使用完整内核版本标签，例如 `6.18.47-Unraid`。配套驱动仓库只作关联审查，本轮未修改。

## 已修复的问题

| 级别 | 确认的问题及影响 | 本轮处理 |
|---|---|---|
| 高 | Unraid 重启后根文件系统重建；仅加载模块不能保证已启用驱动恢复，启动时机也可能晚于 VM 自启动 | 从本地校验通过的缓存恢复当前内核的驱动；在 `starting` 阶段完成加载和设备恢复，不依赖开机联网 |
| 高 | 更新先复用旧缓存，或只比较驱动版本，导致 GitHub 的同版本新构建无法实际更新 | 显式更新强制查询 Release，同时比较版本、完整内核和构建号；安装失败向上传递 |
| 高 | 下载失败、错误内核包或损坏缓存可能掩盖准备失败 | 严格匹配资产名称，临时下载并校验后才发布到缓存；无有效匹配包就失败，保留其他内核和驱动缓存 |
| 高 | 只检查 VM 持久配置会漏掉仍在运行的绑定；设备停止失败时删除定义会丢失配置 | 同时检查持久和活动 XML；阻止冲突操作；停止或删除失败保留配置，驱动繁忙时不继续卸载 |
| 高 | Intel VF 路径假设、重复重建 VF 或忽略操作失败可能破坏正在使用的设备 | 从 PCI 设备和 PF 的 `virtfn*` 链接发现 VF，校验硬件数量上限及占用；数量相同不重建，失败不保存新数量 |
| 中 | 通过磁盘上的 `modinfo` 判断已加载 i915，可能把原生模块误认成新安装的 SR-IOV 模块 | 检查实际已加载模块的 sysfs 参数；使用插件自己的 modprobe 配置，保留用户启动脚本 |
| 中 | 并发操作及直接覆盖设置可能导致配置丢失；页面输入校验不足 | 驱动操作串行化，设置加锁并原子写入；限定动作、参数、UUID、设备地址和配置值 |
| 中 | 页面数据直接进入 JavaScript / HTML，特殊 VM 名称和配置档内容可能破坏页面；刷新可能重复提交 | 转义 HTML 和内嵌 JSON，安全构造 DOM，POST 使用独立动作端点与 CSRF 校验，完成后通过 GET 刷新 |
| 中 | 保存常规设置会意外重置 NVIDIA unlock；授权地址改变后旧 token 可能继续被复用 | 分开处理设置；地址或端口变化重新获取 token，请求失败保留原运行配置，并提供证书校验选项 |
| 中 | NVIDIA 系列判断及硬件说明不够准确，系统升级时存在意外切换分支的风险 | 共享 PCI ID 元数据；新安装按硬件推荐，系统升级保持已安装系列；缩小未验证硬件的支持声明 |
| 低 | 界面缺少中文、HTTP 环境复制功能受限、移动页面显示不完整 | 新增简体中文 / English / 跟随 Unraid，完善中文提示、剪贴板回退和移动布局 |

主要实现见 [rc.vgpu](source/usr/local/emhttp/plugins/my-unraid-vgpu-manager/scripts/rc.vgpu)、[common.sh](source/usr/local/emhttp/plugins/my-unraid-vgpu-manager/include/common.sh)、[download.sh](source/usr/local/emhttp/plugins/my-unraid-vgpu-manager/include/download.sh) 和 [actions.php](source/usr/local/emhttp/plugins/my-unraid-vgpu-manager/include/actions.php)。

## 新增：按用户启用状态准备系统升级驱动

Unraid 更新写入启动盘后，从 `/boot/bzimage` 的 Linux 启动头读取下一次启动的内核，通过系统更新完成钩子立即检查，并以每分钟任务覆盖其他更新入口。不会从 changelog 的历史记录猜测目标内核。

| 用户当前设置 | 自动准备行为 |
|---|---|
| NVIDIA、Intel 均未启用 | 不查询 GitHub、不下载驱动，等待用户手动安装 |
| 仅启用 NVIDIA | 只准备 NVIDIA，保持当前已安装的 16.x / 19.x 系列；固定版本设置继续生效 |
| 仅启用 Intel | 只准备 Intel，不查询或下载 NVIDIA |
| 两者均启用 | 各自准备，全部校验成功才显示已就绪 |
| 任一已启用驱动缺包、下载失败或校验失败 | 显示未就绪并通知用户重启后可能无法使用相应 GPU 功能 |

“启用”使用用户安装驱动后保存的管理状态判断；检测到硬件或缓存中有旧包都不构成启用。开始下载每个驱动前会再次检查其状态。自动准备可独立关闭，页面也支持输入目标内核手动准备。

预下载不替换当前运行内核的驱动、不自动重启，也不拦截 Unraid 重启按钮。新内核启动后，只从匹配且校验通过的本地缓存恢复已启用驱动。实现见 [upgrade-check.sh](source/usr/local/emhttp/plugins/my-unraid-vgpu-manager/include/upgrade-check.sh) 和 [kernel.php](source/usr/local/emhttp/plugins/my-unraid-vgpu-manager/include/kernel.php)。

## 验证

- **36 项隔离回归测试通过**：涵盖启用状态、单驱动准备、保留系列、缺包和损坏缓存、重复检查节流、错误内核拒绝、更新失败、同版本重构建、无网络启动恢复、VM 活动绑定、设备繁忙、VF 数量及授权失败等行为。
- **浏览器交互验证通过**：中文 / 英文切换、实际表单提交、刷新不重复添加设备、标签页保留、UUID 生成、含引号的 VM 名称、内嵌 JSON 注入防护、CSRF 拒绝、升级弹窗参数和移动布局。
- PHP、Bash、JavaScript、JSON、XML 和 ShellCheck 检查通过，`git diff --check` 通过。
- 通过可重复构建检查，确认 `packages/my-unraid-vgpu-manager-2026.09.08.txz` 与 `source/` 完全一致，且 MD5 与 `.plg` 清单一致。
- 新增 CI 工作流，运行上述检查并保存浏览器截图。以上结果来自发布前的本地验证，远端结果见 [GitHub Actions](https://github.com/hellomrli/my-unraid-vgpu-manager/actions/workflows/check.yml)。

测试入口为 [scripts/check.sh](scripts/check.sh) 和 [tests/browser_server.py](tests/browser_server.py)。驱动命令运行在 bubblewrap 隔离的模拟 Unraid 文件系统中，替换了网络、包管理和 GPU 命令；浏览器连接本地测试服务。

## 仍需验证及后续改进

- **尚未在真实 Unraid 主机、GPU 驱动模块或实际系统升级重启中验证。** 模拟测试不能确认内核 ABI、驱动加载、授权服务、硬件兼容性以及所有 Unraid 主题下的界面行为。发布前应在有回退条件的主机验证“系统更新 → 包准备 → 重启 → 驱动恢复 → VM 自动启动”的完整流程。
- 应实测未启用、仅 NVIDIA、仅 Intel、两者启用以及新内核暂缺驱动包这几种系统更新情况；特别确认 GPU 占用期间更新 / 卸载被正确阻止。
- 配套 NVIDIA 构建仓库的自动检查目前仍跟踪 **16.x**。19.x 的新内核包可能需要手动触发构建；建议后续把自动构建扩展为两个系列。管理插件遇到缺包会提示未就绪，不自动跨系列替换。
- GPU 列表来自驱动配置的 PCI ID，不代表全部硬件已认证或实测。新架构需要的 NVIDIA `sriov-manage` 尚未自动化；消费卡 unlock、不同 Intel 型号及更多宿主 / guest 驱动组合仍需硬件验证。
- MD5 用于与现有发布格式兼容及检测下载损坏；后续可在配套构建和插件中统一增加 SHA-256。缓存保留不同内核以支持回退，未来可增加显示空间占用的手动清理界面。

版本更新需同时发布源码、对应安装包和 `.plg` 清单；现有 GitHub 安装链接从 `master` 分支读取清单及安装包。
