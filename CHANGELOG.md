# Changelog - Vendra Fixes & Optimizations

This changelog summarizes the modifications made to Vendra's conversational commerce system to address security, data integrity, correctness, and performance issues.

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
