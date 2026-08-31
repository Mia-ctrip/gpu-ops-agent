# 数据结构说明 (resource-topology-api-result.json)

本文档配合 `resource-topology-api-result-demo.json` 阅读，供命中需要理解原始 JSON 结构的场景时按需加载。日常的求和/筛选类查询请优先使用 `scripts/topology_query.py`，不要手工在上下文里逐节点累加。

## 顶层结构

```json
{
  "Code": 200, "Success": true, "Message": "OK", "TraceID": "...",
  "Data": {
    "Clusters": {
      "<集群Code>": {
        "Status": "OK",
        "Data": {
          "Train": { "Total": <int>, "Nodes": { "<AcceleratorType>": [ <Node>, ... ] } },
          "Infer": { "Total": <int>, "Nodes": { "<AcceleratorType>": [ <Node>, ... ] } }
        }
      }
    }
  }
}
```

- 最外层 `Code/Success/Message/TraceID` 是**接口层状态**，忽略；
- 每个集群 `Data` 前的 `Status` 字段同样是**接口层状态**，不是机器健康信号——判断机器是否健康只看 `Nodes` 里每台机器自己的 `Status` 字段；
- `Clusters` 下固定包含 **5 个**集群代码。

## 集群别称对照

| 集群 Code | 常见别称 |
|---|---|
| AI-SHAXY-TCS-PRO1 | 新源智算/智算/松江/松江智算/超算 |
| SHARB-A | 日坂/日坂A/SHARB |
| SHARE-SGP-ALI-PRO1 | 阿里云新加坡/新加坡/SGP-ALI |
| SHARE-SHA-ALI-PRO1 | 阿里云上海/上海阿里云/SHA-ALI |
| SHAXY-B | 新源B/新源/SHAXY |

## Train / Infer 的双重含义

- **k8s 视角**：两个不同 namespace，底层宿主机**无物理隔离**。Train 节点打 `role=gps-host` label/taint，Infer 节点打 `role=gpu-app-host`。同一机器可通过修改 role 实现切换，转换是否允许看 `SupportTrainInferSwap` 字段。
- **业务视角**：Train 用于训练，Peta 平台管理，pod 名一般以 `ocppro`/`job-`/`adhoc-` 开头；Infer 用于推理/线上服务，Captain 平台管理，pod 名一般以 `r1000-` 开头。

## AcceleratorType（卡型）命名规则

| 示例 | 解读 |
|---|---|
| `nvidia-h20` | H20卡，未指明显存默认96G，卡数 1/2/4/8 未知 |
| `nvidia-tesla-l20` | L20卡，未指明显存默认48G，卡数未知 |
| `nvidia-h20-141-ib-4` | H20卡，141G显存，`ib` 标识高速网络，后面数字是 IB 设备数非卡数 |
| `nvidia-tesla-a100-1-80` | A100卡，1张，80G显存 |
| `nvidia-tesla-l20-4-192` | L20卡，4张，48×4=192G |
| `cpu` | 纯CPU节点，GPU 恒为0，**非异常** |

## 节点(Node)字段详解

| 字段 | 说明 |
|---|---|
| `Name` | 宿主机唯一代码。私有云以 `svr` 开头，公有云/智算以 `vms` 开头 |
| `Ip` | 宿主机IP |
| `AcceleratorType` | 见上表 |
| `Allocatable.GPU` | 可供Pod调度的GPU额度（不等于硬件总数） |
| `Available.GPU` | 当前真实剩余可用GPU数 |
| `Status` | `Ready`=健康，`NotReady`=不健康。仅有的机器健康判定依据 |
| `GPUPodCount` | 已调度的 pod **数量**（不是卡数） |
| `GPUDistribution` | `{pod名: 占用卡数}`，所有已调度pod的显卡占用明细 |
| `SupportTrainInferSwap` | 布尔值，节点是否支持 Train↔Infer 角色互转 |
| `Label` | 宿主机元数据，pod 与 node label 匹配才能调度 |
| `Taint` | 宿主机排斥标记 |

## GPU 上报异常判定

**错误做法**：`Allocatable为奇数即异常`——大量单卡机型本身就是1张，会被误判。

**正确判定**（`topology_query.py anomaly` 已实现）：

1. `cpu` 类型跳过 GPU 检查；
2. `Available.GPU < 0` → 异常；
3. `Available.GPU > Allocatable.GPU` → 异常；
4. 非 `cpu` 但 `Allocatable.GPU == 0` → 异常；
5. AcceleratorType 命名编码了卡数（如 `-4-`/`-8-`），实际 Allocatable 不符 → 异常；
6. namespace 的 `Total` vs 实际节点数不一致 → 异常。
