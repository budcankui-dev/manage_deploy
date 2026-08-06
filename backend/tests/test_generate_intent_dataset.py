import json

from scripts.generate_intent_dataset import NODES, generate_dataset
from services.intent_batch_eval import DATASET_PATH
from services.intent_batch_eval import VALID_NODES as BATCH_EVAL_VALID_NODES
from services.intent_batch_eval import sample_expected, score_parsed_result
from services.intent_parser import parse_intent


EXPECTED_NODES = [
    "h1",
    "h2",
    "h3",
    "h4",
    "h5",
    "h6",
    "h7",
    "h8",
    "h9",
    "h10",
    "h11",
    "h12",
    "h13",
]


def _expected_nodes(row: dict) -> set[str]:
    expected = row["labels"]
    return {node for node in [expected.get("source_name"), expected.get("destination_name")] if node}


def test_dataset_generator_uses_terminal_slots_only():
    rows = generate_dataset(360)
    valid_nodes = set()
    for row in rows:
        if row["case_type"] == "valid":
            valid_nodes.update(_expected_nodes(row))

    assert NODES == EXPECTED_NODES
    assert valid_nodes == set(EXPECTED_NODES)
    assert BATCH_EVAL_VALID_NODES == EXPECTED_NODES


def test_dataset_generator_never_uses_compute_as_user_endpoint():
    rows = generate_dataset(360)
    for row in rows:
        nodes = _expected_nodes(row)
        assert not any(node.startswith("compute-") for node in nodes), row


def test_dataset_generator_keeps_wrong_node_samples():
    rows = generate_dataset(360)
    wrong_rows = [row for row in rows if row["case_type"] in {"wrong_source_node", "wrong_destination_node"}]

    assert {row["case_type"] for row in wrong_rows} == {"wrong_source_node", "wrong_destination_node"}
    assert all(row["evaluation"]["parse_status"] == "incomplete" for row in wrong_rows)
    assert any("unknown-node" in row["utterance"] for row in wrong_rows)
    assert any("ghost-node" in row["utterance"] for row in wrong_rows)


def test_committed_dataset_matches_generator_and_video_contract():
    generated = generate_dataset(360)
    committed = [json.loads(line) for line in DATASET_PATH.read_text(encoding="utf-8").splitlines() if line.strip()]

    assert committed == generated
    video_rows = [
        row for row in committed
        if row["labels"]["task_type"] == "视频AI推理任务" and row["evaluation"]["parse_status"] == "valid"
    ]
    assert video_rows
    assert all("measured_frames" in row["labels"]["data_profile"] for row in video_rows)
    assert all(
        str(row["labels"]["data_profile"]["measured_frames"]) in row["utterance"]
        for row in video_rows
    )


def test_rule_fallback_meets_acceptance_accuracy_on_committed_dataset():
    rows = [json.loads(line) for line in DATASET_PATH.read_text(encoding="utf-8").splitlines() if line.strip()]
    correct = sum(
        score_parsed_result(
            parse_intent(row["utterance"], valid_nodes=BATCH_EVAL_VALID_NODES),
            sample_expected(row),
        )["match"]
        for row in rows
    )

    assert len(rows) == 360
    assert correct / len(rows) >= 0.9
