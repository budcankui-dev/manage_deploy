"""Shared topology node names used by intent evaluation and demos."""

COMPUTE_NODE_ALIASES = ["compute-1", "compute-2", "compute-3"]
TERMINAL_NODE_ALIASES = [f"h{index}" for index in range(1, 14)]

# These are the user-facing node names and also the values stored in
# nodes.hostname for routing handoff.  Asset IDs such as h18001001 live in
# nodes.topology_node_id and are not used as intent slots.
INTENT_VALID_NODES = COMPUTE_NODE_ALIASES + TERMINAL_NODE_ALIASES
