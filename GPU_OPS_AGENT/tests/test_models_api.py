"""Tests for models/api.py — the class expression of the K8s API return structure.

These tests load the *real* payload captured in data/demo.json (fetched from
the endpoint) to prove the abstraction is faithful.  Demo file lives at repo
root under data/; tests run from anywhere via the repo-relative path.
"""

from __future__ import annotations

import json

import pytest

from models.api import (
    ApiResponse,
    ClusterRaw,
    GpuPodRaw,
    GpuTypeGroup,
    LabelRaw,
    NodeRaw,
    ResourceValues,
    ScenarioRaw,
    TaintRaw,
    parse_mem_mb,
)
from models.domain import ScenarioRole

DEMO_JSON = "data/demo.json"

EXPECTED_CLUSTERS = [
    "AI-SHAXY-TCS-PRO1",
    "SHARB-A",
    "SHARE-SGP-ALI-PRO1",
    "SHARE-SHA-ALI-PRO1",
    "SHAXY-B",
]

KNOWN_H20_NODE = {
    # first nvidia-h20 host under AI-SHAXY-TCS-PRO1 / Train
    "name": "vmsvce02092059",
    "alloc_gpu": 8,
    "alloc_mem": "1993774Mi",
    "avail_gpu": 3,
    "avail_mem": "841774Mi",
}


@pytest.fixture(scope="module")
def api_response() -> ApiResponse:
    with open(DEMO_JSON) as f:
        return ApiResponse.from_dict(json.load(f))


# ── Envelope & structure ─────────────────────────────────────────────


def test_top_level_envelope(api_response: ApiResponse):
    assert api_response.code == 200
    assert api_response.success is True
    assert api_response.data is not None


def test_clusters_are_objects_not_name_keyed_dict(api_response: ApiResponse):
    """The API keys clusters by name; we must NOT keep that habit."""
    assert isinstance(api_response.data.clusters, list)
    names = [c.cluster_name for c in api_response.data.clusters]
    assert names == EXPECTED_CLUSTERS
    # every ClusterRaw is an object with cluster_name + next-object field
    for c in api_response.data.clusters:
        assert isinstance(c, ClusterRaw)
        assert isinstance(c.cluster_name, str)
        assert c.status == "OK"
        assert c.cluster_data is not None


def test_cluster_data_has_explicit_train_and_infer(api_response: ApiResponse):
    shaxy = next(c for c in api_response.data.clusters if c.cluster_name == "AI-SHAXY-TCS-PRO1")
    assert shaxy.cluster_data.train is not None
    assert shaxy.cluster_data.infer is not None
    assert shaxy.cluster_data.train.scenario == ScenarioRole.TRAIN
    assert shaxy.cluster_data.infer.scenario == ScenarioRole.INFER


def test_empty_scenario_is_none_not_missing(api_response: ApiResponse):
    shaxy_b = next(c for c in api_response.data.clusters if c.cluster_name == "SHAXY-B")
    assert shaxy_b.cluster_data.train is not None  # present, but zero hosts
    assert shaxy_b.cluster_data.train.total == 0


# ── Nodes / gpu-type groups / conservation ───────────────────────────


def test_node_count_matches_scenario_total(api_response: ApiResponse):
    """Each scenario's Total equals the number of hosts across all gpu groups."""
    for cluster in api_response.data.clusters:
        for scenario in (cluster.cluster_data.train, cluster.cluster_data.infer):
            if scenario is None:
                continue
            assert sum(len(g.nodes) for g in scenario.node_groups) == scenario.total, (
                f"{cluster.cluster_name}/{scenario.scenario} node count != Total"
            )


def test_gpu_type_groups_carry_their_type(api_response: ApiResponse):
    shaxy = next(c for c in api_response.data.clusters if c.cluster_name == "AI-SHAXY-TCS-PRO1")
    groups = shaxy.cluster_data.train.node_groups
    assert isinstance(groups, list)
    assert all(isinstance(g, GpuTypeGroup) for g in groups)
    assert all(g.gpu_type for g in groups)


def test_flattened_node_self_describes_gpu_type(api_response: ApiResponse):
    """A flattened NodeRaw knows the gpu-type group it was filed under."""
    shaxy = next(c for c in api_response.data.clusters if c.cluster_name == "AI-SHAXY-TCS-PRO1")
    h20_group = next(g for g in shaxy.cluster_data.train.node_groups if g.gpu_type == "nvidia-h20")
    node = h20_group.nodes[0]
    assert node.gpu_type == "nvidia-h20"
    assert node.accelerator_type == node.gpu_type  # real data: they match


# ── Real key casing / memory parsing ─────────────────────────────────


def test_real_resource_keys_are_uppercase_and_parsed(api_response: ApiResponse):
    shaxy = next(c for c in api_response.data.clusters if c.cluster_name == "AI-SHAXY-TCS-PRO1")
    node = next(n for n in shaxy.cluster_data.train.all_nodes() if n.name == KNOWN_H20_NODE["name"])
    assert isinstance(node, NodeRaw)
    assert node.allocatable.gpu == KNOWN_H20_NODE["alloc_gpu"]
    assert node.available.gpu == KNOWN_H20_NODE["avail_gpu"]
    assert node.allocatable.memory_mb == 1993774.0
    assert node.available.memory_mb == 841774.0
    assert node.status == "Ready"
    assert node.gpu_pod_count >= 1
    assert node.gpu_distribution  # non-empty


def test_labels_taints_are_object_lists(api_response: ApiResponse):
    shaxy = next(c for c in api_response.data.clusters if c.cluster_name == "AI-SHAXY-TCS-PRO1")
    node = next(n for n in shaxy.cluster_data.train.all_nodes() if n.name == KNOWN_H20_NODE["name"])
    assert node.labels, "expected at least one label"
    assert all(isinstance(l, LabelRaw) for l in node.labels)
    assert any(l.key == "cloud.ctrip.com/accelerator" and l.value == "nvidia-h20" for l in node.labels)
    assert all(isinstance(t, TaintRaw) for t in node.taints)
    assert any(t.effect == "NoSchedule" for t in node.taints)
    assert all(isinstance(p, GpuPodRaw) and p.gpu_count >= 1 for p in node.gpu_distribution)


def test_legacy_lowercase_fixture_still_parses():
    """Old tests use lowercase resource keys / bare numeric memory — stay compatible."""
    rv = ResourceValues.from_dict({"gpu": 8, "cpu": 96, "mem": 1000000})
    assert rv.gpu == 8
    assert rv.cpu == 96.0
    assert rv.memory_mb == 1000000.0


@pytest.mark.parametrize(
    "raw, expected",
    [
        ("514195Mi", 514195.0),
        ("0Mi", 0.0),
        ("1Gi", 1024.0),
        ("1000Ki", pytest.approx(1000.0 / 1024.0)),
        ("1234", 1234.0),
        (None, 0.0),
        ("", 0.0),
    ],
)
def test_parse_mem_mb(raw, expected):
    assert parse_mem_mb(raw) == expected


# ── from_dict round-trips ────────────────────────────────────────────


def test_empty_or_malformed_inputs_do_not_crash():
    assert ApiResponse.from_dict({}).data is None
    assert ScenarioRaw.from_dict("Train", {}).total == 0
    assert ClusterRaw.from_dict("X", {}).cluster_data.train is None
    assert NodeRaw.from_dict({}, "cpu").name == ""
    assert GpuTypeGroup.from_dict("g", None).nodes == []