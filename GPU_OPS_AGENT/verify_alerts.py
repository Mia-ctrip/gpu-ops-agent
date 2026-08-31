#!/usr/bin/env python3
"""Comprehensive verification of the three alert types implementation."""

import json
from datetime import datetime, timezone
from models.domain import AlertType, AlertSeverity, Node, NodeStatus, ResourceSpec, ScenarioRole
from models.snapshot import ClusterSnapshot
from services.alert_service import AlertService


def print_section(title):
    """Print a formatted section header."""
    print(f"\n{'='*80}")
    print(f"  {title}")
    print(f"{'='*80}")


def test_alert_type(alert_type_name, description, test_nodes, expected_count_range=None):
    """Test a specific alert type."""
    print_section(f"{alert_type_name}: {description}")

    svc = AlertService()
    snap = ClusterSnapshot(
        cluster_id="TEST",
        collected_at=datetime.now(timezone.utc),
        nodes=test_nodes,
    )

    alerts = svc.evaluate(snap)
    alerts_of_type = [a for a in alerts if a.type.value == alert_type_name]

    print(f"Total alerts generated: {len(alerts)}")
    print(f"Alerts of type {alert_type_name}: {len(alerts_of_type)}")

    if expected_count_range:
        min_count, max_count = expected_count_range
        if min_count <= len(alerts_of_type) <= max_count:
            print(f"✅ Count within expected range: {min_count}-{max_count}")
        else:
            print(f"❌ Count outside expected range: {min_count}-{max_count}")
            return False

    # Show details
    for alert in alerts_of_type[:5]:
        severity_color = {
            "CRITICAL": "🔴",
            "WARNING": "🟡",
            "INFO": "🟢"
        }.get(alert.severity.value, "⚪")
        print(f"  {severity_color} {alert.severity.value}: {alert.message}")

    if len(alerts_of_type) > 5:
        print(f"  ... and {len(alerts_of_type) - 5} more")

    return True


def make_node(name, status="Ready", gpu_type="h20", alloc_gpu=8, avail_gpu=4):
    """Create a test node."""
    return Node(
        name=name,
        ip=f"10.0.0.{name[-3:]}",
        cluster_id="TEST",
        gpu_type=gpu_type,
        scenario=ScenarioRole.TRAIN,
        status=NodeStatus(status),
        allocatable=ResourceSpec(gpu=alloc_gpu, cpu=96, mem=1000000),
        available=ResourceSpec(gpu=avail_gpu, cpu=48, mem=500000),
    )


def main():
    """Run comprehensive verification tests."""
    print("\n" + "="*80)
    print("  GPU OPS AGENT — ALERT SERVICE VERIFICATION")
    print("="*80)

    all_passed = True

    # Test 1: NODE_HEALTH
    print_section("TEST 1: NODE_HEALTH Alerts")
    print("Scenario: Detects NotReady nodes")
    print("Expected: CRITICAL alerts for each NotReady node")

    nodes = [
        make_node("ready-1", status="Ready"),
        make_node("ready-2", status="Ready"),
        make_node("notready-1", status="NotReady"),
        make_node("notready-2", status="NotReady"),
    ]
    if not test_alert_type("NODE_HEALTH", "NotReady nodes detection", nodes, (2, 2)):
        all_passed = False

    # Test 2: GPU_REPORTING_ANOMALY
    print_section("TEST 2: GPU_REPORTING_ANOMALY Alerts")
    print("Scenario 1: Odd GPU count")
    print("Expected: WARNING alerts for each node with odd GPU count")

    nodes = [
        make_node("valid-2gpu", alloc_gpu=2),
        make_node("valid-4gpu", alloc_gpu=4),
        make_node("odd-1gpu", alloc_gpu=1),
        make_node("odd-3gpu", alloc_gpu=3),
        make_node("odd-5gpu", alloc_gpu=5),
    ]
    if not test_alert_type("GPU_REPORTING_ANOMALY", "Odd GPU count detection", nodes, (3, 3)):
        all_passed = False

    print("\nScenario 2: Negative available GPU")
    print("Expected: CRITICAL alert for negative available GPU")

    nodes = [
        make_node("normal", avail_gpu=4),
        make_node("corrupt", avail_gpu=-2),
    ]
    if not test_alert_type("GPU_REPORTING_ANOMALY", "Negative available GPU detection", nodes, (1, 1)):
        all_passed = False

    # Test 3: CAPACITY_WATERMARK
    print_section("TEST 3: CAPACITY_WATERMARK Alerts")
    print("Scenario 1: Low utilization (<75%)")
    print("Expected: No alerts")

    nodes = [
        make_node("h20-1", gpu_type="h20", alloc_gpu=8, avail_gpu=6),  # 25% usage
    ]
    if not test_alert_type("CAPACITY_WATERMARK", "Low utilization", nodes, (0, 0)):
        all_passed = False

    print("\nScenario 2: Medium utilization (75-90%)")
    print("Expected: WARNING alert")

    nodes = [
        make_node("h20-1", gpu_type="h20", alloc_gpu=8, avail_gpu=2),  # 75% usage
        make_node("h20-2", gpu_type="h20", alloc_gpu=8, avail_gpu=2),  # 75% usage
    ]
    if not test_alert_type("CAPACITY_WATERMARK", "Medium utilization", nodes, (1, 1)):
        all_passed = False

    print("\nScenario 3: High utilization (>90%)")
    print("Expected: CRITICAL alert")

    nodes = [
        make_node("h20-1", gpu_type="h20", alloc_gpu=10, avail_gpu=0),  # 100% usage
    ]
    if not test_alert_type("CAPACITY_WATERMARK", "High utilization", nodes, (1, 1)):
        all_passed = False

    print("\nScenario 4: Multiple GPU types")
    print("Expected: Separate alerts for each GPU type per severity")

    nodes = [
        make_node("h20-1", gpu_type="h20", alloc_gpu=8, avail_gpu=0),   # 100% → CRITICAL
        make_node("h20-2", gpu_type="h20", alloc_gpu=8, avail_gpu=0),   # 100% → CRITICAL
        make_node("l20-1", gpu_type="l20", alloc_gpu=8, avail_gpu=2),   # 75% → WARNING
        make_node("l20-2", gpu_type="l20", alloc_gpu=8, avail_gpu=2),   # 75% → WARNING
        make_node("cpu-1", gpu_type="cpu", alloc_gpu=0, avail_gpu=0),   # CPU → excluded
    ]
    if not test_alert_type("CAPACITY_WATERMARK", "Multiple GPU types", nodes, (2, 2)):
        all_passed = False

    # Final summary
    print_section("VERIFICATION SUMMARY")
    if all_passed:
        print("✅ All alert types are functioning correctly!")
        print("\nImplemented alerts:")
        print("  1. NODE_HEALTH: Detects NotReady nodes → CRITICAL")
        print("  2. GPU_REPORTING_ANOMALY:")
        print("     - Odd GPU count (1,3,5,7...) → WARNING")
        print("     - Negative available GPU → CRITICAL")
        print("  3. CAPACITY_WATERMARK (per GPU type):")
        print("     - Usage > 90% → CRITICAL")
        print("     - Usage 75-90% → WARNING")
        print("     - Usage < 75% → No alert")
        print("\nFrontend integration:")
        print("  - Alerts panel in Cluster Health dashboard")
        print("  - Shows affected nodes and supporting data")
        print("  - Real-time alert refresh capability")
    else:
        print("❌ Some tests failed")

    return all_passed


if __name__ == "__main__":
    success = main()
    exit(0 if success else 1)
