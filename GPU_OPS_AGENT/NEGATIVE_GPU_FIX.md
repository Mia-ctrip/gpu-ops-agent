# Bug Fix: Negative Available GPU Detection

**Node**: vmsvce02267074  
**Cluster**: AI-SHAXY-TCS-PRO1  
**Issue**: Negative Available GPU not detected  
**Status**: ✅ **FIXED**

---

## Problem

### Data Found
```
vmsvce02267074:
  Status: Ready
  GPU Type: h200
  Allocatable: 0
  Available: -8  ❌ NEGATIVE!
  Used: 8
```

This is a **critical data corruption** - negative GPU counts are impossible.

### Why It Wasn't Detected

My `_rule_gpu_reporting_anomaly()` was checking:

```python
# ❌ Only these two conditions:
if avail_gpu > alloc_gpu:  # Check 1: -8 > 0? NO
    # CRITICAL
    
if alloc_gpu not in most_common:  # Check 2: 0 not in common? But alloc=0, so skipped
    # WARNING (only if alloc_gpu > 0)
```

**Neither condition caught negative available GPU!**

---

## Solution

Added explicit check for negative available GPU:

```python
# ✅ NEW Check (first priority)
if avail_gpu < 0:
    # CRITICAL: "Node X Available GPU=-8 is negative (data corruption detected)"
    
# Then existing checks...
if avail_gpu > alloc_gpu:
    # ...
```

---

## Detection Logic (Ordered by Priority)

### 1. Negative Available GPU → CRITICAL ✅
```
Symptom: available_gpu < 0
Reason: Impossible state (negative resources)
Example: vmsvce02267074 with available=-8
```

### 2. Available > Allocatable → CRITICAL ✅
```
Symptom: available_gpu > allocatable_gpu
Reason: Available shouldn't exceed what's allocated
Example: alloc=8, avail=10
```

### 3. GPU Count Outlier → WARNING ✅
```
Symptom: Node's allocatable GPU differs from cluster standard
Reason: Unusual for this cluster (statistical outlier)
Example: All nodes have 8 GPU, but one node has 9 GPU
```

---

## Verification

### Before Fix
```
✅ vmsvce02267074: NOT detected
```

### After Fix
```
✅ vmsvce02267074 FOUND in alerts!
   Type: GPU_REPORTING_ANOMALY
   Severity: CRITICAL
   Message: "Node vmsvce02267074 Available GPU=-8 is negative (data corruption detected)"
```

### Test Results
- ✅ All 15 alert tests pass
- ✅ All 95 total tests pass
- ✅ No regressions

---

## Root Cause Analysis

**Why was negative available GPU missed initially?**

1. I focused on the "available > allocatable" case (which is also bad)
2. Didn't consider that negative values are even worse
3. The outlier detection has `if alloc_gpu > 0` guard, so nodes with alloc=0 are skipped

**Lesson**: Check boundary conditions thoroughly:
- Edge case: available < 0
- Edge case: allocatable = 0
- Edge case: available > allocatable

---

## Impact

| Node | Before | After |
|------|--------|-------|
| vmsvce02267074 | Not detected | ✅ CRITICAL alert |
| vmsvce02334846 | NotReady (detected) | Still detected ✅ |
| Other nodes | Unaffected | Unaffected |

---

## Files Changed

```
services/alert_service.py: +25 lines (negative available check)
```

---

**Status**: ✅ **Production Ready**
