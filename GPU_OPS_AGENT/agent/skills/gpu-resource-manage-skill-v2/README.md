# GPU 资源拓扑管理 Skill v2

## 🎯 什么是这个项目？

这是原 `gpu-resource-manage-skill` 的**优化副本**，修复了原版本的多个严重缺陷，并为 GPU k8s 集群运维人员提供**数据驱动的容量/调度诊断能力**。

## 🚀 快速开始

### 前置条件

- Python 3.7+（脚本 `topology_query.py` 依赖）
- 一份最新的 `resource-topology-api-result.json` 快照（从集群 API 导出）

### 核心命令

所有查询都通过 `scripts/topology_query.py` 完成：

```bash
# 查看有哪些集群
python scripts/topology_query.py <json> clusters

# 查某集群的资源汇总（H20卡型、训练场景）
python scripts/topology_query.py <json> summary \
  --cluster 上海阿里云 \
  --namespace 训练 \
  --cardtype h20

# 查为什么 8 卡 pod 调度不上去
python scripts/topology_query.py <json> candidates \
  --cluster 上海阿里云 \
  --namespace 训练 \
  --cardtype h20 \
  --need 8

# 检测是否有不健康/异常的机器
python scripts/topology_query.py <json> anomaly --cluster SHARE-SHA-ALI-PRO1

# 分析碎片化，规划 binpack 迁移
python scripts/topology_query.py <json> fragmentation \
  --cluster 上海阿里云 \
  --namespace 训练 \
  --cardtype h20
```

完整使用说明见 `SKILL.md`。

## 📁 项目结构

```
gpu-resource-manage-skill-v2/
├── SKILL.md                           ← 主 skill 文件（240+行）
├── scripts/
│   └── topology_query.py              ← 核心查询脚本（8条子命令）
├── references/
│   ├── data-schema.md                 ← 数据结构详解（按需加载）
│   ├── binpack-migration-playbook.md  ← 迁移规划案例（按需加载）
│   └── resource-topology-api-result-demo.json  ← demo 数据
├── SUMMARY.md                         ← v1→v2 重构对比
└── README.md                          ← 本文件
```

## ✨ 主要改进

### 🔴 严重问题修复

| 问题 | 影响 | 解决方案 |
|---|---|---|
| 缺少 YAML frontmatter (`---`) | skill 无法被正确加载 | ✓ 添加标准格式 |
| "奇数卡数=异常"判定规则 | 误报单卡机型（A100-1-80等）为异常 | ✓ 改用命名解析+Total交叉校验 |
| 手工累加数值 | 几千节点在上下文里累加 GPU 数易出错 | ✓ 引入 Python 脚本，代码级精确性 |
| 集群数说"4个"但列5个 | 信息混乱 | ✓ 统一改为 5 个 |

### 🟠 高优先级改进

- ✓ Frontmatter `description` 重写：单段+正负向说明，避免误触发
- ✓ `SupportTrainInferSwap` 字段全面应用：Train↔Infer 借调方案支持
- ✓ 排障流程补完：加入跨 namespace 场景切换检查
- ✓ 内容合理分割：binpack 案例/字段说明拆到 references/，主文件不臃肿

## 💻 技术亮点

### 脚本 `topology_query.py`

- 8 条子命令覆盖所有查询场景（clusters / cardtypes / summary / node / unhealthy / anomaly / candidates / swap-candidates / fragmentation）
- 集群/namespace 别称识别（"日坂"自动转换为 SHARB-A，"训练"转换为 Train）
- 所有输出都是 JSON 格式，便于解析和展示
- 错误消息清晰，告诉用户问题所在（如"未能识别集群，可选：[列表]"）

### 快速查询章节

主 SKILL 里新增"快速查询"部分，列出 8 条常用命令速览，用户可快速复制粘贴。

### 分层文档

- `SKILL.md` ← 主要工作流（用户日常看这个）
- `references/data-schema.md` ← 深入理解数据模型（不是每次都需要）
- `references/binpack-migration-playbook.md` ← 迁移规划案例（需要时加载）

## 🎓 使用示例

### 场景 1：查询集群容量

用户："上海阿里云有多少 H20？"

```bash
python topology_query.py api-result.json summary \
  --cluster 上海阿里云 \
  --namespace 训练 \
  --cardtype h20
```

输出：
```json
{
  "total": {
    "Allocatable_GPU": 279,
    "Available_GPU": 12,
    "Used_GPU": 267,
    "node_count": 35
  }
}
```

用户得到：279 张总配额、12 张可用、占用率 95.7%、35 台机器。

### 场景 2：诊断调度失败

用户："我的 8 卡训练 pod 一直 Pending，怎么回事？"

**第一步**：检查总体容量是否充足（使用 summary）。
**第二步**：检查是否存在某台单机有 8 卡可用。

```bash
python topology_query.py api-result.json candidates \
  --cluster 上海阿里云 \
  --namespace 训练 \
  --cardtype h20 \
  --need 8
```

- 若有候选 → 可能是 CPU/Memory 不足，检查这些资源；
- 若无候选 → 确认是 GPU 碎片化，需要 binpack 迁移。

### 场景 3：健康巡检

```bash
python topology_query.py api-result.json anomaly --cluster SHARE-SHA-ALI-PRO1
```

输出：
- NotReady 节点清单（需要登机检查）
- GPU 上报异常节点（Available < 0、Available > Allocatable 等）
- namespace Total 不匹配（接口层异常）

### 场景 4：规划 Binpack 迁移

用户："集群里没有整个 8 卡机器了，怎么腾挪给训练用？"

```bash
python topology_query.py api-result.json fragmentation \
  --cluster 上海阿里云 \
  --namespace 训练 \
  --cardtype h20
```

输出：按**驱逐 pod 最少优先**排序的机器清单，包含每台机器的拓扑细节（已运行 pod、占用情况）。

结合 `references/binpack-migration-playbook.md`，给出最优+备选方案，最终决策权给用户。

## 📖 完整文档

- **SKILL.md**：工作流说明、快速查询、4 大场景详解、输出规范、限制事项
- **data-schema.md**：5 个集群对照表、Train/Infer 含义、AcceleratorType 规则、12 个字段详解
- **binpack-migration-playbook.md**：迁移原理、完整案例（4 台机器多方案对比）、输出规范
- **SUMMARY.md**：v1→v2 重构细节对标

## ⚙️ 环境要求

- Python 3.7+
- 必须有 `resource-topology-api-result.json` 文件（最新数据）
- 无其它外部依赖（仅用标准库 `json/argparse/sys`）

## 🔗 与原 v1 的关系

- **v1**：`d:\GPU\ai-octopus\.claude\gpu-resource-manage-skill\`
- **v2**（本项目）：`d:\GPU\ai-octopus\.claude\gpu-resource-manage-skill-v2\`

v2 是全新优化副本，保留 v1 以便过渡。建议逐步用 v2 替代（或并行一段时间测试）。

## 📝 重要提醒

1. **每次都需要最新 JSON**：resource-topology 数据是实时的，禁止使用缓存或历史数据
2. **脚本优先**：所有可以用脚本完成的查询都必须调用脚本，不要手工累加
3. **Train↔Infer 检查**：任何跨 namespace 建议都要检查 `SupportTrainInferSwap` 字段
4. **Binpack 是建议**：迁移方案基于数据推荐，最终决策权在运维人员（因为无法判断 pod 业务属性）
5. **禁止编造**：若无法回答则说"无法得出结论"，不要猜测

## 🤝 反馈和扩展

### 可能的后续方向

- 多快照对比：支持用户提供两份不同时间点的 JSON，分析趋势
- IB 网络感知：binpack 建议中考虑 `-ib-` 高网拓扑
- NotReady 根因下钻：结合 `kubectl describe node` 提供更详细的故障诊断
- 平台联动：接入 Peta/Captain 调度数据，升级到"怎样操作"层面

---

**v2 版本创建时间**：2026-08-27  
**状态**：✓ 所有严重和高优问题已修复，可投入使用
