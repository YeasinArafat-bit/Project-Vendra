import os
import sys
import json
import pytest
import datetime
from unittest.mock import MagicMock

# Inject project root path to allow absolute imports
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from langchain_core.messages import HumanMessage, AIMessage
from agent.graph import graph
from agent.tools import (
    adapter,
    search_products,
    create_payment_link,
    stripe_breaker
)

@pytest.fixture(autouse=True)
def setup_db():
    adapter.reset_state()
    
    # Seed mock customers
    adapter.customers = [
        {"id": "C001", "name": "Alice Test", "email": "alice@test.com", "phone": "123", "address": "Alice St"},
        {"id": "C002", "name": "Bob Test", "email": "bob@test.com", "phone": "456", "address": "Bob St"}
    ]
    
    # Seed mock products
    adapter.products = [
        {
            "id": "P001",
            "name": "Test Shoe",
            "description": "Test",
            "category": "casual",
            "occasion_tags": ["casual"],
            "mood_tags": ["comfortable"],
            "price": 100.00,
            "currency": "BDT",
            "image_url": ""
        }
    ]
    
    # Seed mock inventory
    adapter.inventory = {
        "P001": {
            "9": 10
        }
    }
    
    adapter.orders = {}
    adapter.tracking = {}
    yield

def test_catalog_failure_fault_isolation(monkeypatch):
    """
    Test that when a sub-agent (Catalog) encounters an exception, it is caught gracefully,
    a fallback message is returned, and a subsequent request to a healthy sub-agent works.
    """
    # 1. Mock safe_llm_invoke to raise an exception only for the Catalog sub-agent
    from agent.graph import safe_llm_invoke
    original_invoke = safe_llm_invoke
    
    def mock_safe_llm_invoke(messages, tools=None, temperature=0):
        if tools and any(getattr(t, "name", None) == "search_products" for t in tools):
            raise RuntimeError("Simulated unhandled model exception in Catalog Subgraph")
        return original_invoke(messages, tools=tools, temperature=temperature)
        
    monkeypatch.setattr("agent.graph.safe_llm_invoke", mock_safe_llm_invoke)
    
    # 2. Invoke the master graph with a browsing query
    state_input = {
        "messages": [HumanMessage(content="Show me some casual shoes")],
        "customer_id": "C001",
        "cart_id": "cart_C001",
        "current_order_id": "",
        "selected_product_id": "",
        "selected_size": "",
        "active_node": "general",
        "intent": "browsing"
    }
    
    config = {"configurable": {"thread_id": "test_thread_c001"}}
    output = graph.invoke(state_input, config)
    
    # 3. Verify fallback message was returned and graph did not crash
    last_msg = output["messages"][-1]
    assert isinstance(last_msg, AIMessage)
    assert "trouble browsing" in last_msg.content or "offline" in last_msg.content or "⚠️" in last_msg.content
    
    # 4. Verify we can still perform another action (like checking general policies) in the same session
    state_input_2 = {
        "messages": list(output["messages"]) + [HumanMessage(content="What is your return policy?")],
        "customer_id": "C001",
        "cart_id": "cart_C001",
        "current_order_id": "",
        "selected_product_id": "",
        "selected_size": "",
        "active_node": "general",
        "intent": "general"
    }
    
    config = {"configurable": {"thread_id": "test_thread_c001"}}
    output_2 = graph.invoke(state_input_2, config)
    last_msg_2 = output_2["messages"][-1]
    assert isinstance(last_msg_2, AIMessage)
    assert "cancellation" in last_msg_2.content.lower() or "policy" in last_msg_2.content.lower()

def test_stripe_circuit_breaker_tripping(monkeypatch):
    """
    Test that if Stripe API throws consecutive errors, the circuit breaker opens
    and subsequent calls fail fast without even invoking Stripe.
    """
    # Force STRIPE_SECRET_KEY to trigger the real Stripe flow
    monkeypatch.setenv("STRIPE_SECRET_KEY", "sk_test_real_key_simulated")
    
    # Mock Stripe Session creation to raise an APIConnectionError
    import stripe
    def mock_stripe_create(*args, **kwargs):
        raise stripe.error.APIConnectionError("Stripe connection timed out")
        
    monkeypatch.setattr(stripe.checkout.Session, "create", mock_stripe_create)
    
    # Setup cart and order
    from agent.tools import CARTS
    CARTS["cart_C001"] = [{"product_id": "P001", "size": "9", "quantity": 1}]
    
    adapter.orders["ORD999"] = {
        "id": "ORD999",
        "customer_id": "C001",
        "items": [{"product_id": "P001", "size": "9", "quantity": 1, "price": 100.0}],
        "total": 100.0,
        "status": "pending_payment",
        "created_at": datetime.datetime.now(datetime.timezone.utc).isoformat()
    }
    
    # Reset Stripe circuit breaker
    stripe_breaker.close()
    
    # Call create_payment_link multiple times to trip the circuit breaker (fail_max = 3)
    results = []
    for _ in range(4):
        res = create_payment_link.invoke({"order_id": "ORD999", "customer_id": "C001"})
        results.append(res)
        
    # Check that at least the last call returned the circuit breaker error
    assert any("gateway is temporarily offline" in r for r in results)
    assert stripe_breaker.current_state == "open"
    
    # Close it back for other tests
    stripe_breaker.close()

def test_create_order_insufficient_stock_fails_fast():
    """
    Test that calling create_order with insufficient stock fails fast (under 0.5 seconds)
    without triggering the tenacity retry mechanism.
    """
    from agent.tools import create_order, CARTS
    import time
    
    # 1. Setup inventory variant with 1 stock left
    adapter.inventory = {
        "P001": {
            "9": 1
        }
    }
    
    # 2. Setup cart requesting 10 items (more than available)
    CARTS["cart_C001"] = [{"product_id": "P001", "size": "9", "quantity": 10}]
    
    # 3. Call create_order and measure time taken
    start_time = time.time()
    res = create_order.invoke({"customer_id": "C001", "cart_id": "cart_C001"})
    elapsed = time.time() - start_time
    
    # 4. Assert it failed fast (under 0.5s) and returned "insufficient stock"
    assert elapsed < 0.5
    assert "checkout failed" in res.lower()
    assert "insufficient stock" in res.lower()

def test_order_routing_and_tool_hallucination(monkeypatch):
    """
    Verify that:
    1. 'show my orders' and phrasing variants route to tracking intent.
    2. A simulated tool hallucination (400 error) in catalog node triggers re-routing.
    """
    from agent.graph import router_node, ToolHallucinationError
    
    # 1. Test routing of "show my orders" and phrasing variants
    phrases = ["show my orders", "my orders", "order history", "show orders", "list orders"]
    for phrase in phrases:
        state_input = {
            "messages": [HumanMessage(content=phrase)],
            "customer_id": "C001",
            "cart_id": "cart_C001",
            "active_node": "general",
            "intent": "general"
        }
        res = router_node(state_input)
        assert res["intent"] == "tracking", f"Expected '{phrase}' to route to tracking, got {res['intent']}"
        assert res["active_node"] == "tracking"

    # 2. Test re-routing upon ToolHallucinationError in browse_node
    from agent.graph import catalog_graph, tracking_graph, browse_node
    
    original_catalog_invoke = catalog_graph.invoke
    original_tracking_invoke = tracking_graph.invoke
    
    def mock_catalog_invoke(*args, **kwargs):
        raise ToolHallucinationError("Simulated 400 Bad Request tool_use_failed brave_search")
        
    def mock_tracking_invoke(state, *args, **kwargs):
        # Return a mock response from tracking subgraph
        return {
            **state,
            "messages": state["messages"] + [AIMessage(content="Here are your orders: ORD123, ORD456.")]
        }
        
    monkeypatch.setattr(catalog_graph, "invoke", mock_catalog_invoke)
    monkeypatch.setattr(tracking_graph, "invoke", mock_tracking_invoke)
    
    state_input = {
        "messages": [HumanMessage(content="show my orders")],
        "customer_id": "C001",
        "cart_id": "cart_C001",
        "current_order_id": "",
        "selected_product_id": "",
        "selected_size": "",
        "active_node": "browsing",
        "intent": "browsing"
    }
    
    output = browse_node(state_input)
    
    # Verify that the output has the re-routed tracking message
    last_msg = output["messages"][-1]
    assert isinstance(last_msg, AIMessage)
    assert "Let me check your order status for you." in last_msg.content
    assert "ORD123" in last_msg.content
    assert output["active_node"] == "tracking"


def test_conversational_tracking_flow():
    """
    Test that sends "where is my order" -> "ORD002" as a two-turn conversation
    through the actual orchestrator/tracking subgraph and asserts the second
    response contains real tracking content (courier name, status, or timeline data).
    """
    import uuid
    from agent.graph import graph
    from agent.tools import adapter
    
    # Seed ORD002
    adapter.orders["ORD002"] = {
        "id": "ORD002",
        "customer_id": "C001",
        "items": [{"product_id": "P001", "size": "10", "quantity": 1, "price": 4500.0}],
        "total": 4500.0,
        "status": "paid",
        "stripe_payment_intent_id": "pi_mock_222",
        "created_at": "2026-07-01T15:00:00Z"
    }
    adapter.tracking["ORD002"] = {
        "order_id": "ORD002",
        "courier": "Steadfast",
        "tracking_code": "SF-9982718",
        "status": "in_transit",
        "estimated_delivery": "2026-07-04T18:00:00Z",
        "timeline": [
            {"time": "2026-07-01T15:00:00Z", "event": "Order placed and payment confirmed"},
            {"time": "2026-07-02T10:00:00Z", "event": "Package picked up by courier"}
        ]
    }
    
    thread_id = f"test_convo_{uuid.uuid4().hex}"
    config = {"configurable": {"thread_id": thread_id}}
    
    # Turn 1
    state1 = {
        "messages": [HumanMessage(content="where is my order")],
        "customer_id": "C001",
        "cart_id": "cart_C001"
    }
    res1 = graph.invoke(state1, config)
    last_msg1 = res1["messages"][-1]
    assert "order ID" in last_msg1.content or "Order ID" in last_msg1.content
    
    # Turn 2
    state2 = {
        "messages": res1["messages"] + [HumanMessage(content="ORD002")],
        "customer_id": "C001",
        "cart_id": "cart_C001"
    }
    res2 = graph.invoke(state2, config)
    last_msg2 = res2["messages"][-1]
    
    # Asserts that response contains courier or status or timeline data
    content = last_msg2.content
    assert "Steadfast" in content or "SF-9982718" in content or "IN_TRANSIT" in content or "Timeline" in content
    assert "PAID" in content or "P001" in content or "4500" in content


