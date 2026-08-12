"""
Unit tests for token efficiency optimizations in Vendra's checkout agent:
- Fast path: direct cart additions (product ID + size) bypass LLM.
- Narration collapse: post-tool success responses bypass LLM.
- Fallback: ambiguous requests still invoke the LLM.
"""

import os
import sys
import pytest
from unittest.mock import patch, MagicMock

# Inject project root path to allow absolute imports
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from langchain_core.messages import HumanMessage, AIMessage, ToolMessage


def _make_state(messages, cart_id="cart_C001", customer_id="C001"):
    return {
        "messages": messages,
        "cart_id": cart_id,
        "customer_id": customer_id,
        "intent": "checkout",
        "active_node": "checkout",
    }


class TestTokenEfficiency:
    @patch("agent.graph.safe_llm_invoke")
    @patch("agent.graph.add_to_cart")
    def test_fast_path_add_product_and_size_direct(self, mock_add_to_cart, mock_safe_llm):
        """1. When the user says 'add P013 in size 9', checkout_agent_node should
        bypass safe_llm_invoke entirely and call add_to_cart directly."""
        mock_add_to_cart.func.return_value = "Successfully added 1 units of 'Retro Street High-Top' (Size 9) to cart."
        
        from agent.graph import checkout_agent_node
        
        state = _make_state([HumanMessage(content="add P013 in size 9")])
        res = checkout_agent_node(state)
        
        # Verify LLM was NOT called
        mock_safe_llm.assert_not_called()
        # Verify tool was called with correct args
        mock_add_to_cart.func.assert_called_once_with(
            cart_id="cart_C001",
            product_id="P013",
            size="9",
            customer_id="C001"
        )
        
        # Verify result contains the mock LangGraph trace and confirmation message
        msgs = res.get("messages", [])
        assert len(msgs) == 3
        assert isinstance(msgs[0], AIMessage) # Mock tool call message
        assert msgs[0].tool_calls[0]["name"] == "add_to_cart"
        assert isinstance(msgs[1], ToolMessage) # Tool result message
        assert isinstance(msgs[2], AIMessage) # Final response message
        assert "Added" in msgs[2].content
        assert "P013" not in msgs[2].content # Uses product name if resolved, or fallback

    @patch("agent.graph.safe_llm_invoke")
    @patch("agent.graph.add_to_cart")
    def test_fast_path_add_with_variation_phrasing(self, mock_add_to_cart, mock_safe_llm):
        """2. When user says 'can you add P001 to cart size 7', checkout_agent_node should
        bypass safe_llm_invoke and call add_to_cart directly."""
        mock_add_to_cart.func.return_value = "Successfully added 1 units of 'Classic Leather Oxford' (Size 7) to cart."
        
        from agent.graph import checkout_agent_node
        
        state = _make_state([HumanMessage(content="can you add P001 to cart size 7")])
        res = checkout_agent_node(state)
        
        mock_safe_llm.assert_not_called()
        mock_add_to_cart.func.assert_called_once_with(
            cart_id="cart_C001",
            product_id="P001",
            size="7",
            customer_id="C001"
        )
        
        msgs = res.get("messages", [])
        assert len(msgs) == 3
        assert "Added" in msgs[2].content

    @patch("agent.graph.safe_llm_invoke")
    @patch("agent.graph.add_to_cart")
    def test_fallback_on_ambiguous_query(self, mock_add_to_cart, mock_safe_llm):
        """3. When user says 'add something comfortable', checkout_agent_node must
        fall back to safe_llm_invoke since there is no clear product ID or size."""
        mock_safe_llm.return_value = AIMessage(content="What size or shoe model would you like to add?")
        
        from agent.graph import checkout_agent_node
        
        state = _make_state([HumanMessage(content="add something comfortable")])
        res = checkout_agent_node(state)
        
        # Verify LLM WAS called
        mock_safe_llm.assert_called_once()
        mock_add_to_cart.func.assert_not_called()
        
        msgs = res.get("messages", [])
        assert len(msgs) == 1
        assert "What size" in msgs[0].content

    @patch("agent.graph.safe_llm_invoke")
    def test_narration_collapse_post_tool_call(self, mock_safe_llm):
        """4. Post-tool success message should bypass the LLM narration pass entirely."""
        from agent.graph import checkout_agent_node
        
        # ToolMessage indicating success is the last message
        tool_success_msg = ToolMessage(
            content="Successfully added 1 units of 'Classic Leather Oxford' (Size 8) to cart.",
            tool_call_id="call_123",
            name="add_to_cart"
        )
        state = _make_state([
            HumanMessage(content="add P001 size 8"),
            AIMessage(content="", tool_calls=[{"name": "add_to_cart", "args": {}, "id": "call_123"}]),
            tool_success_msg
        ])
        
        res = checkout_agent_node(state)
        
        # Verify LLM was NOT called to narrate
        mock_safe_llm.assert_not_called()
        
        msgs = res.get("messages", [])
        assert len(msgs) == 1
        assert isinstance(msgs[0], AIMessage)
        assert "Confirm: Added **Classic Leather Oxford** (Size 8) to your cart." in msgs[0].content

    @patch("agent.graph.safe_llm_invoke")
    @patch("agent.graph.add_to_cart")
    def test_fast_path_add_by_name_from_context(self, mock_add_to_cart, mock_safe_llm):
        """5. When the user has search results in context, they should be able to add by name
        without calling the LLM, and it must resolve to the correct product ID."""
        from agent.graph import checkout_agent_node
        
        # Scenario A: Add the Midnight Velvet Derby (P002)
        mock_add_to_cart.func.return_value = "Successfully added 1 units of 'Midnight Velvet Derby' (Size 10) to cart."
        history_a = [
            HumanMessage(content="show me some formal shoes for a wedding"),
            AIMessage(content="[PRODUCTS SHOWN: P001 = Classic Leather Oxford; P002 = Midnight Velvet Derby; P015 = Patent Gala Pump; P030 = Executive Derby]"),
            HumanMessage(content="add the Midnight Velvet Derby to my cart in size 10")
        ]
        state_a = _make_state(history_a)
        res_a = checkout_agent_node(state_a)
        
        # Verify LLM was NOT called
        mock_safe_llm.assert_not_called()
        # Verify tool was called with P002
        mock_add_to_cart.func.assert_called_once_with(
            cart_id="cart_C001",
            product_id="P002",
            size="10",
            customer_id="C001"
        )
        
        # Reset mocks
        mock_add_to_cart.reset_mock()
        mock_safe_llm.reset_mock()
        
        # Scenario B: Add the Executive Derby (P030)
        mock_add_to_cart.func.return_value = "Successfully added 1 units of 'Executive Derby' (Size 10) to cart."
        history_b = [
            HumanMessage(content="show me some formal shoes for a wedding"),
            AIMessage(content="[PRODUCTS SHOWN: P001 = Classic Leather Oxford; P002 = Midnight Velvet Derby; P015 = Patent Gala Pump; P030 = Executive Derby]"),
            HumanMessage(content="add the Executive Derby to my cart in size 10")
        ]
        state_b = _make_state(history_b)
        res_b = checkout_agent_node(state_b)
        
        # Verify LLM was NOT called
        mock_safe_llm.assert_not_called()
        # Verify tool was called with P030
        mock_add_to_cart.func.assert_called_once_with(
            cart_id="cart_C001",
            product_id="P030",
            size="10",
            customer_id="C001"
        )
