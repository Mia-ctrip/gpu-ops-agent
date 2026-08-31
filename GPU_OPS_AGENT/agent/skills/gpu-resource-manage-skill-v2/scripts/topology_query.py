#!/usr/bin/env python3
"""
Deterministic aggregation/query helper over resource-topology-api-result.json.

Rationale: the raw file can have tens of thousands of lines. Asking an LLM to
manually sum GPU counts across that many nodes in-context is unreliable and
wastes context. This script does all arithmetic and filtering in code and
returns compact JSON that an agent can directly summarize/format for the user.

Usage:
    python topology_query.py <json_file> <command> [options]

Commands:
    clusters                          List cluster codes present in the file.
    cardtypes    [--cluster X]        List distinct AcceleratorType keys.
    summary      [--cluster X] [--namespace Train|Infer] [--cardtype SUB]
                                       Sum Allocatable/Available/Used GPU
                                       (+ CPU/Memory) across matching nodes.
    node         --name SUB           Full detail for node(s) whose Name
                                       contains SUB (health, capacity, pods).
    unhealthy    [--cluster X] [--namespace Y] [--cardtype SUB]
                                       List nodes with Status != Ready.
    anomaly      [--cluster X]        Detect GPU-count self-reporting issues
                                       (impossible values + Total mismatch).
    candidates   --need N [--cluster X] --namespace Y --cardtype SUB
                                       Nodes with Available.GPU >= N, for
                                       "why won't my pod schedule" triage.
    swap-candidates --need N --cluster X --cardtype SUB
                                       Like `candidates`, but also searches
                                       the OTHER namespace (Train<->Infer)
                                       and only keeps nodes that support the
                                       role swap (SupportTrainInferSwap).
    fragmentation --cluster X --namespace Y --cardtype SUB
                                       Per-node GPU/pod breakdown for a
                                       cardtype, for binpack migration
                                       planning (least-disruptive host).

All commands print a single JSON object to stdout. Errors go to stderr with
a non-zero exit code instead of silently returning empty data.
"""
import argparse
import io
import json
import sys

if hasattr(sys.stdout, "buffer"):
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", newline="")
if hasattr(sys.stderr, "buffer"):
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8", newline="")

CLUSTER_ALIASES = {
    "AI-SHAXY-TCS-PRO1": ["新源智算", "智算", "松江", "松江智算", "超算"],
    "SHARB-A": ["日坂", "日坂A", "SHARB"],
    "SHARE-SGP-ALI-PRO1": ["阿里云新加坡", "新加坡", "SGP-ALI", "SGP"],
    "SHARE-SHA-ALI-PRO1": ["阿里云上海", "上海阿里云", "SHA-ALI"],
    "SHAXY-B": ["新源B", "新源", "SHAXY"],
}

NAMESPACE_ALIASES = {
    "Train": ["train", "训练", "peta"],
    "Infer": ["infer", "推理", "captain"],
}


def load(path):
    with open(path, encoding="utf-8") as f:
        data = json.load(f)
    return data["Data"]["Clusters"]


def resolve_cluster(clusters, query):
    if query is None:
        return list(clusters.keys())
    q = query.strip().lower()
    for code in clusters:
        if code.lower() == q:
            return [code]
    for code, aliases in CLUSTER_ALIASES.items():
        if code in clusters and any(q == a.lower() or q in a.lower() or a.lower() in q for a in aliases):
            return [code]
    matches = [c for c in clusters if q in c.lower()]
    if matches:
        return matches
    raise ValueError(f"未能识别集群: {query!r}. 可选: {list(clusters.keys())}")


def resolve_namespace(query):
    if query is None:
        return ["Train", "Infer"]
    q = query.strip().lower()
    for ns, aliases in NAMESPACE_ALIASES.items():
        if q == ns.lower() or any(q == a.lower() for a in aliases):
            return [ns]
    raise ValueError(f"未能识别namespace: {query!r}. 可选: Train/Infer (train/推理/peta/captain等别称)")


def iter_nodes(clusters, cluster_codes, namespaces, cardtype_sub=None):
    """Yields (cluster, namespace, cardtype, node_dict) for matching nodes."""
    for ccode in cluster_codes:
        cdata = clusters[ccode]["Data"]
        for ns in namespaces:
            if ns not in cdata:
                continue
            nodes_by_type = cdata[ns].get("Nodes", {})
            for cardtype, nodes in nodes_by_type.items():
                if cardtype_sub and cardtype_sub.lower() not in cardtype.lower():
                    continue
                for n in nodes:
                    yield ccode, ns, cardtype, n


def cmd_clusters(args):
    clusters = load(args.json_file)
    print(json.dumps({"clusters": list(clusters.keys())}, ensure_ascii=False, indent=2))


def cmd_cardtypes(args):
    clusters = load(args.json_file)
    ccodes = resolve_cluster(clusters, args.cluster)
    types = set()
    for ccode, ns, cardtype, n in iter_nodes(clusters, ccodes, ["Train", "Infer"]):
        types.add(cardtype)
    print(json.dumps({"cardtypes": sorted(types)}, ensure_ascii=False, indent=2))


def cmd_summary(args):
    clusters = load(args.json_file)
    ccodes = resolve_cluster(clusters, args.cluster)
    namespaces = resolve_namespace(args.namespace)
    matched_types = set()
    total = {"Allocatable_GPU": 0, "Available_GPU": 0, "Allocatable_CPU": 0.0,
             "Available_CPU": 0.0, "node_count": 0}
    breakdown = {}
    for ccode, ns, cardtype, n in iter_nodes(clusters, ccodes, namespaces, args.cardtype):
        matched_types.add(cardtype)
        alloc_gpu = n["Allocatable"]["GPU"]
        avail_gpu = n["Available"]["GPU"]
        total["Allocatable_GPU"] += alloc_gpu
        total["Available_GPU"] += avail_gpu
        total["Allocatable_CPU"] += n["Allocatable"]["CPU"]
        total["Available_CPU"] += n["Available"]["CPU"]
        total["node_count"] += 1
        key = f"{ccode}/{ns}/{cardtype}"
        b = breakdown.setdefault(key, {"Allocatable_GPU": 0, "Available_GPU": 0, "node_count": 0})
        b["Allocatable_GPU"] += alloc_gpu
        b["Available_GPU"] += avail_gpu
        b["node_count"] += 1
    total["Used_GPU"] = total["Allocatable_GPU"] - total["Available_GPU"]
    for b in breakdown.values():
        b["Used_GPU"] = b["Allocatable_GPU"] - b["Available_GPU"]
    print(json.dumps({
        "filters": {"cluster": ccodes, "namespace": namespaces, "cardtype_substring": args.cardtype},
        "matched_cardtypes": sorted(matched_types),
        "total": total,
        "breakdown_by_cluster_namespace_cardtype": breakdown,
    }, ensure_ascii=False, indent=2))


def cmd_node(args):
    clusters = load(args.json_file)
    sub = args.name.lower()
    found = []
    for ccode, ns, cardtype, n in iter_nodes(clusters, list(clusters.keys()), ["Train", "Infer"]):
        if sub in n["Name"].lower():
            found.append({
                "Cluster": ccode, "Namespace": ns, "AcceleratorType": cardtype,
                "Name": n["Name"], "Ip": n["Ip"], "Status": n["Status"],
                "Allocatable": n["Allocatable"], "Available": n["Available"],
                "GPUPodCount": n["GPUPodCount"], "GPUDistribution": n["GPUDistribution"],
                "SupportTrainInferSwap": n.get("SupportTrainInferSwap"),
                "Label": n.get("Label"), "Taint": n.get("Taint"),
            })
    print(json.dumps({"query": args.name, "matches": found}, ensure_ascii=False, indent=2))


def cmd_unhealthy(args):
    clusters = load(args.json_file)
    ccodes = resolve_cluster(clusters, args.cluster)
    namespaces = resolve_namespace(args.namespace)
    result = []
    for ccode, ns, cardtype, n in iter_nodes(clusters, ccodes, namespaces, args.cardtype):
        if n["Status"] != "Ready":
            result.append({
                "Cluster": ccode, "Namespace": ns, "AcceleratorType": cardtype,
                "Name": n["Name"], "Ip": n["Ip"], "Status": n["Status"],
                "Allocatable": n["Allocatable"], "Available": n["Available"],
            })
    print(json.dumps({"unhealthy_count": len(result), "nodes": result}, ensure_ascii=False, indent=2))


def _expected_gpu_from_cardtype(cardtype):
    """Best-effort expected GPU count parsed from naming convention, e.g.
    nvidia-h20-4-384 -> 4, nvidia-tesla-a100-1-80 -> 1. Returns None if the
    name doesn't encode a count (e.g. plain 'nvidia-h20', 'cpu')."""
    if cardtype == "cpu":
        return None
    parts = cardtype.split("-")
    for p in parts:
        if p.isdigit() and int(p) in (1, 2, 4, 8):
            return int(p)
    return None


def cmd_anomaly(args):
    clusters = load(args.json_file)
    ccodes = resolve_cluster(clusters, args.cluster)
    issues = []

    # Node-level impossible/suspicious values
    for ccode, ns, cardtype, n in iter_nodes(clusters, ccodes, ["Train", "Infer"]):
        alloc = n["Allocatable"]["GPU"]
        avail = n["Available"]["GPU"]
        problems = []
        if avail < 0:
            problems.append(f"Available.GPU为负数({avail})")
        if avail > alloc:
            problems.append(f"Available.GPU({avail}) > Allocatable.GPU({alloc})")
        if cardtype != "cpu" and alloc == 0:
            problems.append("非cpu机型但Allocatable.GPU为0")
        expected = _expected_gpu_from_cardtype(cardtype)
        if expected is not None and alloc not in (0, expected):
            problems.append(f"AcceleratorType({cardtype})命名暗示应为{expected}卡, 实际Allocatable.GPU={alloc}")
        if problems:
            issues.append({
                "Cluster": ccode, "Namespace": ns, "AcceleratorType": cardtype,
                "Name": n["Name"], "Ip": n["Ip"],
                "Allocatable_GPU": alloc, "Available_GPU": avail,
                "problems": problems,
            })

    # Namespace-level Total cross-check
    total_mismatches = []
    for ccode in ccodes:
        cdata = clusters[ccode]["Data"]
        for ns in ("Train", "Infer"):
            if ns not in cdata:
                continue
            declared_total = cdata[ns].get("Total")
            actual = sum(len(v) for v in cdata[ns].get("Nodes", {}).values())
            if declared_total is not None and declared_total != actual:
                total_mismatches.append({
                    "Cluster": ccode, "Namespace": ns,
                    "declared_Total": declared_total, "actual_node_count": actual,
                })

    print(json.dumps({
        "node_level_issue_count": len(issues),
        "node_level_issues": issues,
        "namespace_total_mismatches": total_mismatches,
    }, ensure_ascii=False, indent=2))


def cmd_candidates(args):
    clusters = load(args.json_file)
    ccodes = resolve_cluster(clusters, args.cluster)
    namespaces = resolve_namespace(args.namespace)
    need = args.need
    candidates = []
    for ccode, ns, cardtype, n in iter_nodes(clusters, ccodes, namespaces, args.cardtype):
        if n["Status"] != "Ready":
            continue
        if n["Available"]["GPU"] >= need:
            candidates.append({
                "Cluster": ccode, "Namespace": ns, "AcceleratorType": cardtype,
                "Name": n["Name"], "Ip": n["Ip"],
                "Available_GPU": n["Available"]["GPU"], "Allocatable_GPU": n["Allocatable"]["GPU"],
                "Available_CPU": n["Available"]["CPU"], "Available_Memory": n["Available"]["Memory"],
            })
    candidates.sort(key=lambda c: -c["Available_GPU"])
    print(json.dumps({
        "need_GPU": need,
        "candidate_count": len(candidates),
        "candidates": candidates,
        "note": "若candidate_count为0，可合理怀疑该namespace/cardtype下GPU显卡不足导致调度失败；若>0请同时核对Available_CPU/Available_Memory是否也满足需求。" if not candidates else "存在满足GPU需求的候选机器，请同时核对CPU/Memory是否满足。",
    }, ensure_ascii=False, indent=2))


def cmd_swap_candidates(args):
    clusters = load(args.json_file)
    ccodes = resolve_cluster(clusters, args.cluster)
    need = args.need
    other_ns_map = {"Train": "Infer", "Infer": "Train"}
    result = {}
    for target_ns, other_ns in other_ns_map.items():
        found = []
        for ccode, ns, cardtype, n in iter_nodes(clusters, ccodes, [other_ns], args.cardtype):
            if n["Status"] != "Ready":
                continue
            if n["Available"]["GPU"] >= need and n.get("SupportTrainInferSwap") is True:
                found.append({
                    "Cluster": ccode, "current_Namespace": other_ns, "AcceleratorType": cardtype,
                    "Name": n["Name"], "Ip": n["Ip"],
                    "Available_GPU": n["Available"]["GPU"], "Allocatable_GPU": n["Allocatable"]["GPU"],
                    "SupportTrainInferSwap": True,
                })
        found.sort(key=lambda c: -c["Available_GPU"])
        result[f"if_target_is_{target_ns}_check_{other_ns}"] = found
    print(json.dumps({
        "need_GPU": need,
        "note": "这些机器当前在另一namespace，若支持SupportTrainInferSwap=true且Available达标，可作为切换场景(Train<->Infer)的备选方案。",
        **result,
    }, ensure_ascii=False, indent=2))


def cmd_fragmentation(args):
    clusters = load(args.json_file)
    ccodes = resolve_cluster(clusters, args.cluster)
    namespaces = resolve_namespace(args.namespace)
    nodes = []
    for ccode, ns, cardtype, n in iter_nodes(clusters, ccodes, namespaces, args.cardtype):
        nodes.append({
            "Cluster": ccode, "Namespace": ns, "AcceleratorType": cardtype,
            "Name": n["Name"], "Ip": n["Ip"], "Status": n["Status"],
            "Allocatable_GPU": n["Allocatable"]["GPU"], "Available_GPU": n["Available"]["GPU"],
            "GPUPodCount": n["GPUPodCount"], "GPUDistribution": n["GPUDistribution"],
            "SupportTrainInferSwap": n.get("SupportTrainInferSwap"),
        })
    # Sort by fewest running pods first: fewer pods to evict = lower migration risk
    nodes.sort(key=lambda n: (n["GPUPodCount"], -n["Available_GPU"]))
    print(json.dumps({
        "filters": {"cluster": ccodes, "namespace": namespaces, "cardtype_substring": args.cardtype},
        "node_count": len(nodes),
        "nodes_sorted_by_migration_risk_asc": nodes,
        "note": "GPUPodCount越少代表需要驱逐迁移的pod越少，迁移影响面越小，仅供参考排序，实际迁移决策仍需人工确认业务影响。",
    }, ensure_ascii=False, indent=2))


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("json_file", help="resource-topology-api-result.json 的路径")
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("clusters").set_defaults(func=cmd_clusters)

    p = sub.add_parser("cardtypes"); p.add_argument("--cluster"); p.set_defaults(func=cmd_cardtypes)

    p = sub.add_parser("summary")
    p.add_argument("--cluster"); p.add_argument("--namespace"); p.add_argument("--cardtype")
    p.set_defaults(func=cmd_summary)

    p = sub.add_parser("node"); p.add_argument("--name", required=True); p.set_defaults(func=cmd_node)

    p = sub.add_parser("unhealthy")
    p.add_argument("--cluster"); p.add_argument("--namespace"); p.add_argument("--cardtype")
    p.set_defaults(func=cmd_unhealthy)

    p = sub.add_parser("anomaly"); p.add_argument("--cluster"); p.set_defaults(func=cmd_anomaly)

    p = sub.add_parser("candidates")
    p.add_argument("--cluster"); p.add_argument("--namespace", required=True)
    p.add_argument("--cardtype", required=True); p.add_argument("--need", type=float, required=True)
    p.set_defaults(func=cmd_candidates)

    p = sub.add_parser("swap-candidates")
    p.add_argument("--cluster", required=True); p.add_argument("--cardtype", required=True)
    p.add_argument("--need", type=float, required=True)
    p.set_defaults(func=cmd_swap_candidates)

    p = sub.add_parser("fragmentation")
    p.add_argument("--cluster", required=True); p.add_argument("--namespace", required=True)
    p.add_argument("--cardtype", required=True)
    p.set_defaults(func=cmd_fragmentation)

    args = parser.parse_args()
    try:
        args.func(args)
    except Exception as e:
        print(json.dumps({"error": str(e)}, ensure_ascii=False), file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
