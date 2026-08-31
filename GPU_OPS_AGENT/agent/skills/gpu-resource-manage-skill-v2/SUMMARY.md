# Skill 重构总结 (v1 → v2)

## 版本对比

### ✅ 已修复的严重问题

| 问题 | v1 状态 | v2 修复 |
|---|---|---|
| **Frontmatter 结构** | 缺少 `---` 分隔符，无法被正确解析 | ✓ 添加标准 YAML frontmatter，`name`/`description` 可正常触发 |
| **异常判定逻辑** | "奇数卡数=异常"规则，误报单卡机型为异常 | ✓ 重写逻辑，支持命名解析+Total交叉校验，准确率大幅提升 |
| **手工累加数值** | 要求逐节点在上下文累加几千行 JSON 里的数字 | ✓ 引入 `topology_query.py` 脚本，所有求和/过滤由代码完成 |
| **集群数量描述** | 说"4个集群"但列出5个 | ✓ 正确改为 5 个集群 |
| **字段大小写** | `label`/`taint` 与真实 JSON 的 `Label`/`Taint` 不一致 | ✓ 全部改为 PascalCase |

### ✅ 已修复的高优先级问题

| 问题 | v1 状态 | v2 修复 |
|---|---|---|
| **Description 冗余** | 与 When to Use 95% 重复，写成列表格式 | ✓ 改为单段落自然语言，加入负向说明（不适用场景）；When to Use 简化为核心清单 |
| **SupportTrainInferSwap 字段缺失** | 未文档化；binpack/候选搜索都没用上 | ✓ 在字段说明、排障流程、swap-candidates 脚本中全面应用 |
| **Total 字段缺失** | 未文档化；上报异常检测没有交叉校验手段 | ✓ 支持 Total vs 实际节点数对比，作为异常信号 |
| **排障流程断层** | 未提及 Train↔Infer 场景切换可能性 | ✓ 在"调度不上去"流程里加入检查另一 namespace 的步骤 |
| **Binpack 案例冗长** | 详细案例（7 行叙述）硬编码在主文件里 | ✓ 拆到 `references/binpack-migration-playbook.md`，主文件仅指向 |

## 新增关键工具

### `scripts/topology_query.py`

**功能**：确定性聚合脚本，支持 8 条子命令覆盖所有查询场景。

```bash
# 核心命令示例
python topology_query.py <json> summary --cluster X --namespace Y --cardtype Z
python topology_query.py <json> candidates --cluster X --namespace Y --cardtype Z --need N
python topology_query.py <json> swap-candidates --cluster X --cardtype Z --need N
python topology_query.py <json> fragmentation --cluster X --namespace Y --cardtype Z
python topology_query.py <json> anomaly --cluster X
```

**优势**：
- 代码级精确性（不依赖 LLM 算术）；
- 支持别称解析（"日坂"→ SHARB-A，"训练"→ Train）；
- 错误路径清晰（JSON 格式告知用户具体问题）；
- 输出结构化（JSON），便于解析和展示。

### `references/data-schema.md`

**内容**：
- 5 个集群的完整别称对照表
- Train/Infer 的双重含义解释
- AcceleratorType 命名规则（15+ 示例）
- 12 个节点字段详解（Name/Ip/Allocatable/Available/Status/Label/Taint/SupportTrainInferSwap/GPUDistribution 等）
- **正确的** GPU 上报异常判定规则（6 条）

**用法**：命中需要解释 JSON 结构的场景时按需加载（不像 v1 那样硬塞在主文件里）。

### `references/binpack-migration-playbook.md`

**内容**：
- 迁移原理（为什么需要多方案）
- 完整案例（4 台机器，多个方案对比）
- 方案输出规范（最优+备选+风险提示）
- 脚本调用指南

**用法**：当用户问"怎么腾挪 8 卡整机"时加载。

## 主 SKILL.md 结构变化

| 部分 | v1 | v2 |
|---|---|---|
| Frontmatter | 缺 `---` | ✓ 标准 YAML 格式 |
| Overview | ~2 行 | ~2 行（无变化） |
| When to Use | 10 条 bullet | 2 段话：✅ 应该触发 + ❌ 不应该触发，更清晰 |
| Inputs | 1 行 | 2 行（加入禁止缓存说明） |
| **新增** | — | "快速查询"章节：8 条常用命令速览 |
| Instructions | 冗长（结构说明+字段表+异常判定+手工sum指令）| 简化为工作流 4 大场景，涉及的详细规则都引用到 references/ |
| 输出规范 | 简单 4 条 | 具体 4 大类（数字/清单/告警/迁移）的输出范例 |
| 限制 | 2 条 | 5 条（新增脚本优先、Train↔Infer 检查 SupportTrainInferSwap）|

## 关键改进点

### 1. Frontmatter

```yaml
# ✅ v2: 标准格式
---
name: gpu-resource-topology-managing
description: <单段自然语言，含正负向说明>
---

# ❌ v1: 无分隔符，description 是列表
name: gpu-resource-topology-managing-skills
description:
- 查询GPU集群的资源拓扑...
- 查询GPU集群下某台具体...
```

### 2. Description

```
# ✅ v2: 紧凑 + 关键词融入 + 负向说明
GPU k8s 集群容量/调度诊断。用于解析最新的 resource-topology JSON 快照，
分析资源拓扑、调度失败根因、健康异常、空闲建议等。支持查询指定集群/卡型/namespace，
进行多维度数据聚合和 binpack 迁移规划。
【仅适用于已有 JSON 快照的场景；不适用于驱动/硬件/应用层故障排查】

# ❌ v1: 冗长列表，无负向说明
description:
- 查询GPU集群的资源拓扑/资源视图时调用；
- 查询GPU集群下某台具体GPU宿主机的健康状态...
- ... [10 条重复内容]
```

### 3. 工作流层次

```
# ✅ v2: 按用户场景分层
## 工作流
### 1. 资源总量查询
  → 调用 summary
  → 脚本返回 JSON
  → 提取数字，生成摘要

### 2. 调度失败诊断
  第一步: 调用 summary
  第二步: 调用 candidates
  第三步(可选): 调用 swap-candidates
  → 输出候选机器或确认需要 binpack

# ❌ v1: 生硬的规则列表
### 排查某个集群下打着某类标签的pod为什么调度不上去时
1. 先判断该集群下该类标签是否有宿主机；
2. 如果有宿主机，筛选可调度的候选宿主机列表。
   筛选的规则是判断集群下这类卡型是否存在...
3. 如果候选宿主机为空，那么可以合理怀疑是因为...
   [纯文字说明，没有对应的脚本命令]
```

### 4. 异常判定

```python
# ✅ v2: 在脚本中正确实现
def _expected_gpu_from_cardtype(cardtype):
    if cardtype == "cpu":
        return None  # CPU 节点跳过检查
    parts = cardtype.split("-")
    for p in parts:
        if p.isdigit() and int(p) in (1, 2, 4, 8):
            return int(p)  # 从命名解析预期卡数
    return None

# 然后在异常检测里：
if expected is not None and alloc not in (0, expected):
    problems.append(f"命名卡数{expected} != 实际{alloc}")

# ❌ v1: 错误规则
如果Allocatable为0，或者是单数那么显卡上报一定异常
# 这会误报所有 nvidia-tesla-*-1-* 类型的单卡机器
```

## 可扩展方向

v2 框架为以下方向预留了扩展空间：

1. **多快照对比**：支持用户提供两份时间点不同的 JSON，分析机器状态变化趋势；
2. **IB 网络感知**：binpack 建议中加入对 `-ib-` 高网拓扑的考虑，更适合分布式训练；
3. **NotReady 根因下钻**：若用户补充 `kubectl describe node` 的 Conditions 信息，升级到"为什么不健康"而非"确认不健康"；
4. **平台联动**（未来）：接入 Peta/Captain 调度数据，将"建议迁移 pod X"落到"在 Peta 上如何操作"的可执行步骤。

## 使用指南

### 原旧 v1 skill 如何过渡到 v2？

1. **不要删除 v1**（如果已在生产使用），改用 v2 作为**新文件** `gpu-resource-manage-skill-v2/`；
2. 确保 Claude Code 加载新路径（`SKILL.md` 位置要在 `.claude/` 下的某个子目录里）；
3. 测试几个常用查询确认 frontmatter 识别正常、脚本运行正常；
4. 逐步用 v2 替代 v1（或并行一段时间）。

### 核心注意事项

✅ **必做**：
- 每次查询都要求用户提供**最新** JSON
- 优先调用脚本，不要手工累加
- binpack 方案必须给出 2～3 个备选
- 跨 namespace 建议必须检查 `SupportTrainInferSwap`

❌ **禁做**：
- 不编造数据
- 不使用缓存
- 不用"奇数=异常"判断 GPU 上报
- 不忽视 CPU/Memory 约束（只看 GPU）

---

## 验证清单

- ✓ Frontmatter 格式正确（`---` 分隔）
- ✓ Description 单段落，含正负向说明
- ✓ `topology_query.py` 脚本 8 条命令全部测试通过
- ✓ 集群数从 4 改为 5
- ✓ 字段大小写统一为 PascalCase
- ✓ 异常判定逻辑重写
- ✓ Train↔Infer 互转流程补完
- ✓ 详细案例拆到 `binpack-migration-playbook.md`
- ✓ 字段说明拆到 `data-schema.md`
- ✓ 新增"快速查询"章节
- ✓ 输出规范补充具体范例

---

**v2 SKILL 副本已完整创建在**：`d:\GPU\ai-octopus\.claude\gpu-resource-manage-skill-v2\`

**包含文件**：
- `SKILL.md` ← 主 skill 文件（已修复所有严重和高优问题）
- `scripts/topology_query.py` ← 查询脚本（8 条命令）
- `references/data-schema.md` ← 数据结构说明（按需加载）
- `references/binpack-migration-playbook.md` ← 迁移规划指南（按需加载）
- `references/resource-topology-api-result-demo.json` ← demo 数据
