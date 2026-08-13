import os
import re
import sys
import pytest
import json
from unittest.mock import patch, MagicMock

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from langchain_core.messages import HumanMessage, AIMessage, ToolMessage
from agent.graph import (
    validate_order_status_response,
    validate_policy_response,
    render_cart_template,
    render_order_status_template,
    checkout_agent_node,
    tracking_agent_node,
    cancellation_agent_node
)
from agent.tools import adapter

class TestRegressionRound5:
    @pytest.fixture(autouse=True)
    def setup_mocks(self):
        adapter.reset_state()
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
        adapter.products = [
            {
                "id": "P001",
                "name": "Classic Leather Oxford",
                "description": "Premium leather shoes",
                "category": "shoes",
                "price": 4500.0,
                "currency": "BDT",
                "image_url": "https://vendra.com/oxford.jpg"
            },
            {
                "id": "P002",
                "name": "Midnight Velvet Derby",
                "description": "Elegant velvet shoes",
                "category": "shoes",
                "price": 5500.0,
                "currency": "BDT",
                "image_url": "https://vendra.com/derby.jpg"
            }
        ]
        adapter.inventory = {
            "P001": {"10": 5},
            "P002": {"10": 5}
        }
        adapter.orders = {
            "ORD002": {
                "id": "ORD002",
                "customer_id": "C001",
                "items": [
                    {"product_id": "P001", "size": "10", "quantity": 1, "price": 4500.0}
                ],
                "total": 4500.0,
                "status": "paid",
                "created_at": "2026-07-01T15:00:00Z"
            }
        }
        adapter.tracking = {
            "ORD002": {
                "order_id": "ORD002",
                "courier": "Steadfast",
                "tracking_code": "SF-9982718",
                "status": "in_transit",
                "estimated_delivery": "2026-07-04T18:00:00Z",
                "timeline": [
                    {"time": "2026-07-01T15:00:00Z", "event": "Order placed and payment confirmed"}
                ]
            }
        }

    def test_validate_order_status_response_detects_mismatch(self):
        # Valid response: mentions P001 and correct price
        valid_resp = "Order status for ORD002: product P001, total is 4500 BDT."
        assert validate_order_status_response(valid_resp, "ORD002", "C001") is True

        # Hallucinated product ID: mentions PRD001
        invalid_resp_1 = "Order status for ORD002: product PRD001, total is 4500 BDT."
        assert validate_order_status_response(invalid_resp_1, "ORD002", "C001") is False

        # Hallucinated price: mentions 12999.98 BDT
        invalid_resp_2 = "Order status for ORD002: product P001, total is 12999.98 BDT."
        assert validate_order_status_response(invalid_resp_2, "ORD002", "C001") is False

        # Hallucinated image URL: contains example.com
        invalid_resp_3 = "Order status for ORD002: product P001, image is https://example.com/image.jpg."
        assert validate_order_status_response(invalid_resp_3, "ORD002", "C001") is False

    def test_validate_policy_response_detects_restocking_fee(self):
        policy_text = "Customers can cancel and receive a full refund for any order within 7 days."
        
        # Valid response
        valid_resp = "Under Vendra policy, you can cancel within 7 days for a refund."
        assert validate_policy_response(valid_resp, policy_text) is True

        # Fabricated restocking fee
        invalid_resp = "We can cancel but a 10% restocking fee applies."
        assert validate_policy_response(invalid_resp, policy_text) is False

    def test_cart_view_node_bypasses_llm_and_renders_template(self):
        # Setup: Last message is view_cart ToolMessage
        from agent.tools import CARTS
        CARTS["cart_C001"] = [
            {"product_id": "P001", "size": "10", "quantity": 1}
        ]

        state = {
            "messages": [
                HumanMessage(content="what's in my cart right now?"),
                AIMessage(content="", tool_calls=[{"name": "view_cart", "id": "t1", "args": {"cart_id": "cart_C001", "customer_id": "C001"}}]),
                ToolMessage(content="Shopping Cart (ID: cart_C001): 1. Classic Leather Oxford (ID: P001) - Size 10 x1", name="view_cart", tool_call_id="t1")
            ],
            "customer_id": "C001",
            "cart_id": "cart_C001"
        }

        res = checkout_agent_node(state)
        ai_msg = res["messages"][0]
        # Should render deterministic template directly, bypassing LLM
        assert "**Shopping Cart Details**" in ai_msg.content
        assert "Classic Leather Oxford" in ai_msg.content
        assert "P001" in ai_msg.content
        assert "Cart Total:** 4500.00 BDT" in ai_msg.content

    def test_order_status_fails_validation_falls_back_to_template(self):
        # Setup: Tool has run, but LLM safe_llm_invoke is mocked to return a hallucinated response
        with patch("agent.graph.safe_llm_invoke") as mock_llm:
            mock_llm.return_value = AIMessage(
                content="**Order Details**\n- Status: IN_TRANSIT\n- Items:\n  - Product Name: Vendra's Premium Hoodie (ID: PRD002)\n    Price: 2999.99 BDT\n    Image: https://example.com/product-image.jpg\n- Total: 12999.98 BDT"
            )

            state = {
                "messages": [
                    HumanMessage(content="what's the status of my order ORD002?"),
                    AIMessage(content="", tool_calls=[
                        {"name": "get_order_status", "id": "t1", "args": {"order_id": "ORD002", "customer_id": "C001"}},
                        {"name": "track_order", "id": "t2", "args": {"order_id": "ORD002", "customer_id": "C001"}}
                    ]),
                    # Tool messages are parsed
                    ToolMessage(content="Order Details (ID: ORD002, Customer ID: C001):\nDate: 2026-07-01T15:00:00Z\nStatus: PAID\nItems: [1x product P001 (size 10)]\nTotal: 4500.00 BDT", name="get_order_status", tool_call_id="t1"),
                    ToolMessage(content="Order Tracking Details (ID: ORD002, Customer ID: C001):\nCourier: Steadfast\nTracking Code: SF-9982718\nStatus: IN_TRANSIT\nEstimated Delivery: 2026-07-04T18:00:00Z", name="track_order", tool_call_id="t2")
                ],
                "customer_id": "C001",
                "cart_id": "cart_C001"
            }

            # Run tracking agent node
            res = tracking_agent_node(state)
            ai_msg = res["messages"][0]
            # Mismatch in product ID (PRD002) and price (12999.98) should trigger validation failure and render the deterministic template!
            assert "**Order Details**" in ai_msg.content
            assert "PAID" in ai_msg.content
            # Genuine product P001 and correct total should be there
            assert "4500.00 BDT" in ai_msg.content
            assert "P001" in ai_msg.content
            assert "PRD002" not in ai_msg.content
            assert "Hoodie" not in ai_msg.content
            assert "12999.98" not in ai_msg.content
