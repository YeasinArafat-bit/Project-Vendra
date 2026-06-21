import os
import re
import requests
import streamlit as st
from langchain_core.messages import HumanMessage, AIMessage, ToolMessage
from agent_graph import graph, get_or_create_cart
from database import SessionLocal
from models import Cart, CartItem, ProductVariant, Product, Order, OrderItem, Customer

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

# Set Streamlit Page Config
st.set_page_config(
    page_title="Vendra — Conversational Shoe Store Agent",
    page_icon="👟",
    layout="wide",
    initial_sidebar_state="expanded"
)

# Custom Sleek CSS Styles for Rich Aesthetics
st.markdown("""
<style>
    /* Styling headers and fonts */
    .stApp {
        background-color: #0F0F11;
        color: #E2E8F0;
        font-family: 'Inter', sans-serif;
    }
    h1, h2, h3 {
        font-family: 'Outfit', sans-serif;
        color: #FFFFFF !important;
        font-weight: 700;
    }
    .main-title {
        background: linear-gradient(135deg, #FF6B6B 0%, #FF8E53 100%);
        -webkit-background-clip: text;
        -webkit-text-fill-color: transparent;
        font-size: 3rem;
        margin-bottom: 0.5rem;
    }
    /* Chat bubbles custom style */
    .stChatMessage {
        border-radius: 12px;
        margin-bottom: 0.75rem;
        padding: 1rem;
    }
    div[data-testid="stChatMessageUser"] {
        background-color: #1E1E24 !important;
        border-left: 5px solid #FF6B6B;
    }
    div[data-testid="stChatMessageAssistant"] {
        background-color: #16161A !important;
        border-left: 5px solid #FF8E53;
    }
    /* Sidebar styling */
    section[data-testid="stSidebar"] {
        background-color: #08080A !important;
        border-right: 1px solid #27272A;
    }
    .cart-card {
        background-color: #18181B;
        border-radius: 8px;
        padding: 0.75rem;
        margin-bottom: 0.5rem;
        border: 1px solid #27272A;
    }
    .badge-paid {
        background-color: #10B981;
        color: white;
        padding: 0.15rem 0.4rem;
        border-radius: 4px;
        font-size: 0.75rem;
    }
    .badge-pending {
        background-color: #F59E0B;
        color: white;
        padding: 0.15rem 0.4rem;
        border-radius: 4px;
        font-size: 0.75rem;
    }
    .badge-cancelled {
        background-color: #EF4444;
        color: white;
        padding: 0.15rem 0.4rem;
        border-radius: 4px;
        font-size: 0.75rem;
    }
    .badge-refunded {
        background-color: #3B82F6;
        color: white;
        padding: 0.15rem 0.4rem;
        border-radius: 4px;
        font-size: 0.75rem;
    }
</style>
""", unsafe_allow_html=True)

# Initialize Session States
if "messages" not in st.session_state:
    st.session_state["messages"] = []
if "customer_id" not in st.session_state:
    st.session_state["customer_id"] = 1  # Alice Smith
if "cart_id" not in st.session_state:
    st.session_state["cart_id"] = get_or_create_cart(st.session_state["customer_id"])
if "uploaded_image_bytes" not in st.session_state:
    st.session_state["uploaded_image_bytes"] = None
if "current_order_id" not in st.session_state:
    st.session_state["current_order_id"] = None
if "active_node" not in st.session_state:
    st.session_state["active_node"] = "general"
if "intent" not in st.session_state:
    st.session_state["intent"] = "general"

# Helper to query DB details for visual lists in sidebar
def get_sidebar_data():
    db = SessionLocal()
    try:
        cust = db.query(Customer).filter(Customer.id == st.session_state["customer_id"]).first()
        cart_id = get_or_create_cart(cust.id) if cust else st.session_state["cart_id"]
        
        # Cart Items
        cart_items = db.query(CartItem).filter(CartItem.cart_id == cart_id).all()
        cart_details = []
        cart_total = 0.0
        for item in cart_items:
            variant = db.query(ProductVariant).filter(ProductVariant.id == item.product_variant_id).first()
            if variant:
                product = db.query(Product).filter(Product.id == variant.product_id).first()
                if product:
                    subtotal = product.price * item.quantity
                    cart_total += subtotal
                    cart_details.append({
                        "name": product.name,
                        "size": variant.size,
                        "quantity": item.quantity,
                        "price": product.price,
                        "subtotal": subtotal
                    })
                    
        # Historical Orders
        orders = db.query(Order).filter(Order.customer_id == st.session_state["customer_id"]).order_by(Order.id.desc()).all()
        order_list = []
        for o in orders:
            order_list.append({
                "id": o.id,
                "total": o.total_price,
                "status": o.status,
                "created_at": o.created_at
            })
            
        return cust, cart_details, cart_total, order_list
    finally:
        db.close()

# Refresh Sidebar Information
customer, sidebar_cart, total_price, customer_orders = get_sidebar_data()

# Webhook Mock trigger handler
def simulate_webhook_payment(order_id: int):
    # Sends a simulated Stripe webhook delivery request directly to the API
    payload = {
        "order_id": order_id,
        "stripe_event_id": f"evt_mock_streamlit_{order_id}",
        "mock": True
    }
    try:
        # Call api webhook route
        response = requests.post("http://localhost:8000/webhook/stripe", json=payload, timeout=5)
        if response.status_code == 200:
            st.success(f"Webhook simulated! Order #{order_id} is marked as PAID.")
            st.rerun()
        else:
            st.error(f"API webhook failed: {response.text}")
    except Exception:
        # If API is not running, bypass and update database directly to maintain smooth UX
        db = SessionLocal()
        try:
            order = db.query(Order).filter(Order.id == order_id).first()
            if order:
                order.status = "paid"
                order.stripe_event_id = f"evt_mock_direct_{order_id}"
                db.commit()
                st.success(f"Direct DB Payment simulated! Order #{order_id} marked as PAID.")
                st.rerun()
        finally:
            db.close()

# --- SIDEBAR PRESENTATION ---
with st.sidebar:
    st.image("https://cdn-icons-png.flaticon.com/512/3159/3159066.png", width=70)
    st.markdown("<h2 style='margin-top: 0;'>Vendra Assistant</h2>", unsafe_allow_html=True)
    
    if customer:
        st.markdown(f"👤 **Customer Profile**\n- Name: {customer.name}\n- Email: {customer.email}")
        
    st.markdown("---")
    
    # Visual Search Section
    st.subheader("📷 Visual Search")
    uploaded_file = st.file_uploader(
        "Upload a shoe photo to find similar ones in our catalog:", 
        type=["png", "jpg", "jpeg"], 
        key="visual_search_uploader"
    )
    
    if uploaded_file is not None:
        file_bytes = uploaded_file.read()
        
        # If new file, update session state and trigger input
        if st.session_state["uploaded_image_bytes"] != file_bytes:
            st.session_state["uploaded_image_bytes"] = file_bytes
            st.image(uploaded_file, caption="Uploaded image for visual search", use_container_width=True)
            
            # Send message automatically on behalf of user
            st.session_state["messages"].append(HumanMessage(content="[Visual Search Photo Uploaded]"))
            
            # Run LangGraph flow with image bytes
            state_input = {
                "messages": st.session_state["messages"],
                "customer_id": st.session_state["customer_id"],
                "cart_id": st.session_state["cart_id"],
                "current_order_id": st.session_state["current_order_id"],
                "image_bytes": file_bytes,  # Inject image bytes directly to graph
                "active_node": "browsing",
                "intent": "browsing"
            }
            
            with st.spinner("Analyzing image features using CLIP..."):
                output = graph.invoke(state_input)
                
            st.session_state["messages"] = list(output["messages"])
            st.session_state["active_node"] = output.get("active_node")
            st.session_state["intent"] = output.get("intent")
            st.rerun()
            
    st.markdown("---")
    
    # Live Cart Section
    st.subheader("🛒 Current Shopping Cart")
    if sidebar_cart:
        for idx, item in enumerate(sidebar_cart):
            st.markdown(f"""
            <div class="cart-card">
                <b>{item['name']}</b> (Size {item['size']})<br/>
                {item['quantity']} x ${item['price']:.2f} = <b>${item['subtotal']:.2f}</b>
            </div>
            """, unsafe_allow_html=True)
        st.markdown(f"**Total Price: ${total_price:.2f}**")
    else:
        st.info("Your shopping cart is currently empty.")
        
    st.markdown("---")
    
    # Active Orders and Webhook Simulator Section
    st.subheader("📦 Order History")
    if customer_orders:
        for o in customer_orders:
            # Badge rendering depending on status
            badge_class = f"badge-{o['status']}"
            st.markdown(f"""
            <div class="cart-card">
                Order ID: <b>#{o['id']}</b> | Total: <b>${o['total']:.2f}</b><br/>
                Placed: {o['created_at'].strftime('%Y-%m-%d %H:%M')}<br/>
                Status: <span class="{badge_class}">{o['status'].upper()}</span>
            </div>
            """, unsafe_allow_html=True)
            
            # Show payment simulator button if status is pending_payment
            if o['status'] == "pending_payment":
                st.button(
                    f"💳 Simulate Webhook: Pay Order #{o['id']}", 
                    key=f"pay_btn_{o['id']}", 
                    on_click=simulate_webhook_payment,
                    args=(o['id'],)
                )
    else:
        st.info("No order history found.")

# --- MAIN CHAT SCREEN ---
st.markdown("<h1 class='main-title'>Vendra</h1>", unsafe_allow_html=True)
st.markdown("<p style='color: #888888; font-size: 1.1rem; margin-bottom: 2rem;'>Conversational Shopping & Recommendation Agent</p>", unsafe_allow_html=True)

# Render Chat Log
for msg in st.session_state["messages"]:
    msg_content = get_string_content(msg.content)
    if isinstance(msg, HumanMessage):
        if msg_content != "[Visual Search Photo Uploaded]":
            with st.chat_message("user"):
                st.markdown(msg_content)
    elif isinstance(msg, AIMessage):
        with st.chat_message("assistant"):
            # Render Markdown reply text
            st.markdown(msg_content)
            
            # Image parsing renderer:
            # Search for local image URLs mentioned in the text (e.g. '/static/images/some_shoe.png')
            image_matches = re.findall(r'(/static/images/\S+)', msg_content)
            if image_matches:
                cols = st.columns(len(image_matches))
                for idx, path in enumerate(image_matches):
                    # Clean trailing punctuation
                    clean_path = path.strip(").,")
                    local_filepath = "." + clean_path
                    if os.path.exists(local_filepath):
                        with cols[idx]:
                            st.image(local_filepath, width=160, caption=f"Product Option #{idx+1}")

# Handle User Input
user_input = st.chat_input("Ask Vendra about products, policies, or add shoes to cart...")

if user_input:
    # 1. Display user input
    st.session_state["messages"].append(HumanMessage(content=user_input))
    st.rerun()

# Trigger Graph Execution on new human input at end of loop
if st.session_state["messages"] and isinstance(st.session_state["messages"][-1], HumanMessage):
    with st.chat_message("assistant"):
        # Graph execution spinner
        with st.spinner("Thinking..."):
            state_input = {
                "messages": st.session_state["messages"],
                "customer_id": st.session_state["customer_id"],
                "cart_id": st.session_state["cart_id"],
                "current_order_id": st.session_state["current_order_id"],
                "image_bytes": st.session_state["uploaded_image_bytes"],
                "active_node": st.session_state["active_node"],
                "intent": st.session_state["intent"]
            }
            output = graph.invoke(state_input)
            
        # Update states
        st.session_state["messages"] = list(output["messages"])
        st.session_state["active_node"] = output.get("active_node")
        st.session_state["intent"] = output.get("intent")
        st.session_state["current_order_id"] = output.get("current_order_id")
        
        st.rerun()
