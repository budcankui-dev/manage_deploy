# User Endpoint Demo Refactor Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Implement the user endpoint demo refactor while preserving automated benchmark behavior: user mode parses source/destination data-plane endpoints, deploys compute only, supports optional route-only, shows routing decision rationale, and validates online intent evaluation at full dataset scale.

**Architecture:** Keep the existing routing-order HTTP flow (`pending -> claim -> result -> network-ready`) stable. Extend DAG endpoint nodes with resolved topology identity and data-plane IP/port, add a route-only deployment branch that stores route decisions without materializing instances, and reuse endpoint images by adding manual receiver mode for user-controlled destination devices.

**Tech Stack:** FastAPI + SQLAlchemy async backend, Vue 3 + Element Plus frontend, Docker worker images, pytest, Vitest/build scripts where available.

---

## File Map

- `backend/services/endpoint_resolver.py` (create): resolve user-entered alias/topology id/business IP to canonical topology endpoint data.
- `backend/tests/test_endpoint_resolver.py` (create): TDD coverage for alias, topology id, business IP, IPv6 and invalid endpoint resolution.
- `backend/services/routing_payload_builder.py` (modify): include `topology_node_id`, `topology_alias`, `business_ip`, `business_ipv6`, `business_port`, `callback_url`, `deployable` for source/sink nodes.
- `backend/tests/test_routing_payload_builder.py` (modify): verify new endpoint fields while preserving benchmark DAG behavior.
- `backend/api/conversations.py` (modify): parse callback endpoint fields, validate endpoints, set user-demo deployment config, support route-only option.
- `backend/api/orders.py` (modify): route-only result handling, routing decision summary aggregation, detail response data.
- `backend/schemas/*.py` (modify as needed): expose endpoint resolution and routing decision fields.
- `backend/tests/test_conversations_api.py` and `backend/tests/test_business_tasks_api.py` (modify): end-to-end API coverage for user endpoints, route-only and decision summary.
- `workers/high-throughput-matmul/src/receiver_main.py` (create): manual destination receiver for matmul results.
- `workers/low-latency-video/src/receiver_main.py` (create): manual destination receiver for video inference results.
- `workers/*/Dockerfile.endpoint` (modify): include receiver entrypoints.
- `workers/*/src/compute_main.py` (modify if needed): ensure callback body includes `order_id`, task metadata and full result.
- `workers/*/tests/*` (modify/create): verify receiver accepts callbacks and stores per-order result.
- `frontend/src/views/IntentChatView.vue` (modify): endpoint input/preview, route-only advanced option, callback URL construction display.
- `frontend/src/components/OrderDetailPanel.vue` (modify): A->B->C data-plane display, callback status, routing decision card.
- `frontend/src/views/BusinessTasksHubView.vue` / `frontend/src/views/BenchmarkView.vue` (modify only if shared panel props require updates): preserve detail consistency.
- Intent dataset generation files (locate during task): add source/destination data-plane IP and port examples, route-only examples.
- `docs/routing-system-integration-guide.md` (modify): update frozen route integration doc after implementation.
- `docs/智联计算系统使用说明书.md` and `docs/testing.md` (modify lightly): receiver startup and route-only usage notes.

---

### Task 1: Backend Endpoint Resolution

**Files:**
- Create: `backend/services/endpoint_resolver.py`
- Create: `backend/tests/test_endpoint_resolver.py`

- [ ] **Step 1: Write failing resolver tests**

Create `backend/tests/test_endpoint_resolver.py` with tests that insert `Node` rows and assert:

```python
async def test_resolve_endpoint_by_hostname_returns_business_identity(db_session):
    ...

async def test_resolve_endpoint_by_business_ip_returns_same_identity(db_session):
    ...

async def test_resolve_endpoint_rejects_unknown_ip(db_session):
    ...

async def test_resolve_endpoint_rejects_management_ip_when_not_business_ip(db_session):
    ...
```

Expected identity fields: `topology_node_id`, `topology_alias`, `business_ip`, `business_ipv6`, `input_value`.

- [ ] **Step 2: Run tests and confirm failure**

Run: `cd backend && PYTHONPATH=. ./venv/bin/pytest tests/test_endpoint_resolver.py -q`

Expected: FAIL because module/function does not exist.

- [ ] **Step 3: Implement endpoint resolver**

Create a focused resolver with:

```python
@dataclass(frozen=True)
class ResolvedEndpoint:
    input_value: str
    topology_node_id: str
    topology_alias: str
    business_ip: str | None
    business_ipv6: str | None

async def resolve_user_endpoint(db: AsyncSession, value: str) -> ResolvedEndpoint:
    ...
```

Lookup order: `Node.hostname`, `Node.topology_node_id`, `Node.business_ip`, `Node.business_ipv6`. Do not match `management_ip` unless it is also equal to `business_ip` or `business_ipv6`.

- [ ] **Step 4: Verify tests pass**

Run: `cd backend && PYTHONPATH=. ./venv/bin/pytest tests/test_endpoint_resolver.py -q`

Expected: PASS.

---

### Task 2: Routing DAG Endpoint Fields

**Files:**
- Modify: `backend/services/routing_payload_builder.py`
- Modify: `backend/tests/test_routing_payload_builder.py`

- [ ] **Step 1: Add failing tests for source/sink endpoint metadata**

Extend `test_routing_payload_builder.py` to call `build_routing_payload(...)` with resolved endpoint dictionaries for source and sink, destination port `9000`, callback URL, `deployable_roles=["compute"]`, and assert source/sink nodes include `deployable=false`, `topology_node_id`, `topology_alias`, `business_ip`, `business_port`, `callback_url` while edges still use `source`, `compute`, `sink`.

- [ ] **Step 2: Run test and confirm failure**

Run: `cd backend && PYTHONPATH=. ./venv/bin/pytest tests/test_routing_payload_builder.py -q`

Expected: FAIL because new fields are not supported.

- [ ] **Step 3: Extend builder API minimally**

Add optional parameters such as `source_endpoint`, `destination_endpoint`, `destination_port`, `deployable_roles`. Preserve existing call sites by keeping `source_name` and `destination_name` behavior.

- [ ] **Step 4: Verify routing payload tests pass**

Run: `cd backend && PYTHONPATH=. ./venv/bin/pytest tests/test_routing_payload_builder.py -q`

Expected: PASS.

---

### Task 3: Conversation Submit Endpoint Parsing and Route-Only Config

**Files:**
- Modify: `backend/api/conversations.py`
- Modify: schemas used by conversation draft/confirm if needed
- Modify: `backend/tests/test_conversations_api.py`

- [ ] **Step 1: Write failing API tests**

Add tests for:

1. User can patch draft with `source_endpoint_input`, `destination_endpoint_input`, `destination_port=9000`; confirm intent stores resolved source/sink endpoint fields in `routing_input_dag` and `runtime_config.platform_deployment.deployable_roles == ["compute"]`.
2. Unknown endpoint input returns 400 and does not create order.
3. Route-only option stores `platform_deployment.mode == "route_only"`, `deployable_roles == []`, and DAG source/sink/compute `deployable=false` or no deployable roles.

- [ ] **Step 2: Run tests and confirm failure**

Run: `cd backend && PYTHONPATH=. ./venv/bin/pytest tests/test_conversations_api.py -q`

Expected: FAIL for unsupported fields/behavior.

- [ ] **Step 3: Implement parsing and config**

Update draft patching and confirm intent to resolve endpoint inputs with `resolve_user_endpoint`, construct callback URL from destination business IP + port, and pass endpoint metadata to `build_routing_payload`. Add route-only flag under `runtime_plan` or explicit request field, then map it to platform deployment config.

- [ ] **Step 4: Verify conversation tests pass**

Run: `cd backend && PYTHONPATH=. ./venv/bin/pytest tests/test_conversations_api.py -q`

Expected: PASS.

---

### Task 4: Route-Only Routing Result Handling

**Files:**
- Modify: `backend/api/orders.py`
- Modify: `backend/tests/test_business_tasks_api.py`

- [ ] **Step 1: Write failing route-only result test**

Add a test creating a `TaskOrder` with `runtime_config.platform_deployment.mode="route_only"`, `deployable_roles=[]`, and a valid DAG. Call `POST /api/routing-orders/{id}/result` with compute placement and metadata. Assert:

- Response status is ok.
- No `TaskInstance` is created.
- `order.materialized_instance_id is None`.
- `order.routing_status` reaches a completed/route-ready state defined by implementation.
- `runtime_config.routing_result.placements` and `metadata` are stored.
- `network_bindings` is empty or contains route-only logical bindings without container ports.

- [ ] **Step 2: Run target test and confirm failure**

Run: `cd backend && PYTHONPATH=. ./venv/bin/pytest tests/test_business_tasks_api.py::<new_test_name> -q`

Expected: FAIL because `/result` currently tries to materialize or requires deployable instance flow.

- [ ] **Step 3: Implement route-only branch**

In `receive_routing_result`, after validation and persistence of routing_result, branch if platform deployment mode is `route_only` or deployable roles is an empty list with auto_deploy false. Store placements/metadata, sync routing request, do not call `_create_instance_from_template`, do not allocate ports, and return response indicating route-only.

- [ ] **Step 4: Verify route-only and existing routing tests**

Run: `cd backend && PYTHONPATH=. ./venv/bin/pytest tests/test_business_tasks_api.py -q`

Expected: PASS.

---

### Task 5: Routing Decision Summary API Data

**Files:**
- Modify: `backend/api/orders.py`
- Modify: response schemas if needed
- Modify: `backend/tests/test_business_tasks_api.py`

- [ ] **Step 1: Write failing detail response test**

Create an order with routing_result metadata containing `selected_reason` and `candidate_scores`, plus node baseline/resource fixtures. Assert `GET /api/orders/{id}` returns a `routing_decision` object with selected compute node, gpu, selected_reason, candidate scores, and fallback baseline/resource info.

- [ ] **Step 2: Run failing test**

Run target pytest.

- [ ] **Step 3: Implement aggregation**

Add helper that combines `runtime_config.routing_result.placements`, `metadata`, `nodes`, and `node_baselines` into detail response. Keep it optional so old orders still serialize.

- [ ] **Step 4: Verify**

Run targeted and relevant API tests.

---

### Task 6: Worker Receiver and Callback Payloads

**Files:**
- Create: `workers/high-throughput-matmul/src/receiver_main.py`
- Create: `workers/low-latency-video/src/receiver_main.py`
- Modify: `workers/high-throughput-matmul/Dockerfile.endpoint`
- Modify: `workers/low-latency-video/Dockerfile.endpoint`
- Modify: worker compute callback payloads if missing `order_id` or full result
- Create/modify worker tests

- [ ] **Step 1: Write receiver tests**

Test POST `/callback` stores results by `order_id` and GET `/orders/{order_id}` returns the stored payload. For video, assert data URL or result image field is preserved.

- [ ] **Step 2: Run tests and confirm failure**

Run worker pytest commands.

- [ ] **Step 3: Implement minimal receiver**

Use existing lightweight HTTP server helpers if available. Store in memory and optionally write JSON under `/tmp/user-endpoint-results` for demo persistence.

- [ ] **Step 4: Ensure compute callback includes `order_id`**

Update compute callback body for both businesses if needed.

- [ ] **Step 5: Verify worker tests**

Run matmul and video worker tests.

---

### Task 7: Frontend User Endpoint Inputs and Order Detail Display

**Files:**
- Modify: `frontend/src/views/IntentChatView.vue`
- Modify: `frontend/src/components/OrderDetailPanel.vue`
- Modify shared display constants if needed

- [ ] **Step 1: Add UI for endpoint input and route-only advanced option**

Add source/destination endpoint input fields, destination port, endpoint resolution preview, and route-only checkbox under advanced settings. Preserve existing chat flow.

- [ ] **Step 2: Add order detail cards**

Show A->B->C data-plane chain, callback status, and routing decision summary. Reuse `OrderDetailPanel` so user/admin/benchmark details stay consistent.

- [ ] **Step 3: Build frontend**

Run: `cd frontend && npm run build`

Expected: PASS.

---

### Task 8: Dataset and Online Evaluation

**Files:**
- Locate and modify dataset generation scripts and fixtures.
- Modify online eval script only if needed for resume/rate limit reporting.

- [ ] **Step 1: Add dataset cases**

Add cases for alias/IP source/destination, destination port, callback URL wording, route-only wording, and all routing strategies.

- [ ] **Step 2: Run dataset tests**

Run: `cd backend && PYTHONPATH=. ./venv/bin/pytest tests/test_generate_intent_dataset.py tests/test_intent_parser.py tests/test_intent_online_eval.py -q`

- [ ] **Step 3: Run full 360 online evaluation in deployed or local configured environment**

Run low concurrency with retries/resume. Save report path and result summary.

---

### Task 9: Documentation and Final Verification

**Files:**
- Modify: `docs/routing-system-integration-guide.md`
- Modify: `docs/智联计算系统使用说明书.md`
- Modify lightly: `docs/testing.md` or `docs/benchmark-test-plan.md` if needed.

- [ ] **Step 1: Update routing integration doc**

Document user-demo, automated benchmark, and route-only mode DAG differences. Keep the route colleague section minimal.

- [ ] **Step 2: Update usage docs**

Add receiver startup steps and screenshots placeholders if screenshots are not available yet.

- [ ] **Step 3: Run full targeted verification**

Run backend conversation/business tests, worker tests, frontend build, and any E2E scripts available.

- [ ] **Step 4: Review and commit**

Commit in logical chunks, push branch, then deploy after local verification.
