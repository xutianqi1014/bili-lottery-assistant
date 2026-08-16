# B站互动抽奖助手

本项目是一个本机运行的 B 站互动抽奖助手，使用 HTML 控制台操作，浏览器端通过 Playwright 执行页面可见的读写动作。

当前版本：`0.1.2`

当前内置来源：

- MID `100680137`，适配器 `lottery_toolman_v1`，按“抽奖合集/官方抽奖合集”规则发现，仅允许官方和非官方动态；
- MID `492426375`（糯米是个背包），适配器 `nuomi_backpack_v1`，按年份合集规则发现，仅允许官方和预约动态。

来源页：

- <https://space.bilibili.com/100680137/upload/opus>
- <https://space.bilibili.com/492426375/upload/opus>

## 快速使用

Windows 用户建议直接从 GitHub Release 下载：

<https://github.com/xutianqi1014/bili-lottery-assistant/releases/tag/v0.1.2>

下载并解压 `BiliLotteryAssistant-windows-x64-v0.1.2.zip`，保持目录结构不变，然后双击目录内的 `BiliLotteryAssistant.exe`。程序会自动启动本地服务并打开：

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

- 当前内置两个 UP 来源；每个 UP 使用独立适配器，后续新增 UP 仍需单独配置其合集结构和适配器。
- `nuomi_backpack_v1` 选择名称为四位年份的最大合集（当前发现到 `2026`，readlist `rl1016769`），从中取序号最大的 3 篇专栏。该合集中的互动抽奖按官方流程执行；正文出现“预约有奖”卡片的动态按独立预约流程执行，“已结束”按钮仅表示预约卡片终态。
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
