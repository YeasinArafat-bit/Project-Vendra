import pytest
import os
from fastapi.testclient import TestClient
from main import app
from agent.tools import adapter

client = TestClient(app)

@pytest.fixture(autouse=True)
def setup_test_db():
    # Force SQLite test DB
    os.environ["DATABASE_URL"] = "sqlite:///data/test_vendra.db"
    adapter.reset_state()
    
    # Seed mock customers
    adapter.customers = [
        {"id": "C_TEST_001", "name": "Alice", "email": "alice@test.com", "phone": "123", "address": "St", "store_credit": 0.0},
        {"id": "C_TEST_002", "name": "Bob", "email": "bob@test.com", "phone": "123", "address": "St", "store_credit": 0.0}
    ]
    
    # Seed mock products
    adapter.products = [
        {"id": "P001", "name": "Test Shoe", "price": 1000.0, "description": "Desc", "image_url": "/static/images/test.png", "tags": ["test"]}
    ]
    
    # Seed mock inventory
    adapter.inventory = {
        "P001": {"8": 5, "9": 10}
    }
    
    # Seed mock orders
    adapter.orders = {
        "ORD_ALICE_001": {
            "id": "ORD_ALICE_001",
            "customer_id": "C_TEST_001",
            "items": [{"product_id": "P001", "name": "Test Shoe", "size": "9", "quantity": 1, "price": 1000.0, "subtotal": 1000.0}],
            "total": 1000.0,
            "status": "paid",
            "stripe_payment_intent_id": "pi_mock",
            "stripe_event_id": "evt_mock",
            "created_at": "2026-08-06T18:00:00"
        },
        "ORD_BOB_001": {
            "id": "ORD_BOB_001",
            "customer_id": "C_TEST_002",
            "items": [{"product_id": "P001", "name": "Test Shoe", "size": "9", "quantity": 1, "price": 1000.0, "subtotal": 1000.0}],
            "total": 1000.0,
            "status": "pending_payment",
            "stripe_payment_intent_id": None,
            "stripe_event_id": None,
            "created_at": "2026-08-06T18:05:00"
        }
    }
    
    # Seed tracking info
    adapter.tracking = {
        "ORD_ALICE_001": {
            "courier": "Pathao",
            "tracking_code": "PTH-ALICE-123",
            "status": "in_transit",
            "estimated_delivery": "2026-08-08",
            "timeline": [
                {"time": "2026-08-06T18:00:00", "event": "Order placed", "location": "Dhaka Hub"},
                {"time": "2026-08-06T18:10:00", "event": "Picked up by Pathao", "location": "Dhaka Hub"}
            ]
        }
    }
    
    yield
    
    adapter.reset_state()
    if os.path.exists("data/test_vendra.db"):
        try:
            os.remove("data/test_vendra.db")
        except Exception:
            pass

def get_auth_headers(customer_id: str) -> dict:
    # We generate a valid JWT token for the customer
    from agent.auth_utils import create_jwt_token
    token = create_jwt_token(customer_id)
    return {"Authorization": f"Bearer {token}"}

def test_get_tracking_success():
    """Verify that an authorized customer can view their order's tracking details."""
    headers = get_auth_headers("C_TEST_001")
    response = client.get("/api/orders/ORD_ALICE_001/tracking", headers=headers)
    assert response.status_code == 200
    data = response.json()
    assert data["order_id"] == "ORD_ALICE_001"
    assert data["courier"] == "Pathao"
    assert data["tracking_code"] == "PTH-ALICE-123"
    assert len(data["timeline"]) == 2
    assert data["timeline"][1]["event"] == "Picked up by Pathao"

def test_get_tracking_fallback():
    """Verify that if an order has no tracking DB record, it returns a sensible fallback."""
    headers = get_auth_headers("C_TEST_002")
    response = client.get("/api/orders/ORD_BOB_001/tracking", headers=headers)
    assert response.status_code == 200
    data = response.json()
    assert data["order_id"] == "ORD_BOB_001"
    assert data["courier"] == "Pending"
    assert data["tracking_code"] == "Pending"
    assert len(data["timeline"]) == 1
    assert "placed" in data["timeline"][0]["event"]

def test_get_tracking_forbidden():
    """Verify that a customer cannot view tracking info for another customer's order."""
    headers = get_auth_headers("C_TEST_002")  # Bob trying to view Alice's order
    response = client.get("/api/orders/ORD_ALICE_001/tracking", headers=headers)
    assert response.status_code == 403

def test_get_tracking_not_found():
    """Verify that requesting tracking for a non-existent order returns 404."""
    headers = get_auth_headers("C_TEST_001")
    response = client.get("/api/orders/ORD_NONEXISTENT/tracking", headers=headers)
    assert response.status_code == 404
