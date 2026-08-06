import os
import sys
import json
import pytest
import datetime
from unittest.mock import MagicMock
from fastapi.testclient import TestClient

# Inject project root path to allow absolute imports
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from agent.tools import (
    adapter,
    cancel_order,
    check_cancellation_eligibility
)
from agent.graph import graph
from main import app
from langchain_core.messages import HumanMessage, AIMessage

client = TestClient(app)

@pytest.fixture(autouse=True)
def setup_db():
    adapter.reset_state()
    
    # Clear SqliteSaver checkpointer tables to ensure conversation history isolation
    try:
        import sqlite3
        conn = sqlite3.connect("data/vendra.db")
        cursor = conn.cursor()
        for table in ["checkpoints", "checkpoint_blobs", "checkpoint_writes", "writes"]:
            try:
                cursor.execute(f"DELETE FROM {table}")
            except sqlite3.OperationalError:
                pass
        conn.commit()
        conn.close()
    except Exception as e:
        print(f"Failed to clear checkpointer DB: {e}")
    
    # 1. Seed Customer
    adapter.customers = [
        {
            "id": "C001",
            "name": "Alice Test",
            "email": "alice@test.com",
            "phone": "123",
            "address": "Alice St",
            "store_credit": 0.0
        }
    ]
    
    # 2. Seed Product
    adapter.products = [
        {
            "id": "P001",
            "name": "Test Product",
            "description": "Test product description",
            "category": "shoes",
            "occasion_tags": [],
            "mood_tags": [],
            "price": 100.0,
            "currency": "BDT",
            "image_url": ""
        }
    ]
    
    # 3. Seed Inventory
    adapter.inventory = {
        "P001": {
            "9": 10
        }
    }
    
    # 4. Seed Paid Order (within 7 days cancellation window)
    now = datetime.datetime.now(datetime.timezone.utc)
    adapter.orders = {}
    adapter.orders["ORD100"] = {
        "id": "ORD100",
        "customer_id": "C001",
        "items": [{"product_id": "P001", "size": "9", "quantity": 1, "price": 100.0}],
        "total": 100.0,
        "status": "paid",
        "created_at": now.isoformat()
    }
    
    # Also seed a paid order (outside 7 days cancellation window)
    long_ago = now - datetime.timedelta(days=10)
    adapter.orders["ORD200"] = {
        "id": "ORD200",
        "customer_id": "C001",
        "items": [{"product_id": "P001", "size": "9", "quantity": 1, "price": 100.0}],
        "total": 100.0,
        "status": "paid",
        "created_at": long_ago.isoformat()
    }
    
    adapter.tracking = {}
    yield

def test_cancel_order_tool_does_not_execute_immediately():
    """
    Asserts that calling the cancel_order tool does NOT change the order's status,
    does NOT touch inventory, and does NOT issue store credit or payment refunds immediately.
    Instead, it only creates a pending_review record in refund_requests.
    """
    # Verify initial state
    order = adapter.get_order("ORD100")
    assert order["status"] == "paid"
    assert adapter.inventory["P001"]["9"] == 10
    assert adapter.get_store_credit("C001") == 0.0
    
    # Invoke cancel_order tool (passes config mock)
    from langchain_core.runnables import RunnableConfig
    config = RunnableConfig(configurable={"thread_id": "thread_test_c001"})
    
    res = cancel_order.invoke(
        {"order_id": "ORD100", "customer_id": "C001"},
        config=config
    )
    
    # Assert return message mentions submission and request ID
    assert "submitted for review" in res.lower()
    assert "ref" in res.lower()
    
    # Assert Order state is STILL "paid" and untouched
    order_after = adapter.get_order("ORD100")
    assert order_after["status"] == "paid"
    
    # Assert Inventory is STILL 10
    assert adapter.inventory["P001"]["9"] == 10
    
    # Assert Store credit is STILL 0.0
    assert adapter.get_store_credit("C001") == 0.0
    
    # Assert refund_requests has a pending record
    pending = adapter.get_pending_refund_requests()
    assert len(pending) == 1
    assert pending[0]["order_id"] == "ORD100"
    assert pending[0]["status"] == "pending_review"

def test_admin_api_requires_auth():
    """
    Assert that admin endpoints fail with 401 Unauthorized when an invalid or missing API key is sent.
    """
    # 1. No key
    res = client.get("/api/refunds/pending")
    assert res.status_code == 401
    
    # 2. Wrong key
    res = client.get("/api/refunds/pending", headers={"X-Admin-API-Key": "wrong-key"})
    assert res.status_code == 401
    
    # 3. Correct default key
    res = client.get("/api/refunds/pending", headers={"X-Admin-API-Key": "admin-default-secret-key-vendra"})
    assert res.status_code == 200

def test_admin_approval_executes_refund_and_resumes_graph(monkeypatch):
    """
    Test the full end-to-end flow:
    - Customer initiates cancellation, graph pauses on interrupt.
    - Admin approves the request via the POST approve API endpoint (with auth).
    - The graph is resumed, updates order to refunded, and restores inventory/credit.
    """
    monkeypatch.setenv("ADMIN_API_KEY", "secret-test-key")
    headers = {"X-Admin-API-Key": "secret-test-key"}
    
    # 1. Invoke the graph to request cancellation (ORD100 is within 7 days -> full refund)
    state_input = {
        "messages": [HumanMessage(content="Cancel my order ORD100")],
        "customer_id": "C001",
        "cart_id": "cart_C001",
        "current_order_id": "ORD100",
        "active_node": "cancellation",
        "intent": "cancellation"
    }
    
    config = {"configurable": {"thread_id": "thread_alice_123"}}
    
    # The graph invocation will run and pause at the "approval" node
    graph.invoke(state_input, config)
    state = graph.get_state(config)
    assert "approval" in state.next
        
    # Check that a pending refund request is in the DB
    pending = adapter.get_pending_refund_requests()
    assert len(pending) == 1
    req_id = pending[0]["id"]
    assert pending[0]["order_id"] == "ORD100"
    
    # Assert DB/order state is STILL untouched before approval
    assert adapter.get_order("ORD100")["status"] == "paid"
    assert adapter.inventory["P001"]["9"] == 10
    
    # 2. Approve via POST API
    res = client.post(f"/api/refunds/{req_id}/approve", headers=headers)
    assert res.status_code == 200
    
    # 3. Assert DB/order state is now successfully updated after approval
    order = adapter.get_order("ORD100")
    assert order["status"] == "refunded"
    # Inventory restored (10 original + 1 cancelled = 11)
    assert adapter.inventory["P001"]["9"] == 11
    
    # Check that the request status is approved
    req_after = adapter.get_refund_request(req_id)
    assert req_after["status"] == "approved"
    
    # Get graph messages history
    history = graph.get_state(config).values["messages"]
    last_msg = history[-1]
    assert "approved" in last_msg.content.lower()

def test_admin_denial_leaves_db_untouched_and_resumes_graph(monkeypatch):
    """
    Test the denial flow:
    - Customer requests cancellation, graph pauses.
    - Admin denies the request via the POST deny API endpoint (with auth).
    - Graph is resumed, updates request to denied, and records notes without modifying order state.
    """
    monkeypatch.setenv("ADMIN_API_KEY", "secret-test-key")
    headers = {"X-Admin-API-Key": "secret-test-key"}
    
    state_input = {
        "messages": [HumanMessage(content="Cancel my order ORD200")],
        "customer_id": "C001",
        "cart_id": "cart_C001",
        "current_order_id": "ORD200",
        "active_node": "cancellation",
        "intent": "cancellation"
    }
    config = {"configurable": {"thread_id": "thread_bob_456"}}
    
    # The graph invocation will run and pause at the "approval" node
    graph.invoke(state_input, config)
    state = graph.get_state(config)
    assert "approval" in state.next
        
    pending = adapter.get_pending_refund_requests()
    assert len(pending) == 1
    req_id = pending[0]["id"]
    
    # Deny via POST API
    res = client.post(f"/api/refunds/{req_id}/deny?review_notes=outside cancellation window", headers=headers)
    assert res.status_code == 200
    
    # Verify DB state is untouched (status remains paid, inventory remains 10)
    order = adapter.get_order("ORD200")
    assert order["status"] == "paid"
    assert adapter.inventory["P001"]["9"] == 10
    
    # Verify request status is denied
    req_after = adapter.get_refund_request(req_id)
    assert req_after["status"] == "denied"
    assert req_after["review_notes"] == "outside cancellation window"
    
    # Verify graph message history shows denial
    history = graph.get_state(config).values["messages"]
    last_msg = history[-1]
    assert "denied" in last_msg.content.lower()
    assert "outside cancellation window" in last_msg.content.lower()

def test_app_fails_startup_without_admin_api_key(monkeypatch):
    """
    Test that when ADMIN_API_KEY is unset in the environment, the FastAPI app
    refuses to start (startup handler raises RuntimeError) and the dependency
    correctly rejects requests.
    """
    # Temporarily unset the ADMIN_API_KEY environment variable
    monkeypatch.delenv("ADMIN_API_KEY", raising=False)
    
    # We invoke the verification dependency directly to assert it rejects requests when expected_key is empty
    with pytest.raises(Exception) as excinfo:
        from main import verify_admin_key
        import asyncio
        asyncio.run(verify_admin_key(x_admin_api_key="some-key"))
        
    from fastapi import HTTPException
    assert isinstance(excinfo.value, HTTPException)
    assert excinfo.value.status_code == 401
    
    # Also verify that calling startup_event raises RuntimeError
    from main import startup_event
    with pytest.raises(RuntimeError) as run_exc:
        import asyncio
        asyncio.run(startup_event())
    assert "ADMIN_API_KEY environment variable is unset" in str(run_exc.value)
