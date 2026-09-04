# 业务 Agent 从 0 到 1 构建指南

> 定位：**通用范式指南**，不绑定任何具体业务域。主体章节讲的是"任何业务 Agent 都适用"的构建方法；每章结尾的 `▸ 落到本项目` 是**唯一**把范式映射到具体项目的地方。
> 阅读方式：每章开头一行「本章你会理解：…」；正文中所有代码都是**骨架**，函数体留给你实现；每段代码后有「设计说明」。动手节奏：读完 §1、§2 → 跟 §4 一步步敲 → 卡住时回查 §3 对应小节（§3 每节四段固定：设计要点 / 接口契约 / 实现提示 / 自测方法）。
> 技术选型基线（三处可整体替换的选择）：Function-Calling Loop + LLM 官方 SDK + `response_format=json_schema`（或 SDK 对应机制）+ 主 LLM 自选 Skill。换 SDK 时只有 §3.1、§3.2、§3.5 里的调用姿势需要局部改，控制流不变。

---

## 1. 心智模型

**本章你会理解**：一个 Agent 到底由哪四样东西组成、一次用户提问在系统里怎么流动。

### 1.1 Agent 的最小定义

> Agent = **LLM**（会推理和挑工具的大脑）+ **Tools**（能被大脑调用的外部能力）+ **Loop**（把"想 → 做 → 观察 → 再想"串起来的控制流）+ **State**（跨轮/跨步的记忆与上下文）

四者缺一就退化：缺 Loop → 单轮问答；缺 Tools → 只会闲聊；缺 State → 无法追问；缺 LLM → 只是普通脚本。

### 1.2 ASCII 架构图

```
     ┌─────────────┐   user_question
     │   Caller    │───────────────────────┐
     └─────────────┘                       ▼
                              ┌────────────────────────┐
                              │      AgentRuntime      │
                              │  ┌──────────────────┐  │
                              │  │       Loop       │  │
                              │  └──┬────────────┬──┘  │
                              │     │            │     │
                     ┌────────┼─────▼──┐    ┌────▼──┐  │
                     │ SessionMemory   │    │ LLM   │  │
                     │ (state, 跨轮)    │    │ (SDK) │  │
                     └────────┼────────┘    └───┬───┘  │
                              │                 │      │
                              │        tool_use │      │
                              │            ┌────▼────┐ │
                              │            │Executor │ │
                              │            └────┬────┘ │
                              └─────────────────┼──────┘
                                                ▼
                                         ┌─────────────┐
                                         │ ToolRegistry│──► 外部数据源 / 只读服务
                                         └─────────────┘
```

### 1.3 一次请求的数据流（≤ 25 行）

```
1.  Caller 调用 AgentRuntime.handle(session_id, user_question)
2.  Runtime 从 SessionMemory 取上下文（跨轮 state：用户身份/上次结论/候选项）
3.  Runtime 组装 messages = [system_prompt, *history, user_question]
4.  ── 进入 Loop ──
5.  Runtime 调用 LLM(messages, tools=all_tool_schemas)
6.  LLM 返回：
      a) 一或多个 tool_call（含 name + args）  → 走 7
      b) 无 tool_call，stop_reason=end_turn    → 走 12
7.  Runtime 逐个通过 ToolExecutor 执行 tool_call
8.  Executor 校验入参 → 调 Tool.run() → 读外部数据源 → 得到 dict
9.  Runtime 把 tool_result 塞回 messages
10. iteration += 1；未超上限 → 回到 5
11. 超过上限或异常 → 走 12（携带失败标记）
12. Runtime 用 response_format=json_schema 再问 LLM 一次，产出结构化最终答案
13. Runtime 校验/持久化 trace → 更新 SessionMemory → 返回给 Caller
```

**关键**：第 5 步和第 12 步是**同一个 LLM 但不同调用模式**——中间轮用 `tools=`，终轮用 `response_format=json_schema`。这是本指南采用的两阶段范式，§3.2 和 §3.5 会细讲。

### ▸ 落到本项目

- LLM ⇢ OpenAI SDK；Tools ⇢ `agent/tools/*.py`；Loop ⇢ `agent/agent.py::AgentRuntime`；State ⇢ `agent/memory.py::SessionMemory`。
- Tool 层能拿到的**唯一数据来源**是 `SnapshotService`；`k8s_client` 对 Agent 层不可见（架构上物理隔离）。

---

## 2. 组件清单

**本章你会理解**：这个 Agent 层有几个组件、哪些是 MVP 必须、哪些是常见坑。

| 组件 | 职责（一句话） | MVP 必需? | 典型坑 |
|---|---|---|---|
| `LLMClient` 封装 | 收敛 SDK 调用 + retry + 日志 | ✅ | 直接在 Loop 里裸调 SDK → 换模型/加 trace 到处改 |
| `Tool` 基类 | 单能力 + JSON schema + `run()` | ✅ | schema 手写偏离 pydantic 定义 → 参数校验形同虚设 |
| `ToolRegistry` | name → Tool 映射 + 汇总 schema 给 LLM | ✅ | Registry 兼职执行 → 循环依赖、难测 |
| `ToolExecutor` | 参数校验 + 调用 + 异常→Observation | ✅ | 抛异常给 Loop → LLM 拿不到错误无法自纠 |
| `AgentRuntime` | Loop 编排、轮次上限、终止条件 | ✅ | 无 max_iterations → 死循环烧钱 |
| `SessionMemory` | 跨轮上下文（**不存高频变化的事实**） | ✅ | 存下轮就过期的字段 → 每次都看过期数据 |
| `Skill` | 领域知识（prompt + allowed_tools + output_schema） | ✅ | Skill 直接调 Tool，绕过 Executor → 观测缺失 |
| `SkillLoader` | 把可用 Skill 描述拼进 system prompt | ✅ | 提前用小模型分类 → 多一次调用 + 分错就断链 |
| `AgentDecision` schema | Agent 与 UI 的契约 | ✅ | 无 Evidence 强字段 → LLM 幻觉数字 |
| Tracer / Recorder | 记录一次 run 的完整 trace | 🟡 建议 | 只 print → 事后无法回放 |
| Reflection / Self-Critique | LLM 自我审查再改一次 | ❌ 后置 | MVP 阶段引入 → 成本收益不明 |
| Planner（独立规划步） | 提前生成 step-plan | ❌ 后置 | 路径可预测时无需 |
| 向量记忆 / RAG | 长期知识检索 | ❌ 后置 | 领域知识若能塞进 Skill prompt 就不需要 |

三条原则：**能不加就不加**、**能用普通代码就不用 LLM**、**能确定就别让 LLM 决定**。

### ▸ 落到本项目

- MVP 必需组件全部落在 `agent/` 目录；其余标 ❌ 的暂不建目录不建文件——真需要时再新增。

---

## 3. 逐组件讲解

### 3.1 Tool 抽象与注册表

**本章你会理解**：为什么 Tool 要拆基类 + Registry + Executor 三件套；JSON Schema 从哪里来最省心。

#### 设计要点

1. Tool 只做**一件**明确的、外部可观测的事——查询、检索、计算、调用一个下游服务——不做多因素权衡（那是 Skill/LLM 的活）。
2. **Schema 单一来源**：用 pydantic model 定义参数，schema 由 `model.model_json_schema()` 生成，避免"手写 schema 偏离实际参数"。
3. Registry 只管"有什么"（目录），Executor 只管"怎么跑"（执行）——两者都很薄（各 <100 行）。
4. Tool 抛出的异常**不上升到 Loop**，Executor 捕获并转成结构化 Observation 让 LLM 看见并自纠。
5. Tool.name 必须匹配 `^[a-zA-Z0-9_-]{1,64}$`——主流 LLM 平台都有这个约束，别用中文/点号。

#### 接口契约（骨架）

```python
# agent/tools/base.py
from abc import ABC, abstractmethod
from typing import Any, ClassVar, Type
from pydantic import BaseModel


class Tool(ABC):
    """只读能力单元。子类必须声明 ArgsModel 与 name/description。"""
    name: ClassVar[str]
    description: ClassVar[str]
    ArgsModel: ClassVar[Type[BaseModel]]

    @abstractmethod
    def run(self, args: BaseModel) -> dict:
        """执行；入参已由 Executor 校验为 ArgsModel 实例。返回 JSON-serializable dict。"""
        ...

    @classmethod
    def json_schema(cls) -> dict:
        """给 LLM function-calling 用的 schema。默认由 ArgsModel 生成，子类一般不必覆盖。"""
        ...
```

**这段为什么这么设计**：`ArgsModel` 声明为 `ClassVar[Type[BaseModel]]`，让 pydantic 既做**运行时校验**又做**schema 生成器**——避免"schema 说要 int、run 里当 str 用"的经典 bug。`run(args: BaseModel)` 而不是 `run(**kwargs)`：IDE 类型检查生效，"哪些字段可选/必选"由 pydantic 一处定义。

```python
# agent/tools/tool_registry.py
class ToolRegistry:
    def __init__(self) -> None: ...
    def register(self, tool: Tool) -> None:
        """重名直接抛 ValueError——不要静默覆盖。"""
    def get(self, name: str) -> Tool: ...
    def list_llm_tools(self) -> list[dict]:
        """返回目标 SDK 需要的 tools 参数格式。以 OpenAI 为例：
           [{"type": "function", "function": {"name":..., "description":..., "parameters": <schema>}}]"""
```

**这段为什么这么设计**：`list_llm_tools()` 直接产出 SDK 需要的**外壳格式**，换 SDK 时只改这一处。重名抛异常刻意：Registry 承担"目录唯一性"不变量。

```python
# agent/tools/tool_executor.py
from models.agent import ToolCallRecord   # 见 §3.5：一次工具调用的完整记录

class ToolExecutor:
    def __init__(self, registry: ToolRegistry) -> None: ...
    def execute(self, tool_name: str, raw_args: dict) -> ToolCallRecord:
        """
        1) 从 registry 取 Tool
        2) 用 Tool.ArgsModel 校验 raw_args（失败 → 记录到 record.error，仍返回而不抛）
        3) 调 tool.run(args)，捕获所有异常 → record.error
        4) 返回 ToolCallRecord（含 name / args / result / error / started_at / ended_at）
        # TODO: 你来实现 —— 提示：所有分支都要产出 ToolCallRecord，不要 raise
        """
        ...
```

**这段为什么这么设计**：`execute()` 只在极端情况（name 找不到）时可选择抛或转错回传——**建议转错回传**给 LLM 让它自纠。永远返回 `ToolCallRecord` 有两个好处：Loop 无需 try/except，可观测性完整。

#### 实现提示（你该选哪个）

- **JSON schema 来源**：pydantic `model_json_schema()` vs 手写。选 pydantic——手写会漂移。
- **参数校验失败怎么办**：抛出 vs 塞进 Observation 回传给 LLM。选**回传**——LLM 有能力根据错误信息重试；抛出会中断 Loop 让整轮失败。
- **schema 用 `additionalProperties: false` 吗**：主流 strict 模式都要求。**是**——把宽松性放在 LLM 端不如放在自己端，多余字段直接报错更早发现问题。
- **Tool 里能不能读时间/环境变量/随机数**：默认不能。让 Tool 保持"纯函数"般的可测试性；确需当前时间的场景，把时间作为参数由 Runtime 注入，而非在 Tool 内部读时钟。

#### 自测方法

- **不启动 LLM** 直接 `registry.list_llm_tools()` 打印 → 手动比对是否符合目标 SDK 的 tools 参数规范（放进对应 Playground 试）。
- 单测每个 Tool：造一个 fake 数据源实例，注入 Tool 依赖，断言 `run()` 返回值。
- 单测 Executor：传一个不存在的 tool_name、传缺字段的 args、传能跑通的正常 args——三种情况都应返回 `ToolCallRecord` 而不是抛。

#### ▸ 落到本项目

- `agent/tools/base.py`（Tool 基类）、`tool_registry.py`、`tool_executor.py` 三个文件；已有的 `cluster_tools.py / node_tools.py / incident_tools.py` 只需按上述基类改造，业务逻辑不动。

---

### 3.2 Agent Loop（整个系统的心脏）

**本章你会理解**：Loop 到底怎么写才不会死循环、怎么把 tool_result 塞回去、终轮怎么切成 JSON 输出。

#### 设计要点

1. Loop 有 **4 种终止条件**（缺一都不安全）：`stop_reason=stop`（LLM 自己不再要工具）/ `iteration >= max_iterations` / Executor 连续错误达阈值 / 硬 token 上限。
2. **消息只 append 不修改**——历史是不可变的，方便复现和 trace。
3. Tool 结果回传时要**保留 tool_call_id**（多数 SDK 的字段名类似 `tool_call_id` / `tool_use_id`），否则模型对不上因果。
4. 中间轮**只用 tools=**，终轮**只用 response_format=json_schema**（或等价机制）。混用会把 schema 打乱。
5. `system_prompt` 每轮都是 messages[0]，**不重复拼进去**；许多 bug 来自"每轮把 system 又追加一次"。

#### 接口契约（骨架）

```python
# agent/agent.py
from models.agent import AgentDecision  # §3.5 定义的最终输出 schema（业务字段名按需替换）

class AgentRuntime:
    def __init__(
        self,
        llm,                              # 具体类型由所选 SDK 决定
        skill_loader: "SkillLoader",
        tool_executor: "ToolExecutor",
        memory: "SessionMemory",
        max_iterations: int = 8,
        model: str = "<your-model-name>",
    ) -> None: ...

    def handle(self, session_id: str, user_question: str) -> AgentDecision:
        """入口。内部完成 Loop 编排 + 终轮结构化输出。失败也必须返回一个
        AgentDecision（confidence_note 说明失败原因），不要抛给上游。"""
        ...
```

**这段为什么这么设计**：`max_iterations` 默认 8——对多数业务 Agent，5~6 步已能走完"路由 Skill → 收集事实 → 综合结论"，8 是安全余量；实际值按评估集最长链路 +2 定。**失败也返回结构化对象**：让上游 API 层无需 try/except，UI 层永远拿到可渲染的东西。

#### Loop 骨架（30 行左右，可读性 > 简洁）

```python
def _run_loop(self, messages: list[dict], tool_schemas: list[dict]) -> tuple[list[dict], list["ToolCallRecord"]]:
    trace: list[ToolCallRecord] = []
    for step in range(self.max_iterations):
        resp = self.llm.chat.completions.create(
            model=self.model,
            messages=messages,
            tools=tool_schemas,
            tool_choice="auto",  # 让 LLM 自己决定是否还需要工具
        )
        msg = resp.choices[0].message
        messages.append(msg.model_dump(exclude_none=True))  # 保留 assistant 原样

        if not msg.tool_calls:              # ← 终止条件 A: LLM 不再要工具
            return messages, trace

        for call in msg.tool_calls:         # 逐个执行；顺序即 LLM 声明的顺序
            record = self.tool_executor.execute(call.function.name, _safe_json(call.function.arguments))
            trace.append(record)
            messages.append({
                "role": "tool",
                "tool_call_id": call.id,
                "content": _observation_text(record),  # 成功 → JSON 字符串；失败 → 错误描述
            })
    # ← 终止条件 B: 到达 max_iterations
    return messages, trace
```

**这段为什么这么设计（逐点）**：`messages.append(msg.model_dump(...))` 把 assistant 的 tool_call block 原封写回历史——自己拼简化版会丢 tool_call_id；`tool_choice="auto"` 让 LLM 自然停止，用 required 会强制它每轮都调工具；`_safe_json` 兜住 LLM 返回非法 JSON 的小概率——落入 Executor 走"参数错误"路径而非崩溃 Loop；不在 Loop 内做终轮 JSON——JSON 化是另一次调用。

#### 终轮：改用 response_format 强制 schema

```python
def _finalize(self, messages: list[dict], trace: list["ToolCallRecord"]) -> AgentDecision:
    messages.append({
        "role": "user",
        "content": "请基于以上工具结果，输出最终 AgentDecision（严格遵循 schema）。",
    })
    resp = self.llm.chat.completions.create(
        model=self.model,
        messages=messages,
        response_format={"type": "json_schema",
                         "json_schema": {"name": "AgentDecision",
                                          "schema": AgentDecision.model_json_schema(),
                                          "strict": True}},
    )
    # TODO: 你来实现 —— 提示：把返回文本 json.loads → AgentDecision.model_validate → 补上 trace 字段
    ...
```

**这段为什么这么设计**：中间轮**没有** `response_format`——tools + json_schema 严格模式在多数平台上行为不稳定；把结构化输出隔离到"没有 tool_choice"的一次调用里最稳。终轮再问一次多花 1 次调用，换来 100% 命中 schema，值。

> 注：SDK 调用姿势以 OpenAI Chat Completions 为例。换 Anthropic Messages API：`chat.completions.create → messages.create`；`tool_calls` 字段变为 `content` 里的 `tool_use` block；`tool_call_id → tool_use_id`——**Loop 结构不变**，仅取值路径不同。

#### 实现提示（你该选哪个）

- **max_iterations**：默认 8，视你评估集里最长链路 +2 决定。太小会截断真实推理；太大会烧钱。
- **并行工具调用**：主流 SDK 允许一次返回多个 tool_call；若你的 Tool 都是内存读或本地服务，**同轮内串行执行**即可；若 Tool 是慢网络调用（>200ms），才考虑 asyncio 并发。**顺序按 LLM 声明的顺序**，不要重排。
- **是否把 trace 也塞给终轮 LLM**：不必——tool_result 已经在 messages 里，trace 是给系统日志用的。
- **失败恢复**：Executor 连续 3 次错误 → 跳出 Loop 直接进 `_finalize`，让 LLM 在 `confidence_note` 里说明"信息不足"。

#### 自测方法

- **Mock LLM**：写一个假 `llm.chat.completions.create`，第一次返回 `tool_calls=[<某个 tool>]`，第二次返回 `content="..."` 无 tool_calls；断言 `_run_loop` 走了两轮、trace 长度=1。
- **死循环保护测试**：让 mock 永远返回 tool_calls，断言 `_run_loop` 在 `max_iterations` 后返回。
- **schema 强制测试**：让 mock 在终轮返回一个缺字段的 JSON，断言 `_finalize` 走 pydantic 校验失败 → 触发重试或降级路径。

#### ▸ 落到本项目

- Loop 骨架落在 `agent/agent.py::AgentRuntime._run_loop`；终轮 `_finalize` 是**独立方法**，方便单独 mock 测试。

---

### 3.3 上下文与记忆

**本章你会理解**：短期上下文（消息数组）怎么裁；长期记忆（SessionMemory）到底存什么、不存什么。

#### 设计要点

1. **两类记忆分开**：短期=一次 handle() 内的 messages 列表；长期=SessionMemory（跨轮，进程内 dict 或后端存储）。别混。
2. **SessionMemory 存"稳定 state"，不存"高频变更的事实"**——衰减速度 > 一次会话时长的字段禁存，衰减慢的字段（用户身份、偏好、上次结论摘要、候选项）可存。判断法则见"存不存"表。
3. 短期消息裁剪的目标：Token 预算内、**必保 system + 最近一轮 tool_result + 用户最新问题**。可以删的：早轮的 tool_result（保留 assistant reasoning 的文本描述）。
4. MVP 阶段消息不做智能压缩（不用 summarizer LLM 压历史）——直接按轮次滑窗即可。
5. SessionMemory 存储介质与业务需求匹配：单进程、无跨会话需求 → 内存 dict 即可；跨会话/跨进程/需审计 → 后端 KV 或 DB。**接口不变，仅实现替换**。

#### "存不存进 SessionMemory" 判断法则

判断法则：**字段的"新鲜度衰减速度 > 一次会话时长"就禁存；否则可存**。

| 字段类型 | 建议 |
|---|---|
| 用户身份、租户 ID、语言/主题偏好 | ✅ 稳定，跨会话有效 |
| 上次结论的**摘要**、候选方案列表 | ✅ 支持"第二个方案呢"追问 |
| 当前锁定的实体 ID | ✅ 会话中通常不变 |
| 实时业务指标、状态字段、库存数 | ❌ 下轮可能过期，用 Tool 现取 |
| 完整的上次 LLM 输出 JSON / Tool 原始返回 | ❌ 冗余大；存摘要 / 重取 |

#### 接口契约（骨架）

```python
# agent/memory.py
from dataclasses import dataclass, field

@dataclass
class SessionState:
    session_id: str
    # 以下字段按业务替换：这里给出通用形态（稳定实体 + 上次结论 + 候选项）
    focused_entity_id: str | None = None       # 用户当前锁定的主对象 ID
    user_profile: dict = field(default_factory=dict)   # 稳定偏好/身份
    last_conclusion_summary: str | None = None
    candidate_plans: list[str] = field(default_factory=list)


class SessionMemory:
    def get(self, session_id: str) -> SessionState: ...
    def update(self, session_id: str, **kwargs) -> None: ...
    # 预留接口位（不实现）：
    # def persist(self) -> None: ...   # 未来接持久化存储
    # def load(self) -> None: ...
```

**这段为什么这么设计**：字段名故意用通用词，不绑定任何域；`candidate_plans` 支持"给我第二个方案"这类追问——几乎所有业务 Agent 都需要。`persist/load` 用注释而不是空方法——空 method 会让别处代码误以为它已经能用。

#### 消息裁剪策略（不写代码，说清算法）

伪流程：
```
window = messages[:1]  # 保 system
budget = TOKEN_BUDGET - len(system)
tail = messages[1:]
for msg in reversed(tail):
    if fits(budget, msg): window.insert(1, msg); budget -= len(msg)
    else: break
if last_msg_is_tool_result_without_its_call: drop_it  # 保因果配对
```

**这段为什么这么说**：从后往前塞是因为最新消息永远最重要；`drop_it` 防止留下"孤儿 tool_result"——多数平台会直接报 400。

#### 实现提示（你该选哪个）

- **要不要 summarizer 压历史**：MVP 不要。一次 handle() 通常 ≤ 8 轮 Loop、总 tokens 远低于现代模型上下文上限；引入 summarizer 会带来"压丢关键数字"的风险。当会话跨度非常长（例如客服 Agent 一次会话上百轮）时再引入。
- **SessionMemory 存不存高频变化的字段**：不存。用现取——**否则你会陷入永远调不完的"缓存失效"问题**。
- **多用户/多会话**：`SessionMemory` 内部是 `dict[str, SessionState]`；单进程 Python + 单 worker 时可以不加锁；多 worker/多进程场景改为 Redis 或 DB。

#### 自测方法

- 造一个假 session，连发三条追问（"看看 X" → "有什么问题" → "第二个方案呢"）；每轮断言 SessionState 字段更新符合预期。
- 消息裁剪：造 20 轮 fake history，跑一次裁剪函数，断言：system 存在、最新 user 存在、无孤儿 tool_result。

#### ▸ 落到本项目

- `agent/memory.py::SessionMemory` 是 MVP 全部；React 前端在 `/agent/chat` 里传 `session_id` 即可。
- 字段替换：`focused_entity_id → current_cluster`、增加 `current_pod / current_gpu_type / current_issue`、`last_conclusion_summary → last_diagnosis`。

---

### 3.4 System Prompt 工程

**本章你会理解**：一段合格的 system prompt 有几个必要段、每段的具体作用；你能拿到一份可直接改的通用模板。

#### 设计要点

1. 分层写：**角色 → 能力约束 → 输出契约 → 行为规范 → 可用 Skill 目录 → 可用 Tool 目录 → 拒绝清单 → 示例**。
2. 每段用 XML/Markdown 标题分节——LLM 对结构化 prompt 比自然段更稳定。
3. **禁止空指令**（"请仔细思考"）——改成可检查的："调用 Tool 前先在 thinking 里列出你需要哪些字段"。
4. Skill 目录**塞进 system prompt** 让主 LLM 自选（本指南采纳的路由方案）。
5. 加入 Anti-Hallucination 段：`Evidence.value 必须来自某个 tool 的返回；禁止使用你先验知识里的具体数字/事实`。

#### 通用模板（Prompt 是文本资产，可完整给；花括号 `{...}` 为运行时注入位）

```
你是 <项目名> 的核心 Reasoning 引擎。你的职责是 <一句话职责，例如：观测与诊断 / 检索与推荐 / 起草与合规审查>。你 <能做什么，不能做什么，明确边界>。

<capabilities>
- 你可以调用下方 <tools> 里的工具获取真实数据 / 执行受控动作。
- 你可以在 <skills> 中选择一个 Skill 作为本轮的思考框架。
</capabilities>

<skills>
{skill_catalog}   ← SkillLoader 组装：每个 Skill 一行 "name: one-liner-purpose"
</skills>

<tools>
{tool_catalog_summary}   ← ToolRegistry 组装：每个 Tool 一行 "name(args): what it returns"
</tools>

<output_contract>
- 除非用户明确寒暄，否则必须至少调用一次 <tools> 才能给出有事实依据的回答。
- 最终答案将由外部程序以 JSON Schema 严格模式获取，字段包括：
  skill_used / conclusion / evidence[] / recommendations[] / confidence_note
- 每一条 evidence.value 必须能在某次 tool_call 的返回里字面找到；禁止编造具体数值或事实。
- 若信息不足以给出结论，把 conclusion 写成"信息不足"，在 confidence_note 里说明缺什么。
</output_contract>

<behavior_rules>
- {rule_1: 领域先验第一条，例如"先查已有的确定性结论再自行推理"}
- {rule_2: 领域先验第二条，例如"数据从粗到细：先总量后明细，先列表后单条"}
- {rule_3: 何时该停：明确"什么样的信息量足以下结论"}
</behavior_rules>

<refusals>
- {refusal_1: 越权动作，如"修改配置 / 下单 / 发送外部消息"直接拒绝}
- {refusal_2: 能力外任务，如"预测未来 / 医疗诊断 / 法律建议"直接拒绝}
</refusals>

<examples>
{one_positive_example}   ← 一条覆盖典型多步链路的示例；覆盖你最想让 LLM 学到的 tool 调用序列
</examples>
```

**为什么这样切段**：`capabilities`/`output_contract`/`behavior_rules`/`refusals` 四段是任何 Agent 都该有的——分别对应"能做什么 / 输出长啥样 / 怎么想 / 不做什么"；`skills` 段是路由入口；只放**一条**正面示例——多了让 LLM 复读示例结构；`behavior_rules` 是把**领域先验**沉淀为指令的地方，是"通用版"与"具体项目版"的唯一差异所在。

#### 实现提示（你该选哪个）

- **示例用 few-shot 还是 zero-shot**：一条 few-shot（覆盖典型多步链路），足够；不要每个 Skill 各一条——反而让模型混淆。
- **skill_catalog 由谁生成**：`SkillLoader.build_catalog_text() -> str`，把每个已注册 Skill 的 `name + one-liner` 拼接；改 Skill 时改这里，不改 system prompt 模板。
- **要不要在 prompt 里给 JSON schema 全文**：不要，`response_format` 已经在终轮强制了；prompt 里放全 schema 只会挤占 context。
- **中英**：主体中文；结构标签用英文（`<capabilities>` 等）——业界惯例，LLM 对英文标签识别率更高。

#### 自测方法

- 用一个明显违规的问题测拒绝（触发你 `<refusals>` 里的某一条）：应无 tool_call，直接返回拒绝文案。
- 用一个明显信息不足的问题测降级：应产出 `conclusion="信息不足"` 且 `confidence_note` 非空。
- 用一个必须多轮的问题测 skill 路由：观察是否走了预期的 Tool 序列并命中正确 Skill。

#### ▸ 落到本项目

- Prompt 模板存 `agent/prompts/system.md`（新建），运行时 `Path.read_text()` 加载并 `.format(...)` 注入 catalog。
- `<behavior_rules>` 三条填入：① "先 read `get_active_alerts` 再自行推理"；② "从粗到细：`cluster_summary → list_nodes → get_node_detail`"；③ "Ready/异常判断禁止心算，用 alerts 结论"。
- `<refusals>`：拒绝任何写操作（重启/驱逐/改配置）；拒绝预测类问题。
- 输出契约里的 `conclusion` 字段在本项目命名为 `diagnosis`。

---

### 3.5 结构化输出与校验

**本章你会理解**：JSON 输出用什么姿势最稳、Evidence 字段为什么必须强约束、校验失败怎么办。

#### 设计要点

1. **两阶段输出**：中间轮 tools=；终轮 response_format=json_schema，strict=True。
2. Schema 用 **pydantic 生成**，不要手写——手写和 pydantic 会漂移。
3. Evidence 是**防幻觉的机械保险**：字段 `source / field_path / value` 强制 LLM"标注出处"，让下游可以后校验。
4. 校验失败的处理**分级**：pydantic 校验失败 → 修复重试 1 次 → 仍失败 → 兜底一个 `confidence_note="LLM 输出不合契约"` 的降级对象。
5. 不要把 `tool_calls` 字段交给 LLM 填——那是**你自己**记录的 trace，不是 LLM 输出的一部分。

#### 接口契约（骨架）

```python
# models/agent.py：AgentDecision 通用字段建议（业务字段名按需替换）
# session_id / skill_used / conclusion / evidence[] / recommendations[] /
# alternatives_considered? / tool_calls[]（系统填，非 LLM 填） / confidence_note?

def parse_agent_decision(raw_text: str, trace: list["ToolCallRecord"]) -> "AgentDecision":
    """
    1) json.loads(raw_text) → dict
    2) AgentDecision.model_validate(dict) 但先剔除 LLM 自作主张塞进来的 tool_calls
    3) 用外部 trace 覆盖 result.tool_calls
    # TODO: 你来实现 —— 提示：捕获 ValidationError，转成 AgentDecisionParseError
    """
    ...

def fallback_decision(reason: str, trace: list["ToolCallRecord"]) -> "AgentDecision":
    """构造降级对象。conclusion='信息不足或输出不合契约'，confidence_note=reason。"""
    ...
```

**这段为什么这么设计**：`parse_agent_decision` 把"LLM 出的字段"和"系统出的字段"合并——LLM 出结论/证据/建议，系统出 trace。分离职责后即使 LLM 幻觉一份 `tool_calls`，系统会丢弃并覆盖，trace 永远真实。

#### 实现提示（你该选哪个）

- **strict 模式开不开**：开。主流平台的 strict 会拒绝多余字段、类型错误——把校验前移到平台端，等于免费多一层护栏。
- **重试策略**：`_finalize` 失败重试 1 次，第二次仍失败直接 fallback；不要无脑重试 3 次——LLM 若第一次错，通常第二次仍错，重试是烧钱。
- **Evidence 事后校验做不做**：MVP 不做（LLM 已有 strict + prompt 双重约束）；上生产后加一个 `verify_evidence(decision, trace)` 检查 `value` 是否真的出现在 trace 里，作为可观测性指标。

#### 自测方法

- 传一个残缺 JSON 给 `parse_agent_decision`，断言抛 `AgentDecisionParseError`。
- 传一个 LLM 幻觉了 `tool_calls` 的 JSON，断言最终对象的 `tool_calls` 等于传入的 trace。
- Golden test：给 3 组典型 raw_text，断言解析后 AgentDecision 与 fixture 完全一致。

#### ▸ 落到本项目

- `models/agent.py` 已定义 schema；补 `agent/output.py` 放 parse/fallback 两个函数。
- 通用字段 `conclusion` 在本项目命名为 `diagnosis`。

---

### 3.6 可观测性

**本章你会理解**：一次 Agent run 至少要记录哪些字段，事后才可回放/复现/断因。

#### 一次 run 的最小记录字段

| 字段 | 类型 | 用途 |
|---|---|---|
| `trace_id` | uuid | 关联同一次 handle 的所有 log |
| `session_id` | str | 关联跨轮会话 |
| `user_question` | str | 输入 |
| `skill_used` | str | 事后按 Skill 分层看质量 |
| `iterations` | int | Loop 走了多少轮 |
| `stop_reason` | enum | `end_turn` / `max_iterations` / `executor_error` / `parse_error` |
| `tool_calls[]` | list[ToolCallRecord] | 每次调用的 name/args/result/error/latency |
| `input_tokens / output_tokens` | int | 成本核算 |
| `wall_time_ms` | int | 用户体验 |
| `final_decision` | AgentDecision | 输出 |
| `error` | str \| None | 顶层异常 |

**为什么这几项**：`stop_reason` 是分诊断桶的钥匙——`max_iterations` 指向 Loop/Skill prompt 有问题；`executor_error` 指向 Tool 层脆弱；`parse_error` 指向 schema/prompt 契约要修。缺一项都让"哪里坏了"变成猜谜。

#### 实现提示

- 存哪里：MVP 直接 `logging.info(json.dumps(record))` 写 `<project_data_dir>/agent_traces/<date>.jsonl`；不上 DB。
- 用什么库：不上 OpenTelemetry——单进程 MVP 用不上；等要接可视化后端（Grafana / Datadog / …）时再改。
- 打点插在哪：`AgentRuntime.handle` 入口一个 `Tracer(trace_id=...)`，退出前一次性 flush；不要在 Loop 内每步 flush（IO 阻塞）。

#### 自测方法

- 跑 3 次真实请求，`cat <traces_dir>/*.jsonl | jq '.stop_reason'` 手动看分布合不合理。

#### ▸ 落到本项目

- 新增 `agent/trace.py::Tracer`；输出目录 `GPU_OPS_AGENT/data/agent_traces/`。

---

### 3.7 错误处理与重试

**本章你会理解**：Agent 会遇到三类错误、每类应该如何被"包住"而不是"抛出"。

| 层 | 错误来源 | 处理方式 |
|---|---|---|
| Tool 层 | 数据缺失、参数越界 | Executor 捕获 → `ToolCallRecord.error` → 塞回 messages 让 LLM 自纠 |
| LLM 层 | 网络/429/500/超时 | LLMClient 内做指数退避+抖动，最多 3 次；仍失败 → fallback_decision |
| Schema 层 | 终轮 JSON 不合 schema | `_finalize` 内重试 1 次；仍失败 → fallback_decision |

**共同原则**：错误**只在一层被吃掉**——决定"吃"还是"抛"的原则是：**LLM 能自纠的**（工具错、参数错）就吃并回传；**LLM 帮不上忙的**（网络、schema）就抛给上层做降级。

#### 实现提示

- 不要在 Tool.run 内 try/except——由 Executor 统一 try；每一层各扫自家门口。
- 不要重试 `tool_choice=required` 的调用——建议默认用 `auto`；重试也可能白花钱。
- 429/超时：优先使用官方 SDK 提供的 `max_retries` 参数，不必自己写循环。

#### 自测方法

- 让 mock LLM 前两次抛 RateLimitError，第三次正常 → 断言最终成功。
- 让 mock Tool 抛异常 → 断言 Loop 收到 tool 错误消息、LLM 收到该消息、`stop_reason != executor_error`（即 Loop 未中断）。

#### ▸ 落到本项目

- `agent/llm_client.py`（新建）——把 LLM SDK 包一层，负责重试/日志。Runtime 不直接 import SDK。

---

### 3.8 HITL（Human-in-the-Loop）挂载点

**本章你会理解**：即使当前项目全部只读，也需要预留人工介入位——**接口位不能漏**。

#### 三个应预留的挂载点

1. **低置信度输出的显式标记**：`AgentDecision.confidence_note` schema 字段——UI 遇到 non-null 时应高亮。
2. **需要澄清的追问触发**：Skill prompt 里允许 LLM 输出 `conclusion="需要澄清"` + 一个具体 clarifying question，UI 渲染为"追问 chip"；不需新代码，只需 prompt 里明确允许。
3. **未来接入敏感/写操作时的审批钩子**：`ToolExecutor.execute` 内预留 hook：

```python
class ToolExecutor:
    def __init__(self, registry: ToolRegistry, approver: "Approver | None" = None): ...
    # approver.needs_approval(tool) -> bool
    # approver.request(tool_name, args) -> bool  # 阻塞或异步都可
```

**这段为什么这么设计**：一旦 Agent 引入写操作或高敏 Tool（发通知、下单、扣费、生成对外文案），**不改 Executor 主逻辑，只注入 approver**——开闭原则的正确用法。若当前全部只读，approver=None，执行路径零改动。

#### 实现提示

- MVP 不实装 approver。**只保留构造函数的参数位**，body 里 `if self.approver and self.approver.needs_approval(tool): ...` 一行 stub 占位。
- confidence_note 的 UI 呈现：黄色标记 + 文本即可；不做复杂交互。

#### ▸ 落到本项目

- Executor 构造函数留 `approver` 参数位；前端 `AgentDecision` 渲染时若 `confidence_note` 非空则黄边框。

---

## 4. 实施步骤（Step 0 → Step 8）

**本章你会理解**：从"什么都没写"到"完整 Agent 上线"的 9 步顺序，每步能自己验收。每步四要素：**目标 / 产出物 / 你要自己想清楚的问题 / 验收标准**。

### Step 0 — LLMClient 封装 + 一次裸对话

- **目标**：LLM 通路打通，能在 Python 里同步得到一个字符串回复。
- **产出物**：`agent/llm_client.py`（含 retry），一个 `scripts/smoke_llm.py` 手动测试脚本。
- **你要想清楚**：SDK 与版本；模型名（大小档次）；API key 怎么读（`os.environ["<PROVIDER>_API_KEY"]`，别硬编码）。
- **验收**：命令行跑 `python scripts/smoke_llm.py "你好"` 得到自然语言回复；断网时看到重试日志后抛出。

### Step 1 — 一个 Tool + 手工 Executor 调用

- **目标**：证明"数据源 → Tool → dict 结果"这条**不含 LLM**的链路可跑。
- **产出物**：`Tool` 基类 + **一个最简单、最常被问到的 Tool**（例如"按主键查一个实体"）+ `ToolRegistry` + `ToolExecutor`；一个手工调用脚本。
- **你要想清楚**：pydantic ArgsModel 里哪些字段必填、哪些可空；返回 dict 的 key 是否与前端/下游期望一致。
- **验收**：`executor.execute("<your_tool>", {...})` 返回 `ToolCallRecord.result` 是可 JSON 序列化 dict，且值与数据源核对一致。

### Step 2 — Loop 骨架（先不接 Skill、不做终轮）

- **目标**：跑通"user_question → LLM → tool_call → tool_result → LLM → 停止"的最小闭环。
- **产出物**：`AgentRuntime._run_loop` 完整实现；`handle` 暂时返回最后一条 assistant 文本，不做 JSON 化。
- **你要想清楚**：system prompt 先用一版 100 行以内的粗版；`max_iterations` 定 8；tool_choice="auto"。
- **验收**：问一个需要用到该 Tool 的具体问题，Loop 走 1~2 轮、成功调用 Tool、最终 assistant 文本包含正确结果。

### Step 3 — 终轮 JSON 结构化输出

- **目标**：让 `handle()` 返回 `AgentDecision` 对象，而不是自由文本。
- **产出物**：`_finalize` 方法 + `parse_agent_decision` + `fallback_decision`。
- **你要想清楚**：Evidence 字段的 `field_path` 语法约定（如 `entities[<id>].<field>` 或类似 JSON Pointer）；`source` 字段填什么（tool name+call_index）。
- **验收**：同 Step 2 的问题，返回 `AgentDecision`，`evidence` 至少 1 条且 `value` 与 Tool 返回值字面一致。

### Step 4 — 补齐 Tools（把业务能力面覆盖完）

- **目标**：让 LLM 拥有该业务下**完整可用的 Tool 集**。
- **产出物**：其余 Tool 全部实现（一般 3~8 个）。
- **你要想清楚**：**Tool 的粒度**——避免 `get_everything()` 大而全，也避免拆到每字段一个 Tool。经验法则：一个 Tool 一个"查询意图"；参数区分范围，返回形状区分"轻量汇总 vs 明细"。
- **验收**：单独单测每个 Tool 通过；registry 汇总 schema 手动贴到目标平台 Playground 能被接受。

### Step 5 — 第一个 Skill 端到端

- **目标**：不是加"选 Skill"逻辑，而是把**最典型的一个 Skill** 的 prompt 段落写进 system prompt，让端到端跑通一次真实业务问答。
- **产出物**：`agent/skills/<your_first_skill>.py`（含 `build_system_prompt()` 返回该 Skill 的领域段落）；`SkillLoader` 骨架（仅注册，尚不 select）。
- **你要想清楚**：Skill 的领域 prompt 里应放"推理框架"（LLM 该问什么问题、用什么次序、什么条件下下结论），而非具体计算——具体计算已经在 Tool 里。
- **验收**：给一个典型业务问题，Agent 至少走 2~3 步 Tool 调用，最终 conclusion 命中预期方向。

### Step 6 — SkillLoader 做 catalog 组装 + 剩余 Skill

- **目标**：让主 LLM 能自选 Skill；所有 Skill 都能被路由到。
- **产出物**：`SkillLoader.build_catalog_text()` + 剩余 Skill 各一个文件。
- **你要想清楚**：如果某个 Skill 需要尚未实现的 Tool（stub），要在 Skill 的 prompt 里写明"该 tool 未实装，返回 NotImplemented 时请在 caveats 里说明"。
- **验收**：分别问每个 Skill 对应类型的问题，`AgentDecision.skill_used` 命中正确 Skill 名的准确率 ≥ 90%。

### Step 7 — SessionMemory + 对外路由 + 前端联调

- **目标**：多轮追问能工作；对外端点通；前端聊天界面可用。
- **产出物**：`agent/memory.py`；`api/agent_routes.py`（或对应框架）；前端 ChatPanel。
- **你要想清楚**：session_id 怎么生成（浏览器侧 uuid + localStorage）；SessionMemory 更新时机（`handle` 结束前根据本轮结论更新）；哪些字段该存（回看 §3.3 存不存判断表）。
- **验收**：连发三条追问（"看看 X" → "有什么问题" → "第二个方案呢"），第三条能理解 "第二个方案" 指向 `candidate_plans[1]`。

### Step 8（可选，第一版发版后再做）— Tracer + 离线评估

- **目标**：一次 run 的完整 trace 落盘；建立离线评估集雏形。
- **产出物**：`agent/trace.py`；`tests/agent_offline_cases.yaml`（20~30 条真实问题）。
- **验收**：trace 每行包含 §3.6 表格里的字段；跑一次批处理断言 skill 路由准确率 ≥ 90%。

---

## 5. 测试与评估

**本章你会理解**：一个不确定输出的系统怎么被稳定测试；至少要看哪几个指标。

### 5.1 分层测试策略

| 层 | 依赖 LLM | 用什么测 | 频率 |
|---|---|---|---|
| Tool 单测 | ❌ | pytest + 假数据源 fixture | 每次 push |
| Executor 单测 | ❌ | pytest（不存在 tool / 缺字段 args / 正常 args） | 每次 push |
| Skill routing | ✅ 少量 | 20 条固定问题，断言 `skill_used` | 每次 prompt 变更 |
| End-to-end 输出质量 | ✅ 主要 | 离线评估集 + 人工标注 | 每次 prompt/tool 变更 |

### 5.2 离线评估集怎么设计

- **规模**：20~30 条真实业务问题，覆盖每个 Skill 各 5~7 条 + 2~3 条边界（信息不足 / 拒绝 / 澄清）。
- **每条 case 至少含**：`question / expected_skill / must_call_tools[] / must_appear_in_evidence[] / prohibited_content[]`。
- **不做**：期待 conclusion 文本完全一致——LLM 措辞会变；改为断言"是否命中关键概念"。

### 5.3 关键指标

| 指标 | 目标 | 怎么算 |
|---|---|---|
| Skill 路由准确率 | ≥ 90% | `skill_used == expected` 的比例 |
| Tool 覆盖率 | 100% | `must_call_tools ⊆ actual_calls` 的比例 |
| Evidence 真实率 | 100% | `evidence.value` 能在 trace 里字面找到的比例 |
| 平均轮数 | ≤ 4 | 单次 handle 的 Loop iterations |
| p95 wall time | ≤ 8s | 采样 |
| Fallback 触发率 | ≤ 5% | `stop_reason != end_turn` 的比例 |

**为什么这几项**：前三个是**正确性**（选对 Skill、用了工具、没编数字）；后三个是**效率与稳定**。**不要**追"用户满意度"这种主观指标做 MVP 门禁——不可复现。

### 5.4 回归怎么跑

- 一个脚本 `scripts/eval.py` 顺序跑评估集、对比上一次的指标基线（存 `tests/agent_eval_baseline.json`）；任何指标下滑 ≥ 5% 视为回归，人工看 case。
- 不做 CI 集成（每次跑一整轮成本可观）；改 prompt 或加 Skill 时人工触发。

### ▸ 落到本项目

- Tool/Executor 单测放 `tests/test_tools/`；评估集放 `tests/agent_offline_cases.yaml`，脚本 `scripts/eval.py`。

---

## 6. 演进路线

**本章你会理解**：什么时候你该把这个单 Agent 拆成多 Agent、什么时候该引入框架。

### 6.1 单 Agent → 子 Agent / 多 Agent 的判断信号

| 信号 | 应对 |
|---|---|
| 单次 Loop 平均 > 8 轮且不收敛 | 拆子 Agent：一个专攻数据收集，一个专攻综合建议 |
| Skill prompt > 3000 tokens | 切子 Skill，或将部分知识下沉为 Tool |
| 同一次请求需要并行探索多种假设 | 拆并行子 Agent，结果汇总给主 Agent |
| 出现跨系统写能力（通知/工单/支付） | 独立"执行 Agent"，与信息类 Agent 隔离，带 HITL |

### 6.2 什么时候引入框架

**默认零框架**，只有下面**任何一条**成立才考虑：

- 需要 **DAG 式确定性编排**（多个 Agent 有严格依赖顺序）→ 考虑 LangGraph。
- 需要**跨语言/跨进程** Agent 调用（其他团队要复用你的 Agent）→ 考虑 MCP / A2A 协议。
- 需要**海量 RAG**（>10 万 chunk）→ 考虑 LlamaIndex 的检索组件（仅检索，不用它的 Agent 层）。
- **单个开发者维护成本 > 一次重写成本**——不要预期这一天，等它自然来。

**永远不要**"因为大家都用 XX 框架所以我也用"——多数业务 Agent 路径可预测、Tool 数量有限，框架带来的开销远高于收益。

### 6.3 演进的顺序建议

1. **先做深**：把当前 Skill 打磨到评估集 95% 通过。
2. **再做宽**：加新 Skill（覆盖新问题类型）。
3. **然后做长**：拆子 Agent。
4. **最后做写**：接入写操作 + HITL。

### ▸ 落到本项目

- 现阶段目标：Step 0~7 全部完成 + 评估集达标。**不看框架、不看多 Agent**，专注单 Agent。

---

## 7. 反模式清单（避坑）

**本章你会理解**：10 条最常见的踩坑，避开即可省下大量返工。

1. **让 LLM 心算/瞎记业务事实**——凡是确定性判断、总量加总、阈值比较、身份查找，全下沉到普通代码或 Tool。
2. **`get_everything()` 大而全 Tool**——LLM 拿到一堆无关字段，反而不会挑，token 也贵。
3. **手写 JSON schema**——跟 pydantic 一定漂移；用 `model_json_schema()`。
4. **Tool 抛异常给 Loop**——LLM 拿不到错误、无法自纠；Executor 内捕获转 Observation。
5. **每轮把 system prompt 再 append 一次**——上下文膨胀，且 LLM 会误解重复指令。
6. **无 max_iterations 或设成 100**——死循环烧钱；MVP 8 足够。
7. **SessionMemory 存高频变化的事实**——下轮就过期；只存稳定 state 与摘要。
8. **中间轮同时用 tools 和 strict JSON schema**——多数平台上两者混用行为不稳；分两阶段。
9. **prompt 里用"请仔细思考""认真检查"这类空指令**——LLM 只会礼貌应答；改成"调用 Tool 前先列所需字段"这类可检查指令。
10. **过早引入框架/多 Agent/RAG**——MVP 阶段是学 Agent 构建，不是学框架 API；先把标准范式跑通，再谈框架。

---

## 附：本指南与本项目 spec 的映射速查（仅本项目相关）

| spec 章节 | 本指南章节 |
|---|---|
| 1. Architecture | §1 |
| 3. Module Responsibility | §2 |
| 4. Core Classes | §3.1-3.3 |
| 5. Data Models | §3.5 |
| 6. Tool Design | §3.1 + Step 4 |
| 7. Runtime Boundary | §3.4 behavior_rules |
| 8. Implementation Order | §4 Step 0~8 |

**结束语**：这份指南只提供**骨架 + 判断力**——所有函数体、prompt 调优、评估集内容都要你自己敲。不确定的地方，写下选项与其代价，**选最简单能验证的**先跑起来。
