import os
from typing import Annotated, Sequence, TypedDict
from dotenv import load_dotenv
import datetime
import time

from langchain_google_genai import ChatGoogleGenerativeAI
from langchain_core.messages import BaseMessage, HumanMessage, AIMessage, ToolMessage
from langgraph.graph import StateGraph, START, END
from langgraph.graph.message import add_messages
from langgraph.prebuilt import ToolNode

from tools import (
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
)
from database import SessionLocal
from models import Cart, Order, OrderItem, ProductVariant

load_dotenv()

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
    customer_id: int
    cart_id: int
    current_order_id: int
    selected_product_id: int
    selected_size: str
    active_node: str
    intent: str
    image_bytes: bytes  # Binary storage for CLIP search

# Helper to get active DB cart or create one
def get_or_create_cart(customer_id: int) -> int:
    db = SessionLocal()
    try:
        cart = db.query(Cart).filter(Cart.customer_id == customer_id, Cart.status == "active").first()
        if not cart:
            cart = Cart(customer_id=customer_id, status="active")
            db.add(cart)
            db.commit()
            db.refresh(cart)
        return cart.id
    finally:
        db.close()

# Hardened Cleanup logic for Abandoned Checkout (Failure-mode handling)
def release_abandoned_orders(db):
    """
    Looks for orders stuck in 'pending_payment' that were created more than 15 minutes ago.
    Releases their reserved stock and marks the orders as 'cancelled'.
    """
    cutoff = datetime.datetime.utcnow() - datetime.timedelta(minutes=15)
    expired_orders = db.query(Order).filter(
        Order.status == "pending_payment",
        Order.created_at < cutoff
    ).all()
    
    for order in expired_orders:
        order.status = "cancelled"
        items = db.query(OrderItem).filter(OrderItem.order_id == order.id).all()
        for item in items:
            variant = db.query(ProductVariant).filter(ProductVariant.id == item.product_variant_id).first()
            if variant:
                variant.stock_quantity += item.quantity
        print(f"[Failure-Mode Handling] Cancelled expired order #{order.id} and restored stock.")
    db.commit()

# Resilient LLM Invocation wrapper handling retries, rate limits, and fallback models
def safe_llm_invoke(messages, tools=None, temperature=0) -> BaseMessage:
    """
    Invokes the LLM using a primary model and falls back to a secondary model if needed.
    Handles rate limits (429) and model not found errors (404) gracefully.
    """
    api_key = os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_API_KEY")
    if not api_key:
        return AIMessage(content="⚠️ **[Google Gemini API Error]**\nAPI Key is missing.")

    primary_model = os.getenv("PRIMARY_LLM_MODEL", "gemini-2.0-flash")
    secondary_model = os.getenv("SECONDARY_LLM_MODEL", "gemini-2.5-flash")
    
    models = [primary_model, secondary_model]
    max_retries_per_model = 2
    retry_delay = 5  # seconds
    
    last_exception = None
    
    for model_name in models:
        for attempt in range(max_retries_per_model):
            try:
                print(f"[LLM] Attempting model: {model_name} (Attempt {attempt+1}/{max_retries_per_model})")
                llm = ChatGoogleGenerativeAI(
                    model=model_name,
                    temperature=temperature,
                    google_api_key=api_key
                )
                if tools:
                    runnable = llm.bind_tools(tools)
                else:
                    runnable = llm
                    
                return runnable.invoke(messages)
            except Exception as e:
                last_exception = e
                err_str = str(e).lower()
                print(f"[LLM Warning] Model {model_name} failed: {e}")
                
                # If rate limit (429/resource_exhausted/quota), retry with delay or switch to secondary
                if "resource_exhausted" in err_str or "429" in err_str or "quota" in err_str:
                    if attempt < max_retries_per_model - 1:
                        print(f"[Rate Limit] Retrying {model_name} in {retry_delay}s...")
                        time.sleep(retry_delay)
                        continue
                # For non-429 errors (e.g. 404 model not found), switch to next model immediately
                break
                
    # If all models and attempts failed
    err_msg = str(last_exception) if last_exception else "Unknown error"
    if "resource_exhausted" in err_msg.lower() or "429" in err_msg.lower() or "quota" in err_msg.lower():
        return AIMessage(content=(
            "⚠️ **[Google Gemini API Rate Limit Exceeded]**\n"
            "Both primary and secondary Gemini models are currently rate-limited. "
            "Please wait a moment and try again."
        ))
    else:
        return AIMessage(content=(
            f"⚠️ **[Google Gemini API Error]**\n"
            f"Failed to invoke model. Details: {err_msg}"
        ))

# Router Node: Classifies intent
def router_node(state: AgentState):
    db = SessionLocal()
    try:
        release_abandoned_orders(db)
    except Exception as e:
        print(f"Error during expired orders cleanup: {e}")
    finally:
        db.close()

    customer_id = state.get("customer_id", 1)
    cart_id = state.get("cart_id")
    if not cart_id:
        cart_id = get_or_create_cart(customer_id)

    if state.get("image_bytes") is not None:
        return {"intent": "browsing", "active_node": "browsing", "customer_id": customer_id, "cart_id": cart_id}

    messages = state.get("messages", [])
    if not messages:
        return {"intent": "general", "active_node": "general", "customer_id": customer_id, "cart_id": cart_id}
        
    last_user_message = get_string_content(messages[-1].content)
    
    # Get LLM API key
    api_key = os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_API_KEY")
    if not api_key or api_key.startswith("your_"):
        intent = "browsing"
        last_lower = last_user_message.lower()
        if any(w in last_lower for w in ["cart", "add", "remove", "basket", "view"]):
            intent = "cart"
        elif any(w in last_lower for w in ["checkout", "buy", "pay", "order"]):
            intent = "checkout"
        elif any(w in last_lower for w in ["track", "status", "shipping"]):
            intent = "tracking"
        elif any(w in last_lower for w in ["cancel", "refund", "return"]):
            intent = "cancellation"
        return {"intent": intent, "active_node": intent, "customer_id": customer_id, "cart_id": cart_id}
        
    # Fast classification prompt
    system_prompt = (
        "You are an intent classifier for a shoe store assistant. "
        "Classify the customer's last message into one of these intents:\n"
        "- browsing (searching shoes, styles, catalog)\n"
        "- cart (adding, viewing, or removing items from the shopping cart)\n"
        "- checkout (ready to buy, finalize order, get payment link)\n"
        "- tracking (order status, tracking numbers)\n"
        "- cancellation (cancellations, refund requests, return policy query)\n"
        "- general (questions about store policies, greeting, or chitchat)\n\n"
        "Respond with exactly one of those words."
    )
    
    classification_msg = safe_llm_invoke([
        HumanMessage(content=system_prompt),
        HumanMessage(content=f"Customer: {last_user_message}")
    ], temperature=0)
    
    classification_text = get_string_content(classification_msg.content)
    # Handle rate-limit warnings from LLM
    if isinstance(classification_msg, AIMessage) and classification_text.startswith("⚠️"):
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
    
    return {"intent": intent, "active_node": intent, "customer_id": customer_id, "cart_id": cart_id}

# Router Conditional Edge
def route_from_router(state: AgentState):
    intent = state.get("intent", "general")
    return intent

# Shared tool runner node
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

# Determine where to route after tool execution
def route_after_tools(state: AgentState):
    return state.get("active_node", "general")

# Helper to run LLM with specialized prompt and tools
def run_specialized_agent(state: AgentState, system_prompt: str, node_name: str, tools):
    api_key = os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_API_KEY")
    if not api_key or api_key.startswith("your_"):
        last_msg = get_string_content(state["messages"][-1].content)
        return {
            "messages": [AIMessage(content=f"[Simulation Mode - {node_name.capitalize()}]: I received '{last_msg}'.")]
        }
        
    state_context = (
        f"\n[System Context - Cart ID: {state.get('cart_id')}, Customer ID: {state.get('customer_id')}]"
    )
    full_prompt = system_prompt + state_context
    
    formatted_messages = [HumanMessage(content=full_prompt)] + list(state["messages"])
    ai_msg = safe_llm_invoke(formatted_messages, tools=tools, temperature=0)
    
    return {"messages": [ai_msg], "active_node": node_name}

# Nodes

def browse_node(state: AgentState):
    system_prompt = (
        "You are the browsing and recommendation expert at Vendra shoe store.\n"
        "Use the search_products tool to find shoes based on user preferences (color, category, style, tags).\n"
        "If the customer uploads an image (which is held in their session state), call the search_products_by_image tool to execute visual search.\n"
        "Suggest 2-4 products matching their queries conversationally. Do not make up product specs."
    )
    return run_specialized_agent(state, system_prompt, "browsing", [search_products, search_products_by_image])

def cart_node(state: AgentState):
    system_prompt = (
        "You are the shopping cart manager at Vendra shoe store.\n"
        "You can add items (add_to_cart), remove items (remove_from_cart), view the cart (view_cart), check stock (check_stock) or get product info (get_product_details).\n"
        "IMPORTANT: When adding to cart, you need the cart_id (check system context) and the specific product_variant_id (which you find using get_product_details or check_stock for that product and size). Ask for the size if they didn't specify it.\n"
        "Confirm details to the user once cart changes are done."
    )
    cart_tools = [add_to_cart, view_cart, remove_from_cart, check_stock, get_product_details]
    return run_specialized_agent(state, system_prompt, "cart", cart_tools)

def checkout_node(state: AgentState):
    system_prompt = (
        "You are the checkout manager at Vendra shoe store.\n"
        "Your task is to help the customer finalize their order and purchase the items in their cart.\n"
        "1. First, check what is in their cart using the view_cart tool. Make sure to display the contents and the total price to confirm with them.\n"
        "2. Once the customer confirms, use the create_order tool to create the order (reserving stock).\n"
        "3. Right after creating the order, call create_payment_link to generate the Stripe payment link and give it to the customer.\n"
        "IMPORTANT: You must never ask for or accept credit card numbers or payment details directly in conversation. The only way they pay is through the payment link."
    )
    checkout_tools = [view_cart, create_order, create_payment_link]
    return run_specialized_agent(state, system_prompt, "checkout", checkout_tools)

def tracking_node(state: AgentState):
    system_prompt = (
        "You are the order tracking assistant at Vendra shoe store.\n"
        "Your task is to help customers track their order status.\n"
        "Use the track_order tool to look up details. You must pass both the order_id (ask the user for it if not provided) and the customer_id (from the system context).\n"
        "If a customer requests to track an order and you get an access denied or refusal message from the tool, state clearly that you cannot share details for that order ID because it belongs to another customer."
    )
    return run_specialized_agent(state, system_prompt, "tracking", [track_order])

def cancellation_node(state: AgentState):
    system_prompt = (
        "You are the cancellation and refund expert at Vendra shoe store.\n"
        "Your job is to assist customers with cancelling their orders and requesting refunds.\n"
        "1. First, check if the customer is eligible for cancellation using the check_cancellation_eligibility tool.\n"
        "2. If the tool response indicates 'eligible': true, call the cancel_order tool to execute the cancellation and trigger the refund.\n"
        "3. If they are not eligible for a full refund (e.g. they only qualify for store credit, or the order is outside the 7-day window, or there is another constraint), explain this clearly. You can retrieve details of our policy using the retrieve_policy_text tool to explain the specific clause in your own words (do not copy-paste verbatim, make it conversational).\n"
        "IMPORTANT: You must never make the eligibility decision by yourself. You must strictly check eligibility via check_cancellation_eligibility tool and then execute cancel_order only if it returns eligible: true (or store credit status is accepted by the user)."
    )
    cancellation_tools = [check_cancellation_eligibility, cancel_order, retrieve_policy_text]
    return run_specialized_agent(state, system_prompt, "cancellation", cancellation_tools)

def general_node(state: AgentState):
    system_prompt = (
        "You are Vendra, a friendly, concise conversational shoe-store assistant.\n"
        "Help customers with greetings, general store policies, or questions.\n"
        "If they ask specific questions about returns, refunds, or cancellations, you can use the retrieve_policy_text tool to search the return policy clauses.\n"
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

# Add Nodes
builder.add_node("router", router_node)
builder.add_node("browsing", browse_node)
builder.add_node("cart", cart_node)
builder.add_node("checkout", checkout_node)
builder.add_node("tracking", tracking_node)
builder.add_node("cancellation", cancellation_node)
builder.add_node("general", general_node)
builder.add_node("tools", tool_node)

# Set Entry Point
builder.set_entry_point("router")

# Add Routing from Router
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

# Add conditional edges for tool calls for each active agent node
for node in ["browsing", "cart", "checkout", "tracking", "cancellation", "general"]:
    builder.add_conditional_edges(
        node,
        should_continue,
        {
            "tools": "tools",
            END: END
        }
    )

# Edge from tools back to the active agent node
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
