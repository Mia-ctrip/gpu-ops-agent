# GPU Ops Agent — V1 架构与实施规格 (Architecture & Implementation Spec)

状态：草案 v1（架构设计阶段，未开始大规模 Coding）
范围：单用户、本地运行、Read-only GPU 运维观测/诊断 Agent

> 现有仓库已存在 `agent/skills/gpu-resource-manage-skill/SKILL.md`，其中沉淀了大量真实域知识（集群别名、AcceleratorType 解析规则、Allocatable/Available/Capacity 语义、上报异常判断、fragmentation 迁移评估标准、输出格式要求）。本设计不重复发明这些规则，而是把其中"确定性计算"部分下沉为 `services/` 和 `tools/` 里的普通 Python 逻辑，把"需要判断力/权衡"的部分保留为 Skill 的 prompt 指令。

---

## 1. MVP Architecture

```
                         ┌───────────────────────────┐
                         │     Frontend (React)      │
                         │ Cluster Tabs / Current     │
                         │ Facts / Trend / Alerts /   │
                         │ Chat Panel                 │
                         └─────────────┬──────────────┘
                                       │ REST (HTTP/JSON)
                         ┌─────────────▼──────────────┐
                         │   Backend API (FastAPI)    │
                         │ dashboard_routes.py         │
                         │ agent_routes.py             │
                         └─────────────┬──────────────┘
                    ┌──────────────────┼───────────────────┐
                    │                  │                   │
          ┌─────────▼────────┐ ┌───────▼───────┐  ┌────────▼────────┐
          │ SnapshotService  │ │ AlertService  │  │  AgentRuntime   │
          │ (Single Source   │◄┤ (deterministic│  │  (ReAct loop)   │
          │  of Truth)       │ │  rules)       │  └────────┬────────┘
          └─────────▲────────┘ └───────────────┘           │ loads
                    │                                       ▼
          ┌─────────┴────────┐                     ┌────────────────┐
          │  k8s_client.py   │                     │  SkillLoader   │
          │ (thin, read-only │                     │  + Skills      │
          │  adapter)        │                     └────────┬───────┘
          └──────────────────┘                              │ uses
                                                     ┌────────▼───────┐
                                                     │ ToolRegistry / │
                                                     │ ToolExecutor   │
                                                     └────────┬───────┘
                                                              │ reads only
                                                     ┌────────▼───────┐
                                                     │ SnapshotService│
                                                     │ (同一个实例)    │
                                                     └────────────────┘
```

**核心原则：Tool 永远不直接调用 `k8s_client.py`，只读 `SnapshotService` 的当前快照。**

好处：
1. Dashboard 和 Agent 永远看到同一份数据（避免同时查询 API 造成不一致）。
2. Read-only 边界从架构上物理强制：整个进程中只有 `SnapshotService` 持有对 `k8s_client` 的引用；Agent/Tool 层根本拿不到任何有副作用的方法。

单向依赖：
```
Frontend → Backend API → {SnapshotService, AlertService, AgentRuntime}
AgentRuntime → SkillLoader → Skill → ToolExecutor → ToolRegistry → Tool → SnapshotService
AlertService → SnapshotService
SnapshotService → k8s_client.py
```

---

## 2. Project Directory Tree

```
GPU_OPS_AGENT/
├── main.py                        # FastAPI app entrypoint
├── config.py                      # 集群列表、阈值、poll interval、本地文件路径
├── models/
│   ├── domain.py                  # Cluster, Node, Pod, GpuType, ScenarioRole(Train/Infer)
│   ├── snapshot.py                # Snapshot, ClusterSnapshot
│   ├── alert.py                   # Alert, AlertSeverity, AlertType
│   └── agent.py                   # AgentDecision, Evidence, Recommendation, ToolCallRecord
├── k8s_client.py                  # 对已有封装 K8s API 的薄适配层（只读）
├── services/
│   ├── snapshot_service.py        # 采集 + 归一化 + 内存快照 + ring buffer + 落盘
│   └── alert_service.py           # 三类确定性规则引擎
├── agent/
│   ├── agent.py                   # AgentRuntime：ReAct loop
│   ├── memory.py                  # SessionMemory（进程内 dict）
│   ├── skill_loader.py            # Skill 注册与选择
│   ├── skills/
│   │   ├── base.py                # Skill 基类/接口
│   │   ├── scheduling_diagnosis.py
│   │   ├── fragmentation.py
│   │   ├── incident_impact.py
│   │   └── gpu_recommendation.py
│   └── tools/
│       ├── tool_registry.py       # name -> Tool 映射 + schema 列表
│       ├── tool_executor.py       # 参数校验 + 执行 + 异常包装
│       ├── cluster_tools.py       # get_cluster_gpu_summary
│       ├── node_tools.py          # list_nodes, get_node_detail
│       └── incident_tools.py      # get_pod_gpu_allocation, get_active_alerts, (stub) get_service_owner
├── api/
│   ├── dashboard_routes.py        # /clusters, /clusters/{id}/facts, /trend, /alerts
│   └── agent_routes.py            # /agent/chat
├── tests/
│   ├── test_snapshot_service.py
│   ├── test_alert_service.py
│   ├── test_tools/
│   └── test_agent_runtime.py
└── data/
    └── snapshots/                 # ring buffer 落盘文件（重启恢复用，非查询用）

front/
├── src/
│   ├── pages/ClusterDashboard.tsx
│   ├── components/
│   │   ├── ClusterTabs.tsx
│   │   ├── StatTile.tsx
│   │   ├── TrendChart.tsx
│   │   ├── AlertPanel.tsx
│   │   └── ChatPanel.tsx
│   └── api/client.ts
```

设计取舍：**不**把 `snapshot_service` 拆成 `collector.py` + `store.py` 两个文件——MVP 阶段一个类内部两个私有方法足够，等真正复杂再拆。**不**引入 `planner.py`、`orchestrator.py`、`memory_store.py`、`db.py`、`event_bus.py`——单 Agent、单进程、无 DB 场景下这些都是过度设计。

---

## 3. Module Responsibility（逐一裁定是否需要存在）

| 文件 | 是否需要 | 职责 |
|---|---|---|
| `agent/agent.py` | ✅ 需要 | AgentRuntime 核心：ReAct loop（think → select tool → call → observe → continue → 结构化输出）。**不包含任何领域知识**，不知道什么是 fragmentation，只知道怎么循环调用 LLM 和 Tool。 |
| `agent/skill_loader.py` | ✅ 需要，但要轻 | 维护 `skill_name -> Skill` 注册表，根据用户问题选出合适 Skill（关键词匹配或一次轻量 LLM 分类即可，不需要向量检索/路由框架）。 |
| `agent/tools/tool_registry.py` | ✅ 需要 | 纯"目录"：有哪些 Tool、它们的 JSON schema（供 LLM function-calling 用）。不包含执行逻辑。 |
| `agent/tools/tool_executor.py` | ✅ 需要 | 纯"执行器"：校验入参、调用 `tool.run()`、捕获异常、把结果转成 Observation 文本回传给 loop。与 registry 分离是因为"有什么"和"怎么跑"是两类职责，各自都很薄（<100 行）。 |
| `services/snapshot_service.py` | ✅ 需要，系统心脏 | 定时调用 `k8s_client` → 归一化为 domain model → 更新内存 current snapshot → 追加 ring buffer(最近50次) → 定期落盘。对外只暴露 `get_current()` / `get_history()` / `refresh_now()`。 |
| `k8s_client.py` | ✅ 需要，但保持薄 | 对已有封装 API 的适配层，转换为本项目 dataclass。**绝不新增任何写方法**——这是保证只读的物理边界。 |
| `services/alert_service.py` | ✅ 需要 | 纯 deterministic 规则引擎，输入 Snapshot，输出 `List[Alert]`。不用 LLM。 |
| `models/*.py` | ✅ 需要 | 全项目共享的纯数据类（dataclass/pydantic），不依赖任何业务模块，避免循环依赖。 |
| Agent output schema (`models/agent.py`) | ✅ 需要，且必须强约束 | `AgentDecision`/`Evidence`/`Recommendation` 是 Agent 与 UI 的契约，也是防止 LLM 编造事实的结构性约束——强制 Evidence 字段引用 snapshot 的具体字段值。 |

主动删减（不引入）：`planner.py`、`orchestrator.py`、独立 `memory_store.py`（session memory 用进程内 dict 即可，重启丢失可接受）、任何 ORM/DB 层、`event_bus.py`/消息队列。

---

## 4. Core Classes

### `K8sClient`
- Responsibility: 适配已有封装 API，返回本项目 domain model
- Core fields: `wrapped_api_client`
- Core methods:
  - `list_clusters() -> list[str]`
  - `fetch_cluster_nodes(cluster_id: str) -> list[NodeRaw]`

### `SnapshotService`
- Responsibility: 采集、归一化、持有 Single Source of Truth
- Core fields: `_current: dict[str, ClusterSnapshot]`, `_history: dict[str, deque[ClusterSnapshot]]` (maxlen=50), `_lock`
- Core methods:
  - `refresh_now(cluster_id: str | None = None) -> None`
  - `get_current(cluster_id: str) -> ClusterSnapshot`
  - `get_history(cluster_id: str, limit: int = 50) -> list[ClusterSnapshot]`
  - `start_background_refresh(interval_sec: int) -> None`

### `AlertService`
- Responsibility: 对当前 snapshot 跑确定性规则
- Core fields: `rules: list[Callable[[ClusterSnapshot], list[Alert]]]`
- Core methods:
  - `evaluate(snapshot: ClusterSnapshot) -> list[Alert]`
  - `get_active_alerts(cluster_id: str | None) -> list[Alert]`

### `Tool` (base, ABC)
- Responsibility: 单一只读查询能力
- Core fields: `name: str`, `description: str`, `input_schema: dict`
- Core methods:
  - `run(**kwargs) -> dict`

### `ToolRegistry`
- Responsibility: 管理 Tool 集合与其 schema
- Core fields: `_tools: dict[str, Tool]`
- Core methods:
  - `register(tool: Tool) -> None`
  - `get(name: str) -> Tool`
  - `list_schemas() -> list[dict]`

### `ToolExecutor`
- Responsibility: 执行一次 tool call
- Core fields: `registry: ToolRegistry`
- Core methods:
  - `execute(tool_name: str, args: dict) -> ToolCallRecord`

### `Skill` (base, ABC)
- Responsibility: 领域知识 + 允许的 Tool 集合 + 输出 schema
- Core fields: `name: str`, `instructions: str`, `allowed_tools: list[str]`, `output_schema: type`
- Core methods:
  - `build_system_prompt() -> str`

### `SkillLoader`
- Responsibility: 注册与选择 Skill
- Core fields: `_skills: dict[str, Skill]`
- Core methods:
  - `register(skill: Skill) -> None`
  - `select(user_question: str, session: SessionMemory) -> Skill`

### `SessionMemory`
- Responsibility: 保存跨轮对话 context（不存实时事实）
- Core fields: `current_cluster`, `current_pod`, `current_gpu_type`, `current_issue`, `last_diagnosis`, `candidate_plans`
- Core methods:
  - `get(session_id: str) -> SessionMemory`
  - `update(session_id: str, **kwargs) -> None`

### `AgentRuntime`
- Responsibility: ReAct loop 编排
- Core fields: `skill_loader: SkillLoader`, `tool_executor: ToolExecutor`, `memory: SessionMemory`, `max_iterations: int`
- Core methods:
  - `handle(session_id: str, user_question: str) -> AgentDecision`

---

## 5. Core Data Models

### `Alert`
```
alert_id: str
cluster_id: str
type: AlertType            # NODE_HEALTH | GPU_REPORTING_ANOMALY | CAPACITY_WATERMARK
severity: AlertSeverity    # INFO | WARNING | CRITICAL
node_name: str | None
gpu_type: str | None
message: str
detected_at: datetime
raw_values: dict           # 触发该 alert 的原始字段值（allocatable/available/status 等），便于溯源
```

### `Evidence`
```
source: str                # 例如 "snapshot_service.get_current" / tool 名
cluster_id: str
node_name: str | None
field_path: str             # 例如 "nodes[svr-01].available.gpu"
value: Any                  # 该字段的真实值，禁止 LLM 编造
```

### `Recommendation`
```
rank: int                   # 1 = 最优方案，2/3 = 备选
action_summary: str
affected_nodes: list[str]
affected_pods: list[str]
estimated_impact: str       # 例如 "仅迁移1个pod，影响面小"
caveats: str | None         # 例如 "无法判断该pod是否为单实例线上服务，需人工确认"
```

### `AgentDecision`
```
session_id: str
skill_used: str
diagnosis: str              # 结论
evidence: list[Evidence]
recommendations: list[Recommendation]
alternatives_considered: str | None
tool_calls: list[ToolCallRecord]   # 完整调用轨迹，用于可解释性/调试
confidence_note: str | None        # 信息不足时的说明，禁止编造
```

### 领域模型（`models/domain.py` / `models/snapshot.py`，简要）
```
ScenarioRole = Enum("Train", "Infer")

Node:
  name, ip, cluster_id, gpu_type, scenario
  status: "Ready" | "NotReady"
  allocatable: {gpu, cpu, mem}
  available: {gpu, cpu, mem}
  labels: dict, taints: list
  pods: list[PodGpuAllocation]

PodGpuAllocation:
  pod_name, node_name, gpu_count

ClusterSnapshot:
  cluster_id, collected_at
  nodes: list[Node]
```

---

## 6. Agent Tool Design

原则：**不做 `get_everything()`，也不按字段拆到过碎**——用参数区分查询范围，用返回的数据形状区分"轻量汇总"与"重量明细"。

| Tool | Input | Output | 被哪个 Skill 用 | 为什么这个粒度 |
|---|---|---|---|---|
| `get_cluster_gpu_summary` | `cluster_id, gpu_type?, scenario?` | 该维度下 total/used/free GPU、node 数、ready/notready 数 | GPU Recommendation（资源是否存在）、Scheduling Diagnosis（集群总量是否足够） | 汇总数字用参数过滤而非拆多个 tool；这是最常被问到的"事实"查询，值必须与 Dashboard 完全一致（同一份 SnapshotService） |
| `list_nodes` | `cluster_id, gpu_type?, scenario?, min_free_gpu?` | node 列表（name, status, allocatable/available gpu/cpu/mem, labels），**不含** pod 级明细 | Scheduling Diagnosis（单机是否满足）、Fragmentation（候选节点） | 只给"轻量"字段，避免每次都拉全量 pod 明细占用 context |
| `get_node_detail` | `cluster_id, node_name` | 单节点全量明细，含 `GPUDistribution`（pod 级占用） | Incident Impact（node→pods）、Fragmentation（细看候选节点） | 与 `list_nodes` 分离：pod 级明细通常只对 1-2 台具体节点需要，按需拉取更省 context |
| `get_pod_gpu_allocation` | `cluster_id, node_name?, pod_name?` | pod 级 GPU 占用列表 | Incident Impact（汇总受影响 pod）、Scheduling Diagnosis（举证） | 与 `get_node_detail` 互补：可跨节点按 pod 名反查，`get_node_detail` 是按节点查 |
| `get_active_alerts` | `cluster_id?` | 当前 Alert 列表 | 所有 Skill（先看是否已有确定性判断，避免 LLM 重新推导已经算好的结论） | 复用 AlertService 结果，防止 LLM 重复/错误地心算 Ready/异常判断 |
| `get_service_owner`（stub，未来实现） | `pod_name` 或 `app_id` | service 元数据（服务名、owner、联系人） | Incident Impact Analysis | 依赖尚未提供的 Service Metadata 系统；当前返回 `NotImplemented` 占位，接口先占好位置 |

共 5 个可用 tool + 1 个占位 tool。所有 tool 内部只做**确定性计算**（过滤、求和、比较），不做"推荐"或主观判断——推荐留给 Skill 的 prompt 让 LLM 结合多因素权衡。

---

## 7. Agent Runtime Boundary

| 层 | 归属 | 说明 |
|---|---|---|
| Node Ready/NotReady 判断 | **Traditional Python Service**（AlertService） | 纯字段比较，禁止 LLM 判断 |
| GPU 上报异常判断（Allocatable 奇偶/负数校验） | **Traditional Python Service**（AlertService） | 同上，数值幻觉风险高，必须代码判断 |
| Capacity Watermark 阈值判断 | **Traditional Python Service**（AlertService） | 阈值配置在 `config.py`，纯代码比较 |
| 单节点是否满足 GPU/CPU/Mem request | **Tool**（`list_nodes` 的过滤逻辑） | 确定性数值比较，下沉到 Tool 内部 |
| 集群总 Free GPU 加总 | **Tool**（`get_cluster_gpu_summary`） | 同上 |
| ReAct loop 状态机、迭代次数、何时终止 | **Agent Runtime** | 不含领域知识 |
| SessionMemory 读写 | **Agent Runtime** | 只存 context，不存实时事实 |
| "选哪个 Skill" | **Agent Runtime**（经 `skill_loader`） | 轻量分类，不是领域推理 |
| "总 GPU 够但单机不够 → 判定为 fragmentation" 这类业务规则的**推理框架** | **Skill**（prompt 指令） | 告诉 LLM 用什么逻辑框架去问问题，但具体数字仍来自 Tool |
| 迁移方案的影响面权衡、最优/备选排序 | **Skill**（LLM 推理） | 需要判断力，没有唯一公式（是否单实例服务、是否有 DR 等无法从数据直接得出），必须保留给 LLM 并要求给出 caveats |
| 数据查询（拿字段、做过滤/求和） | **Tool** | 无状态，输出结构化 JSON，不经 LLM 二次加工 |

一句话原则：**能用普通代码可靠算出来的数字，永远不交给 LLM 心算；需要结合多因素、无唯一公式的权衡，才交给 LLM，且必须要求给出 Evidence 和 Caveats。**

---

## 8. Implementation Order（实际编码顺序，目标：尽快跑出第一个可运行 MVP）

1. `models/` 全量 dataclass（无依赖，最先写完，后续全部依赖它）
2. `k8s_client.py` 薄适配层（可先用 SKILL.md 里的 demo json 当 mock 数据跑通）
3. `services/snapshot_service.py`：`collect()` + `get_current()` + ring buffer，先手动 `refresh_now()`，不做定时
4. `api/dashboard_routes.py` 暴露 `/clusters/{id}/facts`，先用 curl/Postman 验证，不急着写 React
5. `services/alert_service.py` 三类规则 + `/alerts` 路由 —— **到此为止，即使没有 Agent、没有前端，已经是一个可用的最小闭环系统（事实 + 告警）**
6. 加后台定时刷新 + ring buffer 落盘（进程重启恢复）
7. `front/` 最小 React：Cluster Tabs + Current Facts + Alert Panel
8. Trend 图表（复用 `get_history`）+ Refresh 按钮
9. `agent/tools/`：先写 `cluster_tools.py` / `node_tools.py`，**纯单测**，不涉及 LLM
10. `tool_registry.py` + `tool_executor.py`，写一个手工脚本（不经 LLM）验证 schema 和执行结果
11. `agent/agent.py` ReAct loop 骨架 + `models/agent.py` 的 `AgentDecision`，先只接 **Scheduling Diagnosis** 一个 Skill，跑通端到端
12. `skill_loader.py` + 补齐剩余三个 Skill（Fragmentation → Incident Impact → GPU Recommendation；后者依赖的 Service Metadata Tool 用 stub）
13. 前端 ChatPanel 接入 `/agent/chat`，验证 SessionMemory 支持连续追问（"那第二个方案呢"）
14. 补 `tests/`，尤其 `alert_service` 和各 `tool` 的确定性逻辑必须有单测（这是不依赖 LLM 也要保证正确的部分）

第 5 步之后就有一个真实可用的运维看板；Agent/LLM 相关的、更有不确定性的部分放到最后（步骤 9-13），符合"先出 MVP、把风险最大的部分留在后面且隔离测试"的原则。
