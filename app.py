import os
import re
import requests
import datetime
import streamlit as st
from langchain_core.messages import HumanMessage, AIMessage

API_URL = os.getenv("API_URL", "http://localhost:8000")

def get_auth_headers() -> dict:
    token = st.session_state.get("session_token")
    if token:
        return {"Authorization": f"Bearer {token}"}
    return {}

def api_get_cart(cart_id: str) -> list:
    try:
        res = requests.get(f"{API_URL}/api/cart/{cart_id}", headers=get_auth_headers())
        if res.status_code == 200:
            return res.json().get("items", [])
    except Exception as e:
        st.error(f"Error fetching cart: {e}")
    return []

def api_add_to_cart(cart_id: str, product_id: str, size: str, quantity: int = 1) -> bool:
    try:
        payload = {"product_id": product_id, "size": size, "quantity": quantity}
        res = requests.post(f"{API_URL}/api/cart/{cart_id}/add", json=payload, headers=get_auth_headers())
        if res.status_code != 200:
            st.error(f"Failed to add item: {res.text}")
        return res.status_code == 200
    except Exception as e:
        st.error(f"Error adding to cart: {e}")
    return False



def api_get_customer(customer_id: str) -> dict:
    try:
        res = requests.get(f"{API_URL}/api/customers/{customer_id}", headers=get_auth_headers())
        if res.status_code == 200:
            return res.json()
    except Exception as e:
        st.error(f"Error fetching customer: {e}")
    return {}

def api_get_product_details(product_id: str) -> dict:
    try:
        res = requests.get(f"{API_URL}/api/products/{product_id}/details", headers=get_auth_headers())
        if res.status_code == 200:
            return res.json()
    except Exception as e:
        st.error(f"Error fetching product details: {e}")
    return {}

def api_get_inventory() -> dict:
    try:
        res = requests.get(f"{API_URL}/api/inventory", headers=get_auth_headers())
        if res.status_code == 200:
            return res.json()
    except Exception as e:
        st.error(f"Error fetching inventory: {e}")
    return {}

def api_list_orders(customer_id: str) -> list:
    try:
        res = requests.get(f"{API_URL}/api/orders?customer_id={customer_id}", headers=get_auth_headers())
        if res.status_code == 200:
            return res.json().get("orders", [])
    except Exception as e:
        st.error(f"Error fetching orders: {e}")
    return []

def api_simulate_payment(order_id: str) -> bool:
    try:
        payload = {"order_id": order_id, "stripe_event_id": f"evt_mock_direct_{order_id}", "mock": True}
        res = requests.post(f"{API_URL}/webhook/stripe", json=payload, headers=get_auth_headers())
        return res.status_code == 200
    except Exception as e:
        st.error(f"Error simulating payment: {e}")
    return False

def call_chat_api(messages: list, customer_id: str, cart_id: str, current_order_id: str = None, active_node: str = "general", intent: str = "general", image_bytes: bytes = None) -> dict:
    import base64
    
    # Serialize messages list
    serialized_history = []
    for m in messages:
        content = get_string_content(m.content)
        if isinstance(m, HumanMessage):
            serialized_history.append({"role": "user", "content": content})
        elif isinstance(m, AIMessage):
            serialized_history.append({"role": "assistant", "content": content})
            
    # Base64 encode visual image if present
    img_b64 = None
    if image_bytes:
        img_b64 = base64.b64encode(image_bytes).decode("utf-8")
        
    payload = {
        "message": serialized_history[-1]["content"] if serialized_history else "",
        "history": serialized_history[:-1] if len(serialized_history) > 1 else [],
        "customer_id": customer_id,
        "image_bytes": img_b64,
        "active_node": active_node,
        "intent": intent,
        "current_order_id": current_order_id
    }
    
    res = requests.post(f"{API_URL}/api/chat", json=payload, headers=get_auth_headers())
    if res.status_code != 200:
        raise Exception(f"Backend chat API failed: {res.text}")
        
    data = res.json()
    # Reconstruct langchain message objects
    msg_objs = []
    for msg in data.get("messages", []):
        role = msg.get("role")
        content = msg.get("content")
        if role == "user":
            msg_objs.append(HumanMessage(content=content))
        elif role == "assistant":
            msg_objs.append(AIMessage(content=content))
            
    return {
        "messages": msg_objs,
        "active_node": data.get("active_node"),
        "intent": data.get("intent"),
        "current_order_id": data.get("current_order_id")
    }

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

def render_product_cards(products, inventory, cart_id: str, key_prefix=""):
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
        import html
        sizes_text = ", ".join(available_sizes) if available_sizes else "Out of stock"
        tags_text = " · ".join(product.get("mood_tags", [])[:3])
        img_url = product.get("image_url", "")

        escaped_name = html.escape(str(product.get("name", "")))
        escaped_tags = html.escape(str(tags_text))
        escaped_sizes = html.escape(str(sizes_text))
        escaped_img_url = html.escape(str(img_url))

        img_html = (
            f"<img src='{escaped_img_url}' style='width:100%; height:160px;"
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
                    {escaped_tags}
                </div>
                <div style="font-size:13px; font-weight:700;
                            color:#1a1a1a; margin-bottom:4px;
                            line-height:1.3;
                            display:-webkit-box;
                            -webkit-line-clamp:2;
                            -webkit-box-orient:vertical;
                            overflow:hidden;">
                    {escaped_name}
                </div>
                <div style="font-size:17px; font-weight:800;
                            color:#2563eb; margin-bottom:4px;">
                    ৳ {int(product["price"]):,}
                </div>
                <div style="font-size:10px; color:#666;
                            margin-bottom:2px;
                            white-space:nowrap; overflow:hidden;
                            text-overflow:ellipsis;">
                    📦 {escaped_sizes}
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
                size_to_add = available_sizes[0] if available_sizes else "9"
                if api_add_to_cart(cart_id, product["id"], size_to_add, 1):
                    if "cart" not in st.session_state:
                        st.session_state.cart = []
                    st.session_state.cart.append(product)
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
if "session_token" not in st.session_state:
    st.session_state["session_token"] = None
if "messages" not in st.session_state:
    st.session_state["messages"] = []
if "cart" not in st.session_state:
    st.session_state["cart"] = []
if "customer_id" not in st.session_state:
    st.session_state["customer_id"] = None
if "cart_id" not in st.session_state:
    st.session_state["cart_id"] = None
if "uploaded_image_bytes" not in st.session_state:
    st.session_state["uploaded_image_bytes"] = None
if "current_order_id" not in st.session_state:
    st.session_state["current_order_id"] = None
if "active_node" not in st.session_state:
    st.session_state["active_node"] = "general"
if "intent" not in st.session_state:
    st.session_state["intent"] = "general"

if st.session_state["session_token"] is None:
    st.markdown("<h1 style='text-align: center;'>Welcome to Vendra Shoe Store</h1>", unsafe_allow_html=True)
    st.markdown("<p style='text-align: center;'>Please login or create an account to start shopping and chatting with Vendra.</p>", unsafe_allow_html=True)
    
    col1, col2, col3 = st.columns([1, 2, 1])
    with col2:
        tab1, tab2 = st.tabs(["🔐 Login", "📝 Sign Up"])
        
        with tab1:
            login_email = st.text_input("Email", key="login_email")
            login_password = st.text_input("Password", type="password", key="login_password")
            if st.button("Log In", use_container_width=True):
                if not login_email or not login_password:
                    st.error("Please enter both email and password.")
                else:
                    try:
                        res = requests.post(f"{API_URL}/api/auth/login", json={"email": login_email, "password": login_password})
                        if res.status_code == 200:
                            data = res.json()
                            st.session_state["session_token"] = data["token"]
                            st.session_state["customer_id"] = data["customer_id"]
                            st.session_state["cart_id"] = f"cart_{data['customer_id']}"
                            st.success(f"Welcome back, {data['name']}!")
                            st.rerun()
                        else:
                            st.error(f"Login failed: {res.json().get('detail', 'Invalid email or password')}")
                    except Exception as e:
                        st.error(f"Error connecting to backend: {e}")
                        
        with tab2:
            signup_name = st.text_input("Full Name", key="signup_name")
            signup_email = st.text_input("Email Address", key="signup_email")
            signup_password = st.text_input("Password", type="password", key="signup_password")
            signup_phone = st.text_input("Phone Number (Optional)", key="signup_phone")
            signup_address = st.text_input("Delivery Address (Optional)", key="signup_address")
            
            if st.button("Sign Up", use_container_width=True):
                if not signup_name or not signup_email or not signup_password:
                    st.error("Name, email, and password are required.")
                else:
                    try:
                        res = requests.post(f"{API_URL}/api/auth/signup", json={
                            "name": signup_name,
                            "email": signup_email,
                            "password": signup_password,
                            "phone": signup_phone,
                            "address": signup_address
                        })
                        if res.status_code == 200:
                            data = res.json()
                            st.session_state["session_token"] = data["token"]
                            st.session_state["customer_id"] = data["customer_id"]
                            st.session_state["cart_id"] = f"cart_{data['customer_id']}"
                            st.success(f"Account created successfully! Welcome, {data['name']}!")
                            st.rerun()
                        else:
                            st.error(f"Signup failed: {res.json().get('detail', 'Could not create account')}")
                    except Exception as e:
                        st.error(f"Error connecting to backend: {e}")
    st.stop()

# Handle query parameters (product selection and cart additions from card clicks)
if "select_product" in st.query_params:
    selected_prod_id = st.query_params["select_product"]
    st.query_params.clear()
    
    prod_details = api_get_product_details(selected_prod_id)
    if prod_details:
        user_message = f"Tell me more about {prod_details['name']} (ID: {selected_prod_id}), including available sizes and colors."
        st.session_state["messages"].append(HumanMessage(content=user_message))
        st.rerun()

if "add_to_cart" in st.query_params:
    prod_id = st.query_params["add_to_cart"]
    st.query_params.clear()
    
    prod_details = api_get_product_details(prod_id)
    if prod_details:
        # Get first available size
        inventory = api_get_inventory()
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
        
        # Sync with Vendra's CARTS manager via API
        cart_id = st.session_state["cart_id"]
        if api_add_to_cart(cart_id, prod_id, size_to_add, 1):
            st.success(f"Added {prod_details['name']} to cart!")
            st.rerun()

def get_sidebar_data():
    cust_id = st.session_state["customer_id"]
    cart_id = st.session_state["cart_id"]
    
    cust = api_get_customer(cust_id)
    
    cart_items = api_get_cart(cart_id)
    cart_details = []
    cart_total = 0.0
    for item in cart_items:
        prod_id = item["product_id"]
        size = item["size"]
        qty = item["quantity"]
        
        details = api_get_product_details(prod_id)
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
            
    orders = api_list_orders(cust_id)
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
    except Exception as e:
        if api_simulate_payment(order_id):
            st.success(f"Direct Adapter Payment simulated! Order #{order_id} marked as PAID.")
            st.rerun()
        else:
            st.error(f"Payment simulation failed: {e}")

# --- SIDEBAR PRESENTATION ---
with st.sidebar:
    st.image("https://cdn-icons-png.flaticon.com/512/3159/3159066.png", width=65)
    st.markdown("<h2 style='margin-top: 0;'>Vendra Assistant</h2>", unsafe_allow_html=True)
    
    if customer:
        st.markdown(f"👤 **Customer Profile**\n- **Name:** {customer['name']}\n- **Email:** {customer['email']}\n- **ID:** {customer['id']}")
        if st.button("🚪 Log Out", use_container_width=True):
            st.session_state["session_token"] = None
            st.session_state["customer_id"] = None
            st.session_state["cart_id"] = None
            st.session_state["messages"] = []
            st.session_state["cart"] = []
            st.rerun()
        
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
            
            with st.spinner("Comparing visual CLIP embeddings..."):
                try:
                    output = call_chat_api(
                        messages=st.session_state["messages"],
                        customer_id=st.session_state["customer_id"],
                        cart_id=st.session_state["cart_id"],
                        current_order_id=st.session_state["current_order_id"],
                        active_node="browsing",
                        intent="browsing",
                        image_bytes=file_bytes
                    )
                    st.session_state["messages"] = list(output["messages"])
                    st.session_state["active_node"] = output.get("active_node")
                    st.session_state["intent"] = output.get("intent")
                except Exception as e:
                    st.error(f"Failed to communicate with Vendra backend: {e}")
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
                
                # Fetch inventory details via API
                inventory = api_get_inventory()
                render_product_cards(products, inventory, st.session_state["cart_id"], key_prefix=f"msg_{msg_idx}")
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
        try:
            output = call_chat_api(
                messages=st.session_state["messages"],
                customer_id=st.session_state["customer_id"],
                cart_id=st.session_state["cart_id"],
                current_order_id=st.session_state["current_order_id"],
                active_node=st.session_state["active_node"],
                intent=st.session_state["intent"],
                image_bytes=st.session_state["uploaded_image_bytes"]
            )
            st.session_state["messages"] = list(output["messages"])
            st.session_state["active_node"] = output.get("active_node")
            st.session_state["intent"] = output.get("intent")
            st.session_state["current_order_id"] = output.get("current_order_id")
        except Exception as e:
            st.error(f"Failed to communicate with Vendra backend: {e}")
    st.rerun()
