import os
import re
import sys
import pytest
import json
import time
from unittest.mock import MagicMock, patch

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from langchain_core.messages import HumanMessage, AIMessage, ToolMessage

class TestRegressionRound4:
    @patch("agent.graph.safe_llm_invoke")
    def test_tracking_eagerness_hallucination_injection(self, mock_llm_invoke):
        # Setup: safe_llm_invoke returns an AIMessage with no tool_calls, but we asked for ORD002
        mock_llm_invoke.return_value = AIMessage(content="Here are details for ORD002...")
        
        state = {
            "messages": [HumanMessage(content="what's the status of my order ORD002?")],
            "customer_id": "C001",
            "cart_id": "cart_C001",
            "current_order_id": "",
            "active_node": "tracking",
            "intent": "tracking"
        }
        
        from agent.graph import tracking_agent_node
        res = tracking_agent_node(state)
        
        # Verify that we manually injected the tool calls
        ai_msg = res["messages"][0]
        assert hasattr(ai_msg, "tool_calls")
        assert len(ai_msg.tool_calls) == 2
        tool_names = [tc["name"] for tc in ai_msg.tool_calls]
        assert "get_order_status" in tool_names
        assert "track_order" in tool_names
        assert ai_msg.content == ""

    @patch("agent.graph.safe_llm_invoke")
    def test_tracking_tool_failed_hallucination_blocking(self, mock_llm_invoke):
        # Setup: Tools were run but returned an error. LLM still tried to output order details/courier template.
        mock_llm_invoke.return_value = AIMessage(content="Order Details:\nDate: 2026-07-01\nStatus: IN_TRANSIT\nCourier: DHL")
        
        state = {
            "messages": [
                HumanMessage(content="what's the status of my order ORD002?"),
                AIMessage(content="", tool_calls=[{"name": "track_order", "id": "t1", "args": {"order_id": "ORD002", "customer_id": "C001"}}]),
                ToolMessage(content="Error: Order #ORD002 not found.", name="track_order", tool_call_id="t1")
            ],
            "customer_id": "C001",
            "cart_id": "cart_C001",
            "current_order_id": "",
            "active_node": "tracking",
            "intent": "tracking"
        }
        
        from agent.graph import tracking_agent_node
        res = tracking_agent_node(state)
        
        # Verify that the response content was overridden with the clean tool error
        ai_msg = res["messages"][0]
        assert "Error:" in ai_msg.content or "not found" in ai_msg.content.lower()
        assert "Courier:" not in ai_msg.content

    @patch("agent.graph.safe_llm_invoke")
    def test_cancellation_tool_injection_and_syntax_cleaning(self, mock_llm_invoke):
        # Setup: User requested cancellation, LLM tried to hallucinate/output text instead of calling check_cancellation_eligibility
        mock_llm_invoke.return_value = AIMessage(content="Let me help you cancel. <function=track_order>...</function>")
        
        state = {
            "messages": [HumanMessage(content="I'd like to cancel ORD002 and get a refund")],
            "customer_id": "C001",
            "cart_id": "cart_C001",
            "current_order_id": "",
            "active_node": "cancellation",
            "intent": "cancellation"
        }
        
        from agent.graph import cancellation_agent_node
        res = cancellation_agent_node(state)
        
        # Verify that check_cancellation_eligibility tool call was injected and content was cleared
        ai_msg = res["messages"][0]
        assert len(ai_msg.tool_calls) == 1
        assert ai_msg.tool_calls[0]["name"] == "check_cancellation_eligibility"
        assert ai_msg.content == ""

    @patch("agent.graph.safe_llm_invoke")
    def test_cart_view_loop_prevention(self, mock_llm_invoke):
        # Setup: User asked to view cart, LLM generated a text response without calling view_cart
        mock_llm_invoke.return_value = AIMessage(content="Would you like to proceed with checkout or make changes?")
        
        state = {
            "messages": [HumanMessage(content="what's in my cart right now?")],
            "customer_id": "C001",
            "cart_id": "cart_C001",
            "current_order_id": "",
            "active_node": "cart",
            "intent": "cart"
        }
        
        from agent.graph import checkout_agent_node
        res = checkout_agent_node(state)
        
        # Verify that view_cart tool call was injected and content was cleared
        ai_msg = res["messages"][0]
        assert len(ai_msg.tool_calls) == 1
        assert ai_msg.tool_calls[0]["name"] == "view_cart"
        assert ai_msg.content == ""

    @patch("agent.graph.safe_llm_invoke")
    def test_fault_isolation_chitchat_fallback(self, mock_llm_invoke):
        # Setup: User said "thank you", LLM response contains a fake product card (hallucinated)
        mock_llm_invoke.return_value = AIMessage(content="You're welcome! Buy this: (ID: P001) Price: 4,500 BDT")
        
        state = {
            "messages": [HumanMessage(content="thank you")],
            "customer_id": "C001",
            "cart_id": "cart_C001",
            "current_order_id": "",
            "active_node": "general",
            "intent": "general"
        }
        
        from agent.graph import general_agent_node
        res = general_agent_node(state)
        
        # Verify that the response is a friendly chitchat fallback instead of database/policy error message
        ai_msg = res["messages"][0]
        assert "welcome" in ai_msg.content.lower() or "help you" in ai_msg.content.lower()
        assert "retrieving" not in ai_msg.content.lower()

    def test_router_topic_switching_to_policy(self):
        # Setup: user has active_node="checkout", but asks a policy question
        state = {
            "messages": [HumanMessage(content="আমার আরেকটা প্রশ্ন আছে — return policy কি?")],
            "customer_id": "C001",
            "cart_id": "cart_C001",
            "current_order_id": "",
            "active_node": "checkout",
            "intent": "checkout"
        }
        
        from agent.graph import router_node
        res = router_node(state)
        
        # Verify that the router successfully routed to the general policy node
        assert res["intent"] == "general"
        assert res["active_node"] == "general"

