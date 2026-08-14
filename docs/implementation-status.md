# 实现状态

更新时间：2026-08-11

## 已完成

- Python 3.12 + FastAPI + SQLModel + SQLite 后端骨架。
- `lottery_toolman_v1` 独立来源适配器和来源配置种子。
- 文集标题族识别、后缀最大选择、每个文集最新 5 篇选择。
- `GET /x/article/up/lists` 与 `GET /x/article/list/web/articles` 的只读契约实现，带 User-Agent/Referer，并保留接口契约登记。
- BrowserManager、登录页入口和来源专栏点赞状态 DOM 检查边界。
- 发现快照、来源专栏、文集成员关系、问题记录的 SQLite 表。
- JobRunner、SSE 事件、本机 CSRF token 和 HTML 控制台。
- 问题网址独立查询接口和 HTML 汇总框，显示本轮不点赞。
- 共享抽奖分类器、话题/@好友要求解析器，以及默认停在人工确认的官方/非官方流程边界。
- 来源专栏正文解析：迁移置顶区跳过、`新的 →`/序号起点、开奖合集排除、动态 URL 规范化和单篇去重规则。
- 10 篇来源专栏之间的动态全局去重与 `activity_origins` 来源关系持久化；保存正文指纹、起点模式、排除数和解析问题。
- 单条活动页面读取器、共享分类器和要求解析器已迁移为执行时即时检查能力；不会在计划生成阶段批量调用。
- 官方动态即时检查现在会只读点击 `a[data-type="lottery"]` 入口，等待 `iframe[src*="/h5/lottery/result"]` 或官方 dialog，读取 iframe 文本后再判断“已成功参与/已结束”；绝不点击参与、确认、转发、点赞或关注按钮。
- 新增只读逐条运行执行器：确认计划后通过 `POST /api/runs/{id}/start` 启动，每次只打开当前条目，保存分类、证据码、置信度、要求和安全终态；遇到未知、模式冲突或可参与条目即进入 `waiting_user`，可通过 `POST /api/runs/{id}/resume` 人工继续；若人工完成了阻塞动态，可通过 `POST /api/runs/{id}/restart` 只重置当前动态并重新检查。
- HTML 控制台显示动态候选、重复来源关系和来源类别推导的计划流程；候选页面不再提供活动只读预检按钮。
- 预检兼容接口 `/api/discoveries/{id}/preflight` 只返回 `410 ACTIVITY_PREFLIGHT_REMOVED`，不会提交 Job。
- 新增 `runs`/`run_items` 不可变执行计划快照：动态候选完成全局去重后直接按 `normal`/`official` 顺序生成动作清单，计划条目初始为 `unknown/unchecked`；问题来源仍自动阻塞；`confirm_each` 确认门只写入本地确认状态，`direct_write_enabled` 固定为 `false`。
- 新增 `POST /api/runs`、`GET /api/runs/{run_id}`、`POST /api/runs/{run_id}/confirm`、`POST /api/runs/{run_id}/start`、`POST /api/runs/{run_id}/resume` 和 `POST /api/runs/{run_id}/restart`；HTML 控制台可预览计划、人工确认、启动逐条即时检查并在每条后暂停。重新开始只重置当前人工复核动态，终态条目不会重复执行。
- 前端生产构建已输出到 `web_static/dist`。
- PyInstaller onedir 与 Inno Setup 的 Windows 打包起始文件；本轮已成功重新生成 `dist/BiliLotteryAssistant`，Inno Setup 安装器仍未构建验证。
- Python 编译、Ruff、Mypy（77 个后端文件）、31 个后端测试、3 个前端 Vitest 测试、接口契约审计和 FastAPI 健康检查均通过。
- 真实只读端到端验证：6 个候选文集中选出 `抽奖合集④`/`官方抽奖合集③`，各 5 篇，共 10 篇；浏览器未就绪时 10 篇均进入 `unknown/manual_review`。

## 当前仍未自动启用

- 直接调用候选写 API（仍禁止）。
- 非官方自动化默认启用；正式写入必须同时满足已确认运行计划、首页设置表单中的 DeepSeek Key 和登录浏览器。`BILI_UNOFFICIAL_AUTOMATION_ENABLED=false` 时仍会在写入前安全阻断。
- 来源专栏收尾只对全部关联活动终态且无开放问题的来源执行，异常来源保持未点赞。

官方抽奖参与已改为运行计划级自动化；其范围只能来自用户已确认的不可变运行计划。来源点赞和非官方互动仍保持各自独立安全门，不会被官方自动化开关连带启用。

## 本地运行

```powershell
Set-Location .\bili-lottery-assistant
python -m backend.launcher
```

开发前端：

```powershell
Set-Location .\frontend
pnpm install
pnpm run build
pnpm dev
```

默认页面：`http://127.0.0.1:8787/`。先点击“打开登录页”完成用户自己的 B 站登录，再点击“开始只读发现”；发现完成后，有待处理动态就自动生成执行计划，没有待处理动态则明确提示并且不创建空计划。检查顺序与目标后，再点击“确认本次运行计划”和“开始官方自动执行”。官方条目按顺序串行处理，页面通过事件流主动刷新；执行期间不要关闭或手动操作自动化浏览器窗口。

## 2026-08-08 后续阶段：非官方动作检查点（已完成安全骨架）

本轮完成了非官方抽奖的本地动作编排，但没有启用任何 B 站写请求：

- 新增 `backend/activity_engine/unofficial/actions.py`，独立定义评论、转发、点赞、关注四步顺序。
- 新增 `ActionCheckpointLedger`：前一步没有确定成功（或明确已完成）时，不能开始下一步。
- 写适配器异常或超时统一归类为 `WRITE_RESULT_UNKNOWN`，状态进入 `blocked_unknown`，禁止自动重试，必须人工打开动态确认。
- `GuardedUnofficialActionExecutor` 在 `ManualGate`、用户确认和 `https://*.bilibili.com/opus/*` 目标校验全部通过前不会调用传输层；当前全局 `direct_write_enabled=false`，因此生产运行仍不会发出外部写请求。
- 非官方运行快照现在附带 `unofficialActionPlan` 和 `unofficialCheckpoints`，便于后续 HTML 控制台展示每一步的安全状态。

验证结果：后端 `36 passed, 2 skipped`，Ruff 和 mypy 均通过。仍未实现的部分是实际评论/转发/点赞/关注传输、结果 DOM/API 复核、DeepSeek 评论生成、来源专栏收尾点赞，以及暂停/取消和持久化检查点；这些必须完成接口契约、allowlist、人工确认和受控测试后才能进入下一阶段。

## 2026-08-08 官方抽奖过期误判修复

实测动态：<https://www.bilibili.com/opus/1231172523107811364>。页面互动抽奖 iframe 显示“开奖倒计时 03 天 19 时 22 分”和“开奖时间：2026年08月12日 18:00”，但旧版本可能因整页残留文案而返回 `LOTTERY_EXPIRED`。

修复位置：`backend/activity_engine/runtime_inspection/reader.py`。

- 官方面板打开并成功读取文本时，以面板文本作为过期判断权威来源。
- 检测到“开奖倒计时/距离开奖/倒计时”时强制保持未过期。
- 删除“暂时无法参与”的过期含义，该文案现在进入人工复核。
- 新增正文残留结束文案、活跃倒计时和暂时无法参与回归测试。

## 2026-08-08 来源专栏收尾判定（已实现，只读）

本阶段在逐条运行状态和问题记录的基础上，新增来源专栏收尾汇总。实现位置为
`backend/use_cases/source_closure.py`、`backend/use_cases/run_execution.py`，只更新本地
`runs.stats_json.sourceClosure`，不调用 B 站点赞接口。

- `ready_to_mark`：来源专栏存在；其关联的全部去重活动均为 `completed` 或 `skipped`；没有开放问题记录；且当前来源点赞状态不是 `liked`。这只是“可交给后续点赞适配器”的本地资格，不代表已经点赞。
- `already_liked`：发现阶段已经确认来源专栏为已点赞，直接跳过来源收尾。
- `blocked_not_marked`：存在未终态活动、`waiting_user`/`blocked` 条目、开放问题记录、来源专栏缺失或没有关联活动；该来源本轮不点赞。
- 全局去重后的一个 `RunItem` 通过 `source_article_ids_json` 关联到全部来源，因此同一动态完成一次后会同时计入每个来源专栏，不能只根据主来源判断。
- 发生运行时异常时，`ProblemRegistry` 记录问题网址；来源收尾读取开放记录并保持 `blocked_not_marked`，直到人工处理或明确关闭问题。

新增只读接口：`GET /api/runs/{run_id}/source-closure`。运行详情的 `stats.sourceClosure` 与该接口返回相同结构，HTML 控制台在执行计划下显示来源专栏、终态活动数、开放问题数和原因码。该接口不需要 CSRF，也不产生外部写操作。
`GET /api/runs/{run_id}` 也会在序列化时即时补算该字段，因此旧运行记录刷新后仍能看到当前来源收尾状态。

本历史阶段当时仍未实现来源专栏实际点赞、非官方互动和官方参与；官方参与已在后续 2026-08-09 自动化阶段实现，来源点赞与非官方互动仍保持独立安全门。

本阶段验证：`python -m pytest -q` 为 `45 passed, 2 skipped`；Ruff、mypy、接口契约审计、前端 typecheck/Vitest/build 均通过。Windows 目录包已重建到 `dist/BiliLotteryAssistant`。

## 2026-08-09 来源点赞计划与受控执行骨架（已实现，实际写入未启用）

本阶段把来源专栏收尾结果接入独立的来源点赞计划模块：

- `backend/use_cases/source_like_plan.py` 只从 `ready_to_mark` 来源生成目标，并把人工确认写入运行计划的本地 `stats_json.sourceLikePlan`。
- `backend/source_adapters/lottery_toolman/source_like.py` 定义单步检查点、`https://www.bilibili.com/read/cv数字` 目标 allowlist、成功/已完成/失败/未知结果和“未知不重试”策略；它不包含真实 B 站传输实现。
- `GET /api/runs/{run_id}/source-like-plan` 查看来源点赞计划；`POST /api/runs/{run_id}/source-like-plan/confirm` 只保存本地人工确认，仍不会点击来源专栏点赞按钮。POST 接口需要本地 CSRF token。
- HTML 控制台在来源收尾区域显示目标、阻塞数和计划状态；只有存在 `ready_to_mark` 目标时显示“确认来源收尾计划（仍不点赞）”。确认后显示 `confirmed_waiting_write` 与 `SOURCE_LIKE_WRITE_DISABLED`。
- 新增接口契约 `SOURCE-LIKE-WRITE-001`，当前状态仍是 `SOURCE_FOUND`；契约要求登录浏览器、DOM 点按 `.side-toolbar__action.like`，并以 `.side-toolbar__action.like.is-active` 作为终态证据。未完成受控写测试前，不能把状态升级为 `WRITE_TEST_PASSED` 或 `PRODUCTION_APPROVED`。

执行器的状态逻辑：目标不在 allowlist 立即拒绝；全局写开关关闭或用户未确认时不调用 transport；明确成功/已点赞进入 `completed`；传输异常进入 `blocked_unknown`，禁止自动重试；明确失败进入 `blocked_failed`。当前应用始终用 `ManualGate(False)`，所以不会发出外部请求。

本阶段验证：后端 `52 passed, 2 skipped`，Ruff、mypy、6 个接口契约审计、前端 typecheck/Vitest/build 均通过。下一阶段只能在用户明确授权的 allowlist 目标、实际 Network/DOM 契约和一次性受控写测试完成后，单独实现 DOM 写适配器。

## 2026-08-09 DOM 来源点赞适配器（已接入，写开关仍关闭）

人工审查通过后，新增 `backend/source_adapters/lottery_toolman/source_like_dom.py`，并在
`LotteryToolmanSourceAdapter.build_source_like_transport()` 中保留构造入口。它没有被应用自动路径调用，也没有执行真实 B 站点击。

DOM 判断顺序：

1. 目标 URL 必须是 `https://www.bilibili.com/read/cv数字` 或 `https://bilibili.com/read/cv数字`。
2. 打开登录浏览器并等待 `.side-toolbar__action.like`；读取异常返回 `SOURCE_LIKE_PAGE_READ_UNKNOWN`。
3. 优先检查 `.side-toolbar__action.like.is-active`；存在则 `ALREADY_DONE / SOURCE_ALREADY_LIKED`，不点击。
4. 未点赞时要求普通点赞按钮数量恰好为 1；0 个或多个都不点击并返回失败码。
5. 点击一次；点击异常返回 `UNKNOWN / SOURCE_LIKE_CLICK_UNKNOWN`。
6. 点击后等待并复读 `.side-toolbar__action.like.is-active`；活动类出现才返回 `SUCCESS / SOURCE_LIKE_CONFIRMED`，其余情况返回 `UNKNOWN / SOURCE_LIKE_TERMINAL_STATE_UNKNOWN`，进入人工复核且禁止重试。

它通过 `GuardedSourceLikeExecutor` 受全局 `ManualGate`、用户确认、allowlist 和单步检查点保护。当前 `direct_write_enabled=false`，来源点赞计划确认后仍为 `confirmed_waiting_write / SOURCE_LIKE_WRITE_DISABLED`，不会发出外部写请求。接口契约 `SOURCE-LIKE-WRITE-001` 仍为 `SOURCE_FOUND`。

新增离线伪页面测试覆盖：已点赞跳过、单次点击后终态确认、点击异常、终态超时、按钮歧义和页面读取异常。验证结果：`58 passed, 2 skipped`，Ruff、mypy 和 6 个接口契约审计通过；真实写测试仍需用户明确授权的单一 allowlist 目标，未授权前不得升级契约状态。
最终 Windows 目录包已按本阶段源码重建：`dist/BiliLotteryAssistant/BiliLotteryAssistant.exe`；包内前端资源包含 `source-like-plan` 和 `source-closure` 路由字符串。

## 2026-08-09 受控来源点赞写测试准备（未执行真实写入）

新增 `backend/use_cases/source_like_write_test.py`，但不接入普通运行路径。该封装要求：

- `tests/live_contracts/write_allowlist.yaml` 的 `enabled` 为 `true`，且 `article_ids` 恰好一个数字 ID；
- 环境变量 `BILI_LIVE_WRITE_TEST=I_UNDERSTAND`；
- 精确的 `https://www.bilibili.com/read/cv数字` 目标 URL；
- 人工确认短语 `I_UNDERSTAND_SOURCE_LIKE_WRITE`；
- 一个受控会话最多调用一次，未知结果禁止重试。

模板 `tests/live_contracts/write_allowlist.example.yaml` 默认关闭。当前没有创建真实 allowlist，也没有设置环境变量；`SOURCE-LIKE-WRITE-001` 仍为 `SOURCE_FOUND`，普通应用仍使用关闭的 `ManualGate`。

本阶段仅完成离线授权拒绝、单目标约束、URL allowlist、一次性消费和禁写门测试，不访问 B 站、不执行真实点赞。
验证结果：后端 `63 passed, 2 skipped`，Ruff、mypy、6 个接口契约审计、前端 typecheck/Vitest/build 均通过；Windows 目录包已按本阶段源码重建。

## 2026-08-09 单一来源专栏目标已登记（未执行点赞）

用户提供的 `https://www.bilibili.com/opus/1234111126833201155` 经浏览器只读核对，页面正文对应专栏文章 `cv52173801`。该页面当前普通点赞按钮数量为 1，活动类 `.is-active` 数量为 0；`/read/cv52173801` 会回到同一页面，因此 allowlist 使用文章 ID `52173801`。

本地忽略文件 `tests/live_contracts/write_allowlist.yaml` 曾登记唯一文章目标；受控写测试完成后已关闭为 `enabled: false`，防止重复执行。`SOURCE-LIKE-WRITE-001` 已升级为 `WRITE_TEST_PASSED`，但生产写入仍未启用。

## 2026-08-09 单一目标来源点赞受控测试已完成

用户明确确认对 `cv52173801` 执行一次测试后，登录浏览器完成了单次 DOM 点击并复核终态：点击前普通按钮数量为 1、`.is-active` 数量为 0；点击次数为 1 且无重试；点击后 `.is-active` 数量为 1，结果码为 `SOURCE_LIKE_CONFIRMED`。脱敏证据保存于
`tests/fixtures/contracts/SOURCE-LIKE-WRITE-001/evidence-2026-08-09-cv52173801.json`，未保存 Cookie、请求头或账号标识。

该结果只代表单一目标的受控写测试通过，不代表启用批量或生产写入；应用仍保持 `direct_write_enabled=false`。

## 2026-08-09 来源点赞结果回写计划闭环（已实现）

`backend/use_cases/source_like_plan.py` 现在会把已保存的 `confirmed_waiting_write` 计划与当前来源专栏点赞状态重新对账：当保存的全部目标均已是 `liked` 时，返回 `completed / SOURCE_LIKE_CONFIRMED` 并清空待写目标；目标集合变化或只完成部分目标时返回 `stale / SOURCE_CLOSURE_CHANGED`，要求人工重新确认且禁止自动重试。前端将 `completed` 显示为“已完成（已点赞）”。本地运行 11 已验证该回写结果；`direct_write_enabled` 仍为 `false`，不会因回写而产生新的外部写操作。

## 2026-08-09 单目标来源点赞应用入口（已接入，默认禁写）

新增 `POST /api/runs/{run_id}/source-like-plan/execute`，接入 `SourceLikeExecutionService`。该入口只有在运行计划已确认、目标恰好一个、CSRF、`BILI_ENABLE_DIRECT_WRITE_API=true`、单目标 allowlist、`BILI_LIVE_WRITE_TEST=I_UNDERSTAND` 和确认短语 `I_UNDERSTAND_SOURCE_LIKE_WRITE` 全部满足时才会调用 DOM transport；默认配置不会调用浏览器写入。

执行结果持久化到 `stats_json.sourceLikeWrite`：成功/已点赞更新本地来源点赞状态为 `liked` 并支持幂等读取；未知结果为 `blocked_unknown`，明确失败为 `blocked_failed`，均禁止自动重试。新增 `writeState`、`writeResultCode` 和 `writeResultMessage` 展示字段。allowlist 路径由 `BILI_SOURCE_LIKE_WRITE_ALLOWLIST_PATH` 提供，默认未配置。

本阶段验证：后端 `66 passed, 2 skipped`，Ruff、mypy、6 项接口契约审计、前端 typecheck/Vitest/build 均通过。前端资源已更新，Windows 目录包待重新构建。

## 2026-08-09 历史阶段：官方单目标受控参与（已被运行计划自动化替代）

当前没有可用非官方动态时，官方流程已经具备独立的单目标受控参与骨架：只打开当前动态的 `a[data-type="lottery"]`，读取 `iframe[src*="/h5/lottery/result"]`，不批量预检、不点击动态外层点赞/转发/关注。默认 `direct_write_enabled=false`，本阶段没有新的 B 站官方写操作。

已实际只读核对动态 `1232685708814057480` 和 `1231172523107811364`：外层入口可打开官方 iframe，能读到开奖条件、奖品、倒计时和“已成功参与”。随后用户授权动态 `1231128413813604353`，实测唯一 `div.join-button`“转发抽奖动态”点击一次后显示“已成功参与”；证据文件为 `tests/fixtures/contracts/OFFICIAL-PARTICIPATE-WRITE-001/evidence-2026-08-09-1231128413813604353.json`，契约已升级为 `WRITE_TEST_PASSED`。应用全局写开关仍关闭。

新增模块：

- `backend/activity_engine/official/participation.py`：官方 URL 校验、一次性检查点、写门和未知结果禁止重试。
- `backend/activity_engine/official/participation_dom.py`：iframe 文本读取、过期/已参与/安全挑战判断，以及唯一参与控件白名单。
- `backend/use_cases/official_participation_write_test.py`：单动态 allowlist、`BILI_LIVE_WRITE_TEST=I_UNDERSTAND` 和确认短语 `I_UNDERSTAND_OFFICIAL_PARTICIPATION`。
- `backend/use_cases/official_participation_execution.py`：运行条目校验、幂等执行、`runs.stats_json.officialParticipationWrites` 持久化。
- `POST /api/runs/{run_id}/official-participation/execute`：必须 CSRF、官方 `waiting_user/MANUAL_GATE_REQUIRED` 条目、单目标 allowlist 和全局写开关。

iframe 内仅允许文本命中 `关注UP主并转发抽奖动态`、`关注我并转发抽奖动态` 或 `转发抽奖动态` 的唯一 `button`、`[role="button"]`、`a` 或实测 `div.join-button` 控件。已参与、已结束、验证码/风控、按钮缺失或歧义、点击后终态不明确分别进入安全跳过、明确失败或人工复核；未知结果为 `blocked_unknown`，同一目标不得自动重试。默认配置下接口返回 `OFFICIAL_PARTICIPATION_WRITE_DISABLED`，不会打开浏览器。

结构异常、验证码/风控和未知终态会通过 `ProblemRegistry` 记录动态规范 URL，来源收尾保持 `blocked_not_marked`，不点赞对应来源专栏；明确 `LOTTERY_EXPIRED` 只作为正常跳过记录。

离线回归现为 `80 passed, 2 skipped`；Ruff、Mypy 和 7 项接口契约审计通过。真实官方单目标写测试已完成，但 `tests/live_contracts/official_participation_allowlist.yaml` 仍保持 `enabled: false`，应用不会自动扩展到其他官方动态。

## 2026-08-09 历史阶段：官方单目标人工授权界面（已删除）

官方执行接口现在已接入 HTML 控制台的运行计划表格：当条目为官方流程、状态为 `waiting_user` 且结果码为 `MANUAL_GATE_REQUIRED` 时，显示“授权并执行一次”入口。该入口严格按单个 `activityId` 工作，不提供批量授权。

- `frontend/src/features/discovery/view.ts` 在当前条目旁显示授权状态；写入开关关闭时按钮禁用并明确提示，不会调用后端写入接口。
- 运行计划响应新增 `officialParticipationWriteEnabled`，表示当前官方单目标写入配置；它与始终保持只读语义的 `directWriteEnabled` 运行快照分离，避免为了显示授权按钮而开放普通执行器。
- 写入开关开启且用户点击入口后，弹出目标 URL、页面状态、唯一目标确认框和精确短语 `I_UNDERSTAND_OFFICIAL_PARTICIPATION`；必须同时勾选人工确认并输入短语才能提交。
- 提交按钮在请求期间立即禁用；接口返回后自动重新读取运行计划，不要求手动刷新页面。成功、已参与、过期、失败和未知结果均沿用后端结果码；未知结果仍禁止重试。
- `frontend/src/shared/api.ts` 复用既有 `executeOfficialParticipation` API，并集中导出确认短语，避免前后端确认文本漂移。
- 运行计划同时展示“官方授权候选清单”：它只从本地计划生成，不批量打开动态；待即时检查、待授权、已完成和需人工复核分别显示状态。清单没有批量执行按钮，用户必须在每一行单独点击授权。

本次仅增加人工授权界面、候选清单和结果刷新，没有改变 `direct_write_enabled=false` 默认值，也没有启用官方批量参与。前端 Vitest 为 `5 passed`，typecheck 和生产构建通过；后端既有 `80 passed, 2 skipped`、Ruff、Mypy 和 7 项契约审计保持通过。

## 2026-08-09 官方运行计划自动化与真实 B 站运行（当前实现）

逐条人工授权流程已完整删除：前端不再包含授权按钮、勾选框、确认短语或弹窗；`frontend/src/shared/api.ts` 不再暴露 `executeOfficialParticipation`；后端删除 `/api/runs/{run_id}/official-participation/execute` 和 `official_participation_write_test.py`。官方自动化仅由已确认的不可变运行计划授权，普通用户无需维护 YAML allowlist。

当前入口为 `POST /api/runs/{run_id}/start`：

- `BILI_OFFICIAL_AUTOMATION_ENABLED` 默认 `true`，可设为 `false` 关闭；
- `BILI_OFFICIAL_AUTOMATION_DELAY_MIN_SEC` 与 `BILI_OFFICIAL_AUTOMATION_DELAY_MAX_SEC` 默认组成 3–5 秒随机间隔；
- 官方目标数量不设上限；范围仍严格等于当前已确认运行中的官方数字 opus ID，不能扩展到计划外 URL；
- 目标必须是运行计划中 `family=official` 的数字 opus ID，程序不能扩展到计划外 URL；
- 已参与、明确失效和跨运行已确认参与直接跳过；历史成功记录跨运行去重，不重新打开页面；
- 未参与时，只有一个文本白名单参与控件才点击一次；点击后必须读取到明确成功终态；
- 验证码、风控、歧义、结构异常或未知终态会停止整队列、记录问题网址且禁止自动重试当前目标；
- `ProblemRegistry` 的开放记录继续阻止来源点赞，满足“问题网址所在合集处理完成后不点赞”。

运行计划 #15 已在真实 B 站完成 23 条官方动态：16 条参与成功、6 条明确失效、1 条依据运行 #12 的历史成功记录跳过。来源专栏 `cv52199188` 因保留 2 条开放问题记录而为 `blocked_not_marked`，未点赞。脱敏证据为 `tests/fixtures/contracts/OFFICIAL-PARTICIPATE-WRITE-001/automation-run-2026-08-09-run15.json`，不包含 Cookie、请求头或账号标识。

第 3 条的首次页面读取中断由用户人为关闭自动化浏览器窗口造成，不是程序判断失败。程序没有对该条重新执行外部操作，而是用运行 #12 已保存的明确参与成功终态进行本地对账，最终记为 `ALREADY_PARTICIPATED_PREVIOUS_RUN`；原中断仍保留为开放问题记录，保证来源专栏不被错误点赞。

本阶段最终验证基线：后端 `89 passed, 2 skipped`、Ruff、Mypy、前端 `5 passed`、typecheck、生产构建和 7 项接口契约审计均通过。

Windows 目录包已重新构建。打包入口改为直接导入 FastAPI 应用对象，避免 PyInstaller 漏收 `backend.api`；实际启动 `dist/BiliLotteryAssistant/BiliLotteryAssistant.exe` 后，`GET /api/health` 返回 `ok=true`、首页返回 HTTP 200、`POST /api/runs/{run_id}/start` 存在，已删除的 `/official-participation/execute` 路由不存在。冒烟测试完成后已关闭测试进程。当前 EXE SHA-256 为 `B80A899EF85AED091CC9DAFE9BAF6BF2DD3B50CA530FEC95E377979526153598`。

## 2026-08-09 官方点赞标记、开奖时间字段与随机延时（当前规则）

本节替代上一节中的“跨运行历史成功直接跳过”“明确失效文本优先”和“固定 20 秒”规则。旧运行 #15 与旧结果码仅作为历史证据保留，不再决定新运行是否跳过。

- `backend/activity_engine/official/activity_like_marker.py` 独立负责动态点赞标记。每条先要求 `.side-toolbar__action.like` 恰好一个；`.side-toolbar__action.like.is-active` 存在表示已经点赞，直接返回 `ALREADY_PARTICIPATED_LIKED`，不打开互动抽奖面板。
- 未点赞时才打开 `a[data-type="lottery"]` 和官方 iframe。成功读取的面板存在“开奖时间”字段即视为未结束；不存在该字段即返回 `LOTTERY_EXPIRED`。登录、验证码、安全验证和风控仍属于未知状态，不能误判为已结束。
- 未结束且未参与时，只允许点击唯一文本白名单参与控件一次。面板确认参与后，先关闭 `.bili-popup__header__close` 并证明官方 iframe 与关闭控件均已移除，再以非强制方式点击一次外层动态点赞并要求 `.is-active` 点亮；只有参与、弹窗关闭和点赞标记都确认后才返回 `OFFICIAL_PARTICIPATION_CONFIRMED`。
- 为兼容上一版本，未点赞动态打开面板后，只要在任何参与点击前读到“已成功参与/已参与/已转发”等明确状态，就直接返回 `ALREADY_PARTICIPATED`。该分支不点击参与按钮，也不补点动态点赞，并优先于“开奖时间”字段判断。运行 #16 的动态 `1234029204674183171` 暴露出开奖时间先渲染、成功状态后渲染的时序问题；现已禁止因开奖时间提前结束面板等待，并在控件查找后、点击前再次复核成功终态，防止误报 `OFFICIAL_PARTICIPATION_BUTTON_NOT_FOUND`。
- 点赞标记缺失、数量歧义、点击结果未知或终态未点亮均停止整队列、记录问题网址且禁止自动重试。历史数据库结果不再覆盖当前页面点赞状态。
- 运行 #19 的活动 111（动态 `1233672735227379797`）在参与成功后返回 `OFFICIAL_ACTIVITY_LIKE_TERMINAL_UNKNOWN`。2026-08-10 只读实测确认面板显示“已成功参与”、外层点赞仍未点亮，且模态框结构为 `.bili-popup__header__close` + `iframe[src*="/h5/lottery/result"]`；关闭控件后 iframe 数量为 0、遮罩不可见。结合旧代码在弹窗仍打开时使用 `force=True` 的调用顺序，判断点赞事件未可靠落到被遮挡的外层控件。现已改为先关闭并验证弹窗，再执行普通点击；无法关闭时停止且不点赞。
- 配置改为 `BILI_OFFICIAL_AUTOMATION_DELAY_MIN_SEC=3` 与 `BILI_OFFICIAL_AUTOMATION_DELAY_MAX_SEC=5`；每个非末尾终态条目完成后重新生成一次区间内随机延时。

接口契约 `OFFICIAL-PARTICIPATE-WRITE-001` 暂时标记为 `STALE`：旧参与点击已有真实证据，但“参与成功后动态点赞并以点赞作为跨运行标记”的新组合路径尚需一次受控人工审查。完成该审查前，不得使用运行 #15 的旧证据宣称新规则已获生产验证。

本阶段离线验收：后端 `98 passed, 2 skipped`，Ruff、Mypy、7 项接口契约审计、前端 `5 passed`、TypeScript 类型检查和生产构建全部通过。Windows 目录包已经重建并实际启动；恢复旧版面板终态兼容分支、运行 #16 的异步渲染时序，以及运行 #19 的弹窗遮挡点赞问题后，临时端口 8799 的健康接口返回 `ok=true`、首页 HTTP 200 且包含应用根节点，打包静态资源包含新的弹窗关闭说明。测试进程已关闭，8787 与 8799 端口均已释放。当前 EXE SHA-256 为 `81051D32B81ED4E6079C21C6B0E286F9009E239C77A3718C5D77A5FDFD01E7B3`。

## 2026-08-10 运行 #20 官方新规则验收与来源专栏自动收尾（当前实现）

运行计划 #20、发现快照 #36 已由用户人工审查通过。23 条官方动态全部进入安全终态：20 条为兼容路径 `ALREADY_PARTICIPATED` 且零业务按钮点击，1 条为 `LOTTERY_EXPIRED`，2 条为 `OFFICIAL_PARTICIPATION_CONFIRMED`。后两条动态 `1229961252141268994`、`1230812226883944467` 均完成“参与成功 → 关闭抽奖弹窗并确认 iframe 移除 → 普通点击动态点赞 → `.is-active` 终态确认”。脱敏证据为 `tests/fixtures/contracts/OFFICIAL-PARTICIPATE-WRITE-001/automation-run-2026-08-10-run20.json`，`OFFICIAL-PARTICIPATE-WRITE-001` 恢复为 `WRITE_TEST_PASSED`。

本阶段新增 `backend/use_cases/source_like_automation.py`，替代正常应用中的来源收尾人工确认流程。运行最后一个活动成为终态后，`RunExecutionService` 才调用该模块。目标只取不可变运行计划 `source_article_ids_json` 中经 `source_closure.py` 计算为 `ready_to_mark` 的来源，必须同时满足：来源发现时为未点赞、存在关联活动、全部关联活动为 `completed/skipped`、开放问题数为 0、URL 为 `https://www.bilibili.com/read/cv数字`，且单轮不超过默认上限 10。

每个合格来源在首次写入前随机等待 3–5 秒，随后复用 `DomSourceLikeTransport`：先检查是否已经 `.is-active`，已点赞则零点击完成；否则要求唯一点赞按钮、普通点击一次并复核 `.is-active`。成功后在同一持久化阶段把 `SourceArticle.like_state` 更新为 `liked`，运行证据写入 `stats_json.sourceLikeAutomation.writes`。未知、明确失败或上次在 `running` 状态中断都会记录来源专栏规范 URL，运行进入人工复核，当前来源禁止自动重试且不写本地已点赞状态。

正常应用不再暴露 `/api/runs/{run_id}/source-like-plan`、`/confirm` 和 `/execute` 路由，前端删除“确认来源收尾计划（仍不点赞）”按钮及确认文案。旧 `source_like_plan.py`、`source_like_execution.py`、单目标 allowlist 和确认短语仅保留为历史受控写测试与离线回归代码，不再构成应用入口。

可配置项：`BILI_SOURCE_LIKE_AUTOMATION_ENABLED=true`、`BILI_SOURCE_LIKE_AUTOMATION_DELAY_MIN_SEC=3`、`BILI_SOURCE_LIKE_AUTOMATION_DELAY_MAX_SEC=5`、`BILI_SOURCE_LIKE_AUTOMATION_MAX_ITEMS_PER_RUN=10`。来源自动挂接路径当前仅完成离线编排测试，尚未执行新的真实来源写入，故 `SOURCE-LIKE-WRITE-001` 暂标 `STALE`，下一步必须人工审查真实自动收尾，不得把 2026-08-09 的单目标手工测试当作新编排已验收。

本阶段验证基线：后端 `105 passed, 2 skipped`、Ruff、Mypy（92 个后端文件）、前端 `6 passed`、TypeScript 类型检查、生产构建和 7 项接口契约审计通过。新增测试覆盖自动成功与幂等、开放问题不调用 transport、未知终态记录问题且不重试、配置关闭不写入、官方整轮结束后自动来源收尾的集成路径、中断记录禁止重试，HTML 不再显示第二次来源人工确认，以及旧 `/source-like-plan*` 路由未暴露。

Windows 目录包已重建并实际启动：临时端口 8799 的 `GET /api/health` 返回 `ok=true`，首页包含应用根节点，OpenAPI 保留 `/api/runs/{run_id}/start` 且旧来源人工路由数量为 0，包内静态资源包含 `SOURCE-LIKE AUTOMATION`。测试进程已关闭，8799 已释放。`dist/BiliLotteryAssistant/BiliLotteryAssistant.exe` 的 SHA-256 为 `CAF8070528FAFA60519F032FEEEC689947D2B8729D4E60F65D8ECED65BE9859A`。

## 2026-08-10 双来源专栏启动范围修复（当前实现）

运行 #22、#23 的不可变快照各包含两个来源专栏 `[15,16]` 和 31 条去重官方动态。旧默认上限 25 在 `/start` 的启动前校验中拒绝该合法范围，导致运行保持 `confirmed_waiting_user`；当时尚未打开浏览器或操作 B 站。

当前代码已删除 `official_automation_max_items_per_run`、`BILI_OFFICIAL_AUTOMATION_MAX_ITEMS_PER_RUN` 和 `OFFICIAL_AUTOMATION_RUN_TARGET_LIMIT_EXCEEDED`。官方条目数量不设上限，空范围、非数字 ID、计划外目标、未确认运行和含阻塞项运行仍然失败关闭；执行仍为单页串行、条目间随机等待 3–5 秒，未知终态仍停止且不重试。来源收尾的最多 10 个来源限制保持不变。

回归测试构造两个来源和 31 条官方目标，确认启动进入 `queued` 且校验期间浏览器零调用；策略测试另验证 1000 条合法 ID 可授权。正式数据库只读复核显示当前策略对 #22、#23 均授权 31 条。最终基线为后端 `107 passed, 2 skipped`、Ruff、Mypy（92 个文件）、前端 `6 passed`、TypeScript 生产构建和 7 项契约审计通过。新版 Windows EXE 已隔离冒烟验证，SHA-256 为 `50262DC0E510E3710DED4344D49BC4407A09AC9037A172524B6581C4A72CF07C`。

## 2026-08-10 发现完成后自动生成执行计划（当前实现）

发现任务现在在同一个 `JobRunner` 回调中先等待 `DiscoveryService.execute()` 完成，再调用独立的 `AutomaticExecutionPlanService`。服务从本轮实际活动来源关系读取候选数：大于 0 时自动创建一个 `awaiting_confirmation` 计划，等于 0 时记录 `skipped_no_candidates` 且不创建空 `Run`。同一发现快照重复触发时复用已有计划。

发现统计保存 `automaticPlanState`、`automaticPlanCandidateCount`、`automaticPlanRunId` 或 `automaticPlanErrorCode`；发现详情响应增加 `runPlanId`。前端已删除“生成执行计划（不打开动态）”按钮与 `createRunPlan()`，通过 `run.plan_created` 自动显示计划，并为无候选和失败订阅 `discovery.plan_skipped`、`discovery.plan_failed`。计划仍需用户显式确认，自动衔接不打开候选动态也不启动执行。

新增测试覆盖有候选创建、零候选跳过、幂等复用、脱敏失败状态、发现先于计划、前端自动加载和无候选提示。验证基线为后端 `111 passed, 2 skipped`、Ruff、Mypy（93 个文件）、前端 `7 passed`、TypeScript 生产构建和 7 项契约审计通过。Windows 包隔离冒烟正常，旧按钮文案未进入包内资源；EXE SHA-256 为 `55032EF267E109B4E3DDF3283BC654CA255374B5D9FCDC48F13FE81908904EAE`。

## 2026-08-10 非官方真实样本结构识别与加码分流（当前实现）

用户授权以 `https://www.bilibili.com/opus/1234577521676124161`（`cv52207798`）作为非官方抽奖只读参考。本次实际读取三种代表页面，没有评论、转发、点赞或关注：普通样本 `1234492144127836163`、带“分享你的 EC6 清凉小妙招”指定评论要求的样本 `1233348009982427170`，以及加码外层转发样本 `https://t.bilibili.com/1234423607216570384`。转发弹窗只打开用于读取结构，随后通过关闭控件退出，未点击“发布”。脱敏证据位于 `tests/fixtures/contracts/UNOFFICIAL-PAGE-READ-001/evidence-2026-08-10-cv52207798.json`。

新增 `backend/activity_engine/unofficial/page_evidence.py`，仅在正式执行当前条目时读取 DOM，不批量预检。普通正文优先取 `.opus-module-content`；加码页面外层要求取 `.bili-dyn-content__forw__desc[data-orig="0"]`，并以 `.bili-dyn-content__orig.reference` 证明存在内层原动态。分类器不再要求页面明确出现“加码”二字：只要存在该双层结构，就输出 `unofficial/boosted`、`high` 置信度与 `BOOSTED_FORWARDED_OUTER_DYNAMIC`。要求解析始终使用外层正文，禁止混入内层原动态或评论区其他用户文字。

要求解析拆分为 `requirements/numbers.py`、`requirements/comment_rules.py` 与 `requirements/parser.py`，新增中文数字、反向人数表达、20 人安全上限，以及“分享你的……、聊聊……、说说……”等隐式评论语义。动作计划现在按结构分流：普通为 `comment → repost → like → follow`，策略 `comment_with_repost_checkbox`；加码为 `repost → comment → like → follow`，策略 `repost_then_comment_outer_dynamic`，目标固定为外层当前动态。HTML 运行快照展示策略、DOM 证据、指定评论、动作要求与检查点顺序。

接口登记新增 `UNOFFICIAL-PAGE-READ-001` 和 `COMMENT-COMPONENT-DOM-READ-001`。后者记录 open Shadow DOM 链 `bili-comments → bili-comments-header-renderer → bili-comment-box → bili-comment-rich-textarea → .brt-editor`、发布按钮文本、`bili-checkbox`，以及加码转发弹窗的编辑器/发布/关闭选择器。两个契约只证明读取结构，不能作为写入通过证据。

本阶段仍保持非官方写入关闭：没有 DeepSeek Key 管理、评论生成、评论发布、转发发布、动态点赞或关注 transport，也没有对任何真实非官方动态执行写测试。遇到未点赞非官方目标时只生成可审查策略并停在本地等待状态。

仅含非官方条目的计划现在可以在没有官方目标和官方执行服务的情况下进入本地执行队列；界面统一显示“开始执行计划”，仅官方计划仍显示“开始官方自动执行”。这项修正没有启用非官方写操作。

最终验证为后端 `122 passed, 2 skipped`、Ruff、Mypy（96 个文件）、前端 `8 passed`、TypeScript 类型检查、生产构建和 9 项网页接口契约审计通过。Windows 目录包已重新构建；隔离端口 8799 的 `GET /api/health` 返回 `ok=true`，首页 HTTP 200 且包含应用根节点，OpenAPI 保留 `/api/runs/{run_id}/start`，包内前端同时包含 `repost_then_comment_outer_dynamic` 和“开始执行计划”。测试 PID 已按可执行文件路径核对后关闭，8799 已释放，8787 未被操作。当前 EXE SHA-256 为 `CDCD0729E9F8C6C3BEB90C0CE8051C48BB7232187F16FCB4DB4C478642DD8744`。

## 2026-08-11 非官方 DeepSeek 评论与点赞短路逻辑（当前实现）

本次修改依据用户提供的油猴脚本，把非官方处理逻辑补齐为：

1. 运行时读取动态右侧点赞状态。`.is-active`、`aria-pressed="true"`、`data-state="active"`、`data-liked="true"` 和 `liked` 类均作为 active 证据；已点赞直接返回 `ALREADY_LIKED_SKIPPED`，不调用 DeepSeek，也不执行评论、转发、点赞或关注。
2. 分类器继续自动区分普通动态和“转发加码抽奖”：普通正文为 `comment → repost → like → follow`，转发叠层/加码为 `repost → comment → like → follow`，后者始终以外层动态为写入目标。
3. 新增 `backend/integrations/deepseek/client.py` 和 `backend/api/routes/settings.py`。应用生产路径注入 `DeepSeekCommentGenerator`，调用首页设置表单中的 API 地址和模型，默认地址 `https://api.deepseek.com/chat/completions`、模型 `deepseek-v4-flash`；超时、网络、408/425/429/5xx 和空响应最多重试 3 次，等待 2/5 秒。API Key 只在当前本地服务进程内保存，不进日志、HTML、运行计划或数据库。
4. DeepSeek 的上下文只来自 `ActivitySnapshot.actionable_text`，最多 4000 字；输出会清理代码围栏、引号、换行并限制 80 字。发布前由 `RequirementParser` 补上正文要求且尚未存在的话题标签，以及首页设置表单中前 N 个固定账号，名称最多 3 个。超过 3 个或超过解析上限时返回 `COMMENT_MENTION_MAPPING_EXHAUSTED`/`COMMENT_MENTION_LIMIT_EXCEEDED`，transport 零调用。
5. DeepSeek 生成失败、Key 未配置或返回空评论均在首个 B 站写操作前进入 `blocked_failed`，记录安全错误和问题网址；写入后的未知终态仍沿用 `manual_review_no_retry`。
6. `unofficialParticipationWrites[activityId]` 额外保存 `commentSource`、`activityContext`（截断 4000 字）、`requiredTopics`、`requiredMentionCount` 和 `mentionNames`，HTML 结果区显示评论草稿来源与内容。运行计划响应新增 `deepseekConfigured`，只返回布尔值。
7. 评论发布后的终态判定已调整：唯一发布按钮点击完成且未抛出异常即返回 `COMMENT_SUBMIT_ACCEPTED`，不再等待新评论进入 `bili-comments` 或等待成功提示；这是针对 B 站评论异步展示的刻意例外。转发、点赞和关注仍保留各自的 DOM 终态复核，发布点击异常仍返回 `COMMENT_SUBMIT_UNKNOWN`。

环境配置示例（Key 和固定账号改在首页 HTML 设置表单输入）：

```powershell
$env:BILI_DEEPSEEK_TIMEOUT_SEC = "30"
$env:BILI_DEEPSEEK_MAX_ATTEMPTS = "3"
```

未进行真实 B 站非官方写入；已授权动态 `https://www.bilibili.com/opus/1234865782700113928` 被隔离为单条运行计划 #35，已完成计划确认但尚未开始写入，因为当前服务没有 DeepSeek Key。最新 Windows 目录包 EXE SHA-256：`BF49A27F65E54E47676FC5571F8450B28F33C711DABBB65071040D6F6994CC98`。

## 2026-08-11 前端设置与授权动态测试状态

- 首页新增“DeepSeek 与非官方账号设置”表单，支持 API Key、API 地址、模型和最多 3 个固定 @账号；默认值为油猴脚本中的“你的抽奖工具人、哔哩哔哩弹幕网、哔哩哔哩足球赛事”。
- `POST /api/settings` 只在本地进程内更新 `Settings`；Key 不回显、不进入运行计划、SQLite、日志或问题记录，服务重启后需重新输入。
- `BILI_UNOFFICIAL_AUTOMATION_ENABLED` 默认值为 `true`；设置表单保存与 `deepseekConfigured` 状态已通过本地 HTML 页面验证。
- 用户授权动态已被单独加入运行计划 #35，运行范围只有 `1234865782700113928`；只读页面确认当前未点赞，正文包含“转赞评+关注”及 3 个话题标签，识别为非官方普通动态。
- 真实评论、转发、点赞、关注尚未执行。当前唯一阻塞是本地设置表单尚未输入 DeepSeek Key；输入并保存后，应从计划 #35 继续启动，任何失败/未知终态仍会停止且不重试。

## 2026-08-11 非官方评论、转发、点赞、关注真实执行与终态确认（历史基线；已由后续 DeepSeek 章节更新）

本阶段将原先“只读动作计划”接入独立的 `DomUnofficialTransport` 和 `UnofficialParticipationExecutionService`。应用创建运行计划后仍不会打开候选动态；只有用户确认计划并点击“开始执行计划”，运行器才逐条打开动态并产生外部写操作。没有对本轮真实 B 站动态执行写入，新增测试全部使用脱敏 DOM/transport 假对象。

### 执行顺序

| 分类 | 目标页面 | 顺序 | 说明 |
|---|---|---|---|
| `unofficial/normal` | 当前 `www.bilibili.com/opus/<id>` | `comment → repost → like → follow` | 评论框填写确定性文本；勾选 `bili-checkbox[value="sync"]` 后，评论成功同时确认转发检查点，不再重复打开转发弹窗。 |
| `unofficial/boosted` | 外层 `t.bilibili.com/<id>` 或外层 opus | `repost → comment → like → follow` | 点击外层转发控件，使用转发弹窗发布；随后只对外层动态评论，不能把内层原动态当目标。 |

### DOM 控件和终态

- 动态点赞：`.side-toolbar__action.like`；开始前若 `.side-toolbar__action.like.is-active` 可见，返回 `DYNAMIC_ALREADY_LIKED`，不点击；点击后必须看到 active 标记，否则 `DYNAMIC_LIKE_TERMINAL_UNKNOWN`。
- 评论：`bili-comments bili-comment-box bili-comment-rich-textarea .brt-editor`、评论框内文本为“发布”的唯一按钮；同步转发控件为 `bili-checkbox[value="sync"]`。填写评论后等待最多 6 次轮询，直到同步转发控件恰好一个可见，兼容 Shadow DOM 中旧/新复选框短暂并存；持续不唯一才返回 `COMMENT_REPOST_CONTROL_NOT_UNIQUE`。点击唯一发布按钮未抛出异常即返回 `COMMENT_SUBMIT_ACCEPTED`，不再等待评论列表或成功提示，因为 B 站新评论可能异步展示；发布点击本身异常仍返回 `COMMENT_SUBMIT_UNKNOWN`。
- 加码转发：`.side-toolbar__action.forward`、`.bili-dyn-share__wrap`、`.bili-rich-textarea__inner`、`.bili-dyn-share-publishing__action.launcher`。发布后必须同时看到弹窗关闭和“转发成功/动态发布成功/已转发”证据，否则 `REPOST_TERMINAL_UNKNOWN`。
- 关注：先从动态作者 `.opus-module-author__name` 与正文 `a.opus-text-rich-hl.at` 等可见 `a[href*="space.bilibili.com/"]` 链接中匹配作者名称（兼容 `@作者`），若得到唯一数字 UID，直接打开 `https://space.bilibili.com/<mid>`；只有旧版动态没有直接作者链接时才访问 `https://search.bilibili.com/upuser?keyword=<名称>` 作为后备，并只接受唯一精确匹配。个人页是异步渲染 SPA，进入后会等待最多 6 次轮询直到 `.space-follow-btn` 恰好一个可见，避免首个 DOM 快照出现 0/重复控件而提前返回 `FOLLOW_CONTROL_NOT_UNIQUE`。按钮显示“已关注/互相关注”返回 `FOLLOW_ALREADY_DONE`，点击“关注”后必须变为已关注，否则 `FOLLOW_TERMINAL_UNKNOWN`；6 次后仍不唯一才返回 `FOLLOW_CONTROL_NOT_UNIQUE`。

所有写操作都要求控件唯一且可见。评论发布只要求唯一按钮点击完成；转发、点赞、关注仍要求各自终态。点击异常、页面出现登录/验证码/安全验证、弹窗未打开或这些终态无法证明，均记录 `unknown`/`failed` 检查点，设置 `requiresManualReview=true`，写入问题网址，当前条目保持 `waiting_user`，不会自动重试。已确认或 `already_done` 的检查点可继续；普通评论返回 `confirmed_actions=("repost",)`，因此转发检查点以同步转发终态完成。

### 非官方兜底分类（2026-08-11）

此前分类器在没有官方入口且正文暂时没有“评论/转发/关注”文字时返回 `CLASSIFICATION_UNKNOWN`，导致部分确实属于非官方流程的动态被错误停在人工复核。现已调整为：

1. `a[data-type="lottery"]` 或 HTML 中的 `data-type="lottery"` 存在时，判定为 `official`；官方判断优先级最高。
2. 只要未检测到官方入口，统一判定为 `unofficial`；正文要求不再是非官方顶层分类的必要条件。
3. 转发原动态结构 `.bili-dyn-content__orig.reference` 仍直接判定 `boosted`；“加码/翻倍/额外奖励/转发加码”仍作为文字加码证据；其余情况为 `normal`。
4. 未检测到官方入口且没有正文要求时，分类置信度为 `low`，证据码为 `NON_OFFICIAL_FALLBACK_NO_OFFICIAL_ENTRY`，但不会再产生 `CLASSIFICATION_UNKNOWN`。这只改变类别路由，不改变控件唯一性、登录/风控、写入终态未知时的人工复核和禁止重试规则。

新增回归测试覆盖空正文无官方入口时的 `unofficial/normal` 兜底分类。

### 评论和安全边界

评论文本优先使用页面解析出的指定评论语义；没有指定语义时使用 `BILI_UNOFFICIAL_COMMENT_DEFAULT`（默认“参与抽奖，感谢分享！”），不会调用 DeepSeek。检测到 `requiredMentionCount > 0` 或超过 20 个 @ 要求时，在第一次写入前返回 `COMMENT_MENTION_REQUIRED`，不猜测好友账号、不发送半成品评论。非官方动作间隔由 `BILI_UNOFFICIAL_AUTOMATION_DELAY_MIN_SEC`/`MAX_SEC` 控制，默认随机 1–2 秒；作者搜索回退页打开后同样随机等待 1–2 秒，再匹配唯一精确作者。

### 持久化和接口

`Run.stats_json.unofficialParticipationWrites[activityId]` 保存动作顺序、评论文本、每个检查点、结果码、开始/结束时间和 `unknownResultPolicy=manual_review_no_retry`。`POST /api/runs/{run_id}/start` 和 `/resume` 仍需要 CSRF；运行响应增加 `unofficialAutomationEnabled` 与 1–2 秒配置字段。任何 `running`、`blocked_unknown` 或 `blocked_failed` 写记录再次调用都会返回 `UNOFFICIAL_PARTICIPATION_WRITE_TERMINAL_NO_RETRY`。

新增 `tests/unit/test_unofficial_transport.py` 和 `tests/integration/test_unofficial_participation_execution.py`，覆盖点赞 active 终态、评论同步转发、加码转发弹窗、动态作者链接直达个人页、无直接链接时的搜索后关注、评论填写后复选框瞬时重复、未知结果持久化/禁重试、@ 提及预阻断以及运行器端到端串行执行。监测中发现动态评论组件可能短暂同时保留两个可见候选，已将写入选择器限定为 `.brt-editor[contenteditable="true"]`，并在写入前等待最多 6 次轮询直到恰好一个可见编辑器；同步转发复选框也在填写后等待最多 6 次直到唯一可见，持续不唯一仍安全失败。随后发现运行器曾用完整页面文本解析非官方评论要求，可能把评论区/工具栏计数生成成评论内容，现已统一改用 `ActivitySnapshot.actionable_text`，只解析当前动态正文；本次又取消评论发布后的评论列表复检，发布按钮点击完成返回 `COMMENT_SUBMIT_ACCEPTED`；个人主页关注控件同样增加最多 6 次唯一可见轮询，避免 SPA 水合期间首个快照误报 `FOLLOW_CONTROL_NOT_UNIQUE`；结果表改为优先显示已持久化的写入检查点，不再把预执行快照当作当前下一步；作者搜索回退页打开后新增随机 1–2 秒等待，避免异步搜索结果尚未水合时误报作者不唯一。当前验证：后端 `148 passed, 2 skipped`，Ruff、Mypy（102 个文件）、前端 `9 passed`、TypeScript 类型检查、Vite 生产构建通过；2026-08-11 本地服务健康接口连续监测返回 `ok=true`，首页复查确认已展示非官方真实写入边界，修正了过期的“不会自动评论”文案。Windows 目录包已按修复后的静态资源、动作 1–2 秒延时、搜索等待、选择器、关注等待、直达个人页和结果表逻辑重建，EXE SHA-256 为 `18D872CDC5FDA9D44EF0E78F2ED6A7D2E76AB0D37B9A7D87E8AB8538BC9C8E98`。真实 B 站写测试仍需用户在界面确认目标和运行计划后单独进行。

## 2026-08-12 加码抽奖统一使用评论同步转发（当前实现）

加码分类仍保留在分类证据、运行快照和 DeepSeek 上下文中，但普通与加码计划现在都使用 `comment_with_repost_checkbox`，目标均为当前动态。实际写入顺序统一为：评论并勾选“同时转发到我的动态” → 点赞 → 关注作者；计划中的 `repost` 仅作为评论同步转发产生的副作用检查点，由评论成功返回的 `confirmed_actions=("repost",)` 自动确认，不再单独打开转发弹窗。新增加码计划回归测试确认 transport 调用序列只有 `comment`、`like`、`follow`；后端 `151 passed, 2 skipped`，前端 `9 passed`、TypeScript 检查和生产构建通过。当前 Windows 目录包 EXE SHA-256 为 `5FF3C98E7ECC11A4C07E68C80477DAF89D811BD0212B26689A63234E8B499352`。

## 2026-08-12 加码动态点赞控件结构修复（当前实现）

验证已完成：后端 `152 passed, 2 skipped`，前端 `9 passed`、TypeScript 检查和 Vite 生产构建通过；Windows 目录包 EXE SHA-256 为 `8CFEBD17D6097CD15E480403D965724BD25263CE56CB16AE98ADB6A642697743`。

授权动态 `https://t.bilibili.com/1234841370069303300` 的只读 DOM 显示，实际点赞控件位于 `.content > .sidebar-wrap > .side-toolbar > .side-toolbar__box > .side-toolbar__action.like`；通用 `.side-toolbar__action.like` 在转发动态水合或叠层场景可能同时匹配多个可见节点。非官方 transport 现优先使用外层结构选择器，再回退 `.content .sidebar-wrap .side-toolbar__action.like` 和旧版通用选择器；最多轮询 6 次，只有确认唯一可见外层控件才点击，避免误点转发原动态或水合副本。选择器版本升级为 `unofficial_write_dom_v7-comment-repost-hydration-scoped-like-direct-author-profile`。本次新增重复通用点赞控件回归测试；代码修改后应重新运行后端、前端测试并重建 Windows 包。已有 `DYNAMIC_LIKE_CONTROL_NOT_UNIQUE` 的终态记录不自动重试，必须建立新的运行计划。

## 2026-08-12 加码动态作者识别修复（当前实现）

授权动态 `https://t.bilibili.com/1234841370069303300` 的只读 DOM 显示，发布者名称实际位于 `.bili-dyn-item__header .bili-dyn-title__text`；旧版作者选择器遗漏该节点，导致关注步骤返回 `FOLLOW_AUTHOR_NOT_FOUND`。非官方页面证据与写入 transport 现共享该外层 header 选择器，作者名最多轮询 6 次；加码动态不会读取 `.bili-dyn-content__orig.reference` 内层原作者作为关注目标。选择器版本升级为 `unofficial_page_evidence_v2-author-header` / `unofficial_write_dom_v8-comment-repost-hydration-scoped-like-author-header`。新增页面证据和 transport 回归测试；后端 `153 passed, 2 skipped`，Ruff、Mypy（102 个文件）、前端 `9 passed`、TypeScript 检查和 Vite 生产构建均通过；Windows 目录包 EXE SHA-256 为 `88C933346FA4D96AF6AF959C96083122B91458B40B22DBFC45A9D4EAA9B84A94`。旧的 `FOLLOW_AUTHOR_NOT_FOUND` 终态不自动重试，必须建立新的运行计划；若旧条目的评论/同步转发已成功，重跑前需防止重复写入。

## 2026-08-13 Windows 桌面启动与页面生命周期（当前实现）

`BiliLotteryAssistant.exe` 现在负责完整桌面生命周期：启动前识别 8787 上是否已经存在本助手；已有实例时只打开其页面，其他程序占用时拒绝抢占；端口可用时启动 Uvicorn，监听成功后自动调用默认浏览器打开 `http://127.0.0.1:8787/`。HTML 页面用带本机会话令牌的 WebSocket 连接 `/api/desktop/lifecycle`，后端按连接数判断页面存活状态。关闭最后一个页面后进入 3 秒宽限期，若没有页面重新连接则设置 Uvicorn `should_exit`，依次取消后台任务、关闭 Playwright、释放 SQLAlchemy 连接并退出进程；页面刷新会在宽限期内重新连接，因此不会被当作关闭。当前发现 ID 同时写入当前标签页的 `sessionStorage`，F5 后会重新读取发现、问题和关联执行计划；该存储不包含 API Key 或 B 站数据。多标签页时只有最后一个连接断开才会退出。

新增桌面生命周期、WebSocket 鉴权、刷新重连、F5 工作区恢复、多页面、重复启动和非助手端口占用测试。最终验证为后端 `163 passed, 2 skipped`、Ruff、Mypy（106 个后端文件）、前端 `11 passed`、TypeScript 检查和 Vite 生产构建通过。隔离端口 8799 对源码和 Windows 目录包完成启动、HTML/静态资源加载、WebSocket 连接和端口释放测试；最新打包资源已确认包含 F5 恢复键。最后一次自动打开测试还确认真实浏览器页面会作为第二个客户端阻止测试客户端单独关闭服务，符合“最后一个页面关闭才退出”；测试 EXE 已按精确路径终止，8787/8799 当前均无监听。最新目录包 EXE SHA-256 为 `E94B13F5901B5500472BF457BFA971F7D8955F225B84FFC88A2C6E0DEFF82F19`。

## 2026-08-13 登录页唯一实例与关闭重开（当前实现）

原浏览器管理器把登录页和自动化工作页共同保存到 `_page`，且只用 `_context is not None` 判断浏览器是否可用。用户关闭登录页或关闭最后一个浏览器页面后，Playwright 上下文可能已经失效，但旧引用仍会阻止重新启动，导致后续 `/api/account/open-login` 在已关闭上下文上失败。

当前 `BrowserManager` 分别管理未分配初始页、自动化页和唯一登录页，并监听 Page/BrowserContext 的 `close` 事件及时清除对应引用。每次操作前通过 `context.cookies()` 验证上下文实际存活；关闭的上下文会用同一持久化用户配置重新启动。登录页仍存在时只调用 `bring_to_front()`，不再次导航也不创建标签；关闭后使用空闲初始页或 `new_page()` 重开。所有页面分配都经过一个 `asyncio.Lock`，因此快速连点或并发请求也只能创建一个登录页。登录页与自动化页不再互相导航。前端按钮在请求进行期间禁用，完成后刷新浏览器就绪状态，提示“已打开或已切换至前台”。

新增 5 项浏览器管理器回归测试，覆盖重复点击、同一上下文关闭重开、最后页面关闭后上下文重启、5 个并发请求和登录/自动化页面隔离。真实 Edge 使用临时隔离配置验证结果为：首次 1 页、重复点击仍为 1 页、关闭后返回新 Page、两个并发请求仍返回同一页。完整验证为后端 `168 passed, 2 skipped`、Ruff、Mypy（106 个后端文件）、前端 `11 passed`、TypeScript 检查和 Vite 构建通过；Windows 目录包已重建，包内前端确认包含防重复提示。最新目录包 EXE SHA-256 为 `43B209A7E70407AC40659D5E3477784EFF405F19CC964A94D62D3EBFC93540F0`。
