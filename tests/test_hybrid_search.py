import os
import sys
import pytest

# Inject project root path to allow absolute imports
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from agent.search_service import search_products_text, search_products_image
from agent.tools import search_products, search_products_by_image, adapter

@pytest.fixture(autouse=True)
def setup_db():
    # Reset states to disk defaults first
    adapter.reset_state()
    
    # Seed mock products
    adapter.products = [
        {
            "id": "P001",
            "name": "Classic Oxford Shoe",
            "description": "Premium leather dress shoe",
            "category": "formal",
            "occasion_tags": ["formal"],
            "mood_tags": ["elegant"],
            "price": 100.00,
            "currency": "BDT",
            "image_url": ""
        },
        {
            "id": "P_SALE",
            "name": "Final Sale Boot",
            "description": "Clearance final sale shoe.",
            "category": "sale",
            "occasion_tags": ["sport"],
            "mood_tags": ["rugged"],
            "price": 50.00,
            "currency": "BDT",
            "image_url": ""
        }
    ]
    
    # Seed mock inventory
    adapter.inventory = {
        "P001": {
            "9": 0,  # Out of stock in size 9
            "10": 5  # In stock in size 10
        },
        "P_SALE": {
            "9": 2   # In stock in size 9
        }
    }
    
    yield

def test_metadata_filtering_category():
    # Only "sale" category should be returned
    results = search_products_text("shoe", category="sale")
    assert len(results) == 1
    assert results[0]["product_id"] == "P_SALE"

def test_metadata_filtering_price():
    # Oxford price is 100, Sale boot price is 50.
    # Searching with max_price=75 should only return the boot.
    results = search_products_text("shoe", max_price=75.0)
    assert len(results) == 1
    assert results[0]["product_id"] == "P_SALE"

def test_exact_sku_matching():
    # Searching for "P_SALE" should match the boot via sparse token lookup
    results = search_products_text("P_SALE")
    assert len(results) > 0
    assert results[0]["product_id"] == "P_SALE"

def test_size_stock_filtering_in_tool():
    # Size 9 is out of stock for P001, but in stock for P_SALE.
    # Searching with size="9" should only show P_SALE.
    output = search_products.invoke({"query": "shoe", "size": "9"})
    assert "Final Sale Boot" in output
    assert "Classic Oxford Shoe" not in output

    # Size 10 is in stock for P001.
    output_10 = search_products.invoke({"query": "shoe", "size": "10"})
    assert "Classic Oxford Shoe" in output_10

def test_visual_search_with_metadata_filter():
    from PIL import Image
    import io
    
    img = Image.new('RGB', (10, 10), color='blue')
    img_byte_arr = io.BytesIO()
    img.save(img_byte_arr, format='PNG')
    mock_image_bytes = img_byte_arr.getvalue()
    
    # 1. Filter by category
    output = search_products_by_image.invoke({
        "image_bytes": mock_image_bytes, 
        "category": "sale"
    })
    assert "Final Sale Boot" in output
    assert "Classic Oxford Shoe" not in output
    
    # 2. Filter by max_price
    output = search_products_by_image.invoke({
        "image_bytes": mock_image_bytes, 
        "max_price": 75.0
    })
    assert "Final Sale Boot" in output
    assert "Classic Oxford Shoe" not in output
    
    # 3. Filter by size
    output = search_products_by_image.invoke({
        "image_bytes": mock_image_bytes, 
        "size": "9"
    })
    assert "Final Sale Boot" in output
    assert "Classic Oxford Shoe" not in output

def test_corrective_rag_policy_retrieval():
    from agent.tools import retrieve_policy_text
    output = retrieve_policy_text.invoke({"query": "What is the return window?"})
    assert "Relevant Policy Clauses" in output

def test_router_intent_retention():
    from agent.graph import router_node
    from langchain_core.messages import HumanMessage, AIMessage
    
    state = {
        "messages": [
            HumanMessage(content="where is my parcel"),
            AIMessage(content="Please provide your order ID so I can help you track it."),
            HumanMessage(content="ORD002")
        ],
        "active_node": "tracking"
    }
    
    result = router_node(state)
    assert result["intent"] == "tracking"
    assert result["active_node"] == "tracking"

def test_tracking_code_lookup():
    from agent.tools import track_order
    
    adapter.orders["ORD002"] = {
        "id": "ORD002",
        "customer_id": "C001",
        "items": [],
        "total": 2800.0,
        "status": "paid",
        "stripe_payment_intent_id": "pi_mock_222",
        "created_at": "2026-06-19T15:00:00Z"
    }
    adapter.tracking["ORD002"] = {
        "order_id": "ORD002",
        "courier": "Steadfast",
        "tracking_code": "SF-9982718",
        "status": "in_transit",
        "estimated_delivery": "2026-06-23T18:00:00Z",
        "timeline": []
    }
    
    # 1. Test lookup with order ID containing spaces: "ORD 002"
    res1 = track_order.invoke({"order_id": "ORD 002", "customer_id": "C001"})
    assert "Order Tracking Details" in res1
    assert "Steadfast" in res1
    
    # 2. Test lookup with visual tracking code: "SF-9982718"
    res2 = track_order.invoke({"order_id": "SF-9982718", "customer_id": "C001"})
    assert "Order Tracking Details" in res2
    assert "Steadfast" in res2
    
    # 3. Test lookup with visual tracking code with spaces/different casing: "sf 9982718"
    res3 = track_order.invoke({"order_id": "sf 9982718", "customer_id": "C001"})
    assert "Order Tracking Details" in res3
    assert "Steadfast" in res3
