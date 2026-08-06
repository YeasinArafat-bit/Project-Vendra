import os
import sys
import pytest
from unittest.mock import MagicMock
from fastapi.testclient import TestClient

# Inject project root path to allow absolute imports
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from agent.tools import (
    CARTS,
    get_cached_catalog_value,
    set_cached_catalog_value,
    invalidate_catalog_cache,
    RedisCartProxy
)
from main import app

client = TestClient(app)

def test_redis_cart_fallback_when_unset(monkeypatch):
    """
    Test that RedisCartProxy falls back gracefully to in-memory dictionary
    when REDIS_URL is unset or connection fails.
    """
    # Create proxy instance without REDIS_URL
    proxy = RedisCartProxy()
    assert proxy.redis_client is None
    
    # Verify we can set and get items normally in memory mode
    proxy["test_cart"] = [{"product_id": "P001", "quantity": 1}]
    assert "test_cart" in proxy
    assert proxy.get("test_cart")[0]["product_id"] == "P001"
    
    # Test dictionary methods mapping
    assert list(proxy.keys()) == ["test_cart"]
    popped = proxy.pop("test_cart")
    assert popped[0]["product_id"] == "P001"
    assert "test_cart" not in proxy

def test_caching_fallback_no_op():
    """
    Test that catalog caching functions (get, set, invalidate) no-op silently
    and do not raise exceptions when Redis is offline.
    """
    # Assuming Redis is offline in testing environment, get should return None
    assert get_cached_catalog_value("some_key") is None
    
    # Set and invalidate should run without throwing errors
    try:
        set_cached_catalog_value("some_key", "some_value")
        invalidate_catalog_cache("some_product_id")
        invalidate_catalog_cache()
    except Exception as e:
        pytest.fail(f"Caching helper threw exception when Redis is unset/offline: {e}")

def test_http_chat_endpoint_success():
    """
    Test that the POST /api/chat HTTP endpoint successfully parses,
    routes, invokes the graph, and returns serialized response.
    """
    payload = {
        "message": "hi",
        "history": [],
        "customer_id": "C001",
        "current_order_id": "",
        "active_node": "general",
        "intent": "general",
        "image_bytes": None
    }
    
    # Invoke chat endpoint over HTTP using test client
    from agent.auth_utils import create_jwt_token
    token = create_jwt_token("C001")
    headers = {"Authorization": f"Bearer {token}"}
    res = client.post("/api/chat", json=payload, headers=headers)
    assert res.status_code == 200
    
    data = res.json()
    assert "messages" in data
    assert len(data["messages"]) >= 2  # The prompt user "hi" + agent reply
    assert data["messages"][0]["role"] == "user"
    assert data["messages"][-1]["role"] == "assistant"
    assert "active_node" in data
    assert "intent" in data

def test_http_chat_endpoint_with_history():
    """
    Test that the POST /api/chat HTTP endpoint successfully parses
    and reconstructs history and current message, returning a valid response.
    """
    payload = {
        "message": "can you tell me about sneakers?",
        "history": [
            {"role": "user", "content": "hi"},
            {"role": "assistant", "content": "Hello! I am Vendra. How can I help you today?"}
        ],
        "customer_id": "C001",
        "current_order_id": "",
        "active_node": "general",
        "intent": "general",
        "image_bytes": None
    }
    from agent.auth_utils import create_jwt_token
    token = create_jwt_token("C001")
    headers = {"Authorization": f"Bearer {token}"}
    res = client.post("/api/chat", json=payload, headers=headers)
    assert res.status_code == 200
    data = res.json()
    assert "messages" in data
    assert len(data["messages"]) >= 4
    assert data["messages"][0]["role"] == "user"
    assert data["messages"][1]["role"] == "assistant"
    assert data["messages"][2]["role"] == "user"
    assert data["messages"][-1]["role"] == "assistant"

def test_sqlite_worker_warning(caplog):
    """
    Test that main.py startup log contains a safety warning about SQLite file locking
    concurrency issues when running on the SQLite fallback database.
    """
    import logging
    # Ensure logs are captured at warning level
    with caplog.at_level(logging.WARNING):
        from main import startup_event
        import asyncio
        asyncio.run(startup_event())
        
    warnings = [rec.message for rec in caplog.records if "sqlite" in rec.message.lower()]
    assert len(warnings) > 0
    assert "UNSAFE" in warnings[0]

def test_app_fully_decoupled():
    """
    Asserts that app.py does not contain any direct backend imports (from agent or adapters packages).
    """
    app_path = os.path.abspath(os.path.join(os.path.dirname(__file__), "../app.py"))
    with open(app_path, "r", encoding="utf-8") as f:
        content = f.read()
        
    assert "from agent" not in content
    assert "import agent" not in content
    assert "from adapters" not in content
    assert "import adapters" not in content

def test_http_health_endpoint():
    """
    Test that the GET /health HTTP endpoint returns a 200 OK status
    and checks database and Redis connectivity.
    """
    res = client.get("/health")
    assert res.status_code == 200
    data = res.json()
    assert "status" in data
    assert "database" in data
    assert "redis" in data

def test_http_metrics_endpoint():
    """
    Test that the GET /metrics HTTP endpoint returns a 200 OK status
    and contains Prometheus-formatted metric output.
    """
    res = client.get("/metrics")
    assert res.status_code == 200
    text = res.text
    assert "# HELP vendra_subagent_requests_total" in text
    assert "vendra_refund_request_queue_depth" in text

def test_list_customers_is_removed():
    """
    Asserts that the /api/customers endpoint has been fully removed (returns 404).
    """
    res = client.get("/api/customers")
    assert res.status_code == 404

def test_get_customer_does_not_leak_password_hash():
    """
    Asserts that GET /api/customers/{customer_id} does not leak the password_hash.
    """
    from agent.auth_utils import create_jwt_token
    token = create_jwt_token("C001")
    headers = {"Authorization": f"Bearer {token}"}
    
    # 1. Access as owner C001
    res = client.get("/api/customers/C001", headers=headers)
    assert res.status_code == 200
    data = res.json()
    assert "password_hash" not in data
    assert data["id"] == "C001"
    
    # 2. Accessing other customer is forbidden
    res_forbidden = client.get("/api/customers/C002", headers=headers)
    assert res_forbidden.status_code == 403
