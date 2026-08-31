---
name: gpu-resource-topology-managing
description: GPU k8s 集群容量/调度诊断。用于解析最新的 resource-topology JSON 快照，分析资源拓扑、调度失败根因、健康异常、空闲建议等。支持查询指定集群/卡型/namespace，进行多维度数据聚合和 binpack 迁移规划。仅适用于已有 JSON 快照的场景；不适用于驱动/硬件/应用层故障排查。
---

# GPU 资源拓扑分析 Skill

## 概述

本 skill 通过解析用户提供的 `resource-topology-api-result.json` 快照（来自 GPU 集群实时数据 API），对集群容量、节点健康、调度失败、碎片化等问题进行**数据驱动的诊断**。不进行硬件/驱动层排障，仅用于为运维决策提供结构化数据佐证。

## 适用场景

✅ **应该触发此 skill**：

- 查询 GPU 集群整体资源拓扑/资源视图；
- 查询某台宿主机的健康状态、总卡数、剩余可用卡数、运行的 pod；
- 查询某一类显卡卡型（如 H20/A100/L20）的全集群拓扑情况；
- 查询某种卡型一共有多少张、在训练/推理场景各有多少张；
- 查询某种卡型有多少张被占用、在训练/推理场景各有多少张；
- 查询训练/推理场景下空闲可用的显卡总数、及哪些机器还有空闲；
- 检测集群下是否存在不健康机器（Status ≠ Ready）；
- 检测是否存在 GPU 显卡上报异常的机器；
- 排查打着某类卡型标签的 pod 为什么调度不上去；
- 推荐空闲机器列表，规划 binpack 迁移方案以腾挪满足需求的整机；
- 发现 Train↔Infer 场景切换的可能性（SupportTrainInferSwap 机器）。

❌ **不应该触发此 skill**：

- Pod 启动失败、OOM、Xid 错误等应用层/驱动层问题；
- GPU 硬件故障诊断、温度异常、显存泄漏等；
- CUDA 环境配置、docker 镜像问题；
- 用户没有提供 JSON 快照，仅凭口头描述的"集群可能满了"。

## 输入要求

**必需**：用户必须提供一份**最新查询**的 `resource-topology-api-result.json` 文件，结构与 `references/resource-topology-api-result-demo.json` 完全一致。

**禁止使用缓存数据**：resource-topology 数据是**实时的**，会随集群调度不断变化。若需了解最新情况，必须使用用户提供的最新文件，不能用任何缓存/历史信息替代。

## 快速查询

本 skill 依赖脚本工具 `scripts/topology_query.py` 做所有的算术和过滤——不要手工在上下文里对几千个节点逐个累加。以下是常见命令速查：

### 命令速览

```bash
# 查看有哪些集群
python scripts/topology_query.py <json> clusters

# 某集群有哪些卡型
python scripts/topology_query.py <json> cardtypes --cluster 上海阿里云

# 汇总某集群某namespace某卡型的容量/占用/空闲
python scripts/topology_query.py <json> summary \
  --cluster 上海阿里云 \
  --namespace 训练 \
  --cardtype h20

# 查某个机器的完整详情（包括 pod 分布）
python scripts/topology_query.py <json> node --name vmsali01727032

# 检测是否有不健康或上报异常的机器
python scripts/topology_query.py <json> anomaly --cluster SHARE-SHA-ALI-PRO1

# 排查为什么 8 卡 pod 调度不上——哪些机器有 8 卡可用？
python scripts/topology_query.py <json> candidates \
  --cluster 上海阿里云 \
  --namespace 训练 \
  --cardtype h20 \
  --need 8

# 如果上面没找到 8 卡，检查另一 namespace（Train↔Infer）是否支持借调
python scripts/topology_query.py <json> swap-candidates \
  --cluster 上海阿里云 \
  --cardtype h20 \
  --need 4

# 分析碎片化情况，为 binpack 迁移规划找出驱逐最少 pod 的方案
python scripts/topology_query.py <json> fragmentation \
  --cluster 上海阿里云 \
  --namespace 训练 \
  --cardtype h20
```

### 集群/namespace 别称

**集群代码**：`AI-SHAXY-TCS-PRO1` / `SHARB-A` / `SHARE-SGP-ALI-PRO1` / `SHARE-SHA-ALI-PRO1` / `SHAXY-B`

**集群别称**举例（脚本可识别）：
- AI-SHAXY-TCS-PRO1 → 新源智算/智算/松江/松江智算/超算 
- SHARB-A → 日坂/日坂A
- SHARE-SGP-ALI-PRO1 → 阿里云新加坡/新加坡/SGP-ALI
- SHARE-SHA-ALI-PRO1 → 阿里云上海/上海阿里云/SHA-ALI
- SHAXY-B → 新源B/新源/SHAXY

**namespace 别称**（脚本可识别）：
- Train → train/训练/peta
- Infer → infer/推理/captain

## 工作流

### 1. 资源总量查询

用户问："阿里云上海有多少张 H20？训练场景一共多少？"

→ 调用 `python topology_query.py <json> summary --cluster 上海阿里云 --namespace 训练 --cardtype h20`

→ 脚本返回 JSON，包含：
- `total.Allocatable_GPU`: 总配额（所有机器加起来）
- `total.Available_GPU`: 当前可用（未被 pod 占用）
- `total.Used_GPU`: 当前已占用（Allocatable - Available）
- `total.node_count`: 机器总数
- `breakdown_by_cluster_namespace_cardtype`: 维度细分

→ 提取数字，生成用户友好的摘要输出。

### 2. 调度失败诊断

用户说："我有个 8 卡训练 pod 怎么老是 Pending，上海阿里云 H20 应该够呀？"

**第一步**：调用 `summary` 查总体容量是否充足。若 `Available_GPU >= 8` 但仍 Pending，说明**机器碎片化**。

**第二步**：调用 `candidates --need 8` 查是否存在某台单机 `Available.GPU >= 8`。
- 若有候选：输出这些机器，同时检查 CPU/Memory 是否也充足（可能不是 GPU 不足）；
- 若无候选：确认是 GPU 显卡分散在多台机器，需要 binpack 迁移。

**第三步**（可选）：若候选为空，检查**另一 namespace** 是否支持借调。调用 `swap-candidates --need 8`，查 Infer namespace 是否有满足需求的机器，且该机器 `SupportTrainInferSwap=true`。如果有，告诉用户可以考虑通过修改 role 把那台机器临时转到 Train 来用。

### 3. 健康检测

用户问或你主动巡检："集群有没有不健康的机器？"

→ 调用 `anomaly --cluster <code>`

→ 脚本返回两类异常：
- **node_level_issues**：某台机器的 `Available < 0`、`Available > Allocatable`、命名与实际 GPU 数不符等；
- **namespace_total_mismatches**：该 namespace 声明的 `Total` 与实际节点数不一致。

→ 逐条列出，输出表格形式：机器名 | IP | 异常原因。

### 4. Binpack 迁移规划

用户需要：整机 8 卡训练，但集群中不存在可用的完整机器。

→ 调用 `fragmentation --cluster X --namespace Y --cardtype Z`

→ 脚本按**驱逐 pod 最少优先**排序机器，输出拓扑细节。

→ 你需要向用户提供：
1. **最优方案**：哪台机器需要驱逐、驱逐哪些 pod、其余 pod 迁往何处；
2. **2～3 个备选方案**；
3. **风险提示**："这些方案仅基于数据推荐，实际驱逐前需确认 pod 业务性质"（某个可能是线上单实例会中断全部流量，某些可能是多实例有 DR）。

详见 `references/binpack-migration-playbook.md`。

## 数据模型

### 集群拓扑全景

5 个集群 × 2 个 namespace（Train/Infer）× 若干卡型 × 若干宿主机

- **集群代码**：见上文别称表
- **Train namespace**：训练场景，peta 平台调度，pod 以 `ocppro`/`job-`/`adhoc-` 开头，节点打 `role=gps-host` label
- **Infer namespace**：推理/线上服务，captain 平台调度，pod 以 `r1000-` 开头，节点打 `role=gpu-app-host` label
- 底层宿主机**无物理隔离**，可通过修改 role 实现 Train↔Infer 切换（前提是 `SupportTrainInferSwap=true`）

### 节点关键字段

详见 `references/data-schema.md`。简要说明：

- `Name`：机器唯一代码
- `AcceleratorType`：卡型（如 `nvidia-h20`, `nvidia-tesla-l20-4-192` 等）
- `Allocatable.GPU`：可供 pod 调度的 GPU 额度
- `Available.GPU`：当前真实剩余可用 GPU 数
- `Status`：`Ready` 或 `NotReady`，唯一的健康判定依据
- `GPUPodCount`：已调度 pod 数（不是卡数）
- `GPUDistribution`：`{pod名: 占用卡数}`，pod 级细节
- `SupportTrainInferSwap`：是否支持 Train↔Infer 角色切换，规划迁移/借调方案时必须检查
- `Label`/`Taint`：调度匹配条件

### GPU 上报异常判定

不要用"奇数卡数=异常"这种规则。正确判定见 `references/data-schema.md` 第 4.1～4.6 条。脚本 `topology_query.py anomaly` 已实现，直接调用即可。

## 输出规范

### 数字查询

"集群一共有多少张 H20？"

```
【查询结果】阿里云上海(SHARE-SHA-ALI-PRO1) Train namespace H20 卡统计
- 总配额 (Allocatable): 279 张
- 当前占用: 267 张（使用率 95.7%）
- 当前可用: 12 张
- 涉及机器: 35 台

来源: summary 汇总, 详见附表
```

### 机器清单查询

"哪些机器还有空闲？"

```
| 机器名 | IP | 集群 | 卡型 | 总卡 | 可用 | 占用 pod 数 | 状态 |
|---|---|---|---|---|---|---|---|
| vmsali01727032 | 10.24.16.242 | 上海阿里云 | nvidia-h20 | 8 | 8 | 0 | Ready |
| vmsali02026431 | 10.24.16.69 | 上海阿里云 | nvidia-h20 | 8 | 0 | 1 | Ready |
| ... | | | | | | | |

共 N 台机器有剩余, 其中 M 台完全空闲

来源: summary 或 candidates/fragmentation 输出
```

### 异常告警

"有没有不健康的机器？"

```
【异常发现】SHARB-A 集群共 2 个异常

【不健康机器】
| 机器名 | IP | Status | 卡型 | Allocatable GPU | Available GPU |
|---|---|---|---|---|---|
| svrgpu-121 | 192.168.1.x | NotReady | nvidia-h20 | 4 | ? |

【上报异常】
| 机器名 | IP | 卡型 | 异常症状 |
|---|---|---|---|
| svrgpu-456 | 192.168.1.y | nvidia-h20 | Available.GPU(-2) < 0 |

建议: NotReady 机器可能故障，需登机检查; 上报异常可能是驱动卡顿，建议 kubelet 重启

来源: anomaly 诊断
```

### Binpack 迁移建议

"需要一台整机 8 卡，怎么腾挪？"

详见 `references/binpack-migration-playbook.md`。输出包含最优方案+备选方案的详细拓扑、驱逐清单、风险提示。

## 限制与注意

1. **禁止编造数据**：若用户表述不清或提供的 JSON 无法回答问题，说"无法得出结论"，不要猜测。
2. **不能使用缓存**：每次查询必须用用户提供的**最新** JSON，不能用上一次查询结果或其它源代替。
3. **脚本优先**：所有可用脚本完成的查询都必须调用脚本，不要手工累加。脚本无法覆盖的边界情况才考虑手工分析。
4. **明确触发范围**：binpack 方案仅是**数据推荐**，最终决策权在运维人员，因为无法自动判断 pod 业务属性（单实例/多实例/有无 DR）。
5. **Train↔Infer 切换要检查**：任何涉及跨 namespace 的建议都必须检查节点 `SupportTrainInferSwap` 字段，不是所有机器都支持切换。
