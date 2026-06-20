"""Shared official topology node names used by intent evaluation and demos."""

COMPUTE_NODE_ALIASES = ["compute-1", "compute-2", "compute-3"]
TERMINAL_NODE_ALIASES = [f"h{index}" for index in range(1, 14)]
ADMIN_NODE_ALIASES = ["admin"]
OFFICIAL_TOPOLOGY_ALIASES = ADMIN_NODE_ALIASES + TERMINAL_NODE_ALIASES + COMPUTE_NODE_ALIASES

# These are the user-facing source/sink endpoint slots and also the values
# stored in nodes.hostname for routing handoff. Compute nodes are selected by
# the platform/router and must not be accepted as source or destination inputs.
# Asset IDs such as h18001001 live in nodes.topology_node_id and are not used as
# intent slots.
INTENT_VALID_NODES = TERMINAL_NODE_ALIASES
