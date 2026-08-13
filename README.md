# B站互动抽奖助手

本项目是一个本机运行的 B 站互动抽奖助手，使用 HTML 控制台操作，浏览器端通过 Playwright 执行页面可见的读写动作。

当前版本：`0.1.0`

当前内置来源：MID `100680137`，适配器 `lottery_toolman_v1`
当前来源页：<https://space.bilibili.com/100680137/upload/opus>

## 快速使用

Windows 用户建议直接从 GitHub Release 下载：

<https://github.com/xutianqi1014/bili-lottery-assistant/releases/tag/v0.1.0>

下载并解压 `BiliLotteryAssistant-windows-x64-v0.1.0.zip`，保持目录结构不变，然后双击目录内的 `BiliLotteryAssistant.exe`。程序会自动启动本地服务并打开：

<http://127.0.0.1:8787/>

进入页面后按以下顺序操作：

1. 点击“打开登录页”，在自动打开的 B 站浏览器中完成登录。
2. 在首页配置 DeepSeek Key、API 地址、模型和最多 3 个固定 @账号，然后点击“保存设置”。
3. 点击“开始只读发现”。发现结束后，如果存在待处理动态，执行计划会自动生成。
4. 进入“执行与结果”页，检查动态顺序、流程、页面状态和运行状态，点击“确认本次运行计划”。
5. 点击“开始执行计划”。程序会按确认计划串行处理，完成后显示来源专栏收尾判定。

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

- 当前只配置了 MID `100680137`；其他 UP 需要单独开发并注册来源适配器。
- 只读发现阶段不会打开候选动态；正式执行时才读取动态页面状态。
- 官方互动抽奖和非官方互动抽奖均默认自动执行，但遇到登录、验证码、风控、控件不唯一或终态未知时会立即停止当前条目，并记录问题网址，不自动重试。
- DeepSeek Key 仅保存在当前本地服务进程内，不写入运行计划、SQLite 或日志；关闭服务后需要重新输入。
- B 站页面结构、登录状态和风控策略可能变化，自动化结果以页面明确终态为准。

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
