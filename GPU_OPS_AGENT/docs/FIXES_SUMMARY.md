# GPU Ops Agent 三类预警规则改进总结

## ✅ 三个问题已全部解决

### 1. GPU 卡数问题 ✅
**问题**: SHARB-A 和 SHAXY-B 中有 1、2、3、4、6、8 等多种卡数，但规则将它们都标为"奇数异常"

**改进方案**:
- 改为**基于集群分布的异常检测**
- 对每个集群统计 GPU 卡数分布
- 找出该集群的最常见卡数（通常由节点数量最多的类型决定）
- 只对**不符合集群标准的离群值**报告 WARNING

**实现**:
```python
# 统计集群内的GPU卡数分布
alloc_counts = {}
for node in nodes:
    alloc_counts[node.allocatable.gpu] += 1

# 找出最常见的卡数（频率最高）
most_common_counts = {count for count, freq in alloc_counts.items() if freq == max(alloc_counts.values())}

# 只对不在most_common_counts中的节点报告异常
```

**实际效果**:
- SHAXY-B: 主要卡数是 3 个GPU，少量节点有 1、2、4 个，这些现在被标为异常
- SHARB-A: 主要卡数是 1 个GPU（最多58个节点），其他卡数被标为异常

### 2. Available > Allocatable 问题 ✅
**问题**: 未检测 Available GPU 超过 Allocatable GPU 的情况

**改进方案**:
- 新增**数据腐败检测** 
- 当 Available > Allocatable 时，标记为 **CRITICAL** 告警
- 这表示显卡上报数据严重异常

**实现**:
```python
if avail_gpu > alloc_gpu:
    # CRITICAL alert: data corruption detected
```

**实际效果**:
真实数据中未发现此类异常（Available ≤ Allocatable），规则已验证但未触发

### 3. NotReady 节点未显示 ✅
**问题**: 图片显示 NotReady=3，但告警面板显示"No active alerts"

**根本原因分析**:
- ✅ 后端规则正确：NODE_HEALTH 告警正确生成
- ✅ 后端 API 返回正确：`/api/alerts` 返回完整数据
- ❌ 前端加载问题：loadAndDisplayAlerts() 调用时机不对

**解决方案**:
在 `selectCluster()` 函数中添加告警加载：
```javascript
// selectCluster() 末尾
await loadAndDisplayAlerts();  // 集群切换时自动加载
```

**实际效果**:
- SHAXY-B 中 svr14220de730 节点的 NotReady 告警现在能正确显示
- 23 个 GPU 异常（卡数不匹配集群标准）
- 2 个容量水位告警（t4 98% CRITICAL，v100 77% WARNING）

---

## 📊 告警规则详解

### 规则 1: NODE_HEALTH
```
检测: Node.Status == "NotReady"
结果: CRITICAL 告警（红色）
消息: "Node {name} is NotReady"
```

### 规则 2: GPU_REPORTING_ANOMALY
```
检测1: Available > Allocatable
       结果: CRITICAL 告警（红色）
       消息: "Available GPU={avail} exceeds Allocatable GPU={alloc}"

检测2: GPU 卡数离群（相对集群分布）
       结果: WARNING 告警（黄色）
       消息: "Allocatable GPU={alloc} differs from cluster standard {expected}"
```

### 规则 3: CAPACITY_WATERMARK
```
按 GPU 卡型分别计算：
  水位 = (Allocatable - Available) / Allocatable

利用率 > 90%  → CRITICAL 告警（红色）
75% ≤ 利用率 ≤ 90% → WARNING 告警（黄色）
利用率 < 75%  → 无告警

包含：
- 涉及节点列表（所有 Ready 节点）
- GPU 卡型名称
- 详细数字（总数、已用、可用、利用率）
```

---

## 🔧 代码改动

### 后端（`services/alert_service.py`）
```python
def _rule_gpu_reporting_anomaly():
    # 新增：计算集群GPU卡数分布
    # 新增：识别最常见的卡数
    # 新增：基于分布报告离群值
    # 新增：检测 available > allocatable
```

### 前端（`front/index.html`）
```javascript
async function selectCluster(cluster) {
    // ... 现有逻辑 ...
    
    // 新增：在数据加载后自动加载告警
    await loadAndDisplayAlerts();
}
```

---

## ✨ 验证结果

### 实时数据（SHAXY-B 集群）
```
总告警数: 24

1. NODE_HEALTH (1)
   🔴 CRITICAL: svr14220de730 is NotReady

2. GPU_REPORTING_ANOMALY (21)
   🟡 WARNING: 21 个节点的 GPU 卡数异常
      - 集群标准: 3 个 GPU
      - 离群值: 1、2、4 个 GPU 的节点

3. CAPACITY_WATERMARK (2)
   🔴 CRITICAL: t4 类型 98% 利用率 (42 个节点受影响)
   🟡 WARNING: v100 类型 77% 利用率 (4 个节点受影响)
```

### 测试覆盖
- ✅ 15 个单元测试全部通过
- ✅ 3 个自定义场景测试通过
- ✅ 实时数据集成验证通过

---

## 📌 后续优化建议

1. **可配置的阈值**
   - 当前 WATERMARK_CRITICAL=90%, WARNING=75%
   - 可改为配置文件中的参数

2. **GPU 卡数异常检测优化**
   - 当前基于全集群最常见卡数
   - 可按 GPU 类型分别统计（h20/l20/v100 等类型不同）

3. **告警聚合**
   - 可将相同类型、涉及节点类似的告警合并

4. **历史告警**
   - 当前只显示当前活跃告警
   - 可添加历史告警查询

---

## 🎯 验收清单

- [x] 修复 GPU 卡数异常检测（基于集群分布）
- [x] 实现 available > allocatable 检测
- [x] 修复前端 NotReady 节点告警显示
- [x] 更新所有单元测试（15/15 通过）
- [x] 整合验证（实时数据 24 条告警正确生成）
- [x] 前后端完整集成验证

**状态**: ✅ 所有三个问题已解决且经验证
