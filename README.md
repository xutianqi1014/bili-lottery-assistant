# B站互动抽奖助手

本项目是一个本机运行、以 HTML 为操作界面的 B 站抽奖助手。目前只注册 MID `100680137` 的 `lottery_toolman_v1` 适配器，并为后续增加其他 UP 预留独立来源适配器。

## 已实现流程

- 从指定 UP 的图文/专栏页发现“抽奖合集”和“官方抽奖合集”，按数字后缀选择最新文集。
- 每类取最新 5 篇来源专栏，检查来源点赞状态，解析动态引用并按动态 ID 全局去重。
- 候选阶段不打开动态；只读发现完成后，有待处理动态就自动生成不可变运行计划，没有待处理动态则不生成计划；用户仍须审查并确认计划。
- 非官方当前条目已支持只读结构识别：正文只取动态自身内容，不读取评论列表作为参与要求；真实转发叠层 DOM 会识别为加码抽奖，并只解析外层动态要求。
- 非官方点赞优先定位外层动态工具栏 `.content > .sidebar-wrap > .side-toolbar > .side-toolbar__box > .side-toolbar__action.like`，并在水合期间最多轮询 6 次；只有确认唯一可见控件才点击，避免把转发副本或叠层中的其他点赞控件误当成当前动态点赞。
- 非官方关注步骤兼容当前动态页发布者节点 `.bili-dyn-item__header .bili-dyn-title__text`，作者名最多轮询 6 次；加码动态只读取外层 header 的发布者，不会把内层原作者当成关注目标。
- 运行时分类以官方互动抽奖入口为唯一的官方正向信号：存在 `a[data-type="lottery"]` 才判定为官方；未检测到该入口的动态统一按非官方处理。正文要求和转发叠层只用于细分普通/加码；即使正文暂时为空，也不会再返回 `CLASSIFICATION_UNKNOWN`。
- 普通和加码非官方策略都显示为“评论并勾选同时转发”。加码分类仍保留用于运行证据和 DeepSeek 上下文，但不再单独执行外层转发。确认运行计划并开始执行后，当前版本会真实提交非官方评论、转发、点赞和关注，并逐步确认终态。
- 官方动态在确认计划后自动串行处理，条目间默认随机等待 3–5 秒；官方条目数量不设上限，但目标只能来自当前已确认的不可变运行计划。
- 每条先读取 `.side-toolbar__action.like.is-active`：已点赞视为已参与并跳过；未点赞才打开互动抽奖面板。
- 未点赞但面板已经显示“已成功参与/已参与/已转发”时，兼容旧版本直接返回 `ALREADY_PARTICIPATED`，不点击参与按钮，也不补点动态点赞。
- 面板存在“开奖时间”字段视为未结束，不存在该字段视为已结束；未结束且只有一个文本白名单参与控件时点击一次。
- 参与成功后程序先关闭互动抽奖弹窗并确认 iframe 已移除，再用普通可操作性点击动态点赞一次并复核点亮；不会穿透遮罩强制点击。非官方自动化的评论提交在唯一发布按钮点击完成后即视为已接受，不等待评论列表立即展示（B站评论可能异步渲染）；转发、点赞和关注仍保留终态复核。
- 验证码、风控、控件歧义、结构异常、点击后未知终态会立即停止队列，记录问题网址，并禁止自动重试当前目标。
- 历史运行结果不再替代当前页面点赞状态；跨运行判断以 B 站当前点赞标记为准。
- 所有活动安全终态后，程序重新计算来源收尾：只有初始未点赞、全部关联活动终态且开放问题为 0 的来源才自动点赞；写入前默认随机等待 3–5 秒，并复核 `.is-active`。
- 只要来源关联开放问题，对应来源保持 `blocked_not_marked`，本轮不点赞；来源点赞未知或失败会记录专栏网址、停止收尾并禁止自动重试。

逐条人工授权按钮、确认勾选框、`I_UNDERSTAND_OFFICIAL_PARTICIPATION` 短语、官方单目标 allowlist 和独立的 `/official-participation/execute` 接口均已删除。已确认的不可变运行计划就是官方自动化的唯一目标范围。

## 本地启动

```powershell
Set-Location C:\Users\35267\Desktop\b站抽奖\bili-lottery-assistant
py -3.12 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -e ".[dev]"
python -m playwright install chromium
python -m backend.launcher
```

打开 <http://127.0.0.1:8787/>，先完成 B 站登录，再依次执行。“打开登录页”使用独立的唯一登录标签：页面仍打开时再次点击只会切换到已有标签，不会重复创建；关闭该标签或整个自动化浏览器后，再次点击会自动新建浏览器会话和登录页。

1. 点击“开始只读发现”；发现结束后，如有待处理动态，执行计划会自动出现；
2. 审查目标与顺序后点击“确认本次运行计划”；
3. 点击运行按钮。官方条目按自动化规则执行；非官方条目会在运行时检查后真实执行评论、转发、点赞和关注，并逐步确认终态。若没有待处理动态，页面会明确提示且不会生成空计划。

也可以直接运行 Windows 目录包：

```powershell
& '.\dist\BiliLotteryAssistant\BiliLotteryAssistant.exe'
```

双击目录包中的 `BiliLotteryAssistant.exe` 后，程序会自动占用本机 `127.0.0.1:8787`，等服务就绪后自动打开 <http://127.0.0.1:8787/>。控制台页面通过 WebSocket 维持桌面会话：刷新页面时，新页面会在 3 秒宽限期内重新连接，不会误停服务，并从当前标签页的 `sessionStorage` 恢复同一发现和执行计划；关闭最后一个助手页面后，程序等待约 3 秒，随后安全停止任务与浏览器、关闭数据库并释放 8787 端口。若同时打开多个助手页面，必须全部关闭才会退出。重复双击 EXE 时不会启动第二个服务，而是打开已经运行的页面；若 8787 被其他程序占用，助手不会擅自终止该程序。

执行期间不要关闭或手动操作自动化使用的 B 站窗口。可用环境变量调整官方自动化：

```powershell
$env:BILI_OFFICIAL_AUTOMATION_ENABLED = "true"   # 默认 true；设为 false 可关闭
$env:BILI_OFFICIAL_AUTOMATION_DELAY_MIN_SEC = "3"
$env:BILI_OFFICIAL_AUTOMATION_DELAY_MAX_SEC = "5"
$env:BILI_SOURCE_LIKE_AUTOMATION_ENABLED = "true"  # 默认 true；设为 false 可关闭
$env:BILI_SOURCE_LIKE_AUTOMATION_DELAY_MIN_SEC = "3"
$env:BILI_SOURCE_LIKE_AUTOMATION_DELAY_MAX_SEC = "5"
$env:BILI_SOURCE_LIKE_AUTOMATION_MAX_ITEMS_PER_RUN = "10"
```

旧的来源点赞单目标 allowlist、人工确认短语和 `/source-like-plan/*` 应用路由已退出正常流程，仅保留离线回归模块与历史证据。来源自动收尾的唯一授权范围来自已确认运行计划中的来源专栏 ID。非官方页面结构、普通/加码分类、指定评论语义、动作计划和 DOM 写入已接入；运行时先检查动态点赞，未点赞时把当前动态正文发送给 DeepSeek 生成短评论，再补全要求的话题和固定 @好友。

非官方自动化内置默认为 `true`（仍可用 `BILI_UNOFFICIAL_AUTOMATION_ENABLED=false` 临时关闭）。普通和加码动态统一顺序为“DeepSeek 评论并勾选同时转发 → 点赞 → 关注”。动态打开并确认身份后，首次读取前也随机等待 1–2 秒；每个动作之间随机等待 1–2 秒；作者搜索回退页打开后也会先随机等待 1–2 秒再匹配唯一精确作者。评论在唯一发布按钮点击完成且未抛出异常时返回 `COMMENT_SUBMIT_ACCEPTED`，不复检评论列表；控件不唯一、登录/安全验证、转发/点赞/关注点击后没有明确终态都会停止本条并记录问题，禁止自动重试。评论要求包含 1–3 个 @好友时使用固定名称映射；超过 3 个或 DeepSeek 未配置时在写入前阻断。

```powershell
$env:BILI_UNOFFICIAL_AUTOMATION_ENABLED = "true"
$env:BILI_UNOFFICIAL_AUTOMATION_DELAY_MIN_SEC = "1"
$env:BILI_UNOFFICIAL_AUTOMATION_DELAY_MAX_SEC = "2"
$env:BILI_UNOFFICIAL_COMMENT_DEFAULT = "参与抽奖，感谢分享！"
$env:BILI_DEEPSEEK_TIMEOUT_SEC = "30"
$env:BILI_DEEPSEEK_MAX_ATTEMPTS = "3"
```

DeepSeek Key、API 地址、模型和 3 个固定账号现在在首页的“DeepSeek 与非官方账号设置”表单中填写并保存。Key 只保存在当前本地服务进程内，接口只返回 `deepseekConfigured` 布尔值，不写入运行计划、SQLite 或日志；关闭服务后需重新输入。

非官方评论生成和写入顺序：先检查动态右侧点赞；已点亮直接按 `ALREADY_LIKED_SKIPPED` 跳过，未点亮才识别普通或“转发加码抽奖”。两种类型都按“DeepSeek 评论 → 填写后等待唯一可见的‘同时转发到我的动态’控件并发布 → 点赞 → 打开作者主页检查关注”。关注步骤优先读取动态中指向作者的 `space.bilibili.com/<mid>` 链接并直达个人主页，旧版页面没有直接链接时才使用唯一精确搜索结果。DeepSeek 使用当前动态的 scoped 正文，不发送评论列表、页面导航或 API Key；生成失败、Key 未配置、超过 3 个 @要求或控件不唯一时，在任何 B 站写入前阻断并记录问题网址。评论发布按钮点击完成后返回 `COMMENT_SUBMIT_ACCEPTED`，不依赖刚发评论立即出现在评论列表；转发、点赞、关注仍要求各自 DOM 终态。生成评论随后只追加正文中检测到且尚未存在的话题，以及设置表单中的前 N 个固定账号。结果和评论草稿会保存到 `Run.stats_json.unofficialParticipationWrites`，未知结果不自动重试。

## 实际 B 站验证

2026-08-12 加码动态作者识别修复已完成离线验收：授权动态 `https://t.bilibili.com/1234841370069303300` 的发布者实际位于 `.bili-dyn-item__header .bili-dyn-title__text`；后端 `153 passed, 2 skipped`，Ruff、Mypy、前端 `9 passed`、TypeScript 检查和生产构建通过；最新 Windows 目录包 EXE SHA-256 为 `88C933346FA4D96AF6AF959C96083122B91458B40B22DBFC45A9D4EAA9B84A94`。

2026-08-12 点赞控件结构修复已完成离线验收：后端 `152 passed, 2 skipped`，前端 `9 passed`、TypeScript 检查和生产构建通过；最新 Windows 目录包 EXE SHA-256 为 `8CFEBD17D6097CD15E480403D965724BD25263CE56CB16AE98ADB6A642697743`。授权动态 `https://t.bilibili.com/1234841370069303300` 仅用于只读 DOM 参照，本轮未执行点赞写操作。

2026-08-09 的运行计划 #15 是旧规则的历史验证。新规则已由运行计划 #20 完成真实验收：23 条全部终态，其中 20 条兼容旧版已参与、1 条明确失效、2 条完成新参与并在关闭弹窗后确认动态点赞，用户人工审查通过。来源专栏自动收尾的编排已完成离线测试，但尚未对新的自动挂接路径执行真实来源点赞，因此 `SOURCE-LIKE-WRITE-001` 暂标为 `STALE`，需下一轮人工审查。2026-08-11 监测期间修正了首页过期文案、收紧评论编辑器选择器并修复了从完整页面文本误生成评论内容的问题；本次新增 DeepSeek 客户端、前端设置表单、普通/加码评论补全、固定 @映射和多形态点赞终态判断，并取消评论发布后的评论列表复检；本次又修复个人主页关注控件的异步 DOM 水合等待，以及运行结果页面显示旧检查点快照的问题；现在关注步骤优先从动态作者链接直达 `space.bilibili.com/<mid>`，并为“同时转发到我的动态”复选框增加填写后的唯一可见等待，不再把用户搜索页作为正常路径；加码分类现在也统一使用评论组件的同步转发复选框，不再单独执行外层转发。后端 151 项测试（2 项跳过）、前端 9 项测试、TypeScript 检查和生产构建均通过。最新 Windows 目录包 EXE SHA-256 为 `5FF3C98E7ECC11A4C07E68C80477DAF89D811BD0212B26689A63234E8B499352`。
