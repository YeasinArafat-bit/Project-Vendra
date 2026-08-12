# Project Vendra — Production Roadmap (Phase-by-Phase for Antigravity)

Give Antigravity ONE phase at a time, in order. Each phase ends with `pytest tests/ -v` green plus the phase's own new tests, and a dated `CHANGELOG.md` entry, before starting the next. Do not let scope creep between phases — each phase should be a complete, mergeable unit of work.

**Product requirement driving this roadmap:** a customer can (1) browse/search for shoes, (2) check their order status, (3) request a refund/cancellation — which must route to a human for approval before executing, (4) check live parcel/courier tracking status. The whole system must survive partial failure: if one capability (e.g. the refund flow) throws an unhandled error or an external dependency is down, every other capability keeps working normally for that customer and for all other customers. It must run on a real production database, not local JSON files, and must be able to handle concurrent load from many simultaneous customers — because this is being sold as a product, not a demo.

---

## PHASE 0 — Database migration (JSON files → PostgreSQL)

This unblocks everything else; do this first.

1. Stand up PostgreSQL (via Docker for local dev — see Phase 5 for the compose file). Design tables mirroring current JSON shape but normalized: `products`, `product_inventory` (product_id, size, quantity), `customers`, `orders`, `order_items`, `tracking`, `tracking_events` (one row per timeline entry, not a nested list), `promotions`, `store_credit_ledger` (append-only ledger, not just a balance field — every credit/debit is its own row with a reason and timestamp, so balance is always auditable/reconstructable).
2. Use SQLAlchemy (already in `requirements.txt`, currently unused — confirm and remove that inconsistency) with Alembic for migrations. Write the initial migration from scratch based on the schema above.
3. Build a new `adapters/postgres_adapter.py` implementing the exact same `BaseAdapter` interface as `JSONAdapter` (`get_products`, `get_product_details`, `create_order`, `cancel_order`, `confirm_payment`, `mark_refunded`, `set_payment_intent`, `get_store_credit`, `issue_store_credit`, everything currently in `adapters/base.py`). This preserves the Adapter Pattern that already exists — the rest of the app (`agent/tools.py`, `app.py`) should need zero changes to switch adapters.
4. Replace the `threading.Lock`-based concurrency control with real DB-level guarantees: use `SELECT ... FOR UPDATE` row locking for order/inventory mutations, and wrap each mutating operation in a proper transaction (`BEGIN`/`COMMIT`/`ROLLBACK` on exception) instead of Python in-process locks. This is what actually makes concurrent-order/race-condition safety work correctly across multiple server processes/workers, which the current `threading.Lock` singleton cannot do.
5. Write a one-time migration script that reads all existing `data/*.json` files (including the expanded realistic mock dataset from the previous roadmap phase, if already generated) and inserts them into Postgres, so you don't lose the mock catalog work.
6. Set `ADAPTER=postgres` as the new default in `.env.example`, keep `ADAPTER=json` working as a fallback/local-dev/demo mode (useful for quick local testing without a DB running).
7. Update `config.py` to validate `DATABASE_URL` is set and reachable at startup when `ADAPTER=postgres`, failing fast with a clear error otherwise.
8. Full test suite must pass against the Postgres adapter, not just the JSON adapter — parametrize `tests/test_adversarial.py` to run against both adapters if feasible, or duplicate the critical concurrency/ownership tests for the Postgres path specifically.

---

## PHASE 1 — Multi-agent architecture with fault isolation

Split the current single LangGraph graph (`agent/graph.py`) into specialized, isolated sub-agents. Goal: a crash or exception in one capability never breaks another, and never crashes the whole customer conversation.

1. **Define five specialized sub-agents as separate LangGraph subgraphs**, each with its own system prompt, tools, and internal error handling:
   - **Catalog Agent** — product search (text + CLIP visual), recommendations, product detail lookups. Wraps `search_products_text`, `search_products_image`, `get_product_details`.
   - **Order & Tracking Agent** — order history lookup, courier/parcel tracking status. Wraps `get_order`, tracking lookups.
   - **Refund & Cancellation Agent** — eligibility check, then **must stop and wait for human approval before executing anything** (see Phase 2 — this is the human-in-the-loop gate). Wraps `check_cancellation_eligibility`, and a new gated `execute_refund` tool that only the approval flow can call.
   - **Checkout & Payment Agent** — cart management, payment link generation, webhook-driven payment confirmation. Wraps `add_to_cart`, `view_cart`, `remove_from_cart`, `create_payment_link`.
   - **General Agent** — greeting handling, chitchat, and policy FAQ lookups. Wraps `retrieve_policy_text`.
2. **Top-level Orchestrator node** replaces the current `router_node` — classifies intent (keep the existing hybrid keyword + LLM classification + Bengali/Banglish support, that logic is solid) and dispatches to the correct sub-agent graph.
3. **Fault isolation at the orchestrator level:** wrap every sub-agent invocation in a try/except. If a sub-agent throws an unhandled exception:
   - Log the full exception with structured logging (agent name, customer_id, conversation state) for alerting/debugging.
   - Return a graceful, honest fallback message to the customer for that specific capability only (e.g. "I'm having trouble checking tracking right now, but I can still help you browse products or check your order status") — never a raw stack trace, never a silent hang, never a crash of the whole chat session.
   - The conversation must remain usable — the customer's next message should route normally to any other (healthy) sub-agent.
4. **Per-external-dependency circuit breakers:** wrap every external call (Gemini/LLM API, Stripe API, courier API if one exists, DB queries) with a retry-with-backoff (e.g. `tenacity`) and a circuit breaker (e.g. `pybreaker`) so a slow/down external dependency degrades gracefully (fast-fail after N retries with a clear message) instead of hanging the whole request or cascading failures into unrelated capabilities.
5. Write new tests: for each sub-agent, a test that deliberately makes its tool throw an exception and asserts (a) the orchestrator doesn't crash, (b) a graceful message is returned, (c) a subsequent message routed to a *different* healthy sub-agent still works correctly in the same test.

---

## PHASE 2 — Human-in-the-loop refund approval

This is a hard product requirement: refunds must never execute automatically.

1. Add a new DB table `refund_requests`: `id`, `order_id`, `customer_id`, `requested_at`, `refund_type` (`full_refund` / `store_credit`), `eligibility_reason`, `status` (`pending_review`, `approved`, `denied`), `reviewed_by`, `reviewed_at`, `review_notes`.
2. Change the **Refund & Cancellation Agent** so that when a customer requests a cancellation/refund and `check_cancellation_eligibility` confirms it's eligible, the agent does **not** call `adapter.cancel_order`/`mark_refunded` directly. Instead it inserts a row into `refund_requests` with `status=pending_review` and tells the customer clearly: their request has been submitted for review and they'll be notified once approved (do not imply instant refund).
3. Use LangGraph's `interrupt`/human-in-the-loop primitives (already partially scoped in prior conversation context — the pattern is: graph pauses, external system resumes it later with a decision) to model this as a real pause-and-resume flow, not a fire-and-forget DB insert with no connection back to the conversation.
4. Build a minimal **admin approval interface** — this can be a simple authenticated internal page/endpoint (doesn't need to be fancy for v1): lists `pending_review` refund requests with order/customer context, lets an authorized human click Approve or Deny with optional notes. On Approve, this triggers the actual `adapter.cancel_order()` + `adapter.mark_refunded()` (or `issue_store_credit()`) execution and updates `refund_requests.status`. On Deny, updates status and stores the reason.
5. Add a notification hook (can start as simple: an email via a transactional email API, or even just a webhook you can wire up later) that fires when a refund request is approved/denied, so the customer isn't left wondering — at minimum, the next time they open the chat, the Order & Tracking Agent should be able to tell them the current status of their refund request if asked.
6. Tests: submit a refund request via the agent, assert no money/inventory/status changes happen immediately; simulate an admin approval via the new endpoint; assert the order is now correctly refunded and the ledger/inventory reflects it; simulate a denial; assert nothing changed and the customer-facing status reflects "denied" with the reason.

---

## PHASE 3 — Scalability for concurrent/production load

1. **Make the app stateless and horizontally scalable.** The current `CARTS` global in-memory dict and `JSONAdapter` singleton pattern cannot survive multiple server processes or instances. Move cart state into the Postgres DB (a `carts` / `cart_items` table) or Redis (faster for ephemeral cart data with a TTL) — Redis is the better fit here since carts are semi-ephemeral and need fast read/write under load.
2. **Add Redis caching** for hot, rarely-changing reads: product catalog listings, product details. Cache-aside pattern with a sensible TTL (e.g. 5 minutes) and explicit invalidation on product update. This matters a lot under load since catalog reads will vastly outnumber writes.
3. **Move slow/non-critical work off the request path** using a background task queue (Celery or RQ with Redis as the broker): CLIP image embedding generation during seeding, sending refund-decision notifications, any future email/SMS sending. The customer-facing chat response should never block on these.
4. **Run FastAPI with multiple workers** (`uvicorn --workers N` or behind Gunicorn with the Uvicorn worker class) now that state is out of process memory (Phases 0 and 3.1 make this safe — currently it is NOT safe, and the roadmap up to this point explains exactly why).
5. **Connection pooling** for Postgres (SQLAlchemy's built-in pooling, tuned pool size for expected concurrency) and for Redis (connection pool, not a new connection per request).
6. **Rate limiting** per customer/IP on the chat endpoint and webhook endpoint (`slowapi` or similar) to prevent one abusive client from degrading service for everyone else.
7. **Load test** with Locust or k6 simulating realistic concurrent customer sessions (browsing, checking orders, requesting refunds simultaneously) — set a concrete target (e.g. "500 concurrent users, p95 response time under 3s for chat turns") and tune based on results. Document the tested capacity in the README so you can honestly represent it when selling this.

---

## PHASE 4 — Mock data & real product images (carry-over from previous prompt)

If not already done, this phase is unchanged from the previous roadmap — execute it against whichever adapter is now live (Postgres, post-Phase 0):

- Fix the broken image pipeline: every product needs a real, distinct, correctly-matching downloaded photo (not shared/duplicated Unsplash links), stored and referenced correctly so CLIP visual search actually indexes them (verify the `seed.py` skip-logic bug is truly fixed against the new DB-backed seeding path).
- Expand to 60–80 realistic products, 15–20 realistic Bangladeshi customers, 30–40 historical orders with consistent totals, matching tracking records, 6–8 promotions with a mix of active/expired.
- Preserve exact IDs/values that existing tests depend on.

---

## PHASE 5 — Containerization, config, observability (carry-over + expanded)

1. `Dockerfile` (FastAPI backend), `Dockerfile.streamlit` (frontend), `docker-compose.yml` wiring FastAPI + Streamlit + **Postgres + Redis** (new services vs. the previous version of this phase) with proper service networking, named volumes for Postgres data persistence, and healthchecks on each service.
2. `.dockerignore`, pinned `requirements.txt` versions.
3. `config.py` startup validation (`DATABASE_URL`, `REDIS_URL`, `GEMINI_API_KEY`, adapter-specific keys) — fail fast and loud, not a cryptic error three calls deep.
4. Structured logging throughout (replace remaining `print()` calls), with agent name / customer_id / request_id context on every log line so you can trace a single customer's journey across the multi-agent split from Phase 1.
5. `/health` endpoint checking DB and Redis connectivity, not just "the process is alive."
6. Basic metrics (Prometheus-compatible `/metrics` endpoint, or at minimum structured logs you can aggregate) tracking: requests per sub-agent, error rate per sub-agent, refund request queue depth, response latency — this is what lets you (and future customers who buy this) actually operate it with confidence.

---

## PHASE 6 — Security & auth hardening (carry-over + expanded)

1. Everything from the earlier security pass (webhook fail-closed, cart/payment-link ownership checks, locked+persisted mutations) — confirm all of this survived the Postgres migration correctly (row-level ownership checks especially, now enforced at the query level, not just in Python).
2. **Real customer authentication** — replace the Streamlit sidebar customer-selector dropdown (fine for a demo, not for a real product) with actual login (email + password or magic link), session tokens, and route every agent tool call through the authenticated customer's ID — never trust a client-supplied `customer_id`.
3. **Admin authentication** for the refund-approval interface from Phase 2 — separate role, not the same auth as customers.
4. CORS allow-list, rate limiting (tie into Phase 3.6), and a final full re-read of `main.py` and every adapter to confirm no regressions were introduced across all the above phases.

---

## PHASE 7 — Professional frontend (post-launch polish)

Do this last, after Phase 6, once the final set of screens is known (customer chat, login, admin refund-approval panel). None of Phases 0–6 need to change for this phase to happen — the FastAPI backend is already a clean API boundary, so the frontend can be reskinned or fully replaced without touching `adapters/`, `agent/`, or `main.py`.

There are two paths. Pick one before starting — they're very different scopes.

### Option A — CSS reskin of the existing Streamlit app (days, not weeks)

Keep the current architecture. Streamlit's component structure still shows through underneath, but a real design pass makes it look far less "default Streamlit."

1. Inject custom CSS via `st.markdown(..., unsafe_allow_html=True)`: a real color palette and type scale (not Streamlit defaults), custom chat bubble styling for the conversation view, a proper header/nav bar, consistent spacing/padding overrides on Streamlit's default containers.
2. Custom product cards for search results (image, name, price, tags) instead of the current plain text block output — render `search_products`/`search_products_by_image` results as an actual card grid.
3. Polish the cart/checkout view into a real summary layout (line items, subtotal, total) instead of plain text.
4. Style the new admin refund-approval panel (from Phase 2) and the login flow (from Phase 6) to match the same design system, not as bolted-on afterthoughts.
5. Add a proper loading/typing indicator during agent responses instead of Streamlit's default spinner, and smooth out the image rendering fix from the mock-data phase (base64-embedded local images) so it doesn't flash/reflow.
6. Mobile responsiveness pass — check the chat and product cards on a narrow viewport, since customers will likely use this on phones.

### Option B — Full custom frontend (React/Next.js), Streamlit retired

This is what actually gets you a "looks like a real, sellable product" result — full layout control, animations, no framework tells. Separate project-sized effort, not a few days.

1. New Next.js (or plain React + Vite) frontend calling the existing FastAPI backend directly — no backend changes needed beyond confirming CORS is configured correctly for the new frontend's origin (this should already be covered by Phase 5/6's CORS work).
2. Rebuild the chat interface, product catalog/search UI, cart/checkout, order tracking view, login, and the admin refund-approval panel as real React components with a proper design system (component library or custom, your call — e.g. shadcn/ui or Tailwind from scratch).
3. Handle streaming responses from the agent properly (if the backend supports streaming; if not, that's a small backend addition, not a redesign) so replies feel responsive rather than a single blocking wait.
4. Image handling: serve product images as real static assets from a CDN or the FastAPI static file mount, not the base64-embedding workaround needed for Streamlit.
5. Deploy the new frontend as its own service in `docker-compose.yml` (or separately if you want it on a CDN/edge host like Vercel while the backend stays on your own infra) — update Phase 5's compose file accordingly.
6. Decide whether to keep the Streamlit app around at all after this (e.g. as an internal/admin-only tool) or retire it entirely.

### Either way

- Do a full manual smoke test of all four core customer flows (browse, check order, request refund, check tracking) through the new UI before calling this done — visual bugs in a redesign often hide functional regressions (e.g. a button that looks right but lost its `onClick`/tool-call wiring).
- Get this in front of a few real people (not just yourself) before finalizing, since "professional-looking" is subjective and you're building this to sell.

----

## Execution notes

- Phases 0–2 are the core product-correctness work (real DB, fault-isolated multi-agent design, mandatory human refund approval) — this is what actually fixes the biggest current gaps relative to your requirements.
- Phases 3–6 are what make it genuinely sellable as "production grade, handles massive load."
- Each phase is written to be handed to Antigravity as its own self-contained task — copy one phase's section at a time.
- After every phase, do a quick manual smoke test yourself (not just pytest) by actually running the app and trying the four core customer flows (browse, check order, request refund, check tracking) end to end, since integration issues between phases won't always show up in unit tests alone.
