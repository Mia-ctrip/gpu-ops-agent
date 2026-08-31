---
name: gpu-resource-topology-managing-skill
description: 当需要查询GPU集群的资源拓扑/资源视图、某台GPU宿主机的健康状态/总卡数/剩余可分配卡数/运行的pod、某一类卡型所有宿主机的资源拓扑，统计某卡型显卡的总数（区分训练/推理场景）、占用数、空闲数及空闲宿主机列表，排查集群中不健康或显卡总卡数上报异常的GPU机器，排查某类卡型标签的Pod调度不上的原因，以及缺少满足GPU数的宿主机时推荐较空闲宿主机作为binpack调整目标时使用。
---

# gpu-resource-topology-managing-skill

## Overview
本skill通过解析结构与.claude\gpu-resource-manage-skill\references\resource-topology-api-result-demo.json完全一致的用户输入的实时数据，可以分析得到当前GPU集群的资源拓扑/资源视图情况。

## When to Use
- 查询GPU集群的资源拓扑/资源视图时调用；
- 查询GPU集群下某台具体GPU宿主机的健康状态，总卡数，剩余可分配卡数，运行的pod分别有哪些时调用；
- 查询某一类显卡卡型的所有GPU宿主机资源拓扑情况时调用；
- 查询GPU集群中某种卡型的GPU显卡一共有多少张，在训练场景一共有多少张，在推理场景下一共有多少张；
- 查询GPU集群中某种卡型的GPU显卡有多少张被占用了，在训练场景有多少张被占用，在推理场景有多少张被占用；
- 查询GPU集群中训练/推理场景下空闲可用的显卡共多少张，列出这些空闲还没被完全占有的机器的name，总卡数，空闲卡数，cpu和mem的使用情况等；
- 查询集群下是否存在不健康的GPU机器时调用；
- 查询集群下是否存在GPU显卡的总卡数上报异常的GPU机器时调用；
- 打着某类显卡卡型标签的pod在某个集群上为什么调度不上去；
- 当缺少满足GPU数的宿主机导致pod无法调度时，推荐较为空闲的宿主机列表作为binpack的调整目标


## Inputs
- 用户必须提供一份最新查询的resource-topology-api-result.json文件，结构与.claude\gpu-resource-manage-skill\references\resource-topology-api-result-demo.json完全一致，这份文件提供了集群最新资源拓扑数据。本skill的分析依据全来源于这份最新的资源拓扑数据。

## Instructions

### resource-topology-api-result-demo.json中结构分析：
- Clusters下包含4个dict数据，key为GPU k8s集群的名字，value是集群中GPU资源的最新拓扑状态，Clusters下一般会包含五个key：AI-SHAXY-TCS-PRO1，SHARB-A，SHARE-SGP-ALI-PRO1，SHARE-SHA-ALI-PRO1，SHAXY-B。用户提问时一般会先限定他希望查询的集群是哪个，在有限定集群的前提下，你无需查询所有集群的拓扑情况，如未限定集群你需要汇总所有集群的数据。用户查询时一般不会输入这五个集群的全程，你需要掌握以下别称便于定位具体的集群：
1. AI-SHAXY-TCS-PRO1：新源智算集群/机房；智算集群/机房；松江集群/机房；松江智算集群/机房；超算集群/机房
2. SHARB-A：日坂机房/集群；日坂A集群/机房；日坂；SHARB
3. SHARE-SGP-ALI-PRO1：阿里云新加坡机房/集群；新加坡机房/集群；SGP-ALI;
4. SHARE-SHA-ALI-PRO1：阿里云上海机房/集群；阿里云上海机房/集群；SHA-ALI;
5. SHAXY-B：新源机房/集群；新源B集群/机房；新源；SHAXY
- 机房的value下Data存储了每个机房的资源拓扑情况，一个机房中包含Train和Infer两个namespace。
  这两个namespace从k8s集群的角度理解：是两个不同的namespace，对应的配置和权限集有区别，但底层的宿主机没有物理隔离，Train namespace下的宿主机会被打上role=gps-host的label和taint, Infer namespace下的宿主机被打上role=gpu-app-host的label和taint，k8s调度时通过role来区分宿主机的场景实现分别调度，同样的机器可以通过修改该role实现场景转换。
  这两个namespace从业务的角度理解：Train是用于训练的机器，都在peta平台调度和管理。Infer是用于推理/部署线上服务的机器，都在captain平台调度和管理。Train下的宿主机上对应的pod一般以"ocppro","job-","adhoc-"开头，而Infer下宿主机上对应的pod一般以“r1000-”开头。
  所以当用户查询时提问“训练场景” “Peta平台”有多少机器之类的问题时？请对应到"Train"key下的value查询拓扑情况。提问“推理场景”“Captain”上的机器怎么不够了之类的问题时请对应到"Infer"key下的value查询拓扑情况
- Nodes key下存储了多组dict， dict的key是卡型，values就是按卡型陈列的宿主机列表了。其中标识卡型的key一般是以“nvidia-”或者“nvidia-tesla-”开头，包含了卡数，显存等信息。例如以下为few shots：
  1. nvidia-h20： h20卡型，未指明显存数则默认是96G，未指明卡数则列表中的宿主机总卡数1 2 4 8均有可能；
  2. nvidia-tesla-l20：l20卡型，未指明显存数则默认是48G，未指明卡数则列表中的宿主机总卡数1 2 4 8均有可能；
  3. nvidia-h20-141-ib-4： h20卡型，未指明卡数则列表中的宿主机总卡数1 2 4 8均有可能，指明了141G显存，ib标识了对应的宿主机有高网，ib后的数字代表有4个ib设备而非4张显卡；
  4. nvidia-tesla-a100-1-80：a100卡型，宿主机上仅1张卡，显存80G；
  5. nvidia-tesla-l20-4-192: l20卡型，宿主机上有4张卡，显存是48*4=192G;
- 仅需关注Data下Clusters的数据，接口状态数据可以忽略；

### resource-topology-api-result-demo.json中宿主机对象字段解释：
- Name：宿主机的code, 唯一不变的code，私有云机房（SHARB-A SHAXY-B）的宿主机一般以svr开头，公有云机房（SHARE-SHA-ALI-PRO1 SHARE-SGP-ALI-PRO1）的宿主机一般以vms开头，智算/松江机房（AI-SHAXY-TCS-PRO1）的宿主机一般以vms开头；
- Ip：宿主机的ip， 一般当用户明确指明需要查询IP相关的信息时才会用到；
- AcceleratorType：宿主机上用于标识显卡信息&调度的标识，包含了卡数，显存等信息。
- Allocatable：宿主机可供 Pod 调度使用的额度，包含GPU，CPU，MEM三个维度。首要关心的是GPU数量，其次是MEM和CPU。Allocatable并不代表宿主机上的硬件总数，Allocatable一般小于等于Capacity，当Allocatable小于Capacity时，该宿主机出现故障了。
- Available：宿主机当前真实剩余可用，包含GPU，CPU，MEM三个维度。首要关心的是GPU数量，其次是MEM和CPU。当Available为0时宿主机满了无法再调度上新的pod，Available>0时显示的数字为可用的显卡数。
- label: 给宿主机贴的 key=value 元数据,用于筛选/分组，pod和node的label对应得上时才能调度。
- taint: 给宿主机打的排斥标记
- Status：宿主机节点在k8s集群中的状态，当Status为Ready时，可认为宿主机健康，当Status为NotReady时，宿主机不健康。
- GPUPodCount： 宿主机上已经调度上去正在运行的pod的数量，仅代表pod的数量不代表已使用显卡的卡数。
- GPUDistribution： 宿主机上所有已经调度上去正在运行的pod的集合，key为pod的名字，value为每个pod占用的显卡卡数。


### 判断宿主机是否健康的条件
查询宿主机节点的Status字段，当Status为Ready时，可认为宿主机健康。当Status为NotReady时，宿主机不健康。

### 判断宿主机显卡上报是否有问题
从理论上直接判断宿主机节点的Allocatable是否等于宿主机上的硬件总数Capacity值即可，但该文件未提供Capacity值，可从以下几个角度间接推测：
1. 宿主机的Capacity一定属于（1，2，4，8）中的某一个值，如果Allocatable为0，或者是大于1的单数那么显卡上报一定异常；
2. 宿主机的Available一定大于等于0，如果Available是负数则显卡上报一定异常。

### 查询某类宿主机在集群中的总卡数时
对集群下某类卡型对应宿主机的Allocatable值做sum

### 查询某类宿主机在集群中的空闲总卡数时
对集群下某类卡型对应宿主机的Available值做sum

### 查询某类宿主机在集群中的已占用的总卡数时
先计算集群下某类卡型对应宿主机的Allocatable与Available的差值得到该宿主机的占用卡数，再对所有宿主机的占用卡数做sum

### 排查某个集群下打着某类标签的pod为什么调度不上去时
1. 先判断该集群下该类标签是否有宿主机；
2. 如果有宿主机，筛选可调度的候选宿主机列表。筛选的规则是判断集群下这类卡型是否存在宿主机的Available值大于等于pod需要的显卡卡数。注意在这一步对所有宿主机求和计算Available值是没有意义的，必须轮询每台宿主机，某台宿主机上的Available值大于等于pod需要的显卡卡数才可作为候选；
3. 如果候选宿主机为空，那么可以合理怀疑是因为GPU显卡不足导致的调度失败。如果候选宿主机有值，你需要将候选机器列表返回，同时也要返回CPU和MEM的值给用户，并引导用户判断下是否是CPU和MEM资源不满足。

### 当缺少满足GPU数的宿主机导致pod无法调度时，推荐较为空闲的宿主机列表作为binpack的调整目标时
该需求是pod需要8卡/4卡等多卡资源才可以调度时，集群中的宿主机存在碎片，Available的gpu显卡分布在不同的宿主机上。用户管理集群需要对部分宿主机上的pod驱逐迁移，腾挪出满足需求的宿主机以供调度。
迁移难度的评估标准：需要被迁移/驱逐的pod越少影响面越小。
例如：当pod需要上海阿里云8卡H20的整机训练时，上海阿里云的H20宿主机拓扑情况为：A宿主机有3个单卡实例，占用了3张显卡，剩余5张可用；B宿主机有1个4卡实例，占用了4张显卡，剩余4张可用；C宿主机有1个8卡实例，占用了8张显卡，剩余8张可用；D宿主机有2个1卡实例，占用了2张显卡，剩余6张可用。
- 此时你给用户提供的最优方案是，B宿主机上的4卡实例可迁移到A宿主机或者C宿主机上，因为仅有一个实例需要迁移。
- 同时你可以向用户提供D宿主机上的2个1卡实例迁移到A或者B作为备选方案。
- 向用户提供备选方案很重要，B宿主机上的4卡实例迁移看上去是最优的方案，但实际上可能存在B实例是一个线上的单实例服务，如果迁移时中断会导致全部流量中断，导致线上业务受影响。但是D宿主机上的2个1卡实例都是多实例服务，且有DR方案，这个服短时间中断下影响面是比较小的。在这种情况下方案D宿主机上的2个1卡实例迁移就变成了最优方案。从这个接口无法判断出具体业务的情况，所以你需要提供备选让用户自己决策。
你需要向用户提供最优方案，同时向用户提供2-3个备选方案。而且需要提供A B C宿主机此时的拓扑情况。你只是提供方案，而拓扑细节也展示给用户是因为最终操作方案需要由用户自行判断和决策。


## Outputs
输出中需要包含以下三点：
1. 如果问询的是数字，给出总数；
2. 如果问询的是候选节点数，给出总数，给出详细的items；
3. 如果查询的是排障问题，给出结论，分析过程，你结论的佐证；
4. 如果问询的是方案，给出最佳方案，给出2-3个备选方案，分析过程，你结论的佐证。

## Restriction
- resource-topology-api-result.json文件的字段是基于从k8s集群中获取的信息，信息和拓扑会随着集群中调度情况发生改变，用户需要查询最新的情况就必须提供最新的文件，本skill禁止用任何从缓存中获取的信息代替最新的信息，以避免获取的数据失真。
- 如果用户表述不清楚，你无法得到相应的结论，可问询可无返回，禁止编纂数据；