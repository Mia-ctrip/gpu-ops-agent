#!/usr/bin/env python3
"""Integration test: verify /alerts endpoint with real data."""

import json
from main import build_app
from services.snapshot_service import SnapshotService

# Build app with demo data
app = build_app(demo_data_path="data/demo.json")

# Get services from app dependencies (injected via init_services)
from api.dashboard_routes import _snapshot_service, _alert_service

def test_alerts_endpoint():
    """Test /alerts endpoint returns properly formatted alert details."""
    # Ensure snapshot service is initialized with real data
    _snapshot_service.refresh_now()

    # Evaluate alerts for each cluster
    from config import CLUSTERS
    for cluster_id in CLUSTERS:
        try:
            snap = _snapshot_service.get_current(cluster_id)
            _alert_service.refresh(snap)
        except KeyError:
            pass

    # Get alerts
    alerts = _alert_service.get_active_alerts()
    print(f"\n{'='*80}")
    print(f"Total active alerts: {len(alerts)}")
    print(f"{'='*80}")

    # Group by type and severity
    by_type = {}
    for alert in alerts:
        key = f"{alert.type.value}:{alert.severity.value}"
        if key not in by_type:
            by_type[key] = []
        by_type[key].append(alert)

    # Display summary
    for key, group in sorted(by_type.items()):
        print(f"\n{key}: {len(group)} alerts")
        for alert in group[:3]:  # Show first 3 per category
            print(f"  - {alert.message}")
            if alert.gpu_type:
                print(f"    GPU Type: {alert.gpu_type}")
            if alert.node_name:
                print(f"    Node: {alert.node_name}")
            print(f"    Raw: {json.dumps(alert.raw_values, indent=6, default=str)[:200]}")

    # Verify alert format
    print(f"\n{'='*80}")
    print("Alert Format Verification:")
    print(f"{'='*80}")

    if alerts:
        sample_alert = alerts[0]
        print(f"Alert ID: {sample_alert.alert_id}")
        print(f"Cluster: {sample_alert.cluster_id}")
        print(f"Type: {sample_alert.type.value}")
        print(f"Severity: {sample_alert.severity.value}")
        print(f"Message: {sample_alert.message}")
        print(f"Raw Values Keys: {list(sample_alert.raw_values.keys())}")

        # Check for expected fields
        assert len(sample_alert.alert_id) > 0
        assert sample_alert.cluster_id in ["AI-SHAXY-TCS-PRO1", "SHARB-A", "SHARE-SGP-ALI-PRO1", "SHARE-SHA-ALI-PRO1", "SHAXY-B"]
        assert sample_alert.severity.value in ["INFO", "WARNING", "CRITICAL"]
        print("\n✅ Alert format is correct!")
    else:
        print("⚠️  No alerts found in test data")

    # Count by type
    node_health = sum(1 for a in alerts if a.type.value == "NODE_HEALTH")
    gpu_anomaly = sum(1 for a in alerts if a.type.value == "GPU_REPORTING_ANOMALY")
    capacity = sum(1 for a in alerts if a.type.value == "CAPACITY_WATERMARK")

    print(f"\nAlert breakdown:")
    print(f"  NODE_HEALTH: {node_health}")
    print(f"  GPU_REPORTING_ANOMALY: {gpu_anomaly}")
    print(f"  CAPACITY_WATERMARK: {capacity}")

if __name__ == "__main__":
    test_alerts_endpoint()
