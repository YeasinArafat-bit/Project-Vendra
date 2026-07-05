# Vendra — Decoupled Conversational Commerce Agent

Vendra is a state-of-the-art conversational commerce assistant built using the **Adapter Pattern**. The agent and tools remain completely identical across deployments, while a swap in the data adapter redirects all queries to local JSON files (demo), Shopify REST API, or WooCommerce REST API.

---

## Architecture Diagram

```text
LangGraph Agent (agent/graph.py)
            |
      Tool Functions (agent/tools.py) <-- Unchanged
            |
      Data Adapter Interface (adapters/base.py)
            |
  +---------+---------+---------+
  |                   |         |
JSON Adapter      Shopify    WooCommerce
(json_adapter.py) (shopify_  (woocommerce_
                  adapter.py) adapter.py)
```

## Directory Structure

```text
Project Vendra/
├── main.py                     # FastAPI Backend Webhook Server
├── app.py                      # Streamlit Frontend Chat UI
├── config.py                   # Decoupled Adapter Config
├── .env                        # Environment Settings
├── .env.example                # Config Template
├── README.md                   # Documentation
├── seed.py                     # Vector Seeding Script
├── adapters/
│   ├── base.py                 # Abstract Adapter Class Interface
│   ├── json_adapter.py         # Local JSON Mock Adapter
│   ├── shopify_adapter.py      # Production Shopify API Adapter
│   └── woocommerce_adapter.py  # Production WooCommerce REST API Adapter
├── agent/
│   ├── graph.py                # LangGraph Flow Routing Nodes
│   ├── tools.py                # Agent Tools with Adapter Isolation
│   ├── prompts.py              # Assistant Persona System Prompt
│   └── search_service.py       # ChromaDB Vector Store Controller
├── data/
│   ├── products.json           # Catalog of 20 shoe products
│   ├── inventory.json          # Stock levels per size (5-11)
│   ├── customers.json          # Target customer registry
│   ├── orders.json             # Order transaction list
│   ├── tracking.json           # Shipment courier logs
│   └── promotions.json         # Active promotion details
├── policies/
│   └── return_policy.md        # Return and Cancellation Policy Rules
├── vectorstore/                # Local ChromaDB Database Folder
└── tests/
    └── test_adversarial.py     # Automated Pytest Test Suite
```

---

## Local Setup & Run Instructions

### 1. Seeding the Vector Search Database
Populate ChromaDB collections with product information and return policy text:
```bash
python seed.py
```

### 2. Launching the FastAPI Webhook Backend
Runs the Stripe webhook handler server:
```bash
uvicorn main:app --reload --port 8000
```

### 3. Launching the Streamlit Frontend App
Runs the chat UI interface:
```bash
streamlit run app.py
```

---

## Thread-Safety and Concurrency Note

> [!WARNING]
> The default `JSONAdapter` implementation coordinates thread-safety using an in-memory python `threading.Lock`. 
> While this works perfectly for single-process deployments (such as Uvicorn running with `--workers 1`), it will **not** synchronize state updates across multiple worker processes or distributed environments. 
> 
> If you deploy Vendra with multiple processes, you must migrate from the `JSONAdapter` to the production-ready `ShopifyAdapter` or `WooCommerceAdapter` (which leverage external database transactions for thread-safety and concurrency coordination).

---

## Running the Automated Test Suite

We use `pytest` to execute adversarial tests checking refund rules, cross-customer privacy, stock concurrency, and webhook idempotency:
```bash
pytest tests/test_adversarial.py -v
```
All tests will execute in isolation.

