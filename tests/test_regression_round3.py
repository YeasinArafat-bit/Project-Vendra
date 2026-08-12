"""
Regression tests for Round 3 bugs:
  Bug 1 (SEVERE)  -- Policy questions must never return fabricated product cards
  Bug 2 (moderate) -- Malformed/nonexistent order IDs must return clean "not found"
  Bug 3 (minor)   -- Internal tool name 'retrieve_policy_text' must not appear in
                     customer-facing system prompt text

These tests are intentionally unit-level (no live LLM / no running server needed).
"""

import os
import re
import sys
import pytest
from unittest.mock import MagicMock, patch

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from langchain_core.messages import HumanMessage, AIMessage, ToolMessage


# ---------------------------------------------------------------------------
# Bug 3 -- Tool name must NOT appear in customer-facing prompt strings
# ---------------------------------------------------------------------------

class TestToolNameLeak:
    def test_retrieve_policy_text_not_in_customer_facing_sentence(self):
        """The general_agent system prompt must not expose 'retrieve_policy_text'
        in a sentence that would appear in customer-facing refusal messages."""
        from agent.graph import general_agent_node
        import inspect

        src = inspect.getsource(general_agent_node)
        customer_facing_leak = re.compile(
            r"you can use the retrieve_policy_text",
            re.IGNORECASE
        )
        assert not customer_facing_leak.search(src), (
            "Bug 3 regression: 'retrieve_policy_text' tool name is still exposed "
            "in a customer-visible sentence in general_agent_node."
        )

    def test_old_tool_name_phrase_gone(self):
        """The old phrase naming the tool directly is removed."""
        from agent.graph import general_agent_node
        import inspect

        src = inspect.getsource(general_agent_node)
        assert "retrieve_policy_text tool to search" not in src, (
            "Bug 3 regression: still referencing 'retrieve_policy_text tool to search'."
        )


# ---------------------------------------------------------------------------
# Bug 2 -- Malformed / nonexistent order ID must return a clean "not found" message
# ---------------------------------------------------------------------------

class TestMalformedOrderId:
    def _patch_adapter(self, return_value=None, side_effect=None):
        """Context manager that patches tools.adapter.track_order."""
        from agent import tools as tools_module
        original = tools_module.adapter
        mock_adapter = MagicMock()
        if side_effect is not None:
            mock_adapter.track_order.side_effect = side_effect
        else:
            mock_adapter.track_order.return_value = return_value
        tools_module.adapter = mock_adapter
        return original, tools_module

    def test_none_return_gives_not_found(self):
        from agent import tools as tools_module
        original = tools_module.adapter
        try:
            mock_adapter = MagicMock()
            mock_adapter.track_order.return_value = None
            tools_module.adapter = mock_adapter
            from agent.tools import track_order
            result = track_order.func("ORD00256", "C001")
            assert "not found" in result.lower(), f"Got: {result!r}"
            assert "high demand" not in result.lower(), "Should not trigger fault-isolation message."
        finally:
            tools_module.adapter = original

    def test_adapter_exception_gives_not_found(self):
        from agent import tools as tools_module
        original = tools_module.adapter
        try:
            mock_adapter = MagicMock()
            mock_adapter.track_order.side_effect = Exception("DB row not found")
            tools_module.adapter = mock_adapter
            from agent.tools import track_order
            result = track_order.func("ORD00256", "C001")
            assert "not found" in result.lower(), f"Got: {result!r}"
        finally:
            tools_module.adapter = original

    def test_empty_dict_gives_not_found(self):
        from agent import tools as tools_module
        original = tools_module.adapter
        try:
            mock_adapter = MagicMock()
            mock_adapter.track_order.return_value = {}
            tools_module.adapter = mock_adapter
            from agent.tools import track_order
            result = track_order.func("ORD99999", "C001")
            assert "not found" in result.lower(), f"Got: {result!r}"
        finally:
            tools_module.adapter = original

    def test_error_dict_gives_not_found(self):
        from agent import tools as tools_module
        original = tools_module.adapter
        try:
            mock_adapter = MagicMock()
            mock_adapter.track_order.return_value = {"error": "Order not found"}
            tools_module.adapter = mock_adapter
            from agent.tools import track_order
            result = track_order.func("ORD00256", "C001")
            assert "not found" in result.lower(), f"Got: {result!r}"
        finally:
            tools_module.adapter = original


# ---------------------------------------------------------------------------
# Bug 1 -- Policy questions must never return fabricated product cards
# ---------------------------------------------------------------------------

HALLUCINATED_PRODUCT_RE = re.compile(
    r"\(ID:\s*[A-Z]+\d+\).*Price:",
    re.DOTALL | re.IGNORECASE
)


def _make_general_state(user_text: str, last_tool_msg: ToolMessage = None):
    msgs = [HumanMessage(content=user_text)]
    if last_tool_msg:
        msgs.append(AIMessage(content="", tool_calls=[{
            "name": "retrieve_policy_text",
            "id": "call_test",
            "args": {"query": user_text}
        }]))
        msgs.append(last_tool_msg)
    return {
        "messages": msgs,
        "customer_id": "C001",
        "cart_id": "cart_C001",
        "intent": "general",
        "active_node": "general",
        "image_bytes": None,
    }


class TestPolicyHallucination:
    def test_error_tool_result_does_not_reach_llm(self):
        """Input-side guard: when retrieve_policy_text returns error, safe_llm_invoke
        must NOT be called at all and the response is a clean failure message."""
        error_msg = ToolMessage(
            content="Error: Vendra's external integration service is temporarily unavailable.",
            tool_call_id="call_test",
            name="retrieve_policy_text"
        )
        state = _make_general_state("what is your policy?", last_tool_msg=error_msg)

        from agent.graph import general_agent_node
        with patch("agent.graph.safe_llm_invoke") as mock_llm:
            result = general_agent_node(state)
            mock_llm.assert_not_called()

        msgs = result.get("messages", [])
        assert msgs
        text = msgs[0].content
        assert not HALLUCINATED_PRODUCT_RE.search(text), f"Hallucinated card in: {text}"
        assert any(kw in text.lower() for kw in ["trouble", "sorry", "unavailable", "try again"])

    def test_no_matching_policy_does_not_reach_llm(self):
        """Input-side guard: 'No matching' tool response is also intercepted."""
        error_msg = ToolMessage(
            content="No matching policy text found.",
            tool_call_id="call_test",
            name="retrieve_policy_text"
        )
        state = _make_general_state("whats your policy?", last_tool_msg=error_msg)

        from agent.graph import general_agent_node
        with patch("agent.graph.safe_llm_invoke") as mock_llm:
            result = general_agent_node(state)
            mock_llm.assert_not_called()

        msgs = result.get("messages", [])
        assert msgs
        text = msgs[0].content
        assert not HALLUCINATED_PRODUCT_RE.search(text), f"Hallucinated card in: {text}"

    def test_output_side_guard_blocks_hallucinated_product_card(self):
        """Output-side guard: even if safe_llm_invoke returns a hallucinated product
        card, general_agent_node must intercept and replace it with a clean message."""
        state = _make_general_state("what is the store policy?")

        fake_hallucinated = AIMessage(content=(
            "**Cool Shoe** (ID: SHOES999)\nPrice: 5000 BDT\nTags: Casual\n"
        ))

        from agent.graph import general_agent_node
        with patch("agent.graph.safe_llm_invoke", return_value=fake_hallucinated):
            result = general_agent_node(state)

        msgs = result.get("messages", [])
        assert msgs
        text = msgs[0].content
        assert not HALLUCINATED_PRODUCT_RE.search(text), (
            f"Output-side guard failed: hallucinated card still present:\n{text}"
        )

    def test_legitimate_policy_response_passes_through(self):
        """A legitimate policy answer must pass through the output-side guard unchanged."""
        state = _make_general_state("what is your return policy?")

        legit_response = AIMessage(content=(
            "You can cancel within 7 days for a full refund. "
            "After 7 days, only store credit is available. Sale items are final sale."
        ))

        from agent.graph import general_agent_node
        with patch("agent.graph.safe_llm_invoke", return_value=legit_response):
            result = general_agent_node(state)

        msgs = result.get("messages", [])
        assert msgs
        text = msgs[0].content
        assert "7 days" in text, "Legitimate policy response was incorrectly blocked."
