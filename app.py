import os
import re
import requests
import datetime
import streamlit as st
from langchain_core.messages import HumanMessage, AIMessage

from agent.graph import graph
from agent.tools import adapter, CARTS, confirm_payment, update_cart_activity

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

def parse_message_for_products(content: str):
    """
    Parses product recommendations from an assistant response block.
    Extracts name, ID, price, image path, and description.
    """
    # Normalize bullet points (asterisks or numbers) to dash bullets
    normalized = content
    normalized = re.sub(r'^\s*[\*\-]\s+\*\*', '- **', normalized, flags=re.MULTILINE)
    normalized = re.sub(r'^\s*\d+[\.\s]+\*\*', '- **', normalized, flags=re.MULTILINE)
    
    if "- **" not in normalized:
        return content, [], ""
        
    first_prod_idx = normalized.find("- **")
    intro_text = normalized[:first_prod_idx].strip()
    
    products_and_after = normalized[first_prod_idx:]
    blocks = products_and_after.split("- **")
    products = []
    after_text = ""
    
    for i, block in enumerate(blocks):
        if not block.strip():
            continue
            
        lines = block.split("\n")
        name_line = lines[0]
        if "**" in name_line:
            parts = name_line.split("**")
            name = parts[0].strip()
            rest = parts[1]
        else:
            name = name_line.strip()
            rest = ""
            
        id_match = re.search(r'\(ID:\s*([^)]+)\)', rest)
        product_id = id_match.group(1).strip() if id_match else ""
        
        price_match = re.search(r'Price:\s*([^\n]+)', block)
        price_str = price_match.group(1).strip() if price_match else "0"
        
        price_val = 0.0
        try:
            price_val = float(re.sub(r'[^\d.]', '', price_str))
        except ValueError:
            pass
            
        # Skip promotions that leaked into product format
        if price_val == 0:
            continue
        if any(kw in name for kw in
            ["Sale", "Deal", "Promo", "Offer", "Discount"]):
            continue
            
        img_match = re.search(r'(https?://\S+|/?static/images/\S+)', block)
        image_url = img_match.group(1).strip(").,") if img_match else ""
        
        tags_match = re.search(r'Tags:\s*([^\n]+)', block)
        tags_list = []
        if tags_match:
            tags_list = [t.strip() for t in tags_match.group(1).split(",")]
            
        desc_lines = []
        for line in lines[1:]:
            line_strip = line.strip()
            if not line_strip:
                continue
            if line_strip.startswith("Price:") or line_strip.startswith("Image:") or line_strip.startswith("Image URL:") or line_strip.startswith("Tags:"):
                continue
            if any(kw in line_strip for kw in ["Want me to filter", "Active Promotions:", "Promotions:", "Would you like", "Shall I"]):
                continue
            desc_lines.append(line_strip)
            
        description = " ".join(desc_lines)
        products.append({
            "id": product_id,
            "name": name,
            "price": price_val,
            "image_url": image_url,
            "mood_tags": tags_list,
            "description": description
        })
        
    # After the for loop ends, extract after_text from full content
    after_keywords = [
        "Want me to filter",
        "Active Promotions:",
        "Promotions:",
        "Would you like",
        "Shall I"
    ]
    after_text = ""
    for keyword in after_keywords:
        idx = normalized.find(keyword)
        if idx != -1:
            after_text = normalized[idx:].strip()
            break
            
    return intro_text, products, after_text

def render_product_cards(products, inventory, key_prefix=""):
    if not products:
        return

    # Inject CSS to make columns horizontally scrollable
    st.markdown("""
    <style>
    [data-testid="stHorizontalBlock"] {
        overflow-x: auto !important;
        flex-wrap: nowrap !important;
        padding-bottom: 12px;
        scrollbar-width: thin;
        scrollbar-color: #2563eb #f0f0f0;
        -webkit-overflow-scrolling: touch;
    }
    [data-testid="stHorizontalBlock"] > div {
        min-width: 200px !important;
        max-width: 200px !important;
        flex-shrink: 0 !important;
    }
    </style>
    """, unsafe_allow_html=True)

    cols = st.columns(len(products))

    for i, product in enumerate(products):
        available_sizes = [
            size for size, qty in
            inventory.get(product["id"], {}).items()
            if int(qty) > 0
        ]
        sizes_text = ", ".join(available_sizes) if available_sizes else "Out of stock"
        tags_text = " · ".join(product.get("mood_tags", [])[:3])
        img_url = product.get("image_url", "")

        img_html = (
            f"<img src='{img_url}' style='width:100%; height:160px;"
            f"object-fit:cover; border-radius:12px 12px 0 0;'/>"
            if img_url else
            "<div style='width:100%; height:160px; display:flex;"
            "align-items:center; justify-content:center;"
            "font-size:48px; background:#f5f5f5;"
            "border-radius:12px 12px 0 0;'>👟</div>"
        )

        card_html = f"""
        <div style="
            background: #ffffff;
            border: 1px solid #e8e8e8;
            border-radius: 16px;
            overflow: hidden;
            box-shadow: 0 2px 12px rgba(0,0,0,0.08);
            width: 100%;
        ">
            {img_html}
            <div style="padding: 10px 12px 6px 12px;">
                <div style="font-size:10px; color:#999;
                            margin-bottom:3px;
                            white-space:nowrap; overflow:hidden;
                            text-overflow:ellipsis;">
                    {tags_text}
                </div>
                <div style="font-size:13px; font-weight:700;
                            color:#1a1a1a; margin-bottom:4px;
                            line-height:1.3;
                            display:-webkit-box;
                            -webkit-line-clamp:2;
                            -webkit-box-orient:vertical;
                            overflow:hidden;">
                    {product["name"]}
                </div>
                <div style="font-size:17px; font-weight:800;
                            color:#2563eb; margin-bottom:4px;">
                    ৳ {int(product["price"]):,}
                </div>
                <div style="font-size:10px; color:#666;
                            margin-bottom:2px;
                            white-space:nowrap; overflow:hidden;
                            text-overflow:ellipsis;">
                    📦 {sizes_text}
                </div>
            </div>
        </div>
        """

        with cols[i]:
            st.markdown(card_html, unsafe_allow_html=True)
            if st.button(
                "🛒 Add to Cart",
                key=f"cart_{key_prefix}_{product['id']}_{i}",
                use_container_width=True
            ):
                if "cart" not in st.session_state:
                    st.session_state.cart = []
                st.session_state.cart.append(product)
                cart_id = st.session_state["cart_id"]
                if cart_id not in CARTS:
                    CARTS[cart_id] = []
                size_to_add = available_sizes[0] if available_sizes else "9"
                existing = next(
                    (item for item in CARTS[cart_id]
                     if item["product_id"] == product["id"]
                     and item["size"] == size_to_add), None
                )
                if existing:
                    existing["quantity"] += 1
                else:
                    CARTS[cart_id].append({
                        "product_id": product["id"],
                        "size": size_to_add,
                        "quantity": 1
                    })
                update_cart_activity(cart_id)
                st.success(f"✅ {product['name']} added to cart!")
                st.rerun()


# Set Page Config
st.set_page_config(
    page_title="Vendra — Conversational Shoe Store Agent",
    page_icon="👟",
    layout="wide",
    initial_sidebar_state="expanded"
)

# Custom styling for high-visibility light theme
st.markdown("""
<style>
    .stApp {
        background-color: #ffffff;
        color: #1a1a1a;
        font-family: 'Inter', sans-serif;
    }
    h1, h2, h3 {
        font-family: 'Outfit', sans-serif;
        color: #1a1a1a !important;
        font-weight: 700;
    }
    .main-title {
        background: linear-gradient(135deg, #2563eb 0%, #3b82f6 100%);
        -webkit-background-clip: text;
        -webkit-text-fill-color: transparent;
        font-size: 3.2rem;
        margin-bottom: 0.2rem;
    }
    
    /* Force chat messages to have readable background */
    .stChatMessage {
        background-color: #f8f9fa !important;
        border-radius: 12px;
        margin-bottom: 0.75rem;
        padding: 1rem;
    }
    
    /* User chat bubble */
    div[data-testid="stChatMessageUser"] {
        background-color: #e8f0fe !important;
        color: #1a1a1a !important;
        border-left: 5px solid #2563eb;
    }
    
    /* Assistant chat bubble */
    div[data-testid="stChatMessageAssistant"] {
        background-color: #f1f3f5 !important;
        color: #1a1a1a !important;
        border-left: 5px solid #ff9966;
    }
    
    /* Fix any black overlay on containers */
    div[data-testid="stVerticalBlock"] > div {
        background: transparent !important;
    }
    
    /* Make sure buttons are visible */
    .stButton > button {
        background-color: #2563eb !important;
        color: white !important;
        border: none !important;
        border-radius: 8px !important;
        font-weight: 600 !important;
    }
    
    .stButton > button:hover {
        background-color: #1d4ed8 !important;
        color: white !important;
    }
    
    /* Chat input styling */
    .stChatInputContainer {
        border-top: 1px solid #e0e0e0;
    }
    
    section[data-testid="stSidebar"] {
        background-color: #f8f9fa !important;
        border-right: 1px solid #e0e0e0;
        color: #1a1a1a;
    }
    
    .cart-card {
        background-color: #ffffff;
        border-radius: 8px;
        padding: 0.75rem;
        margin-bottom: 0.5rem;
        border: 1px solid #e0e0e0;
        color: #1a1a1a;
    }
    
    .badge-paid {
        background-color: #10B981;
        color: white;
        padding: 0.15rem 0.4rem;
        border-radius: 4px;
        font-size: 0.75rem;
    }
    .badge-pending_payment {
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
if "cart" not in st.session_state:
    st.session_state["cart"] = []
if "customer_id" not in st.session_state:
    st.session_state["customer_id"] = "C001"
if "cart_id" not in st.session_state:
    st.session_state["cart_id"] = f"cart_{st.session_state['customer_id']}"
if "uploaded_image_bytes" not in st.session_state:
    st.session_state["uploaded_image_bytes"] = None
if "current_order_id" not in st.session_state:
    st.session_state["current_order_id"] = None
if "active_node" not in st.session_state:
    st.session_state["active_node"] = "general"
if "intent" not in st.session_state:
    st.session_state["intent"] = "general"

# Handle query parameters (product selection and cart additions from card clicks)
if "select_product" in st.query_params:
    selected_prod_id = st.query_params["select_product"]
    st.query_params.clear()
    
    prod_details = adapter.get_product_details(selected_prod_id)
    if prod_details:
        user_message = f"Tell me more about {prod_details['name']} (ID: {selected_prod_id}), including available sizes and colors."
        st.session_state["messages"].append(HumanMessage(content=user_message))
        st.rerun()

if "add_to_cart" in st.query_params:
    prod_id = st.query_params["add_to_cart"]
    st.query_params.clear()
    
    prod_details = adapter.get_product_details(prod_id)
    if prod_details:
        # Get first available size
        inventory = getattr(adapter, "inventory", {})
        available_sizes = [
            size for size, qty in 
            inventory.get(prod_id, {}).items() 
            if int(qty) > 0
        ]
        size_to_add = available_sizes[0] if available_sizes else "9"
        
        # Add to session state cart
        if "cart" not in st.session_state:
            st.session_state.cart = []
        st.session_state.cart.append(prod_details)
        
        # Sync with Vendra's CARTS manager
        cart_id = st.session_state["cart_id"]
        if cart_id not in CARTS:
            CARTS[cart_id] = []
            
        existing = next((item for item in CARTS[cart_id] if item["product_id"] == prod_id and item["size"] == size_to_add), None)
        if existing:
            existing["quantity"] += 1
        else:
            CARTS[cart_id].append({
                "product_id": prod_id,
                "size": size_to_add,
                "quantity": 1
            })
        update_cart_activity(cart_id)
        st.success(f"Added {prod_details['name']} to cart!")
        st.rerun()

def get_sidebar_data():
    cust_id = st.session_state["customer_id"]
    cart_id = st.session_state["cart_id"]
    
    cust = next((c for c in adapter.customers if c["id"] == cust_id), None)
    
    cart_items = CARTS.get(cart_id, [])
    cart_details = []
    cart_total = 0.0
    for item in cart_items:
        prod_id = item["product_id"]
        size = item["size"]
        qty = item["quantity"]
        
        details = adapter.get_product_details(prod_id)
        if details:
            subtotal = details["price"] * qty
            cart_total += subtotal
            cart_details.append({
                "name": details["name"],
                "size": size,
                "quantity": qty,
                "price": details["price"],
                "subtotal": subtotal
            })
            
    orders = [o for o in adapter.orders.values() if o["customer_id"] == cust_id]
    try:
        orders.sort(key=lambda x: x.get("created_at", ""), reverse=True)
    except Exception:
        pass
        
    return cust, cart_details, cart_total, orders

customer, sidebar_cart, total_price, customer_orders = get_sidebar_data()

def simulate_webhook_payment(order_id: str):
    payload = {
        "order_id": order_id,
        "stripe_event_id": f"evt_mock_streamlit_{order_id}",
        "mock": True
    }
    backend_url = os.getenv("BACKEND_URL", "http://localhost:8000")
    try:
        response = requests.post(f"{backend_url.rstrip('/')}/webhook/stripe", json=payload, timeout=3)
        if response.status_code == 200:
            st.success(f"Webhook simulated! Order #{order_id} is marked as PAID.")
            st.rerun()
        else:
            st.error(f"FastAPI Webhook endpoint failed: {response.text}")
    except Exception:
        res = confirm_payment(order_id, f"evt_mock_direct_{order_id}")
        st.success(f"Direct Adapter Payment simulated! Order #{order_id} marked as PAID. {res}")
        st.rerun()

# --- SIDEBAR PRESENTATION ---
with st.sidebar:
    st.image("https://cdn-icons-png.flaticon.com/512/3159/3159066.png", width=65)
    st.markdown("<h2 style='margin-top: 0;'>Vendra Assistant</h2>", unsafe_allow_html=True)
    
    cust_options = [c["id"] for c in adapter.customers]
    if not cust_options:
        cust_options = ["C001", "C002", "C003", "C004", "C005"]
    default_idx = 0
    if st.session_state.get("customer_id") in cust_options:
        default_idx = cust_options.index(st.session_state["customer_id"])
        
    selected_cust_id = st.selectbox(
        "Select Active Customer Profile:",
        options=cust_options,
        index=default_idx
    )
    if selected_cust_id != st.session_state["customer_id"]:
        st.session_state["customer_id"] = selected_cust_id
        st.session_state["cart_id"] = f"cart_{selected_cust_id}"
        st.rerun()
        
    if customer:
        st.markdown(f"👤 **Customer Profile**\n- **Name:** {customer['name']}\n- **Email:** {customer['email']}\n- **ID:** {customer['id']}")
        
    st.markdown("---")
    
    st.subheader("📷 Visual Search (CLIP)")
    uploaded_file = st.file_uploader(
        "Upload a shoe photo to find matches:", 
        type=["png", "jpg", "jpeg"], 
        key="visual_search_uploader"
    )
    
    if uploaded_file is not None:
        file_bytes = uploaded_file.read()
        
        if st.session_state["uploaded_image_bytes"] != file_bytes:
            st.session_state["uploaded_image_bytes"] = file_bytes
            st.image(uploaded_file, caption="Uploaded query image", use_container_width=True)
            
            st.session_state["messages"].append(HumanMessage(content="[Visual Search Photo Uploaded]"))
            
            state_input = {
                "messages": st.session_state["messages"],
                "customer_id": st.session_state["customer_id"],
                "cart_id": st.session_state["cart_id"],
                "current_order_id": st.session_state["current_order_id"],
                "image_bytes": file_bytes,
                "active_node": "browsing",
                "intent": "browsing"
            }
            
            with st.spinner("Comparing visual CLIP embeddings..."):
                output = graph.invoke(state_input)
                
            st.session_state["messages"] = list(output["messages"])
            st.session_state["active_node"] = output.get("active_node")
            st.session_state["intent"] = output.get("intent")
            st.rerun()
            
    st.markdown("---")
    
    st.subheader("🛒 Current Shopping Cart")
    if sidebar_cart:
        for item in sidebar_cart:
            st.markdown(f"""
            <div class="cart-card">
                <b>{item['name']}</b> (Size {item['size']})<br/>
                {item['quantity']} x {item['price']:.0f} BDT = <b>{item['subtotal']:.0f} BDT</b>
            </div>
            """, unsafe_allow_html=True)
        st.markdown(f"**Total Price: {total_price:.0f} BDT**")
    else:
        st.info("Your shopping cart is currently empty.")
        
    st.markdown("---")
    
    st.subheader("📦 Order History")
    if customer_orders:
        for o in customer_orders:
            badge_class = f"badge-{o['status']}"
            created_at_str = o["created_at"]
            if isinstance(created_at_str, str):
                created_at_str = created_at_str.replace("T", " ")[:16]
            st.markdown(f"""
            <div class="cart-card">
                Order ID: <b>#{o['id']}</b> | Total: <b>{o['total']:.0f} BDT</b><br/>
                Date: {created_at_str}<br/>
                Status: <span class="{badge_class}">{o['status'].upper()}</span>
            </div>
            """, unsafe_allow_html=True)
            
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
st.markdown("<p style='color: #8A8A93; font-size: 1.1rem; margin-bottom: 2rem;'>Conversational Commerce Assistant powered by the Adapter Pattern</p>", unsafe_allow_html=True)

# Render Chat Log
for msg_idx, msg in enumerate(st.session_state["messages"]):
    msg_content = get_string_content(msg.content)
    if isinstance(msg, HumanMessage):
        if msg_content != "[Visual Search Photo Uploaded]":
            with st.chat_message("user"):
                st.markdown(msg_content)
    elif isinstance(msg, AIMessage):
        if not msg_content.strip():
            continue
        with st.chat_message("assistant"):
            intro, products, after = parse_message_for_products(msg_content)
            if products:
                if intro:
                    st.markdown(intro)
                
                # Fetch inventory details from adapter
                inventory = getattr(adapter, "inventory", {})
                render_product_cards(products, inventory, key_prefix=f"msg_{msg_idx}")
                if after:
                    st.markdown(after)
            else:
                st.markdown(msg_content)

# Handle User Input
user_input = st.chat_input("Ask Vendra about products, sizing, policies, or manage your cart...")

if user_input:
    st.session_state["messages"].append(HumanMessage(content=user_input))
    st.rerun()

# Trigger Graph Execution on new human input at end of loop
if st.session_state["messages"] and isinstance(
    st.session_state["messages"][-1], HumanMessage
):
    with st.spinner("Vendra is thinking..."):
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

    st.session_state["messages"] = list(output["messages"])
    st.session_state["active_node"] = output.get("active_node")
    st.session_state["intent"] = output.get("intent")
    st.session_state["current_order_id"] = output.get("current_order_id")
    st.rerun()
