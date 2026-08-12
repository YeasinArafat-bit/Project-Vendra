# Vendra — Enterprise-Grade Decoupled Conversational Commerce Agent

Vendra is a state-of-the-art conversational commerce system built using a decoupled multi-agent architecture. Designed with the **Adapter Pattern**, Vendra's core AI reasoning engine remains completely identical across deployments, while a swap in the data adapter redirects all transactions and catalog queries to local mock databases, Shopify REST APIs, or WooCommerce REST APIs.

Featuring a high-performance **Next.js frontend**, a robust **FastAPI backend webhook server**, and a **LangGraph-based multi-agent routing graph**, Vendra provides a seamless, production-ready shopping experience backed by vector search and human-in-the-loop validation.

---

## 📸 User Interface Showcase

### 1. Welcome & Homepage Workspace
A clean, dual-pane layout featuring an interactive chat workspace on the left and utility tabs (cart, order tracking, and profiles) on the right.
![Vendra Homepage](image/Homepage.png)

### 2. Secure Auth Gateway
JWT-based customer session authentication with login/signup views.
![Vendra Signin Page](image/Signin%20_page.png)

### 3. Visual Search & Product Cards
Retrieves products dynamically using ChromaDB semantic search and renders rich product cards with dynamic size selectors.
![Product Discovery](image/show_some_shoes.png)

### 4. Interactive Cart Operations
Seamlessly add, update, and view items in your shopping cart.
![Add to Cart](image/add_to_cart.png)
![Cart Summary](image/Whats_in_my_cart.png)

### 5. Live Order Tracking Timeline
Renders real-time, database-backed courier timelines (e.g., Steadfast Courier) with payment status tracking.
![Order Tracking](image/track_order.png)

### 6. Safety & Out-of-Scope Guardrails
Adversarial prompt injection defense and strict policy checks filter out non-retail queries.
![Safety Guardrails](image/without_shoes_related_quesion_doesnot_ans.png)

---

## 🏛️ System Architecture

Vendra uses a **One Backend, Multiple Clients** approach, orchestrating specialized sub-agents with strict intent isolation.

```text
               +----------------------------------+
               |        Next.js Frontend          | (Port 3000)
               +----------------+-----------------+
                                |
                                | REST API / JWT Auth
                                v
               +----------------------------------+
               |         FastAPI Backend          | (Port 8000)
               +----------------+-----------------+
                                |
                                v
               +----------------------------------+
               |   LangGraph Agent Orchestrator   | (agent/graph.py)
               +----------------+-----------------+
                                |
        +-------+-------+-------+-------+-------+
        |       |       |       |       |       |
        v       v       v       v       v       v
      +-----+ +-----+ +-----+ +-----+ +-----+
      |Brow-| |Cart | |Track| |Canc-| |Gene-|
      |sing | |Agent| |Agent| |el   | |ral  |
      +--+--+ +--+--+ +--+--+ +--+--+ +--+--+
         |       |       |       |       |
         +-------+-------+-------+-------+
                         |
                         v
               +----------------------------------+
               |      Data Adapter Interface      | (adapters/base.py)
               +----------------+-----------------+
                                |
        +-----------------------+-----------------------+
        |                       |                       |
        v                       v                       v
+---------------+       +---------------+       +---------------+
| SQLite/Postgres|      | Shopify API   |       | WooCommerce   |
| (Local DB)    |       | Adapter       |       | Adapter       |
+---------------+       +---------------+       +---------------+
```

### The 5 Specialized Sub-Agents:
1. **Catalog/Browsing Agent** (`browsing_agent_node`): Restricts tool usage to catalog search, checking stock, and product details.
2. **Cart/Checkout Agent** (`checkout_agent_node`): Manages cart actions (adding/removing items, cart views) and payment creation.
3. **Order & Tracking Agent** (`tracking_agent_node`): Retrieves delivery timelines, status, and tracking metrics.
4. **Refund & Cancellation Agent** (`cancellation_agent_node`): Validates returns/cancellation rules and queues refund requests.
5. **General/Policy Agent** (`general_agent_node`): Resolves FAQs, policy lookups, and greetings.

### Key Technical Specs:
* **LLM Engine:** Groq API (Primary: `llama-3.1-8b-instant`, Secondary: `llama-3.3-70b-versatile` with automatic rate-limit failovers).
* **Conversational Logic:** LangGraph (Stateful multi-agent workflows with node isolation).
* **Visual Search:** CLIP embeddings (`sentence-transformers/clip-ViT-B-32`) with ChromaDB vector search.
* **Payment Integration:** Stripe Checkout webhook simulation with transaction locks.
* **Caching:** Redis cart state proxy with fail-safe local memory fallbacks.
* **Human-in-the-Loop:** Suspended refund execution queues requiring Admin authorization.

---

## 📁 Directory Structure

```text
Project Vendra/
├── main.py                     # FastAPI Backend Server & Endpoints
├── app.py                      # Streamlit Mock Frontend UI
├── run.py                      # Multi-Service Production Server Launcher
├── config.py                   # Decoupled Adapters & Security Environment Config
├── seed.py                     # Vector Store Seeding & Embedding Pre-generation
├── Dockerfile                  # API Docker Packaging
├── Dockerfile.streamlit        # Streamlit App Docker Packaging
├── docker-compose.yml          # Containerized Orchestration Spec
├── CHANGELOG.md                # System Modification History Ledger
├── adapters/
│   ├── base.py                 # Abstract Adapter Class Interface
│   ├── json_adapter.py         # Local JSON Mock Adapter
│   ├── shopify_adapter.py      # Production Shopify API Integration
│   └── woocommerce_adapter.py  # Production WooCommerce REST Integration
├── agent/
│   ├── graph.py                # LangGraph Flow Routing Nodes & Failovers
│   ├── tools.py                # Agent Tools with Adapter Isolation
│   ├── prompts.py              # Assistant Persona System Prompt Guidelines
│   └── search_service.py       # ChromaDB Vector Store Controller
├── data/
│   ├── products.json           # Catalog of 20 shoe products
│   ├── inventory.json          # Stock levels per size (5-11)
│   ├── customers.json          # Target customer registry
│   ├── orders.json             # Order transaction list
│   ├── tracking.json           # Shipment courier logs
│   └── promotions.json         # Active promotion details
├── image/                      # User Interface Screenshots
├── policies/
│   └── return_policy.md        # Ground-truth Return and Cancellation Policy
├── static/
│   └── images/                 # Catalog Product Images
├── vectorstore/                # Local ChromaDB Database Folder
└── tests/
    ├── test_adversarial.py     # Automated Adversarial/Privacy/Security Pytest Suite
    └── test_regression_round4.py # Automated Regression & Failover Verification Suite
```

---

## 🚀 Setup & Execution Guide

### Prerequisites
* Python 3.10+
* Node.js v18+ (for frontend)
* Groq API Key (added to `.env`)
* Redis (optional, for caching)

### 1. Vector Database Seeding
Populate ChromaDB collections with product information and return policy text:
```bash
python seed.py
```

### 2. Start the Backend API (FastAPI)
Launch the webhook server and REST endpoints:
```bash
python run.py
```
*The API server will run on `http://localhost:8000`.*

### 3. Start the Next.js Frontend
Navigate to the frontend directory, install dependencies, and start the development server:
```bash
cd frontend
npm install
npm run dev
```
*The web interface will run on `http://localhost:3000`.*

---

## 🔑 Test Credentials & Admin Review Key

To test the system immediately without having to sign up or create new accounts, you can log in with the following seeded records:

### Customer Accounts (Password for all is `password123`)
* **Alice Test:** `alice@test.com` *(Customer ID: `C001`, owns order `ORD002`)*
* **Bob Test:** `bob@test.com` *(Customer ID: `C002`)*
* **Imran Hossain:** `imran@email.bd` *(Customer ID: `C003`)*

### Admin Panel Key
To approve or deny pending cancellation refund requests in the Admin Panel interface:
* **Admin Key:** `test_admin_key` *(configured via `ADMIN_API_KEY` in `.env`)*

---

## 🔒 Security & Policy Guardrails

Vendra is built to survive aggressive prompt injections and adversarial customer interactions:
* **JWT Authenticated Boundaries:** All customer mutations (`/api/chat`, `/api/orders`, `/api/cart/*`) resolve and override `customer_id` server-side via token verification, completely blocking cross-customer access.
* **Prompt Injection Shield:** Evaluates all queries against strict system persona locks to reject instructions requesting system-level changes or unauthorized discounts.
* **Fault-Tolerant Circuit Breakers:** Gracefully falls back to the secondary `llama-3.3-70b-versatile` model in case of Groq rate limits, preventing system downtime.
* **Out-of-Scope Blocking:** Explicitly redirects off-topic chatter or irrelevant prompts to a polite refusal message.

---

## 🧪 Automated Testing

Vendra includes a comprehensive test suite to prevent regressions and security vulnerabilities:

To execute adversarial privacy and webhook tests:
```bash
pytest tests/test_adversarial.py -v
```

To execute regression, topic-switching, and model-failover tests:
```bash
pytest tests/test_regression_round4.py -v
```
