from scripts.generate_intent_dataset import NODES, generate_dataset
from services.intent_batch_eval import VALID_NODES as BATCH_EVAL_VALID_NODES


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
