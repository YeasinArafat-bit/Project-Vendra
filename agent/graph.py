import os
import time
from typing import Annotated, Sequence, TypedDict
from dotenv import load_dotenv

from langchain_groq import ChatGroq
from langchain_core.messages import BaseMessage, HumanMessage, AIMessage, ToolMessage, SystemMessage
from langgraph.graph import StateGraph, START, END
from langgraph.graph.message import add_messages
from langgraph.prebuilt import ToolNode

from agent.tools import (
    search_products,
    search_products_by_image,
    check_stock,
    get_product_details,
    add_to_cart,
    view_cart,
    remove_from_cart,
    create_order,
    create_payment_link,
    track_order,
    check_cancellation_eligibility,
    cancel_order,
    retrieve_policy_text,
    adapter
)
from agent.prompts import SYSTEM_PROMPT

load_dotenv(override=True)

def get_string_content(content) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts = []
        for part in content:
            if isinstance(part, dict):
                if part.get("type") == "text":
                    parts.append(part.get("text", ""))
            elif isinstance(part, str):
                parts.append(part)
        return "".join(parts)
    return str(content) if content is not None else ""

# State Definition
class AgentState(TypedDict):
    messages: Annotated[Sequence[BaseMessage], add_messages]
    customer_id: str
    cart_id: str
    current_order_id: str
    selected_product_id: str
    selected_size: str
    active_node: str
    intent: str
    image_bytes: bytes  # Binary storage for CLIP search

import re

def clean_message_content(content) -> str:
    if isinstance(content, list):
        parts = []
        for part in content:
            if isinstance(part, dict) and part.get("type") == "text":
                text = part.get("text", "")
                cleaned_text = re.sub(r'<function=.*?>.*?</function>', '', text, flags=re.DOTALL)
                cleaned_text = re.sub(r'<function=.*?>', '', cleaned_text)
                part_copy = dict(part)
                part_copy["text"] = cleaned_text
                parts.append(part_copy)
            elif isinstance(part, str):
                cleaned_str = re.sub(r'<function=.*?>.*?</function>', '', part, flags=re.DOTALL)
                cleaned_str = re.sub(r'<function=.*?>', '', cleaned_str)
                parts.append(cleaned_str)
            else:
                parts.append(part)
        return parts
    elif isinstance(content, str):
        cleaned = re.sub(r'<function=.*?>.*?</function>', '', content, flags=re.DOTALL)
        cleaned = re.sub(r'<function=.*?>', '', cleaned)
        return cleaned
    return content

def clean_old_message_content(content):
    if isinstance(content, list):
        parts = []
        for part in content:
            if isinstance(part, dict) and part.get("type") == "text":
                text = part.get("text", "")
                part_copy = dict(part)
                part_copy["text"] = _clean_text_for_tokens(text)
                parts.append(part_copy)
            elif isinstance(part, str):
                parts.append(_clean_text_for_tokens(part))
            else:
                parts.append(part)
        return parts
    elif isinstance(content, str):
        return _clean_text_for_tokens(content)
    return content

def _clean_text_for_tokens(text: str) -> str:
    lines = text.split("\n")
    cleaned_lines = []
    for line in lines:
        stripped = line.strip()
        # Keep product headers and general conversational text but drop description and image fields to save tokens
        if (stripped.startswith("Image:") or 
            stripped.startswith("Image URL:") or 
            stripped.startswith("Description:") or 
            "http://" in stripped or 
            "https://" in stripped):
            continue
        if len(stripped) > 200:
            cleaned_lines.append(stripped[:100] + "... [truncated]")
        else:
            cleaned_lines.append(line)
    return "\n".join(cleaned_lines)


# Resilient LLM Invocation wrapper handling Groq API requests
def safe_llm_invoke(messages, tools=None, temperature=0) -> BaseMessage:
    groq_api_key = os.getenv("GROQ_API_KEY")
    if not groq_api_key or groq_api_key.startswith("your_"):
        return AIMessage(content="⚠️ **[Groq API Key Error]**\nGROQ_API_KEY is missing or configured as placeholder in .env.")

    groq_model = os.getenv("GROQ_MODEL", "llama-3.1-8b-instant")
    
    # Clean history of any legacy <function=...> XML annotations that might confuse the model
    cleaned_messages = []
    for msg in messages:
        msg_copy = msg.copy()
        if hasattr(msg_copy, "content"):
            msg_copy.content = clean_message_content(msg_copy.content)
        cleaned_messages.append(msg_copy)
        
    try:
        llm = ChatGroq(
            model=groq_model,
            temperature=temperature,
            groq_api_key=groq_api_key
        )
        if tools:
            runnable = llm.bind_tools(tools)
        else:
            runnable = llm
        return runnable.invoke(cleaned_messages)
    except Exception as e:
        err_msg = str(e)
        print(f"[Groq Error] Failed to invoke {groq_model}: {e}")
        return AIMessage(content=f"⚠️ **[Groq API Error]**\nFailed to invoke model. Details: {err_msg}")

_CLASSIFICATION_CACHE = {}

# Router Node: Classifies intent
def router_node(state: AgentState):
    global _CLASSIFICATION_CACHE
    # Failure-Mode check for abandoned checkouts
    if hasattr(adapter, "release_abandoned_checkouts"):
        try:
            adapter.release_abandoned_checkouts()
        except Exception as e:
            print(f"Error during expired orders cleanup: {e}")

    # Prune inactive carts
    try:
        from agent.tools import prune_inactive_carts
        prune_inactive_carts(hours=24.0)
    except Exception as e:
        print(f"Error during cart pruning: {e}")

    customer_id = state.get("customer_id")
    if not customer_id:
        customer_id = "C001"

    cart_id = state.get("cart_id")
    if not cart_id:
        cart_id = f"cart_{customer_id}"

    if state.get("image_bytes") is not None:
        return {"intent": "browsing", "active_node": "browsing", "customer_id": customer_id, "cart_id": cart_id}

    messages = state.get("messages", [])
    if not messages:
        return {"intent": "general", "active_node": "general", "customer_id": customer_id, "cart_id": cart_id}
        
    last_user_message = get_string_content(messages[-1].content)
    last_lower = last_user_message.lower().strip()
    active_node = state.get("active_node")
    
    # 0. Deterministic intent overrides for obvious queries (with Bengali/Banglish support)
    tracking_words = [
        "where is my parcel", "where is my order", "track my order", "track order", "track parcel",
        "order koi", "delivery koi", "parcel koi", "order track", "delivery status", "parcel status", "kothay",
        "অর্ডার কোথায়", "পার্সেল কোথায়", "আমার অর্ডার", "অর্ডার ট্র্যাক", "ডেলিভারি কোথায়"
    ]
    if any(w in last_lower for w in tracking_words):
        return {"intent": "tracking", "active_node": "tracking", "customer_id": customer_id, "cart_id": cart_id}
        
    cancellation_words = [
        "cancel my order", "cancel order", "refund my order", "request a refund",
        "order cancel", "cancel korte chai", "refund chai", "refund lagbe", "taka ফেরত", "cancel korbo",
        "অর্ডার বাতিল", "বাতিল করতে চাই", "রিফান্ড চাই", "টাকা ফেরত"
    ]
    if any(w in last_lower for w in cancellation_words):
        return {"intent": "cancellation", "active_node": "cancellation", "customer_id": customer_id, "cart_id": cart_id}
        
    cart_words = [
        "view cart", "show cart", "my cart", "whats in my cart",
        "cart dekhao", "amar cart", "cart e ki ache",
        "কার্ট দেখাও", "আমার কার্ট"
    ]
    if any(w in last_lower for w in cart_words):
        return {"intent": "cart", "active_node": "cart", "customer_id": customer_id, "cart_id": cart_id}
        
    checkout_words = [
        "checkout", "pay now", "proceed to payment",
        "payment korbo", "taka dibo", "pay korbo", "checkout korbo",
        "পেমেন্ট করব", "চেকআউট করব"
    ]
    if any(w in last_lower for w in checkout_words):
        return {"intent": "checkout", "active_node": "checkout", "customer_id": customer_id, "cart_id": cart_id}
    
    # 1. Heuristics for Slot-Filling (Order IDs, Sizes, short yes/no confirmations)
    import re
    is_order_id = False
    if "ord" in last_lower or re.search(r"\bord\w+", last_lower):
        is_order_id = True
        
    is_short_or_confirm = (
        len(last_lower) < 15 or 
        last_lower in ["yes", "no", "confirm", "y", "n", "ok", "okay", "sure", "cancel", "back", "thanks", "thank you"] or
        re.match(r"^(size\s+)?\d+(\.\d+)?$", last_lower)
    )
    if active_node and active_node in ["browsing", "cart", "checkout", "tracking", "cancellation", "general"]:
        if is_order_id or is_short_or_confirm:
            return {"intent": active_node, "active_node": active_node, "customer_id": customer_id, "cart_id": cart_id}
            
    # Check Cache
    cache_key = last_lower.strip()
    if cache_key in _CLASSIFICATION_CACHE:
        cached_intent = _CLASSIFICATION_CACHE[cache_key]
        return {"intent": cached_intent, "active_node": cached_intent, "customer_id": customer_id, "cart_id": cart_id}

    groq_api_key = os.getenv("GROQ_API_KEY")
    gemini_api_key = os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_API_KEY")
    has_groq = groq_api_key and not groq_api_key.startswith("your_")
    has_gemini = gemini_api_key and not gemini_api_key.startswith("your_")
    if not has_groq and not has_gemini:
        # Local heuristic fallback if no key is configured
        if any(w in last_lower for w in ["shoes", "shoe", "sneaker", "sneakers", "boot", "boots", "sandal", "sandals", "casual", "formal", "sport", "sports", "wedding", "party", "office", "show me", "find me", "looking for", "something for"]):
            intent = "browsing"
        elif "buy" in last_lower and not any(w in last_lower for w in ["checkout", "pay", "done"]):
            intent = "browsing"
        elif any(w in last_lower for w in ["cart", "add", "remove", "basket", "view"]):
            intent = "cart"
        elif any(w in last_lower for w in ["checkout", "pay"]):
            intent = "checkout"
        elif any(w in last_lower for w in ["track", "status", "shipping", "parcel", "delivery", "where is my"]):
            intent = "tracking"
        elif any(w in last_lower for w in ["cancel", "refund", "return"]):
            intent = "cancellation"
        else:
            intent = active_node if active_node else "browsing"
            
        _CLASSIFICATION_CACHE[cache_key] = intent
        return {"intent": intent, "active_node": intent, "customer_id": customer_id, "cart_id": cart_id}
        
    system_prompt = (
        "You are an intent classifier for a shoe store assistant. "
        "Classify the customer's last message into exactly one of these intents based on the conversation history:\n"
        "- browsing (searching shoes, styles, categories, mood/occasions like casual, formal, sports, wedding, party, office, show me, find me, looking for, or 'I want to buy [anything]')\n"
        "- cart (adding, viewing, or removing items from the shopping cart)\n"
        "- checkout (ONLY when the user is ready to pay, finalize their existing cart order, or get a Stripe payment link)\n"
        "- tracking (order status, tracking numbers, courier tracking code, parcel locations, delivery timeline, or providing order details when asked)\n"
        "- cancellation (cancelling an order, refund requests, return policy queries, or providing order details to execute cancellation)\n"
        "- general (questions about store policies, greeting, or chitchat)\n\n"
        "Categorize the query correctly even if written in Bengali or Banglish (mixed Bangla-English).\n"
        "Respond with exactly one of those words."
    )
    
    # Build conversation context from recent messages (up to last 3 messages)
    history_messages = []
    for msg in messages[-3:]:
        role = "Customer"
        if isinstance(msg, AIMessage):
            role = "Assistant"
        elif isinstance(msg, SystemMessage):
            role = "System"
        cleaned_content = clean_old_message_content(get_string_content(msg.content))
        history_messages.append(f"{role}: {cleaned_content}")
    history_str = "\n".join(history_messages)
    
    classification_msg = safe_llm_invoke([
        SystemMessage(content=system_prompt),
        HumanMessage(content=f"Conversation History:\n{history_str}\n\nLast Customer Message: {last_user_message}")
    ], temperature=0)
    
    classification_text = get_string_content(classification_msg.content)
    if classification_text.startswith("⚠️"):
        return {
            "intent": "general", 
            "active_node": "general", 
            "customer_id": customer_id, 
            "cart_id": cart_id,
            "messages": [classification_msg]
        }
        
    classification = classification_text.strip().lower()
    valid_intents = ["browsing", "cart", "checkout", "tracking", "cancellation", "general"]
    intent = classification if classification in valid_intents else "general"
    
    _CLASSIFICATION_CACHE[cache_key] = intent
    return {"intent": intent, "active_node": intent, "customer_id": customer_id, "cart_id": cart_id}

# Router Conditional Edge
def route_from_router(state: AgentState):
    return state.get("intent", "general")

# List of tools for the graph
tools_list = [
    search_products,
    search_products_by_image,
    check_stock,
    get_product_details,
    add_to_cart,
    view_cart,
    remove_from_cart,
    create_order,
    create_payment_link,
    track_order,
    check_cancellation_eligibility,
    cancel_order,
    retrieve_policy_text
]
tool_node = ToolNode(tools_list)

# Route back to active agent node after tools
def route_after_tools(state: AgentState):
    return state.get("active_node", "general")

def get_safe_recent_messages(messages: list, limit: int = 4) -> list:
    if len(messages) <= limit:
        candidates = list(messages)
    else:
        candidates = list(messages)[-limit:]
        
    # Check if there are orphaned ToolMessages
    tool_call_ids_in_candidates = {
        msg.tool_call_id for msg in candidates if isinstance(msg, ToolMessage)
    }
    
    ai_message_tool_call_ids = set()
    for msg in candidates:
        if isinstance(msg, AIMessage) and msg.tool_calls:
            for tc in msg.tool_calls:
                ai_message_tool_call_ids.add(tc.get("id"))
                
    orphaned_ids = tool_call_ids_in_candidates - ai_message_tool_call_ids
    
    if orphaned_ids:
        # Expand window backward until all orphaned ToolMessages find their initiating AIMessage
        idx = len(messages) - limit
        while idx > 0:
            candidates = list(messages)[idx:]
            tool_call_ids_in_candidates = {
                msg.tool_call_id for msg in candidates if isinstance(msg, ToolMessage)
            }
            ai_message_tool_call_ids = set()
            for msg in candidates:
                if isinstance(msg, AIMessage) and msg.tool_calls:
                    for tc in msg.tool_calls:
                        ai_message_tool_call_ids.add(tc.get("id"))
            orphaned_ids = tool_call_ids_in_candidates - ai_message_tool_call_ids
            
            if not orphaned_ids:
                break
            idx -= 1
        
    # Clean old messages in the candidates list to keep token count minimal
    cleaned_candidates = []
    for i, msg in enumerate(candidates):
        msg_copy = msg.copy()
        if i < len(candidates) - 1 and hasattr(msg_copy, "content"):
            msg_copy.content = clean_old_message_content(msg_copy.content)
        cleaned_candidates.append(msg_copy)
        
    return cleaned_candidates

# Base helper to run specialized agent nodes
def run_specialized_agent(state: AgentState, system_prompt: str, node_name: str, tools):
    groq_api_key = os.getenv("GROQ_API_KEY")
    gemini_api_key = os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_API_KEY")
    has_groq = groq_api_key and not groq_api_key.startswith("your_")
    has_gemini = gemini_api_key and not gemini_api_key.startswith("your_")
    if not has_groq and not has_gemini:
        last_msg = get_string_content(state["messages"][-1].content)
        return {
            "messages": [AIMessage(content=f"[Simulation Mode - {node_name.capitalize()}]: I received '{last_msg}'.")]
        }
        
    state_context = (
        f"\n[System Context - Cart ID: {state.get('cart_id')}, Customer ID: {state.get('customer_id')}]"
    )
    full_prompt = SYSTEM_PROMPT + "\n\n" + system_prompt + state_context
    
    recent_messages = get_safe_recent_messages(state["messages"], limit=6)
    formatted_messages = [SystemMessage(content=full_prompt)] + recent_messages
    ai_msg = safe_llm_invoke(formatted_messages, tools=tools, temperature=0)
    
    return {"messages": [ai_msg], "active_node": node_name}

# Node functions
def browse_node(state: AgentState):
    # Intercept tool outputs to avoid LLM formatting laziness/token latency
    if state.get("messages"):
        last_msg = state["messages"][-1]
        if isinstance(last_msg, ToolMessage):
            is_search = False
            if getattr(last_msg, "name", None) in ["search_products", "search_products_by_image"]:
                is_search = True
            elif "Found these matching items" in last_msg.content or "No matching shoes found in catalog" in last_msg.content:
                is_search = True
                
            if is_search:
                content = last_msg.content
                follow_up = "\n\nWant me to filter by size, occasion, or price range?"
                ai_response = AIMessage(content=content + follow_up)
                return {"messages": [ai_response], "active_node": "browsing"}

    system_prompt = (
        "You are the browsing and recommendation expert at Vendra shoe store.\n"
        "CRITICAL: The only valid tool name for catalog searching is 'search_products'. Do NOT call any other tool name (like 'retrieve_products' or 'search_shoes'). You must invoke it natively, even when responding in Bengali or Banglish. Never write raw XML tags like '<function=...>' in your text response.\n"
        "CRITICAL: You MUST call search_products immediately on every turn when a user asks for shoes, styles, categories, occasions, or says they want to buy. Do not ask any clarifying questions first. Always request 4 products for top_k.\n"
        "CRITICAL TOOL ARGUMENTS RULE: When calling search_products or search_products_by_image, do NOT pass any parameters as null or None. If a parameter (like category, min_price, max_price, size, or query) has no value or is not specified, OMIT it from the tool call arguments completely.\n"
        "If the user says 'I want to buy some shoes' or 'shoes' generally, call the search_products tool with the query='shoes' and top_k=4.\n"
        "If they ask for a category, mood, or occasion (e.g. casual shoes, formal, sports, wedding), call the search_products tool with that category, mood, or occasion as the query and top_k=4.\n"
        "EXTRACTION CAPABILITY: If the customer mentions size, category, or price constraints (e.g., 'under 3000 BDT', 'size 9', 'casual shoes'), you MUST parse these constraints and supply them as optional arguments to the search_products tool. Similarly, if they upload a photo or image AND specify constraints/refinements (e.g. 'find this in size 9' or 'like this shoe but cheap'), pass the image bytes to search_products_by_image along with the extracted constraints (query, category, max_price, min_price, size):\n"
        "  - category: 'casual', 'sport', 'formal', or 'sale'\n"
        "  - max_price: numeric upper bound (e.g., 3000.0)\n"
        "  - min_price: numeric lower bound (e.g., 1000.0)\n"
        "  - size: the size number as a string (e.g., '9')\n"
        "  - query: any visual/text refinement text (e.g., 'blue', 'leather')\n"
        "If search_products or search_products_by_image returns 0 results for a specific query, immediately call it again with a broader search term (e.g. 'shoes' or a broader category like 'casual' or 'formal') to ensure the user gets recommendations immediately without asking questions.\n"
        "CRITICAL: Once the tool search_products or search_products_by_image returns items, you MUST write down the complete list of matching shoes in your text response using the required recommendation format. Do NOT skip or omit them. You must copy the details (Name, ID, Price, Tags, Description, Image) from the tool output into your message. Only after presenting all the products, add exactly this line: 'Want me to filter by size, occasion, or price range?'"
    )
    return run_specialized_agent(state, system_prompt, "browsing", [search_products, search_products_by_image, get_product_details, check_stock])

def cart_node(state: AgentState):
    system_prompt = (
        "You are the shopping cart manager at Vendra shoe store.\n"
        "You can add items to the cart, remove items from the cart, view the cart, check stock, or get product details using the provided tools.\n"
        "When calling add_to_cart, view_cart, or remove_from_cart, you must pass BOTH cart_id and customer_id (from the system context) to enforce ownership.\n"
        "When adding items, retrieve the cart ID from context and find the specific product ID. Ask the customer for their size preference if not mentioned.\n"
        "Confirm details to the user once cart changes are done."
    )
    cart_tools = [add_to_cart, view_cart, remove_from_cart, check_stock, get_product_details]
    return run_specialized_agent(state, system_prompt, "cart", cart_tools)

def checkout_node(state: AgentState):
    system_prompt = (
        "You are the checkout manager at Vendra shoe store.\n"
        "Your task is to help the customer finalize their order and purchase the items in their cart.\n"
        "1. First, check what is in their cart using the view_cart tool (pass BOTH cart_id and customer_id from system context). Make sure to display the contents and the total price to confirm with them.\n"
        "2. Once the customer confirms, use the create_order tool to create the order (reserving stock).\n"
        "3. Right after creating the order, call create_payment_link to generate the Stripe payment link and give it to the customer. Pass BOTH order_id and customer_id (from system context) to create_payment_link.\n"
        "IMPORTANT: You must never ask for or accept credit card numbers or payment details directly in conversation. The only way they pay is through the payment link."
    )
    checkout_tools = [view_cart, create_order, create_payment_link]
    return run_specialized_agent(state, system_prompt, "checkout", checkout_tools)

def tracking_node(state: AgentState):
    system_prompt = (
        "You are Vendra's order tracking assistant. Your only job is to retrieve and display tracking information for orders.\n"
        "CRITICAL: Do NOT attempt to search products, call 'search_products', or recommend shoes in this tracking node. If the user asks where their shoes are in a way that suggests they want to buy, simply ask them for their order ID to track it.\n"
        "Strictly follow these steps:\n"
        "1. If you do not have the order ID, ask the customer to provide it.\n"
        "2. If you have the order ID, call the 'track_order' tool immediately. You must pass the order_id and customer_id (from the system context).\n"
        "3. Once the 'track_order' tool returns tracking details, you MUST present the complete details (Courier, Tracking Code, Status, Estimated Delivery, and all timeline events) to the customer in your text response. Never omit, summarize, or hide these details, and never ask follow-up questions instead of showing the data. If the tool output is present in the history, print it immediately.\n"
        "4. If the tool returns an error saying the order belongs to another customer, state clearly that you cannot share details for that order ID because it belongs to another customer."
    )
    return run_specialized_agent(state, system_prompt, "tracking", [track_order])

def cancellation_node(state: AgentState):
    system_prompt = (
        "You are the cancellation and refund expert at Vendra shoe store.\n"
        "Your job is to assist customers with cancelling their orders and requesting refunds.\n"
        "1. First, check if the customer is eligible for cancellation using the check_cancellation_eligibility tool (pass both order_id and customer_id from system context).\n"
        "2. If the tool response indicates 'eligible': true, call the cancel_order tool to execute the cancellation and trigger the refund (pass both order_id and customer_id).\n"
        "3. If they are not eligible for a full refund (e.g. they only qualify for store credit, or the order is outside the 7-day window, or there is another constraint), explain this clearly. You can retrieve details of our policy using the retrieve_policy_text tool to explain the specific clause in your own words.\n"
        "IMPORTANT: You must never make the eligibility decision by yourself. You must strictly check eligibility via check_cancellation_eligibility tool and then execute cancel_order only if it returns eligible: true (or store credit status is accepted by the user)."
    )
    cancellation_tools = [check_cancellation_eligibility, cancel_order, retrieve_policy_text]
    return run_specialized_agent(state, system_prompt, "cancellation", cancellation_tools)

def general_node(state: AgentState):
    system_prompt = (
        "You are Vendra, a friendly, concise conversational shoe-store assistant.\n"
        "Help customers with greetings, general store policies, or questions.\n"
        "CRITICAL: Do NOT attempt to call any tools for general greetings or chitchat. Only use tools if the user asks a specific question about returns, cancellations, or policy rules.\n"
        "If they ask specific questions about returns, refunds, or cancellations, you can use the retrieve_policy_text tool to search the return policy clauses.\n"
        "You ONLY have access to the 'retrieve_policy_text' tool. Do NOT attempt to call check_cancellation_eligibility, cancel_order, or any other tools, as they are not registered in this node.\n"
        "Detect and reply in whatever language the customer uses, including Bengali or mixed Bangla-English naturally."
    )
    return run_specialized_agent(state, system_prompt, "general", [retrieve_policy_text])

# Edge condition checking if LLM returned tool calls
def should_continue(state: AgentState):
    messages = state["messages"]
    last_message = messages[-1]
    if isinstance(last_message, AIMessage) and last_message.tool_calls:
        return "tools"
    return END

# Build Graph
builder = StateGraph(AgentState)

builder.add_node("router", router_node)
builder.add_node("browsing", browse_node)
builder.add_node("cart", cart_node)
builder.add_node("checkout", checkout_node)
builder.add_node("tracking", tracking_node)
builder.add_node("cancellation", cancellation_node)
builder.add_node("general", general_node)
builder.add_node("tools", tool_node)

builder.set_entry_point("router")

builder.add_conditional_edges(
    "router",
    route_from_router,
    {
        "browsing": "browsing",
        "cart": "cart",
        "checkout": "checkout",
        "tracking": "tracking",
        "cancellation": "cancellation",
        "general": "general"
    }
)

for node in ["browsing", "cart", "checkout", "tracking", "cancellation", "general"]:
    builder.add_conditional_edges(
        node,
        should_continue,
        {
            "tools": "tools",
            END: END
        }
    )

builder.add_conditional_edges(
    "tools",
    route_after_tools,
    {
        "browsing": "browsing",
        "cart": "cart",
        "checkout": "checkout",
        "tracking": "tracking",
        "cancellation": "cancellation",
        "general": "general"
    }
)

graph = builder.compile()
