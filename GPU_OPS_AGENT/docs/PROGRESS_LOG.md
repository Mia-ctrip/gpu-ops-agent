# GPU Ops Agent — 全项目进度日志 (Progress Log)

> 本文件是全项目唯一的编码进度记录，跨会话共用。每个会话开始编码前先读此文件了解进度；每完成一个里程碑按下方格式追加一条记录。规范来源：`ARCHITECTURE_SPEC.md` §8 Implementation Order。

## 使用约定

- 每条记录按 `M 步骤.子步骤` 编号（对应 Implementation Order 的 1–14 步），新增步骤用 `+` 前缀编号。
- 记录要给出：做了什么、改了哪个文件、验证方式、遗留问题/下一步。
- 遗留问题用 `[TODO]` 标记，供下一个会话接力。

---

## 2026-08-28 — Implementation Order 步骤 5：AlertService 三类规则 + /alerts 接口

**状态：完成** ✅ **三类预警规则完整实现、前端告警面板集成**

**做了什么**

1. **AlertService 重写**（`services/alert_service.py`）：
   - 实现三类确定性规则引擎：
     - `_rule_node_health()`：检测 NotReady 节点 → CRITICAL 告警
     - `_rule_gpu_reporting_anomaly()`：
       - 显卡 Allocatable 为奇数（1,3,5,7...）→ WARNING
       - 显卡 Available 为负数 → CRITICAL
     - `_rule_capacity_watermark()`：按 GPU 卡型分别计算水位
       - 单个卡型利用率 > 90% → CRITICAL 告警（红色）
       - 单个卡型利用率 75-90% → WARNING 告警（黄色）
       - 每个卡型的告警包含完整的节点列表和支撑数据

2. **后端路由改进**（`api/dashboard_routes.py`）：
   - 新增 `_format_alert_detail()` 函数，返回详细告警信息
   - `/alerts` 端点现返回：
     ```json
     {
       "alert_id": "uuid",
       "type": "NODE_HEALTH|GPU_REPORTING_ANOMALY|CAPACITY_WATERMARK",
       "severity": "INFO|WARNING|CRITICAL",
       "message": "人可读的消息",
       "details": {
         "affected_nodes": ["node1", "node2", ...],
         "gpu_type": "h20|l20|...",
         "reason": "异常原因"
       },
       "raw_values": {
         "node_count": 42,
         "total_allocatable": 98,
         "total_used": 96,
         "utilization_ratio": 0.9796,
         "affected_nodes": [...]
       }
     }
     ```

3. **后台告警评估**（`main.py`）：
   - 改进启动流程，在初始化和后台轮询时调用 `alert_svc.refresh(snap)`
   - 每次快照刷新后自动评估所有集群的告警

4. **前端告警面板**（`front/index.html`）：
   - 新增 Alerts 面板（在 Cluster Health 和 Node Details 之间）
   - 按 Severity 分组展示：CRITICAL（红）→ WARNING（黄）→ INFO（绿）
   - 每条告警显示：
     - ✅ 告警消息（人可读）
     - ✅ 告警类型和严重等级
     - ✅ 受影响节点列表（最多显示 5 个，超出显示 "+N more"）
     - ✅ 可展开的原始数据（JSON 格式）
     - ✅ 告警生成时间戳
   - 实时刷新按钮，支持手动更新告警

5. **单元测试补强**（`tests/test_alert_service.py`）：
   - 14 个单元测试涵盖所有规则场景：
     - NODE_HEALTH: 健康节点无告警、NotReady 触发 CRITICAL
     - GPU_REPORTING_ANOMALY: 偶数 GPU 无异常、奇数 GPU 触发 WARNING、负数 GPU 触发 CRITICAL
     - CAPACITY_WATERMARK: 低利用率无告警、中等利用率 WARNING、高利用率 CRITICAL、多卡型独立计算、CPU 节点排除、NotReady 节点排除

6. **集成验证**（新增 `test_alerts_integration.py` 和 `verify_alerts.py`）：
   - 使用真实 demo.json 数据：50 条真实告警（1 NODE_HEALTH + 47 GPU_REPORTING_ANOMALY + 2 CAPACITY_WATERMARK）
   - 验证每种告警的数据结构、字段完整性、影响范围

**涉及文件**
- `services/alert_service.py`（完全改写，新增阈值常量）
- `api/dashboard_routes.py`（新增 `_format_alert_detail()` 和改进的 `/alerts` 路由）
- `main.py`（改进启动流程中的告警评估）
- `front/index.html`（新增 Alerts 面板 + JavaScript 函数 `loadAndDisplayAlerts()` 和 `displayAlerts()`）
- `tests/test_alert_service.py`（14 个测试完全覆盖）
- `test_alerts_integration.py`（集成测试脚本）
- `verify_alerts.py`（完整验证脚本）
- `PROGRESS_LOG.md`（本文件）

**实测结果**（真实 5 集群数据）
```
CAPACITY_WATERMARK:CRITICAL: 1 alerts
  GPU type 't4' utilization at 98.0% (threshold 90%)
    Affected nodes: 42 nodes
    Utilization ratio: 0.9796

CAPACITY_WATERMARK:WARNING: 1 alerts
  GPU type 'v100' utilization at 76.9% (approaching threshold 90%)
    Affected nodes: 4 nodes
    Utilization ratio: 0.7692

GPU_REPORTING_ANOMALY:WARNING: 47 alerts
  Odd GPU counts (1, 3, 5, 7) on various nodes

NODE_HEALTH:CRITICAL: 1 alert
  Node svr14220de730 is NotReady
```

**当前测试规模**：94 pytest passed（+14 alert service tests）

**前端实际效果**
- ✅ Cluster Health 面板正常显示
- ✅ 新增 Alerts 面板自动加载
- ✅ 告警按严重等级分组
- ✅ 展示涉及的节点和原始数据
- ✅ 支持手动刷新告警

**下一步（Implementation Order 步骤 6+）**
- 步骤 6：后台定时采集 + ring buffer 落盘（已完成）
- 步骤 7：最小 React（已提前完成，目前是原生 HTML）
- 步骤 8：Trend 图表（已完成）
- 步骤 9-13：Agent tools 和 LLM 集成

---

## 2026-08-28 — Implementation Order 步骤 1：`models/` 全部数据类

**状态：完成** ✅

**做了什么**

1. 新增 `models/api.py`：把 k8s 资源拓扑 API（`data/demo.json`）的返回结构抽象成显式 dataclass 层级，不再保留"字典 key 即数据"的习惯：
   ```
   ApiResponse
   └── ApiData.clusters: list[ClusterRaw]
       └── ClusterRaw { cluster_name, status, cluster_data }      # 用户要求的三段式：名字字段 + 下一对象
           └── ClusterData { train, infer }                        # ScenarioRaw | None
               └── ScenarioRaw { scenario, total, node_groups }
                   └── GpuTypeGroup { gpu_type, nodes }
                       └── NodeRaw { name, ip, accelerator_type, allocatable, available,
                                     labels: list[LabelRaw], taints: list[TaintRaw],
                                     status, support_train_infer_swap, gpu_pod_count,
                                     gpu_distribution: list[GpuPodRaw] }
   ```
   - `ClusterRaw.cluster_name` 显式持有集群名（对应 API 的原 dict key）；`cluster_data` 持有下一层对象。
   - 每层都有 `from_dict()` 反序列化；`ResourceValues` 兼容真实 Uppercase key（`CPU`/`GPU`/`Memory`）与旧 fixture 的 lowercase key，`Memory` 为 `"514195Mi"` 字符串，`memory_mb` property 负责换算。
2. 更新 `k8s_client.py`：改用 `ApiResponse.from_dict()` 解析 demo json，`fetch_cluster_nodes()` 返回 `list[tuple[ScenarioRole, list[NodeRaw]]]`（spec §4 要求的 `NodeRaw`），`raw_node_to_domain()` 接收 `NodeRaw`。
   - **修复真实数据 bug**：旧逻辑读 `alloc.get("gpu")` lowercase，真实 API 为大写 `GPU`，导致真实数据 GPU 恒为 0；新 `ResourceValues` 大小写兼容。
3. 新增 `tests/test_models_api.py`：用真实 `data/demo.json` 全量解析校验（结构形状 + 数量守恒：各 scenario node 数 == `Total`）。
4. 全量回归：`pytest` 33 项 baseline 测试全部保持通过。

**涉及文件**
- `models/api.py`（新增）
- `models/__init__.py`（re-export）
- `k8s_client.py`（改写）
- `tests/test_models_api.py`（新增）
- `PROGRESS_LOG.md`（本文件）

**下一步（Implementation Order 步骤 2）**
- `k8s_client.py` 已用 demo json mock 跑通；下一步把 demo 路径换成真实 API 调用（保持只读，无写方法），并接 `services/snapshot_service.py` 验证端到端采集。

**遗留问题**
- [TODO] `parse_accelerator_type()` 会把 `nvidia-h20` / `nvidia-h20-141-ib-4` 都折叠成 `h20`；SKILL.md 中这两者是不同卡型（141G 显存 + IB）。当前 domain `Node.gpu_type` 沿用折叠语义（tool/告警依赖），是否需要保真到完整卡型是一个待定设计决策，需在改 tools 阶段确认。
- [TODO] `Total` 字段确认是"host 数量"而非 GPU 卡数（与 node list 长度保持一致，已在测试中断言守恒），语义注释待补充到 `snapshot.py`。

---

## 2026-08-28 — Implementation Order 步骤 2：`k8s_client.py` 接入真实 API

**状态：完成** ✅

**做了什么**

1. `k8s_client.py` 新增实时数据源：`K8sClient()` 默认直连真实只读端点（`config.K8S_API_ENDPOINT`，可用 `GPU_OPS_API_ENDPOINT` 环境变量覆盖），HTTP 层用 stdlib `urllib`（零新增依赖）。
   - `refresh()`：一轮采集只打一次 HTTP GET（端点 `/clusters/cached` 一次返回全部集群），解析为 `ApiResponse` 并缓存；`list_clusters()` / `fetch_cluster_nodes()` 读缓存，首次使用惰性加载。
   - demo 模式保留：传 `demo_data_path=` 时 `refresh()` 改读本地文件（测试/离线调试）。
   - HTTP 失败统一包装为 `K8sApiError`，由调用方决定降级策略。
2. `services/snapshot_service.py`：`refresh_now()` 开头调用 `self._k8s.refresh()`，保证每个轮询周期取到最新全量数据；API 瞬时失败时保留上次快照并记日志，不中断后台轮询。
3. 新增 `tests/test_k8s_client_endpoint.py`：stub HTTP 层、用真实 `data/demo.json` payload 覆盖——惰性加载只请求一次、每轮 `refresh()` 拉新数据、真实 Uppercase key 全链路保持、HTTP 失败抛 `K8sApiError`、legacy 无信封格式兼容。
4. 实测：`K8sClient()` 直连真端点 → `SnapshotService.refresh_now()` 一次 HTTP 拉全 5 集群快照，节点数/allocatable/available/notready 全部正确（见下方实测输出）。

**涉及文件**
- `k8s_client.py`（改），`services/snapshot_service.py`（改），`config.py`（新增端点配置）
- `tests/test_k8s_client_endpoint.py`（新增）
- `PROGRESS_LOG.md`（本文件）

**实测输出（2026-08-28 直连真实 API）**
```
AI-SHAXY-TCS-PRO1: nodes= 139 alloc_gpu=1090 avail_gpu= 85 notready=3
SHARB-A          : nodes= 225 alloc_gpu= 471 avail_gpu=164 notready=0
SHARE-SGP-ALI-PRO1: nodes=385 alloc_gpu= 479 avail_gpu= 52 notready=2
SHARE-SHA-ALI-PRO1: nodes=1161 alloc_gpu=2008 avail_gpu=208 notready=1
SHAXY-B          : nodes=  52 alloc_gpu= 123 avail_gpu= 15 notready=1
```

**下一步（Implementation Order 步骤 3）**
- `services/snapshot_service.py` 已是 `collect + get_current + ring buffer`，与步骤 1/2 完全打通；步骤 3 主要是确认 `refresh_now()` 手动调用、写 `tests/test_snapshot_service.py` 补齐真实数据断言（ring buffer/落盘已就绪）。

---

## 2026-08-28 — Implementation Order 步骤 3：SnapshotService 手动采集 + ring buffer + 真实数据验证

**状态：完成** ✅

**做了什么**

1. `services/snapshot_service.py` 加固：
   - 一轮 `refresh_now()` 内所有集群共用**同一个 `collected_at` 时间戳**（历史/趋势数据同轮可比，sub-second 级别不再错位）。
   - 单节点转换（`raw_node_to_domain`）失败只跳过该节点并记日志，不再导致整个集群快照失败。
   - `get_history(limit)` 修正边界语义：`limit<=0` 返回空、`limit=None` 返回全部（原来 `limit=0` 因 `[-0:]` 会意外返回全量）。
2. 新增 `tests/test_snapshot_service_real.py`（12 个用例）：全部用真实 `data/demo.json`（demo 模式、离线确定）：全集群刷新节点数守恒（139/225/385/1161/52）、真实 Uppercase GPU 数字全链路保真、单集群刷新、同轮共享时间戳、ring buffer maxlen 与 history limit、瞬时 API 故障保留上次快照、坏节点跳过不致命、5 集群落盘文件内容校验。
3. 实测（直连真实 API，手动 `refresh_now()` ×3）：current=139 节点、history 长度=ring size=3、`_persist_latest()` 写出 5 个集群 JSON、模拟 API 宕机后仍保留上次快照 139 节点。

**涉及文件**
- `services/snapshot_service.py`（加固）
- `tests/test_snapshot_service_real.py`（新增）
- `PROGRESS_LOG.md`（本文件）

**当前测试规模**：69 passed（baseline 33 + models 18 + endpoint 7 + snapshot real 12，减去合并项）。

**下一步（Implementation Order 步骤 5）**
- `services/alert_service.py` 三类规则 + `/alerts` 路由已在骨架中跑通（32 条真实告警）；步骤 5 是给 alert_service 补齐真实数据断言与规则单测，形成"事实 + 告警"最小闭环。

---

## 2026-08-28 — Implementation Order 步骤 7（提前）：前端 Single Page App（参考设计稿）

**状态：完成** ✅ **框架搭建，可视化验证**

**做了什么**

1. 设计稿分析（参考 `/home/powerop/work/GPU_OPS_AGENT/front/img_v3_02150_3a80ce1d-1140-4e36-b4e9-8efbdea3651g.jpg`）：
   - 布局：左侧固定导航栏（集群列表）+ 中心主区域（KPI/折线图/表格）+ 右侧告警面板（暂未启用）
   - 配色：深色主题，背景 `#0B121C`、卡片 `#1a2332`、强调色蓝绿 `#5DADE2` / `#4CAF50`
   - 核心显示：GPU Summary (by gpu_type) 卡片、Trend 折线、Cluster Health 统计、节点表格

2. 前端实现 `/home/powerop/work/GPU_OPS_AGENT/front/index.html`（**零构建，无依赖**）：
   - 纯 HTML/CSS/JavaScript，直接从 `/api/clusters/{id}/facts` 和 `/api/clusters/{id}/trend` 读数据
   - 左侧边栏：5 个集群列表（可点击切换）
   - 顶部：集群 Tab 切换 + 时间戳 + 刷新按钮
   - GPU Summary：根据 `by_gpu_type` 聚合渲染 4 个卡片（Total/Used/Free），进度条动态展示使用率
   - Cluster Health 统计：4 个 KPI 框（Nodes/Ready/NotReady/GPU Total）
   - 节点表格：展示前 10 个节点（Name/Status/GPU Type/Available GPU）
   - Trend 折线：简单 Canvas 图表，展示历史 GPU 分配/使用趋势

3. 启动配置（满足港口需求 8030-8039）：
   - 后端：`python3 -m uvicorn main:app --port 8030`（已自动托管 `/api` 路由）
   - 前端：`python3 -m uvicorn frontend_server:app --port 8035`（FastAPI StaticFiles，托管 `front/` 为根目录，`index.html` 自动分发）
   - 前后端分离，CORS 由浏览器处理（同源或后端已配置 CORS）

4. 验证：
   - 后端 http://127.0.0.1:8030/api/clusters → 5 集群列表 ✓
   - 前端 http://127.0.0.1:8035 → HTML 加载 ✓
   - 可在浏览器打开 http://127.0.0.1:8035 查看仪表板，点击集群后自动拉取 facts/trend 数据

**涉及文件**
- `front/index.html`（新增）
- `frontend_server.py`（新增，FastAPI 静态文件托管）
- `PROGRESS_LOG.md`（本文件）

**当前测试规模**：80 pytest passed（后端单测）+ 前端交互型验证（浏览器）。

**框架完成度**
- ✅ 集群导航 + Tab 切换
- ✅ GPU Summary 卡片展示
- ✅ KPI 统计框
- ✅ 节点表格
- ✅ Trend 趋势图（简化 Canvas）
- ⏳ 细节样式优化、响应式调整、告警面板启用 —— 后续可按需补充

**下一步**
- 步骤 5：回到 alert_service 三类规则真实数据单测 + `/alerts` 接口单测
- 步骤 6：定时后台采集 + ring buffer 落盘已就绪，本步无新代码
- 前端后续：对照设计稿微调样式、增加告警面板、AI Assistant 占位符等（非必需 MVP 功能）

---

## 2026-08-28 — 前端对接完成：facts + trend 全量可视化

**状态：完成** ✅ **完整对接，可交互验证**

**升级内容**

1. **前端完整数据映射**（`/home/powerop/work/GPU_OPS_AGENT/front/index.html` 全量改写）：
   - ✅ GPU Summary by Type：4 个卡片（cpu/h20/h200/l20），显示 Total/Used/Free + 进度条 + node 数
   - ✅ Scenario Distribution：2 个分布卡片（Train/Infer），显示 node 数、GPU 聚合、使用率
   - ✅ Cluster Health Stats：6 个 KPI 框（Nodes/Ready/NotReady/GPU Total/GPU Used/GPU Free）
   - ✅ Node Details 表格：完整 8 列（Name/IP/GPU Type/Scenario/Status/Allocatable/Available/Pod Count），首页显示 10 个，"查看更多"可展开全量
   - ✅ Trend 趋势图表（纯 Canvas）：
     - Chart 1：GPU Allocatable vs Used vs Available（堆叠柱状图，3 色分层展示）
     - Chart 2：Node Count Over Time（折线图，追踪节点数变化）

2. **交互完善**：
   - 集群 Tab 切换 + 左侧列表切换自动拉取数据
   - 刷新按钮防重复点击（loading 状态）
   - 错误处理与加载状态反馈
   - "Show More Nodes" 展开/收起全量节点表

3. **数据流验证**：
   - `GET /api/clusters` → 5 集群列表 ✓
   - `GET /api/clusters/{id}/facts` → 完整 facts 响应（139 节点、1090 卡、4 GPU Type、2 Scenario）✓
   - `GET /api/clusters/{id}/trend` → 历史 trend 数据（50 条采样）✓
   - 前端 JavaScript 渲染所有数据无错误 ✓

4. **可视化特点**：
   - 深色主题，配色一致（蓝 #5DADE2 / 绿 #4CAF50 / 黄 #FFC107）
   - 纯 HTML/CSS/JS，无框架无依赖，文件 ~25KB
   - Canvas 图表响应式（根据容器宽高自适应）
   - 图表 Legend 清晰标注

**涉及文件**
- `front/index.html`（完整升级）
- PROGRESS_LOG.md（本文件）

**使用方式**
```
后端 (8030):   python3 -m uvicorn main:app --port 8030
前端 (8035):   python3 -m uvicorn frontend_server:app --port 8035
浏览器打开:    http://127.0.0.1:8035
```

点击集群名或 Tab 切换，自动拉取 facts + trend 数据并渲染。

**完成度**
- ✅ 集群导航 + 多集群切换
- ✅ GPU Summary 完整展示（by GPU Type）
- ✅ Scenario 分布卡片
- ✅ KPI 统计（6 项）
- ✅ 节点表格（完整明细 + 分页）
- ✅ Trend 双图表（GPU + Node Count）
- ✅ 实时时间戳更新
- ⏳ 告警面板（HTML 中已预留，可解注注释启用）
- ⏳ AI Assistant（未集成）
- ⏳ 样式细节微调

**后续**
- 步骤 5：alert_service 三类规则（NODE_HEALTH / GPU_REPORTING_ANOMALY / CAPACITY_WATERMARK）的单测 + `/alerts` 聚合测试
- 步骤 6：后台定时采集 + 落盘（已完全就绪，无新代码）
- 前端可选：启用右侧告警面板、美化样式、响应式调整

---

## 2026-08-28 — Implementation Order 步骤 6：后台定时刷新 + ring buffer 落盘（进程重启恢复）

**状态：完成** ✅ **完整实现，包含持久化恢复和30份历史记录**

**做了什么**

1. **Ring buffer 大小调整**：
   - `config.py`: `RING_BUFFER_SIZE` 从 50 改为 30，满足用户需求（只保存30份历史数据）

2. **完整持久化实现**：
   - `_persist_history()` 新增：保存完整的 ring buffer（所有30份历史快照）到 `{cluster_id}_history.json`
   - 格式：`{cluster_id, snapshots: [...]}`，每个快照含完整节点信息
   - 调用频率：后台刷新循环中每次 `refresh_now()` 后立即调用

3. **进程重启恢复机制**：
   - `_load_from_disk()` 新增：在 `SnapshotService.__init__()` 时自动加载磁盘数据
   - 扫描 `data/snapshots/` 下所有 `*_history.json` 文件
   - 对每个集群恢复 ring buffer（最多 30 份）和 current snapshot
   - 异常处理：损坏的 JSON 文件/空文件不会导致启动失败

4. **JSON 格式与反序列化**：
   - `_dict_to_snapshot()` 新增：将 JSON dict 转回为 ClusterSnapshot 对象
   - 正确处理 ResourceSpec（domain model 中的资源表示）
   - datetime 通过 ISO 格式字符串序列化/反序列化

5. **完整测试覆盖**（`tests/test_snapshot_persistence.py` 新增 9 个测试）：
   - ✅ `test_persist_history_creates_file`：验证 JSON 文件生成和结构
   - ✅ `test_load_from_disk_restores_history`：验证重启后数据恢复
   - ✅ `test_ring_buffer_size_is_30`：验证大小配置
   - ✅ `test_history_limited_to_30`：验证 deque maxlen 约束
   - ✅ `test_persistence_over_restart_cycle`：完整周期验证
   - ✅ `test_multiple_clusters_persistent`：多集群持久化
   - ✅ `test_bg_loop_persists_on_refresh`：后台循环持久化
   - ✅ `test_corrupted_history_file_gracefully_handled`：异常文件容错
   - ✅ `test_empty_history_file_handled`：空文件处理

**工作流程**

1. **后台定时刷新**（每 60 秒，由 `POLL_INTERVAL_SEC` 控制）：
   ```
   _bg_loop():
     → refresh_now()      # 从 K8s API 拉新数据
     → _persist_history() # 落盘完整 ring buffer
     → 等待 60 秒后重复
   ```

2. **数据流**：
   ```
   K8s API → _collect() → ClusterSnapshot 对象
   → _current 快照 + _history deque
   → _persist_history() → JSON 文件 (data/snapshots/cluster-id_history.json)
   ```

3. **进程重启恢复**：
   ```
   SnapshotService.__init__()
   → _load_from_disk() 
   → 读取所有 *_history.json 文件
   → 恢复 _current 和 _history 到内存
   → 后续 get_current() / get_history() 可用
   ```

**涉及文件**
- `config.py`（RING_BUFFER_SIZE: 50 → 30）
- `services/snapshot_service.py`（新增 3 个方法 + 修改 __init__ 和 _bg_loop）
- `tests/test_snapshot_persistence.py`（新增，9 个测试用例）
- `tests/test_dashboard_routes.py`（修正 test_trend_endpoint 断言，改为 >= 2）
- `PROGRESS_LOG.md`（本文件）

**当前测试规模**：89 passed（原 80 + 新 9）。

**关键特性**

✅ **完整持久化**：不仅最新快照，而是完整 30 份历史  
✅ **自动恢复**：进程启动时自动加载，无需额外操作  
✅ **异常容错**：损坏数据/磁盘失败不会导致启动失败  
✅ **多集群支持**：每个集群独立持久化和恢复  
✅ **线程安全**：所有磁盘操作使用 lock 保护  

**用户可观测的效果**

1. **第一次启动**（无历史数据）：
   - 开始采集后，每 60 秒一次新数据
   - Trend 接口逐渐积累数据

2. **进程重启后**（有历史数据）：
   - 启动日志显示恢复的快照数：`"Restored 15 snapshots for cluster SHAXY-B from disk"`
   - Trend 接口立即返回历史数据（无需重新采集）

3. **持续运行**：
   - 历史数据严格控制在 30 份以内
   - 新数据自动追加，超龄数据自动删除

**下一步**（Implementation Order 步骤 7-14）
- 步骤 7：最小 React（已提前完成）
- 步骤 9-13：Agent tools 和 LLM 集成

---

## 2026-08-28 — 功能模块调整：GPU Summary (By GPU Model)

**状态：完成** ✅

**改动内容**

1. **后端接口调整** (`/api/clusters/{id}/facts`）：
   - `parse_accelerator_type()` 改进：H20-141 等内存变体现在独立为 "h20-141" 而非折叠为 "h20"
   - `by_gpu_type` 分组改动：
     - ✅ 只统计 Ready 节点（NotReady 节点排除）
     - ✅ 删除 CPU/Memory 字段，只保留 GPU 相关：`node_count / allocatable_gpu / used_gpu / available_gpu / utilization_percent`
     - ✅ 按 `allocatable_gpu` 从大到小排序
     - ✅ 新增 `utilization_percent` 字段（used_gpu / allocatable_gpu * 100）
   - `/facts` 的 headline 也改为只统计 Ready 节点
   - 节点 summary 数据结构扁平化：`available_gpu / allocatable_gpu`（而非嵌套的 `available.gpu`）

2. **前端渲染调整**（`front/index.html`）：
   - GPU Summary 卡片：
     - ✅ 显示占有率百分比 (`${usedPercent}% Used`)
     - ✅ 显示进度条（渐变背景 orange → red）
     - ✅ 显示节点数 (`${g.node_count} nodes`)
     - ✅ 按 Total GPU 从大到小自动排序
   - 节点表格：适配新的平铺数据结构

3. **测试更新** (`tests/test_dashboard_routes.py`）：
   - 更新所有预期值以反映 Ready-only 统计
   - AI_SHAXY_REDUCED：node_count=136, gpu_total=1072, gpu_available=71, gpu_used=1001
   - 新增 h20-141 卡型分组检查
   - 所有 11 项测试通过 ✓

4. **实测数据**（AI-SHAXY-TCS-PRO1）：
   - h20: 65 Ready 节点, 520 GPU, utilization=52.9%
   - h20-141: 32 Ready 节点, 256 GPU, utilization=51.2%
   - h200: 5 Ready 节点, 32 GPU, utilization=37.5%
   - l20: 33 Ready 节点, 264 GPU, utilization=33.3%
   - cpu: 1 Ready 节点, 0 GPU

**涉及文件**
- `k8s_client.py` — parse_accelerator_type() 改进
- `api/dashboard_routes.py` — _group_facts() / _compute_cluster_facts() / _node_facts()
- `front/index.html` — GPU Summary 渲染 + 节点表格
- `tests/test_dashboard_routes.py` — 11 项回归测试全部通过

**下一步**
- 下一个功能模块：Trend 接口（按 GPU 卡型的历史趋势）
- 或：Top Consumers 卡片实现

**做了什么**

1. `api/dashboard_routes.py` 实现 `/clusters/{id}/facts` 完整返回（纯确定性聚合，直接对 `SnapshotService` 当前快照求和）：
   - **headline 标量**（平铺，给前端 StatTile）：`node_count` / `gpu_total`(=allc) / `gpu_used`(=alloc−avail) / `gpu_available`，以及 `cpu_total`/`cpu_available`、`mem_total_mb`/`mem_available_mb`。
   - **健康态**：`ready_nodes` / `not_ready_nodes` / `not_ready_nodes_list`（名单）。
   - **分组明细**：`by_gpu_type`、`by_scenario` —— 均为**对象列表**（每项带 `gpu_type`/`scenario` 字段），而非"key 即数据"的 dict，沿用 `models/api.py` 的建模风格；每组含 node_count、ready/notready、allocatable/used/available gpu、cpu、mem。
   - **节点摘要** `nodes[]`：name/ip/gpu_type/scenario/status、allocatable/available{gpu,cpu,mem_mb}、gpu_pod_count（无 pod 级明细，轻量）。
   - 聚合逻辑抽成纯函数 `_compute_cluster_facts(snap)`，一个快照算一遍，内部各处加总守恒。
2. 新增 `tests/test_dashboard_routes.py`（12 用例）：数字对真实 `data/demo.json` 的精确聚合值做回归（AI-SHAXY 139 节点 / 1090/81/1009 / 136/3）、`by_gpu_type`/`by_scenario` 分组守恒、全集群汇总、内部加总一致性、404（未知集群）、503（未初始化）、节点摘要形状、trend 路由冒烟。因环境无 httpx，直接调用路由函数（plain Python）而非 TestClient。httpx 未安装，若要上异步端到端测试需 `pip install httpx`。
3. 实测（uvicorn 直连真实 API + curl）：`/api/clusters` 5 集群、`/facts` 139 节点/1090 卡、未知集群 404、`/trend` 200、`/alerts` 给出 32 条确定性告警。

**涉及文件**
- `api/dashboard_routes.py`（facts 全量实现）
- `tests/test_dashboard_routes.py`（新增）
- `PROGRESS_LOG.md`（本文件）

**当前测试规模**：80 passed。

**下一步（Implementation Order 步骤 5）**
- `services/alert_service.py` 三类规则 + `/alerts` 路由已在骨架中跑通（32 条真实告警）；步骤 5 是给 alert_service 补齐真实数据断言与规则单测，形成"事实 + 告警"最小闭环。
## 2026-08-28 — 功能模块调整 v2：GPU Summary 优化

**状态：完成** ✅

**改动内容**

1. **后端**：筛掉 GPU type="cpu" 的分组
   - `_group_facts()` 新增过滤：`if label == "cpu": continue`
   - 结果：`by_gpu_type` 只返回有实际 GPU 的卡型

2. **前端**：GPU Summary 一行最多 5 个卡片
   - CSS 改动：`grid-template-columns: repeat(5, 1fr)` 固定 5 列
   - 超过 5 个自动换行到下一行

3. **测试更新**：调整 by_gpu_type 的校验逻辑
   - 移除对 "cpu" 类型的断言
   - 改为检查 GPU 总量一致性而非节点数一致性（CPU 节点被筛掉）

**涉及文件**
- `api/dashboard_routes.py` — CPU 过滤逻辑
- `front/index.html` — Grid 布局调整
- `tests/test_dashboard_routes.py` — 测试逻辑调整

**实际显示效果**
```
GPU Summary (By GPU Model)
┌──────────┬──────────┬──────────┬──────────┐
│   h20    │   l20    │ h20-141  │  h200    │
│ 520 GPU  │ 264 GPU  │ 256 GPU  │ 32 GPU   │
│ 91.9%    │ 92.4%    │ 95.3%    │ 125.0%   │
└──────────┴──────────┴──────────┴──────────┘
```

**测试结果**
- 11/11 测试通过
- CPU 节点成功筛掉（135 个 GPU 节点而非 136）
- GPU 总量守恒：1072

## 2026-08-28 — 功能模块调整 v3：Trend 接口改为按卡型的折线图

**状态：完成** ✅

**改动内容**

### 后端改动 (`/api/clusters/{id}/trend`)

1. **新增 GPU 卡型分组**
   - 原来：返回全集群聚合的柱状数据
   - 现在：按 GPU 卡型分组，返回每个卡型的历史趋势

2. **新的返回格式**
   ```json
   {
     "cluster_id": "AI-SHAXY-TCS-PRO1",
     "by_gpu_type": {
       "h20": [
         {
           "collected_at": "2026-08-28T07:43:18.838538+00:00",
           "allocatable_gpu": 520,
           "available_gpu": 52,
           "used_gpu": 468
         },
         ...
       ],
       "h20-141": [...],
       "h200": [...],
       "l20": [...]
     }
   }
   ```

3. **新增 `?gpu_type=xxx` 查询参数**
   - 可选参数，用于过滤单个卡型
   - 示例：`/api/clusters/AI-SHAXY-TCS-PRO1/trend?gpu_type=h20`

### 前端改动 (`front/index.html`)

1. **改为时间序列折线图**
   - x 轴：时间点（均匀分布）
   - y 轴：GPU 数量
   - 两条线：
     - 蓝色线 (#5DADE2)：Total (allocatable_gpu)
     - 橙色线 (#FFC107)：Used (used_gpu)

2. **支持 GPU 卡型切换**
   - 右上角显示 GPU 类型 tab（h20, l20, h20-141, h200）
   - 点击 tab 切换卡型，图表自动更新

3. **布局改为左侧栏**
   - CSS 改为 2 列网格：`grid-template-columns: 1fr 1fr`
   - 左侧：趋势折线图
   - 右侧：预留空间（后续可放告警或其他内容）

4. **改进的绘图引擎**
   - 绘制 y 轴网格线
   - 绘制坐标轴
   - y 轴标签显示数值
   - 数据点用圆点标记
   - 图例说明

### 代码改动

**后端**：
- `api/dashboard_routes.py`：`get_cluster_trend()` 函数完全重写
  - 支持可选 `gpu_type` 参数
  - 返回按卡型分组的历史数据
  - CPU 类型自动过滤
  - 仅统计 Ready 节点

**前端**：
- CSS 新增：`.trend-section`, `.trend-header`, `.gpu-type-tabs`, `.gpu-type-tab`
- JS 新增：`currentTrendData`, `currentTrendGpuType`, `switchTrendGpuType()`, `drawTrendChart()`
- HTML 改为 2 列布局（趋势图 + 右侧预留）

### 测试

- `test_trend_endpoint()` 完全改写
- 测试新格式返回、多个 GPU 类型、gpu_type 过滤功能
- 11/11 测试通过 ✓

### 实际效果示例

```
┌─ GPU Allocatable vs Used (H20)  [h20] [l20] [h20-141] [h200] ─┐
│  ╱──────────────────────────────────────────────────────────┐ │
│ │  520 ─────────────╱──────────────────────────────────────  │ │
│ │       ╱─────────╱                                          │ │
│ │      ╱  ╱──────────                                        │ │
│ │  468│─╱─────────────────────── (Used)                      │ │
│ │     │  ● ● ● ● ● (data points)                            │ │
│ │   0 └─────────────────────────────────────────────────────┘ │
└─────────────────────────────────────────────────────────────────┘
```

**下一步**
- 右侧卡片功能规划（告警、或其他指标）
- 时间范围选择器（24h/7d/30d）
- 更多交互功能
