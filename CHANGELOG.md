# Changelog - Vendra Fixes & Optimizations

This changelog summarizes the modifications made to Vendra's conversational commerce system to address security, data integrity, correctness, and performance issues.

---

## [2026-08-12] PHASE 10 — Secondary Model Fallbacks, Topic Switching, & Checkpointer Cleanup

### Added
- Configured secondary Groq model `SECONDARY_GROQ_MODEL=llama-3.3-70b-versatile` inside [`.env`](file:///G:/Project%20Vendra/.env) and [`.env.example`](file:///G:/Project%20Vendra/.env.example).
- Implemented a resilient model fallback mechanism in `safe_llm_invoke` inside [`agent/graph.py`](file:///G:/Project%20Vendra/agent/graph.py) and `retrieve_policy_text` inside [`agent/tools.py`](file:///G:/Project%20Vendra/agent/tools.py) that automatically redirects requests to the secondary model upon rate-limiting (429) or other API exceptions.
- Added `GENERAL_WORDS` into `explicit_switch` triggers inside [`router_node`](file:///G:/Project%20Vendra/agent/graph.py#L502) in [`agent/graph.py`](file:///G:/Project%20Vendra/agent/graph.py) to enable seamless topic switching from cart/checkout flows to policy questions.
- Integrated automated checkpointer state cleanups on `/api/chat` in [`main.py`](file:///G:/Project%20Vendra/main.py#L533) that deletes SQLite/Postgres checkpoints for the thread whenever the incoming request starts a new session (history is empty).
- Created a regression test suite [`tests/test_regression_round4.py`](file:///G:/Project%20Vendra/tests/test_regression_round4.py) covering topic switching, rate limits, cart loop prevention, chitchat isolation, and tool-call safety.

---

## [2026-08-09] PHASE 9 — Conversational Tracking Loop Fix & Language Defaulting

### Added
- Created `test_conversational_tracking_flow` in [`tests/test_fault_isolation.py`](file:///G:/Project%20Vendra/tests/test_fault_isolation.py) to simulate a multi-turn conversation ("where is my order" -> "ORD002") and assert that it returns complete tracking details.
- Added strict response template formatting constraints to [`tracking_agent_node`](file:///G:/Project%20Vendra/agent/graph.py#L580) in [`agent/graph.py`](file:///G:/Project%20Vendra/agent/graph.py) to force `llama-3.1-8b-instant` to populate courier name, status, timeline events, and order details rather than presenting follow-up questions or loops.
- Enforced input-based tool visibility: dynamically hide `tools` (`track_order`/`get_order_status`) in [`tracking_agent_node`](file:///G:/Project%20Vendra/agent/graph.py#L580) when no valid order ID matches in the message history, preventing tool-eagerness/hallucinations on the initial turn.
- Included `Customer ID: {cid}` directly in `track_order` and `get_order_status` tool responses in [`agent/tools.py`](file:///G:/Project%20Vendra/agent/tools.py) to supply explicit customer verification context.

### Fixed
- **Conversational Tracking Loop Bug:** Resolved the issue where the model refused to output tracking details due to a paranoid interpretation of Rule 4 (Privacy Lock). Updated Rule 4 in [`agent/prompts.py`](file:///G:/Project%20Vendra/agent/prompts.py) to declare system context Customer IDs pre-verified. Suppressed tool binding when a `ToolMessage` is the last message in the subgraph to ensure the model focuses purely on rendering the retrieved details.
- **Bangla Greeting Defaulting Bug:** Updated Rule 2 (Language Detection) in [`agent/prompts.py`](file:///G:/Project%20Vendra/agent/prompts.py) and the system prompt in [`general_agent_node`](file:///G:/Project%20Vendra/agent/graph.py#L699) to default to English. The system now strictly avoids switching to Bengali or Banglish unless explicitly greeted or asked questions in those languages.

---

## [2026-08-09] PHASE 8 — LLM Rate-Limiting Mitigation & Routing Hardening

### Added
- Implemented custom retry logic for ChatGroq API invocations with a fixed short backoff (2s then 5s) for rate limit `429 Too Many Requests` errors and a hard ceiling of 15 seconds total retry time per request, failing fast when exceeded.
- Added `ToolHallucinationError` to intercept model hallucinations when calling nonexistent/unbound tools (like `brave_search`).
- Registered `ToolHallucinationError` and `RuntimeError` as excluded exceptions on `llm_breaker` to prevent false positive circuit breaker trips.
- Created orchestrator-level re-routing inside `run_subgraph_safely` that intercepts `ToolHallucinationError`, parses the last user query against intent keywords, and executes the correct sub-agent graph inline with a friendly transition message.
- Defined module-level keyword lists for all intents (`TRACKING_WORDS`, `CANCELLATION_WORDS`, `CART_WORDS`, `CHECKOUT_WORDS`, `BROWSING_WORDS`, `GREETING_WORDS`, `GENERAL_WORDS`) to standardize parsing.
- Refactored `router_node` to check the deterministic keyword lists first, and automatically bypass LLM-based intent classification for continuing conversational turns when an `active_node` is set.
- Added comprehensive unit tests in `tests/test_fault_isolation.py` verifying both order status phrasing classification and the automated re-routing logic for tool hallucinations.

### Changed
- Removed `"return policy"` and `"refund policy"` from `CANCELLATION_WORDS` and added them to `GENERAL_WORDS` to ensure general policy questions route to the general agent rather than cancellation flow.

---

## [2026-08-06] PHASE 7 — Professional Next.js Frontend & Bug Fixes

### Added
- Created a fully decoupled web application in the `frontend` folder using Next.js (App Router), TypeScript, and Tailwind CSS.
- Implemented a secure Auth Gateway with Login and Signup views that persists and manages stateless JWT tokens in localStorage.
- Built a dual-pane conversational customer workspace:
  - Left Pane: Dynamic chat history with message bubbles, loading indicators, auto-scroll, and visual search (CLIP) photo uploader (with inline base64 serialization).
  - Right Pane: Tabs for shopping cart items (supporting inline item removal and subtotal calculations), order lists (displaying courier tracking timelines and payment shortcuts), profile information, and the admin control center.
- Integrated a mock Stripe payment webhook trigger in the order timeline, enabling users to simulate payments on pending checkouts.
- Built an Admin Refund Review Panel that connects to `/api/refunds/pending` using the server's `ADMIN_API_KEY`, supporting inline Approve/Deny actions.
- Configured optimized standalone Next.js builds and packaged the frontend application into a custom production Docker container.
- Updated `docker-compose.yml` to incorporate the Next.js service on port 3000 with a custom Node-based healthcheck.

### Fixed
- **Bug 1 (No Size Selector)**: Replaced the hardcoded size `"9"` with dynamic size-selectors: added an inline size picker dropdown to the chat product cards and a premium button grid selector to the product details modal, populated dynamically from the `/api/inventory` stock.
- **Bug 2 (Mock/Broken Order Tracking)**: Replaced mock order tracking with a real backend endpoint (`GET /api/orders/{order_id}/tracking`) that enforces customer ownership, and updated the frontend order tracking pane to render database-backed multi-step timeline events. Added comprehensive test coverage in `tests/test_tracking_api.py`.
- **Bug 3 (Broken Relative Image Paths)**: Resolved relative image URL issues by mounting the backend's `static/` folder using FastAPI `StaticFiles` in `main.py`, and introduced a frontend helper `getFullImageUrl` to prefix all relative image paths with the backend's `API_URL`.

---

## [2026-08-06] PHASE 6 — Safety, Authentication, & Hardening

### Added
- Integrated stateless JWT session tokens using `pyjwt` (HS256 algorithm with 24-hour expiration) and enforced fail-fast startup checks for `JWT_SECRET_KEY` in `config.py`.
- Refactored all customer mutations and info endpoints (`/api/chat`, `/api/orders`, `/api/cart/*`) to resolve and override the `customer_id` server-side via the authenticated token dependency, blocking cross-customer access with a `403 Forbidden` error.
- Enforced a strict rate limit of 5 requests per minute per IP on `POST /api/auth/login` to prevent brute-forcing.
- Added input parameter validators (`validate_product_id`, `validate_order_id`, `validate_shoe_size` using safe regex filters) to all tools in `agent/tools.py` to prevent SQL/command injection.
- Hardened the model's system prompts in `agent/graph.py` and `agent/prompts.py` to protect against adversarial injection.
- Added XSS sanitization (`html.escape()`) on dynamic product fields inside `app.py` card rendering.
- Implemented a 3,000-character input limit on `/api/chat` to protect against buffer stuffing.
- Enabled production mock webhook locks on `/webhook/stripe` and global exception sanitization to return clean `500` status codes.
- Added comprehensive security checks in `tests/test_scalability.py` confirming that `GET /api/customers` is deleted (returns `404`) and `password_hash` fields are popped from all API payloads.

---

## [2026-08-05] PHASE 3 — Scalability for Concurrent & Production Load

### Added
- Decoupled the frontend and backend by introducing new REST API endpoints in [main.py](file:///G:/Project%20Vendra/main.py) for cart management (`GET /api/cart/{id}`, `POST /api/cart/{id}/add`, `POST /api/cart/{id}/remove`), customer data retrieval (`GET /api/customers`, `GET /api/customers/{id}`), product detail querying (`GET /api/products/{id}/details`), inventory status checks (`GET /api/inventory`), order histories (`GET /api/orders`), and chat interactions (`POST /api/chat`).
- Refactored [app.py](file:///G:/Project%20Vendra/app.py) to communicate with the backend exclusively over HTTP, removing all direct backend and database imports (`agent.tools`, `agent.graph`, `CARTS`, `adapter`, `confirm_payment`) and ensuring complete process isolation.
- Implemented `RedisCartProxy` in [agent/tools.py](file:///G:/Project%20Vendra/agent/tools.py) which stores shopping carts in Redis (`vendra:cart:{customer_id}`) with a 24-hour expiration TTL.
- Added a fail-safe fallback mechanism: if `REDIS_URL` is unset or connection fails, the cart storage automatically falls back to local in-process memory.
- Integrated a Cache-Aside read performance optimization in [agent/tools.py](file:///G:/Project%20Vendra/agent/tools.py) for product catalog reads (`search_products`, `get_product_details`). Includes immediate cache invalidation on order checkout and order cancellation approvals. Caching silently no-ops when Redis is offline.
- Added rate-limiting policies using `slowapi` on all HTTP routes, including `/api/chat` (60 req/min), `/webhook/stripe` (120 req/min), and admin endpoints (30 req/min).
- Introduced a multi-worker SQLite startup guard in [main.py](file:///G:/Project%20Vendra/main.py) warning users that SQLite does not support concurrent multi-process writes. Updated the concurrency documentation in [README.md](file:///G:/Project%20Vendra/README.md).
- Created a comprehensive test suite in [tests/test_scalability.py](file:///G:/Project%20Vendra/tests/test_scalability.py) verifying Redis connection fallbacks, cache no-ops, the new HTTP chat API, and SQLite worker warnings.
- Wrote a load testing configuration in [load_test.js](file:///G:/Project%20Vendra/load_test.js) using the **k6** framework to test concurrent chat turns and latency targets.

---

## [2026-08-05] PHASE 2 — Human-in-the-Loop Refund Approval

### Added
- Implemented human-in-the-loop validation for all refund and cancellation requests, introducing a review queue database.
- Added a `RefundRequest` SQLAlchemy model in [adapters/models.py](file:///G:/Project%20Vendra/adapters/models.py) and generated the migration using Alembic.
- Implemented CRUD adapter functions in `BaseAdapter`, `JSONAdapter`, and `PostgresAdapter` to manage refund requests in database.
- Refactored the `cancel_order` tool in [agent/tools.py](file:///G:/Project%20Vendra/agent/tools.py) to queue requests with a `pending_review` status instead of executing direct refunds/mutations immediately.
- Integrated a persistent `SqliteSaver` checkpointer in [agent/graph.py](file:///G:/Project%20Vendra/agent/graph.py) using a direct global SQLite connection to avoid closure issues.
- Structured the master graph with a two-stage routing pattern: `cancellation` (runs subgraph and returns tool output) -> `approval` (calls `interrupt()` to pause, then processes decisions).
- Created secure FastAPI backend endpoints in [main.py](file:///G:/Project%20Vendra/main.py) for listing (`GET /api/refunds/pending`), approving (`POST /api/refunds/{id}/approve`), and denying (`POST /api/refunds/{id}/deny`) requests.
- Protected admin endpoints via strict `X-Admin-API-Key` header authentication, removing hardcoded defaults and returning a clear `401 Unauthorized` response on invalid keys.
- Enforced a fail-closed application startup check in [main.py](file:///G:/Project%20Vendra/main.py) that validates `ADMIN_API_KEY` presence and raises a `RuntimeError` if unset, preventing the application from initializing with unconfigured keys.
- Documented `ADMIN_API_KEY` requirements and generation details (e.g. `openssl rand -hex 32`) in [.env.example](file:///G:/Project%20Vendra/.env.example).
- Expanded the Streamlit application in [app.py](file:///G:/Project%20Vendra/app.py) to include an Admin Approval Dashboard, allowing admins to enter key, view pending requests, write review notes, and approve/deny requests.
- Created a comprehensive test suite in [tests/test_refund_approval.py](file:///G:/Project%20Vendra/tests/test_refund_approval.py) validating the complete pause-and-resume workflow, including a regression test (`test_app_fails_startup_without_admin_api_key`) to confirm startup blocks on missing keys.
- Declared stubs in `ShopifyAdapter` to ensure compatibilty and avoid Pydantic/OOP instantiation errors.
- Modified adversarial tests in [tests/test_adversarial.py](file:///G:/Project%20Vendra/tests/test_adversarial.py) to incorporate simulated admin approval flow, ensuring full regression coverage.

---

## [2026-08-05] PHASE 1 — Multi-agent architecture with fault isolation & Store Credit Fix

### Added
- Split monolithic `agent/graph.py` into five specialized sub-agents implemented as independent LangGraph subgraphs:
  - **Catalog Agent**: Tool access restricted to `search_products`, `search_products_by_image`, `check_stock`, `get_product_details`.
  - **Order & Tracking Agent**: Tool access restricted to `track_order` and the new read-only `get_order_status` tool.
  - **Refund & Cancellation Agent**: Tool access restricted to `check_cancellation_eligibility`, `cancel_order`, and `retrieve_policy_text`.
  - **Checkout & Payment Agent**: Tool access restricted to `add_to_cart`, `view_cart`, `remove_from_cart`, `create_order`, `create_payment_link`.
  - **General Agent**: Greeting handling and policy question lookups using `retrieve_policy_text`.
- Introduced a new `get_order_status` tool in [agent/tools.py](file:///G:/Project%20Vendra/agent/tools.py) to look up order items, status, and price details securely.
- Implemented try/except fault-isolation boundaries inside Orchestrator wrapper nodes to prevent sub-agent errors from crashing the main session.
- Added `tenacity` retry loops and `pybreaker` circuit breakers (`llm_breaker`, `stripe_breaker`, `db_breaker`) to handle transient failures gracefully.
- Created a proxy class `CircuitBreakerAdapterProxy` in [agent/tools.py](file:///G:/Project%20Vendra/agent/tools.py) to wrap database adapter calls automatically.
- Added unit tests in [tests/test_fault_isolation.py](file:///G:/Project%20Vendra/tests/test_fault_isolation.py) to verify sub-agent isolation and circuit breaker tripping.

### Fixed
- Resolved a critical database inconsistency bug where seeded customer balances were lost from `get_store_credit` after writing to `StoreCreditLedger`.
- Updated `@customers.setter` to populate `StoreCreditLedger` with `"Initial seeded balance"` for non-zero store credit fields during database initialization and seeding.
- Added `test_store_credit_seeded_with_additional` in [tests/test_postgres_adapter.py](file:///G:/Project%20Vendra/tests/test_postgres_adapter.py) to prevent regressions.
- Restricted the `@retry` decorator on database adapter calls in [agent/tools.py](file:///G:/Project%20Vendra/agent/tools.py) to fire only on transient connection errors (`OperationalError`, `DBAPIError`, `TimeoutError`), preventing business-rule rejections from causing multi-second latency.
- Refactored exception blocks in [adapters/postgres_adapter.py](file:///G:/Project%20Vendra/adapters/postgres_adapter.py) (`create_order`, `issue_store_credit`, `cancel_order`, etc.) to let `ValueError` and connection errors propagate natively rather than being masked as generic errors.
- Optimized `_call_llm_with_retry` in [agent/graph.py](file:///G:/Project%20Vendra/agent/graph.py) using a custom `is_transient_llm_exception` filter to bypass retries on permanent failures like bad request payloads.
- Added `test_create_order_insufficient_stock_fails_fast` in [tests/test_fault_isolation.py](file:///G:/Project%20Vendra/tests/test_fault_isolation.py) to verify that out-of-stock orders fail fast (under 0.5s) without retries.

---

## [2026-08-04] PHASE 0 — Database migration (JSON files → PostgreSQL)

### Added
- Created SQLAlchemy models in [adapters/models.py](file:///G:/Project%20Vendra/adapters/models.py) mapping all Vendra entities (`products`, `product_inventory`, `customers`, `orders`, `order_items`, `tracking`, `tracking_events`, `promotions`, and `store_credit_ledger`).
- Integrated append-only tracking of customer credit changes in the `store_credit_ledger` table.
- Initialized Alembic migrations and successfully generated/applied the initial schema migration (`56cae2f58354_initial_schema.py`).
- Implemented [adapters/postgres_adapter.py](file:///G:/Project%20Vendra/adapters/postgres_adapter.py) conforming to `BaseAdapter` with thread-locking for SQLite compatibility.
- Implemented `DBDictProxy` to support backward compatibility with dict-based mutations used in testing.
- Created unit tests in [tests/test_postgres_adapter.py](file:///G:/Project%20Vendra/tests/test_postgres_adapter.py) to verify the append-only ledger transaction behavior.

### Changed
- Modified [adapters/__init__.py](file:///G:/Project%20Vendra/adapters/__init__.py) to load `PostgresAdapter` when `ADAPTER=postgres`.
- Updated [.env.example](file:///G:/Project%20Vendra/.env.example) and local [.env](file:///G:/Project%20Vendra/.env) to set `ADAPTER=postgres` and define `DATABASE_URL` by default.
- Updated [config.py](file:///G:/Project%20Vendra/config.py) to validate the database connection dynamically at startup.
- Updated [seed.py](file:///G:/Project%20Vendra/seed.py) to automatically seed the database using JSON catalog files during startup.

---

## 🔴 Priority 1 — Security Fixes

### 1. Secure Stripe Webhook Validation
* **File Modified:** [main.py](file:///G:/Project%20Vendra/main.py)
* **Change:** Flipped `MOCK_WEBHOOK_ENABLED` default to `"false"`. The webhook handler now enforces a strict **fail-closed** security behavior: mock mode bypasses signature verification only if `MOCK_WEBHOOK_ENABLED` is explicitly `"true"` **and** the environment `ENV` is not `"production"`.
* **Telemetry:** Added a loud startup warning log when mock webhook mode is active.

### 2. Payment Link Ownership Check
* **Files Modified:** [agent/tools.py](file:///G:/Project%20Vendra/agent/tools.py), [agent/graph.py](file:///G:/Project%20Vendra/agent/graph.py)
* **Change:** Added a `customer_id` argument to the `create_payment_link` tool to programmatically verify that the requesting user owns the order (`order["customer_id"] == customer_id`) before generating Stripe payment links, returning an `"Access denied"` error on mismatches. Updated the system prompt in the checkout node of the graph to pass this value from system context.

### 3. Cart Tools Ownership Verification
* **Files Modified:** [agent/tools.py](file:///G:/Project%20Vendra/agent/tools.py), [agent/graph.py](file:///G:/Project%20Vendra/agent/graph.py), [app.py](file:///G:/Project%20Vendra/app.py)
* **Change:** Added `customer_id` parameter to `add_to_cart`, `view_cart`, and `remove_from_cart`. Added validation in the tools enforcing that `cart_id` must match `f"cart_{customer_id}"` to prevent cross-customer data disclosure. Prompts in the graph were modified to retrieve and supply these arguments from system context.

### 4. Session-Based Multi-User Identity
* **File Modified:** [app.py](file:///G:/Project%20Vendra/app.py)
* **Change:** Replaced the hardcoded customer ID `"C001"` with a dynamic selectbox at the top of the sidebar. The selected customer ID is stored in `st.session_state` and passed consistently across all operations.

---

## 🟠 Priority 2 — Data Integrity & Concurrency

### 5. Thread-Safe Payment Confirmation
* **Files Modified:** [adapters/base.py](file:///G:/Project%20Vendra/adapters/base.py), [adapters/json_adapter.py](file:///G:/Project%20Vendra/adapters/json_adapter.py), [agent/tools.py](file:///G:/Project%20Vendra/agent/tools.py)
* **Change:** Moved the in-memory order status mutations in `confirm_payment` inside the `JSONAdapter.confirm_payment` method, executing it thread-safely under the adapter's mutex lock (`self.lock`). The event idempotency check was moved into the same critical section to prevent check-then-act race conditions.

### 6. Atomic Disk State Persistence
* **File Modified:** [adapters/json_adapter.py](file:///G:/Project%20Vendra/adapters/json_adapter.py)
* **Change:** Added automatic disk persistence to the `JSONAdapter`. Every state mutation (`create_order`, `cancel_order`, `confirm_payment`, and `release_abandoned_checkouts`) now persists orders, inventory, tracking, and customer records back to their corresponding JSON files using a safe atomic write (write to temporary file first, then perform atomic replacement using `os.replace`).

### 7. Customer Store Credit Tracking
* **Files Modified:** [adapters/base.py](file:///G:/Project%20Vendra/adapters/base.py), [adapters/json_adapter.py](file:///G:/Project%20Vendra/adapters/json_adapter.py), [agent/tools.py](file:///G:/Project%20Vendra/agent/tools.py)
* **Change:** Added a `store_credit` attribute (defaulting to `0.0` if not present) to customer records. Modified the cancellation logic so that when an order is cancelled outside the 7-day refund window, store credit is programmatically incremented on the customer record under lock, and the updated balance is returned to the user. Exposed `get_store_credit` and `issue_store_credit` adapter methods.

### 8. Uvicorn Worker Configuration & Warning
* **Files Modified:** [run.py](file:///G:/Project%20Vendra/run.py), [README.md](file:///G:/Project%20Vendra/README.md)
* **Change:** Added `--workers 1` explicitly to the FastAPI development launch command in `run.py` to ensure single-process execution since concurrency locks are currently in-memory. Documented this limitation with a warning section in the `README.md` file.

---

## 🟡 Priority 3 — Correctness

### 9. Multi-Lingual Intent Routing
* **File Modified:** [agent/graph.py](file:///G:/Project%20Vendra/agent/graph.py)
* **Change:** Expanded the intent router's deterministic keyword override lists to match common Bengali and Banglish terms for order tracking, cancellations, cart operations, and payments, ensuring mixed-language requests route correctly.

### 10. External Adapter Error Propagation
* **Files Modified:** [adapters/base.py](file:///G:/Project%20Vendra/adapters/base.py), [adapters/shopify_adapter.py](file:///G:/Project%20Vendra/adapters/shopify_adapter.py), [adapters/woocommerce_adapter.py](file:///G:/Project%20Vendra/adapters/woocommerce_adapter.py), [agent/tools.py](file:///G:/Project%20Vendra/agent/tools.py)
* **Change:** Custom exception `AdapterError` is now raised by all methods of `ShopifyAdapter` and `WooCommerceAdapter` when network requests fail, instead of swallowing exceptions and returning empty values. Callers in `agent/tools.py` catch `AdapterError` and return a user-facing `"Vendra's external integration service is temporarily unavailable"` message.

### 11. Image Indexing Optimization in Visual Search
* **File Modified:** [agent/search_service.py](file:///G:/Project%20Vendra/agent/search_service.py)
* **Change:** Re-implemented `seed_vector_store` to clean collections before seeding and to skip indexing visual embeddings entirely for products that do not have a real image on disk, preventing visual search results from falsely matching generic placeholder images.

### 12. Python Compatibility Fix
* **Files Modified:** [adapters/json_adapter.py](file:///G:/Project%20Vendra/adapters/json_adapter.py), [agent/tools.py](file:///G:/Project%20Vendra/agent/tools.py)
* **Change:** Replaced all usages of `datetime.UTC` (which requires Python 3.11+) with the backwards-compatible `datetime.timezone.utc`.

---

## 🟢 Priority 4 — Performance & Code Quality

### 13. Router Caching & Ambiguous Input Classification Avoidance
* **File Modified:** [agent/graph.py](file:///G:/Project%20Vendra/agent/graph.py)
* **Change:** Added a global `_CLASSIFICATION_CACHE` in `agent/graph.py` to cache intent decisions for identical user messages. Extended the slot-filling heuristic to cover short/ambiguous replies, confirmations, and size selections when `active_node` is set, completely bypassing LLM classification overhead for those turns.

### 14. Unbounded Cart Memory Leak Guard (TTL Cleanup)
* **Files Modified:** [agent/tools.py](file:///G:/Project%20Vendra/agent/tools.py), [agent/graph.py](file:///G:/Project%20Vendra/agent/graph.py)
* **Change:** Added activity timestamp tracking to global `CARTS` via `CART_LAST_ACTIVITY`. Implemented `prune_inactive_carts()` which clears carts showing no activity for more than 24 hours. The cleanup is automatically triggered in the background on every turn by the intent router.

### 15. Dynamic Backend URL Configuration
* **File Modified:** [app.py](file:///G:/Project%20Vendra/app.py)
* **Change:** Replaced the hardcoded FastAPI URL `http://localhost:8000` with the `BACKEND_URL` environment variable, fallback defaulting to `http://localhost:8000` to support flexible deployments.

### 16. Code Optimization and Refactoring
* **Files Modified:** [agent/tools.py](file:///G:/Project%20Vendra/agent/tools.py), [agent/search_service.py](file:///G:/Project%20Vendra/agent/search_service.py)
* **Change:** Added comprehensive logging before returning error messages to the client, introduced type hints across all adapters, extracted the category/price filter code into `filter_products_by_metadata()`, and optimized `search_products_text` to short-circuit empty-query search requests.

---

## Verification

* **Total Tests Run:** 13
* **Status:** All tests passed (`pytest tests/test_adversarial.py -v` completed with 100% success).
