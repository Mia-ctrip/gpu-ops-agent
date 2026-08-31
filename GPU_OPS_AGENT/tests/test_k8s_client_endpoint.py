"""Tests for K8sClient live-endpoint mode (step 2).

The real network call is stubbed via ``_http_get_json`` so tests are hermetic,
but every stub returns the *actual* payload captured in data/demo.json, proving
the live path, models and snapshot service work together.
"""

from __future__ import annotations

import json
import urllib.error

import pytest

from k8s_client import K8sApiError, K8sClient
from models.domain import ScenarioRole
from services.snapshot_service import SnapshotService

DEMO_JSON = "data/demo.json"

FIRST_CLUSTER = "AI-SHAXY-TCS-PRO1"


@pytest.fixture
def real_payload() -> dict:
    with open(DEMO_JSON) as f:
        return json.load(f)


@pytest.fixture
def endpoint_client(monkeypatch, real_payload) -> K8sClient:
    def fake_get(self, url: str, timeout: float) -> dict:  # bound as instance method
        return real_payload

    monkeypatch.setattr(K8sClient, "_http_get_json", fake_get)
    return K8sClient()


# ── Lazy load / refresh semantics ────────────────────────────────────


def test_list_clusters_lazily_fetches_once(monkeypatch, real_payload):
    calls = {"n": 0}

    def counting_get(self, url, timeout):
        calls["n"] += 1
        return real_payload

    monkeypatch.setattr(K8sClient, "_http_get_json", counting_get)
    client = K8sClient()

    assert calls["n"] == 0
    assert client.list_clusters() == [
        "AI-SHAXY-TCS-PRO1",
        "SHARB-A",
        "SHARE-SGP-ALI-PRO1",
        "SHARE-SHA-ALI-PRO1",
        "SHAXY-B",
    ]
    assert calls["n"] == 1  # one fetch serves all subsequent reads


def test_refresh_pulls_fresh_payload_on_each_call(endpoint_client: K8sClient, real_payload, monkeypatch):
    payloads = [real_payload, {**real_payload, "Data": {"Clusters": {"NEW-CLUSTER": real_payload["Data"]["Clusters"][FIRST_CLUSTER]}}}]

    def fake_get(self, url, timeout):
        return payloads.pop(0)

    monkeypatch.setattr(K8sClient, "_http_get_json", fake_get)
    client = K8sClient()

    assert client.list_clusters() == [
        "AI-SHAXY-TCS-PRO1",
        "SHARB-A",
        "SHARE-SGP-ALI-PRO1",
        "SHARE-SHA-ALI-PRO1",
        "SHAXY-B",
    ]
    client.refresh()  # next poll cycle → fresh payload
    assert client.list_clusters() == ["NEW-CLUSTER"]


def test_fetch_cluster_nodes_over_endpoint(endpoint_client: K8sClient):
    groups = endpoint_client.fetch_cluster_nodes(FIRST_CLUSTER)
    by_scenario = {scenario: nodes for scenario, nodes in groups}
    assert len(by_scenario[ScenarioRole.TRAIN]) == 40
    assert len(by_scenario[ScenarioRole.INFER]) == 99
    # flat list sums match the 5-cluster totals too
    assert len(endpoint_client.fetch_cluster_nodes("SHARE-SHA-ALI-PRO1")[1][1]) == 997


# ── End-to-end through SnapshotService (real numbers preserved) ──────


def test_snapshot_service_over_endpoint(endpoint_client: K8sClient):
    svc = SnapshotService(endpoint_client)
    svc.refresh_now()

    snap = svc.get_current(FIRST_CLUSTER)
    assert len(snap.nodes) == 139  # 40 train + 99 infer

    h20_train = [n for n in snap.nodes if n.gpu_type == "h20" and n.scenario == ScenarioRole.TRAIN]
    assert h20_train, "expected h20 hosts under Train"
    assert h20_train[0].allocatable.gpu == 8  # real uppercase GPU key survives the whole stack


# ── Error / tolerance paths ──────────────────────────────────────────


def test_legacy_top_level_clusters_normalized():
    from k8s_client import _parse_payload

    legacy = {"Clusters": {"C1": {"Data": {"Train": {"Total": 0, "Nodes": {}}}}}}
    api = _parse_payload(legacy)
    assert api.data is not None
    assert [c.cluster_name for c in api.data.clusters] == ["C1"]


def test_http_failure_raises_k8s_api_error(monkeypatch):
    import urllib.request

    def boom(*args, **kwargs):
        raise urllib.error.URLError("connection refused")

    monkeypatch.setattr(urllib.request, "urlopen", boom)
    client = K8sClient()
    with pytest.raises(K8sApiError):
        client.refresh()


def test_endpoint_mode_has_no_demo_path():
    # Default constructor targets the live endpoint, not a demo file
    client = K8sClient()
    assert client._demo_data_path is None  # noqa: SLF001
    assert "clusters/cached" in client._endpoint