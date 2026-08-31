# Debug Report: vmsvce02334846 NotReady Alert Detection

**Date**: 2026-08-28  
**Issue**: vmsvce02334846 node (NotReady status) not appearing in alerts  
**Status**: ✅ **RESOLVED**

---

## Root Cause Analysis

### Problem Found
The `AlertService` class had a critical design flaw:

```python
# ❌ WRONG - Overwrites all clusters' alerts on each refresh()
class AlertService:
    def __init__(self):
        self._active: list[Alert] = []  # Single list for all clusters
    
    def refresh(self, snapshot: ClusterSnapshot) -> list[Alert]:
        self._active = self.evaluate(snapshot)  # Overwrites previous!
```

### What Happened
In `main.py` lifespan, when refreshing multiple clusters in a loop:

```python
for cid in CLUSTERS:  # [AI-SHAXY-TCS-PRO1, SHARB-A, ..., SHAXY-B]
    snap = snapshot_svc.get_current(cid)
    alert_svc.refresh(snap)  # Each call OVERWRITES _active
```

Result: Only **SHAXY-B**'s alerts (the last one) were kept in `_active`!

---

## The Fix

### Changed Data Structure
```python
# ✅ CORRECT - Per-cluster dict
class AlertService:
    def __init__(self):
        self._active: dict[str, list[Alert]] = {}  # Per-cluster dict!
    
    def refresh(self, snapshot: ClusterSnapshot) -> list[Alert]:
        # Now preserves alerts from all clusters
        self._active[snapshot.cluster_id] = self.evaluate(snapshot)
        return self._active[snapshot.cluster_id]

    def get_active_alerts(self, cluster_id: str | None = None) -> list[Alert]:
        if cluster_id:
            return self._active.get(cluster_id, [])
        # Return all clusters' alerts
        return sum(self._active.values(), [])
```

---

## Verification

### Before Fix
```
curl http://127.0.0.1:8030/api/alerts?cluster_id=AI-SHAXY-TCS-PRO1
{
  "alert_count": 0,  ❌ Empty!
  "alerts": []
}
```

### After Fix
```
curl http://127.0.0.1:8030/api/alerts?cluster_id=AI-SHAXY-TCS-PRO1
{
  "alert_count": 8,  ✅ Now has 8 alerts!
  "alerts": [
    {
      "type": "NODE_HEALTH",
      "severity": "CRITICAL",
      "message": "Node vmsvce02334846 is NotReady",
      ...
    },
    ...
  ]
}
```

---

## Test Coverage

### Alert Detection Verification
```
✅ AI-SHAXY-TCS-PRO1: 3 NODE_HEALTH alerts (including vmsvce02334846)
✅ SHARB-A:          0 NODE_HEALTH alerts (all nodes Ready)
✅ SHARE-SGP-ALI-PRO1: 2 NODE_HEALTH alerts
✅ SHARE-SHA-ALI-PRO1: 1 NODE_HEALTH alert
✅ SHAXY-B:          1 NODE_HEALTH alert (svr14220de730)

Total: 95 tests passed
```

### vmsvce02334846 Details
- **Name**: vmsvce02334846
- **Cluster**: AI-SHAXY-TCS-PRO1
- **GPU Type**: h20
- **Status**: NotReady (in all 30 cached snapshots)
- **Allocatable GPU**: 8
- **Available GPU**: 0
- **Alert Type**: NODE_HEALTH
- **Alert Severity**: CRITICAL ✅

---

## Files Modified

| File | Change | Lines |
|------|--------|-------|
| `services/alert_service.py` | Fix _active structure (list → dict) | +5 |
| `main.py` | Pass demo_data_path to build_app() | +1 |

---

## Impact

### Before
- ❌ Only last cluster's alerts were saved
- ❌ vmsvce02334846 NotReady status invisible in API
- ❌ Frontend shows "No active alerts" misleadingly

### After
- ✅ All clusters' alerts properly maintained
- ✅ vmsvce02334846 alerts correctly detected
- ✅ Frontend shows complete alert list
- ✅ All 95 tests pass

---

## Regression Check

**Test Execution**:
```
95 passed in 41.17s ✅
```

**No regressions** - All existing functionality preserved.

---

## Lesson Learned

When a service needs to track state for **multiple identities** (clusters in this case), use a **per-identity dictionary** rather than a single container that gets overwritten.

```python
# ❌ Anti-pattern
self._active = new_value  # Overwrites all

# ✅ Pattern
self._active[identity] = new_value  # Per-identity
```

---

**Status**: ✅ **Complete and Verified**
