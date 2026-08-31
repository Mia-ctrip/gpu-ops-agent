# Refresh 接口实现总结

## 功能概览

现在页面上的 **Refresh 按钮** 已完全实现，点击时将：

1. ✅ **立即触发 K8s API 查询** — 不等待 5 分钟的定时刷新
2. ✅ **采集最新数据** — 获取集群的实时节点、GPU 状态
3. ✅ **添加到历史** — 新数据加入 ring buffer，历史计数 +1
4. ✅ **更新前端显示** — Facts 和 Trend 图表立即刷新显示最新数据

## 技术实现

### 后端 API 端点

```http
POST /api/clusters/{cluster_id}/refresh
```

**响应示例：**
```json
{
  "success": true,
  "message": "Cluster AI-SHAXY-TCS-PRO1 refreshed successfully",
  "cluster_id": "AI-SHAXY-TCS-PRO1",
  "collected_at": "2026-08-28T08:45:30.123456+00:00",
  "node_count": 139,
  "history_count": 18
}
```

**实现代码** (`api/dashboard_routes.py`)：
```python
@router.post("/clusters/{cluster_id}/refresh")
def refresh_cluster(cluster_id: str) -> dict:
    """Trigger an immediate refresh for a specific cluster."""
    if _snapshot_service is None:
        raise HTTPException(503, "Services not initialised")
    
    try:
        # 立即采集新数据
        _snapshot_service.refresh_now(cluster_id)
        # 立即落盘
        _snapshot_service._persist_history()
        
        # 返回更新后的数据
        snap = _snapshot_service.get_current(cluster_id)
        history = _snapshot_service.get_history(cluster_id, limit=None)
        
        return {
            "success": True,
            "message": f"Cluster {cluster_id} refreshed successfully",
            "cluster_id": cluster_id,
            "collected_at": snap.collected_at.isoformat(),
            "node_count": len(snap.nodes),
            "history_count": len(history),
        }
    except KeyError:
        raise HTTPException(404, f"Cluster {cluster_id!r} not found")
```

### 前端实现

**HTML 按钮** (`front/index.html`)：
```html
<button class="btn-refresh" id="refreshBtn" onclick="refreshData()">🔄 Refresh</button>
```

**JavaScript 函数** (`front/index.html` → `refreshData()`)：
```javascript
function refreshData() {
  if (!currentCluster) {
    showError('Please select a cluster first');
    return;
  }

  const btn = document.getElementById('refreshBtn');
  btn.classList.add('loading');
  btn.disabled = true;

  // 调用后端 Refresh API
  fetch(`${API_BASE}/clusters/${currentCluster}/refresh`, { method: 'POST' })
    .then(r => {
      if (!r.ok) throw new Error(`HTTP ${r.status}`);
      return r.json();
    })
    .then(data => {
      showSuccess(`✓ Refreshed: ${data.node_count} nodes, ${data.history_count} history records`);
      
      // 重新加载 Facts 和 Trend 数据
      return Promise.all([
        fetch(`${API_BASE}/clusters/${currentCluster}/facts`),
        fetch(`${API_BASE}/clusters/${currentCluster}/trend?limit=50`)
      ]);
    })
    .then(([factsResp, trendResp]) => {
      if (!factsResp.ok || !trendResp.ok) {
        throw new Error(`API error: ${factsResp.status} ${trendResp.status}`);
      }
      return Promise.all([factsResp.json(), trendResp.json()]);
    })
    .then(([facts, trend]) => {
      // 更新前端显示
      renderFacts(facts);
      renderTrend(trend);
      updateTimestamp();
    })
    .catch(err => {
      showError(`Refresh failed: ${err.message}`);
    })
    .finally(() => {
      btn.classList.remove('loading');
      btn.disabled = false;
    });
}
```

## 数据流程

```
用户点击 Refresh 按钮
    ↓
前端发送 POST /api/clusters/{id}/refresh
    ↓
后端调用 snapshot_service.refresh_now(cluster_id)
    ↓
从 K8s API 采集最新数据 ← 立即触发，不等待定时刷新
    ↓
数据添加到 ring buffer (历史 +1)
    ↓
立即落盘 JSON 文件
    ↓
返回 {success, node_count, history_count}
    ↓
前端重新拉取 facts 和 trend
    ↓
前端显示刷新
    ↓
用户看到最新数据！
```

## 用户体验

### 场景 1：定时刷新 + 手动刷新并行

```
后台定时刷新（5分钟/次）
    ↓ ↓ ↓
用户可以随时点 Refresh 获取最新数据（无需等待）
    ↓
数据添加到同一个 ring buffer
```

### 场景 2：数据实时性

- **不点 Refresh：** 最多等待 5 分钟看到最新数据（POLL_INTERVAL_SEC）
- **点 Refresh：** 立即获取最新数据

### 场景 3：历史趋势

- 定时刷新每 5 分钟添加一个数据点
- 手动点 Refresh 可以添加额外的数据点
- 所有数据都加入 Trend 图表（显示真实的历史趋势）

## 验证结果

✅ 测试脚本验证通过：
```
✅ POST /api/clusters/{cluster_id}/refresh
✅ 立即触发 K8s API 查询
✅ 数据添加到历史 ring buffer
✅ 返回最新快照和历史计数
✅ 前端 Refresh 按钮已集成
```

实际测试数据：
- 历史数据从 17 → 18（+1 新快照）
- Trend 图表正确更新
- 按钮 loading 状态正常工作

## 配置项

| 配置 | 当前值 | 说明 |
|------|--------|------|
| `POLL_INTERVAL_SEC` | 300 (5min) | 后台定时刷新间隔 |
| `RING_BUFFER_SIZE` | 30 | 历史快照数限制 |

## 与 Feature #6 的关系

✅ **Refresh 接口** 补充了 Feature #6：

- Feature #6 提供 **自动后台采集** — 每 5 分钟自动运行
- **Refresh 接口** 提供 **手动即时采集** — 用户主动点击获取最新

两者都将数据添加到同一个 ring buffer，形成完整的数据历史。
