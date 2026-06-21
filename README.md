# Vendra — Conversational Commerce Agent for Shoe Stores

Vendra is a state-of-the-art conversational AI shopping assistant designed to guide customers through a shoe store’s catalogue, cart additions, Stripe payment links generation, order tracking, and returns/cancellation workflows in natural language.

---

## Technical Stack & Architecture

- **Backend:** FastAPI (`api.py`)
- **Frontend:** Streamlit (`app.py`)
- **Agent Orchestration:** LangGraph (Stateful multi-node conversation graph in `agent_graph.py`)
- **Database:** SQLite with SQLAlchemy (`models.py`, `database.py`)
- **Vector Search & RAG:** ChromaDB with Hugging Face `all-MiniLM-L6-v2` for semantic text query, and `clip-ViT-B-32` for visual photo-based search (`services/search.py`).
- **Payments:** Stripe (Test Mode)

### Core Guardrails & Concurrency
1. **No Hallucinations:** The agent *never* decides order status, stock, or policy eligibility from its parameters. It delegates to deterministic Python tool calls to check SQLite or ChromaDB.
2. **Stock Concurrency (Race Conditions):** Stock reservation happens inside a single transaction during order creation using SQLite `IMMEDIATE` write locking, preventing overselling.
3. **Idempotent Webhooks:** Stripe webhook deliveries are tracked using unique event IDs to prevent double-processing.
4. **Abandoned Checkouts:** Orders in `pending_payment` state for more than 15 minutes are automatically cancelled and their reserved stock is returned to the active inventory.

---

## Directory Structure

```text
Project Vendra/
│
├── api.py                    # FastAPI Webhook and API Backend
├── app.py                    # Streamlit Chat Interface Frontend
├── database.py               # SQLAlchemy SQLite engine setup
├── models.py                 # SQLAlchemy database schemas
├── seed.py                   # Data initializer & Chroma embedder
├── tools.py                  # Core agent tools (stock, cart, checkout)
├── agent_graph.py            # LangGraph routing and agents workflow
├── requirements.txt          # Python packages list
├── .env.example              # Key templates file
├── policies/
│   └── return_policy.md      # Shoe Store Return/Cancellation Markdown
└── tests/
    └── test_adversarial.py   # Automated Pytest Test Suite
```

---

## Local Setup Instructions

### 1. Clone & Set Up Environment
Ensure you are using Python 3.12 (standard for wheel compatibilities). Create a virtual environment and install packages:

```bash
# Recreate venv
python -m venv .venv
.venv\Scripts\activate

# Install dependencies
pip install -r requirements.txt
```

### 2. Configure Environment Variables
Copy `.env.example` to `.env` and fill in your keys:
```bash
cp .env.example .env
```
Ensure you have an `ANTHROPIC_API_KEY` for Claude, and Stripe Test keys if checking actual card redirects. (A Mock fallback checkout operates automatically if keys are omitted).

### 3. Initialize & Seed Database
Seeding populates the shoe inventory with 15 realistic products (and variants of sizes 6-11), embeds the return policies inside the vector store, and creates placeholder image bytes for CLIP visual search:

```bash
python seed.py
```

### 4. Run the Servers

#### Run FastAPI Backend (for webhooks):
```bash
uvicorn api:api --reload --port 8000
```

#### Run Streamlit Chat Interface:
```bash
streamlit run app.py
```

---

## Conversational Testing Walkthrough

Open the Streamlit app at `http://localhost:8501`. Walk through this complete flow in chat:

1. **Browse:** Type *"Hi! I'm looking for some elegant brown leather shoes for a formal wedding"* -> Vendra will fetch results from the product vector database and show options with pictures.
2. **Product details:** Ask *"Show me the details and size availability for Product ID 1"* -> Vendra lists available stock per size with variant IDs.
3. **Add to Cart:** Type *"Add size 8 to my cart"* -> The cart updates immediately in the sidebar list.
4. **Checkout:** Type *"I'm ready to checkout"* -> Vendra displays cart summary and presents a Stripe payment checkout link.
5. **Simulate Payment:** In the sidebar, click the **💳 Simulate Webhook: Pay Order #X** button -> Webhook confirms payment, marking order status as **PAID** on the screen.
6. **Track:** Type *"Where is my order #1?"* -> Vendra checks ownership and confirms order status is PAID.
7. **Cancel & Refund:** Type *"I want to cancel my order"* -> Vendra runs the deterministic policy rules. If cancelled within 7 days, it refunds. Try typing *"cancel order #3"* (seeded as 8 days old) to verify that Vendra offers store credit instead.

---

## Running the Automated Test Suite

We use `pytest` to run our adversarial suite verifying race conditions, boundary rules, and customer scopes:

```bash
pytest tests/test_adversarial.py -v
```

All 7 test cases will execute and verify transaction safety, temporal checks, and privacy locks.

---

## Monitoring and Observability with LangSmith

To trace every agent state transition and tool parameters:
1. Create a free account on [LangSmith](https://smith.langchain.com/).
2. Enable tracing in your `.env` file:
   ```env
   LANGCHAIN_TRACING_V2=true
   LANGCHAIN_API_KEY=your_langsmith_api_key
   LANGCHAIN_PROJECT=vendra-shopping-agent
   ```
3. Restart Streamlit. Every conversation turn, routing decision, and SQL query will be logged and visualised under your project dashboard in real time.
