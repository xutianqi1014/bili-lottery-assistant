# B站互动抽奖助手

本项目是一个本机运行的 B 站互动抽奖助手，使用 HTML 控制台操作，浏览器端通过 Playwright 执行页面可见的读写动作。

当前版本：`1.5.5`

当前内置来源：

- MID `100680137` + `280604312`（双来源主页），适配器 `lottery_toolman_v1`；100680137 按“抽奖合集/官方抽奖合集”规则发现，280604312 只选择名称精确为“抽奖合集”的合集；每个选中合集取最新 5 篇，仅允许官方和非官方动态；
- MID `492426375`（糯米是个背包），适配器 `nuomi_backpack_v1`，按年份合集规则发现，仅允许官方和预约动态。
- MID `3546836235193146`（番茄薯条喵），适配器 `tomato_fries_v1`，只选择“互动抽奖”合集并取最新 3 篇；跳过上期传送门和充电抽奖，仅允许官方、非官方和预约动态。

来源页：

- <https://space.bilibili.com/100680137/upload/opus>
- <https://space.bilibili.com/492426375/upload/opus>
- <https://space.bilibili.com/3546836235193146/upload/opus>
- <https://space.bilibili.com/280604312/upload/opus>

## 快速使用

Windows 完整包：[`BiliLotteryAssistant-windows-x64-v1.5.5.zip`](https://github.com/xutianqi1014/bili-lottery-assistant/releases/download/v1.5.5/BiliLotteryAssistant-windows-x64-v1.5.5.zip)。完整解压后启动 `BiliLotteryAssistant.exe`，必须保留 `_internal` 目录。阶段 4～5 的实施和验证见 [实施记录](docs/阶段4-5实施与构建记录.md)。

下载后请核对 SHA-256：`95A8B465C23148DAECC956F522E1805BB395B85E190ADD613ACE2F759795CA1D`（63,787,341 bytes，约 60.83 MiB）。目录版 EXE SHA-256：`98E53F9C63713AC8C7A861938122AD7F3B2A8C18FF077DD950B97A777F6A8D45`。

GitHub Release 单个资产限制为 2 GiB；本版本仅需上传一个完整 ZIP，解压后保留目录结构及同级 `_internal` 目录。

程序会自动启动本地服务并打开：

<http://127.0.0.1:8787/>

进入页面后按以下顺序操作：

1. 点击“打开登录页”，在自动打开的 B 站浏览器中完成登录。
2. 在“选择来源”中选择要处理的 UP；切换来源后需要重新开始只读发现。
3. 在首页配置 DeepSeek Key、API 地址、模型和最多 3 个固定 @账号，然后点击“保存设置”。
4. 点击“开始只读发现”。发现结束后，如果存在待处理动态，执行计划会自动生成。
5. 进入“执行与结果”页，检查动态顺序、流程、页面状态和运行状态，点击“确认并开始执行”。该按钮会先确认不可变计划，再自动启动执行；若页面刷新后计划已经确认，则显示“开始执行计划”作为恢复入口。
6. 进入“运行日志”页查看实时事件。正常事件仅显示短摘要；运行进入 `waiting_user`、`failed`、`interrupted` 或记录问题网址时，会附加脱敏的详细上下文。可用“复制日志”导出当前日志，或用“清空”并确认后清除本次页面会话日志。
7. 若某条动态因人工复核而暂停，先在 B 站手动完成或修正该动态，再回到第三页点击“重新开始”。该操作只重新检查当前未完成动态，已完成或已跳过动态不会重复执行。

完整的安装、流程、等待时间、环境变量和故障处理请查看：[docs/使用说明.md](docs/使用说明.md)。

## 源码运行

要求 Python 3.12 或更高版本：

```powershell
Set-Location C:\Users\35267\Desktop\b站抽奖\bili-lottery-assistant
py -3.12 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -e ".[dev]"
python -m playwright install chromium
python -m backend.launcher
```

然后打开 <http://127.0.0.1:8787/>。

## 当前边界

- 当前内置三个来源；“你的抽奖工具人”是双来源主页，点击开始只读发现时会依次检查两个主页，其他来源仍使用独立适配器。
- `tomato_fries_v1` 只读取名称为“互动抽奖”的合集（不会选择“转盘合集”），按专栏发布时间取最新 3 篇。正文按可见分区跳过“上期传送门”和“充电抽奖”，只保留预约和互动抽奖；互动抽奖继续按官方/非官方运行时流程分类。
- `lottery_toolman_v1` 会同时检查 MID `100680137` 和 `280604312`：前者选择两个类别的最新合集，后者只接受名称精确为“抽奖合集”的合集；每个选中合集取最新 5 篇，不会把“抽奖合集2”等相似名称作为来源。
- `nuomi_backpack_v1` 选择名称为四位年份的最大合集（当前发现到 `2026`，readlist `rl1016769`），从中取序号最大的 3 篇专栏。该合集中的互动抽奖按官方流程执行；正文出现“预约有奖”卡片的动态按独立预约流程执行；直播已撤销导致卡片只显示“已撤销”时也会安全跳过。
- 加码动态若只在引用原动态中出现官方抽奖入口，会按外层动态进入非官方加码流程，不会误打开内层互动抽奖面板。
- 来源专栏中的“互动抽奖”分段会在计划中显示为“互动”临时标签；动态打开后先检查点赞，已点赞直接跳过，唯一未点赞后才按页面事实选择官方、预约或非官方流程。点赞状态缺失或不唯一时会在类型判断前安全暂停。
- 界面中的原“官方”分类标签统一显示为“互动”；`official` 仍是内部运行模式，用于选择官方互动抽奖面板流程，不改变执行器和安全门。
- 只读发现阶段不会打开候选动态；正式执行时才读取动态页面状态。
- 官方互动抽奖和非官方互动抽奖均默认自动执行，但遇到登录、验证码、风控、控件不唯一或终态未知时会立即停止当前条目，并记录问题网址，不自动重试。
- DeepSeek Key 仅保存在当前本地服务进程内，不写入运行计划、SQLite 或日志；关闭服务后需要重新输入。
- B 站页面结构、登录状态和风控策略可能变化，自动化结果以页面明确终态为准。

## 贡献者

- [xutianqi1014](https://github.com/xutianqi1014) — 仓库所有者、项目贡献者

完整名单见 [CONTRIBUTORS.md](CONTRIBUTORS.md)。

## 开发检查

```powershell
.\.venv\Scripts\Activate.ps1
python -m pytest
python -m ruff check backend tests
python -m mypy backend
```

前端检查：

```powershell
Set-Location frontend
pnpm install
pnpm test
pnpm run typecheck
pnpm run build
```

