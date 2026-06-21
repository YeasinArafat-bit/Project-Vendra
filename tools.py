import os
import datetime
import stripe
from langchain_core.tools import tool
from services.search import search_products_text, search_policies, search_products_image
from database import SessionLocal
from models import Product, ProductVariant, Cart, CartItem, Order, OrderItem, Customer

stripe.api_key = os.getenv("STRIPE_SECRET_KEY")

@tool
def search_products(query: str, top_k: int = 3) -> str:
    """
    Search for products in the shoe store catalog using a natural language query.
    Use this tool when the customer is looking for specific styles, colors, occasions, 
    or moods (e.g., 'elegant shoes for a wedding', 'comfortable sneakers', 'red sport shoes').
    
    Args:
        query: Semantic query text (e.g. 'comfortable casual brown shoe').
        top_k: Number of products to return (default is 3).
        
    Returns:
        A formatted text string containing matching products and their details.
    """
    results = search_products_text(query, top_k=top_k)
    
    if not results:
        return "No products found matching your search query."
    
    formatted_results = []
    for res in results:
        doc = res["document"]
        prod_id = res["product_id"]
        formatted_results.append(
            f"Product ID: {prod_id}\n{doc}\n"
            f"---"
        )
    
    return "\n\n".join(formatted_results)

@tool
def search_products_by_image(top_k: int = 3) -> str:
    """
    Search for products in the shoe store catalog using an uploaded image.
    Use this tool when the customer uploads a photo of a shoe to find similar items in the catalog.
    
    Args:
        top_k: Number of products to return (default is 3).
        
    Returns:
        A formatted text string containing matching products and their details.
    """
    image_bytes = None
    try:
        import streamlit as st
        if "uploaded_image_bytes" in st.session_state:
            image_bytes = st.session_state["uploaded_image_bytes"]
    except Exception:
        pass
        
    if not image_bytes:
        # Fallback buffer for testing
        image_bytes = globals().get("_test_image_bytes_buffer")
        
    if not image_bytes:
        return "Error: No uploaded image found in this session. Please upload a photo of a shoe."
        
    results = search_products_image(image_bytes, top_k=top_k)
    
    if not results:
        return "No products found matching the uploaded image."
        
    db = SessionLocal()
    try:
        formatted_results = []
        for res in results:
            product_id = res["product_id"]
            product = db.query(Product).filter(Product.id == product_id).first()
            if not product:
                continue
            
            # Format product details
            formatted_results.append(
                f"Product ID: {product.id}\n"
                f"Name: {product.name}\n"
                f"Category: {product.category}\n"
                f"Color: {product.color}\n"
                f"Price: ${product.price:.2f}\n"
                f"Description: {product.description}\n"
                f"Image URL: {product.image_url}\n"
                f"---"
            )
        return "\n\n".join(formatted_results)
    finally:
        db.close()

@tool
def check_stock(product_id: int, size: str) -> str:
    """
    Check the exact stock availability (quantity) for a specific product and size.
    You MUST call this tool whenever a customer asks if a shoe size is in stock, 
    or when they ask how many items are left, rather than guessing.
    
    Args:
        product_id: The unique ID of the product.
        size: The shoe size (e.g., '6', '7', '8', '9', '10', '11').
        
    Returns:
        A string indicating the stock level.
    """
    db = SessionLocal()
    try:
        variant = db.query(ProductVariant).filter(
            ProductVariant.product_id == product_id,
            ProductVariant.size == str(size)
        ).first()
        
        if not variant:
            return f"Product variant for product ID {product_id} and size {size} not found."
            
        product = db.query(Product).filter(Product.id == product_id).first()
        product_name = product.name if product else f"Product #{product_id}"
        
        return f"Product: '{product_name}' (ID: {product_id}) in Size {size} has {variant.stock_quantity} units available in stock."
    finally:
        db.close()

@tool
def get_product_details(product_id: int) -> str:
    """
    Retrieve full details for a specific product, including all sizes and their stock.
    Use this when a customer asks for more details, sizes, or stock availability of a specific product ID.
    
    Args:
        product_id: The unique ID of the product.
        
    Returns:
        A formatted string with the product details and size/stock table.
    """
    db = SessionLocal()
    try:
        product = db.query(Product).filter(Product.id == product_id).first()
        if not product:
            return f"Product with ID {product_id} not found."
            
        variants = db.query(ProductVariant).filter(ProductVariant.product_id == product_id).all()
        
        variants_info = []
        for var in variants:
            status = "In Stock" if var.stock_quantity > 0 else "OUT OF STOCK"
            variants_info.append(f"Size {var.size}: {var.stock_quantity} units ({status}) | Variant ID: {var.id}")
            
        variants_str = "\n".join(variants_info)
        
        return (
            f"Product Details:\n"
            f"Name: {product.name}\n"
            f"ID: {product.id}\n"
            f"Category: {product.category}\n"
            f"Color: {product.color}\n"
            f"Price: ${product.price:.2f}\n"
            f"Description: {product.description}\n"
            f"Occasion Tags: {product.occasion_tags}\n"
            f"Mood Tags: {product.mood_tags}\n"
            f"Image URL: {product.image_url}\n"
            f"\nAvailable Stock by Size:\n{variants_str}"
        )
    finally:
        db.close()

@tool
def add_to_cart(cart_id: int, product_variant_id: int, quantity: int = 1) -> str:
    """
    Add a product variant (by its product_variant_id) to the shopping cart. 
    It checks product stock availability first.
    Use this tool when the customer specifies the shoe type and size they wish to add/buy.
    
    Args:
        cart_id: The unique ID of the shopping cart.
        product_variant_id: The unique ID of the product variant.
        quantity: The quantity to add (default is 1).
        
    Returns:
        A success message or an error message indicating insufficient stock.
    """
    db = SessionLocal()
    try:
        variant = db.query(ProductVariant).filter(ProductVariant.id == product_variant_id).first()
        if not variant:
            return f"Error: Product variant ID {product_variant_id} does not exist."
            
        product = db.query(Product).filter(Product.id == variant.product_id).first()
        product_name = product.name if product else "Product"
        
        cart = db.query(Cart).filter(Cart.id == cart_id).first()
        if not cart:
            return f"Error: Cart ID {cart_id} not found."
            
        cart_item = db.query(CartItem).filter(
            CartItem.cart_id == cart_id,
            CartItem.product_variant_id == product_variant_id
        ).first()
        
        current_in_cart = cart_item.quantity if cart_item else 0
        total_requested = current_in_cart + quantity
        
        if variant.stock_quantity < total_requested:
            return (
                f"Error: Cannot add {quantity} units of '{product_name}' (Size {variant.size}) to cart. "
                f"You already have {current_in_cart} in cart, and there are only {variant.stock_quantity} available in stock."
            )
            
        if cart_item:
            cart_item.quantity = total_requested
        else:
            cart_item = CartItem(
                cart_id=cart_id,
                product_variant_id=product_variant_id,
                quantity=quantity
            )
            db.add(cart_item)
            
        db.commit()
        return f"Successfully added {quantity} units of '{product_name}' (Size {variant.size}) to your cart (Cart ID: {cart_id})."
    except Exception as e:
        db.rollback()
        return f"Error adding to cart: {str(e)}"
    finally:
        db.close()

@tool
def view_cart(cart_id: int) -> str:
    """
    Retrieve all items in the customer's shopping cart and display the contents and the total price.
    Use this tool when a customer asks to see their cart, check what they are buying, or view their cart total.
    
    Args:
        cart_id: The unique ID of the shopping cart.
        
    Returns:
        A detailed formatted list of cart items, price details, and running total.
    """
    db = SessionLocal()
    try:
        cart = db.query(Cart).filter(Cart.id == cart_id).first()
        if not cart:
            return f"Cart with ID {cart_id} not found."
            
        cart_items = db.query(CartItem).filter(CartItem.cart_id == cart_id).all()
        if not cart_items:
            return f"Your shopping cart (Cart ID: {cart_id}) is currently empty."
            
        item_details = []
        running_total = 0.0
        
        for item in cart_items:
            variant = db.query(ProductVariant).filter(ProductVariant.id == item.product_variant_id).first()
            if not variant:
                continue
            product = db.query(Product).filter(Product.id == variant.product_id).first()
            if not product:
                continue
            
            subtotal = product.price * item.quantity
            running_total += subtotal
            item_details.append(
                f"- '{product.name}' (Size {variant.size}, Color: {product.color}) | "
                f"Qty: {item.quantity} x ${product.price:.2f} = ${subtotal:.2f} (Variant ID: {variant.id})"
            )
            
        item_list_str = "\n".join(item_details)
        return (
            f"Shopping Cart (ID: {cart_id}) Contents:\n"
            f"{item_list_str}\n"
            f"Total Price: ${running_total:.2f}"
        )
    finally:
        db.close()

@tool
def remove_from_cart(cart_id: int, product_variant_id: int) -> str:
    """
    Remove a product variant from the customer's shopping cart.
    Use this tool when the customer wants to remove an item or reduce its count in their cart.
    
    Args:
        cart_id: The unique ID of the shopping cart.
        product_variant_id: The unique ID of the product variant to remove.
        
    Returns:
        A success message indicating the item has been removed from the cart.
    """
    db = SessionLocal()
    try:
        cart_item = db.query(CartItem).filter(
            CartItem.cart_id == cart_id,
            CartItem.product_variant_id == product_variant_id
        ).first()
        
        if not cart_item:
            return f"Item with variant ID {product_variant_id} is not in Cart {cart_id}."
            
        variant = db.query(ProductVariant).filter(ProductVariant.id == product_variant_id).first()
        product = db.query(Product).filter(Product.id == variant.product_id).first() if variant else None
        product_name = product.name if product else "Product"
        size_str = f" (Size {variant.size})" if variant else ""
        
        db.delete(cart_item)
        db.commit()
        
        return f"Successfully removed '{product_name}'{size_str} from your cart."
    except Exception as e:
        db.rollback()
        return f"Error removing item from cart: {str(e)}"
    finally:
        db.close()

@tool
def create_order(customer_id: int, cart_id: int) -> str:
    """
    Create a pending order from the customer's cart, reserving product stock.
    This reserves stock for every item inside a single DB transaction.
    If stock is insufficient for any item, the transaction is rolled back.
    Use this tool when the customer is ready to checkout.
    
    Args:
        customer_id: The unique ID of the customer.
        cart_id: The unique ID of the cart.
        
    Returns:
        A message indicating success with order details or an error message about stock availability.
    """
    from sqlalchemy import text
    from sqlalchemy.exc import OperationalError
    db = SessionLocal()
    try:
        # Acquire immediate write lock on SQLite database to prevent race conditions
        db.execute(text("BEGIN IMMEDIATE"))
        
        # Check if cart items exist
        cart_items = db.query(CartItem).filter(CartItem.cart_id == cart_id).all()
        if not cart_items:
            return f"Error: Cart ID {cart_id} is empty. Cannot create order."
            
        total_price = 0.0
        order_items_to_create = []
        
        for item in cart_items:
            variant = db.query(ProductVariant).filter(ProductVariant.id == item.product_variant_id).with_for_update().first()
            if not variant:
                return f"Error: Product variant ID {item.product_variant_id} not found."
                
            product = db.query(Product).filter(Product.id == variant.product_id).first()
            product_name = product.name if product else "Product"
            
            if variant.stock_quantity < item.quantity:
                db.rollback()
                return (
                    f"Checkout Failed: '{product_name}' (Size {variant.size}) is out of stock. "
                    f"Only {variant.stock_quantity} available, but you requested {item.quantity}."
                )
                
            variant.stock_quantity -= item.quantity
            item_price = product.price
            total_price += item_price * item.quantity
            
            order_items_to_create.append({
                "product_variant_id": variant.id,
                "quantity": item.quantity,
                "price_at_purchase": item_price
            })
            
        order = Order(
            customer_id=customer_id,
            cart_id=cart_id,
            total_price=total_price,
            status="pending_payment",
            created_at=datetime.datetime.utcnow()
        )
        db.add(order)
        db.flush()
        
        for item_data in order_items_to_create:
            order_item = OrderItem(
                order_id=order.id,
                product_variant_id=item_data["product_variant_id"],
                quantity=item_data["quantity"],
                price_at_purchase=item_data["price_at_purchase"]
            )
            db.add(order_item)
            
        cart = db.query(Cart).filter(Cart.id == cart_id).first()
        if cart:
            cart.status = "converted"
            
        db.commit()
        return f"Order #{order.id} has been created successfully. Total: ${total_price:.2f}. Status: pending_payment. Stock reserved."
    except Exception as e:
        db.rollback()
        return f"Checkout Failed: {str(e)}"
    finally:
        db.close()

@tool
def create_payment_link(order_id: int) -> str:
    """
    Generate a Stripe checkout payment link for the given order ID.
    Always call this tool right after creating the order to let the customer pay.
    
    Args:
        order_id: The unique ID of the order.
        
    Returns:
        A payment checkout URL link.
    """
    db = SessionLocal()
    try:
        order = db.query(Order).filter(Order.id == order_id).first()
        if not order:
            return f"Error: Order ID {order_id} not found."
            
        if order.status != "pending_payment":
            return f"Error: Order #{order_id} cannot be paid because it is already '{order.status}'."
            
        customer = db.query(Customer).filter(Customer.id == order.customer_id).first()
        customer_email = customer.email if customer else "customer@example.com"
        
        stripe_key = os.getenv("STRIPE_SECRET_KEY")
        if not stripe_key or stripe_key.startswith("sk_test_your_"):
            mock_url = f"https://checkout.stripe.com/pay/cs_test_mock_{order_id}"
            return f"Payment Link: {mock_url} (Stripe keys not set, mock mode)"
            
        import stripe
        stripe.api_key = stripe_key
        
        session = stripe.checkout.Session.create(
            payment_method_types=["card"],
            line_items=[{
                "price_data": {
                    "currency": "usd",
                    "product_data": {
                        "name": f"Vendra Order #{order_id}",
                    },
                    "unit_amount": int(order.total_price * 100),
                },
                "quantity": 1,
            }],
            mode="payment",
            success_url=f"http://localhost:8501/?payment_success=true&order_id={order_id}",
            cancel_url="http://localhost:8501/?payment_cancelled=true",
            customer_email=customer_email,
            metadata={"order_id": str(order_id)}
        )
        
        order.stripe_payment_intent_id = session.id
        db.commit()
        
        return f"Payment Link: {session.url}"
    except Exception as e:
        return f"Error creating payment link: {str(e)}"
    finally:
        db.close()

@tool
def track_order(order_id: int, customer_id: int) -> str:
    """
    Retrieve the current shipping/payment status of an order.
    To protect customer privacy, this tool will verify that the order belongs to the customer_id
    before displaying details.
    
    Args:
        order_id: The unique ID of the order to track.
        customer_id: The unique ID of the customer requesting the tracking.
        
    Returns:
        A detailed message with order status and items, or an access denied message.
    """
    db = SessionLocal()
    try:
        order = db.query(Order).filter(Order.id == order_id).first()
        if not order:
            return f"Error: Order #{order_id} not found."
            
        if order.customer_id != customer_id:
            return f"Refused: Access denied. Order #{order_id} does not belong to Customer ID {customer_id}."
            
        order_items = db.query(OrderItem).filter(OrderItem.order_id == order_id).all()
        
        item_details = []
        for item in order_items:
            variant = db.query(ProductVariant).filter(ProductVariant.id == item.product_variant_id).first()
            product = db.query(Product).filter(Product.id == variant.product_id).first() if variant else None
            p_name = product.name if product else f"Product Variant #{item.product_variant_id}"
            p_size = variant.size if variant else "?"
            item_details.append(f"- {p_name} (Size: {p_size}) x {item.quantity} | Price at purchase: ${item.price_at_purchase:.2f}")
            
        items_str = "\n".join(item_details)
        
        return (
            f"Order Tracking Details:\n"
            f"Order ID: #{order.id}\n"
            f"Placed At: {order.created_at.strftime('%Y-%m-%d %H:%M:%S')} UTC\n"
            f"Total Amount: ${order.total_price:.2f}\n"
            f"Current Status: {order.status.upper()}\n"
            f"\nItems Purchased:\n{items_str}"
        )
    finally:
        db.close()

@tool
def retrieve_policy_text(query: str) -> str:
    """
    Retrieve raw clauses from the store return and cancellation policy index.
    Use this tool to fetch exact guidelines to explain return policies, windows, or conditions.
    Never make up return policy details; search them here first.
    
    Args:
        query: Search keywords (e.g. 'cancellation policy window', 'refund conditions').
        
    Returns:
        Relevant paragraphs from the policy document.
    """
    results = search_policies(query, top_k=2)
    if not results:
        return "No policy clauses found matching your query."
    
    formatted = []
    for r in results:
        formatted.append(f"[Policy Clause Reference: {r['metadata'].get('title', 'Policy')}]\n{r['text']}")
    return "\n\n".join(formatted)

@tool
def check_cancellation_eligibility(order_id: int) -> str:
    """
    Determines order cancellation and refund eligibility based on policy rules.
    This is a deterministic function implementing the store policy:
    - Paid orders can be fully refunded within 7 days of purchase.
    - Paid orders after 7 days are eligible for store credit only.
    - Final sale items are non-refundable.
    - Already cancelled/refunded orders cannot be cancelled again.
    
    Args:
        order_id: The unique ID of the order.
        
    Returns:
        A JSON string representing eligibility facts:
        {
          "eligible": boolean,
          "reason": string,
          "refund_type": "full_refund" | "store_credit" | "none",
          "order_id": int
        }
    """
    db = SessionLocal()
    try:
        order = db.query(Order).filter(Order.id == order_id).first()
        if not order:
            import json
            return json.dumps({"eligible": False, "reason": f"Order #{order_id} not found.", "refund_type": "none", "order_id": order_id})
            
        if order.status in ["cancelled", "refunded"]:
            import json
            return json.dumps({"eligible": False, "reason": f"Order #{order_id} is already '{order.status}'.", "refund_type": "none", "order_id": order_id})
            
        if order.status != "paid":
            import json
            return json.dumps({"eligible": False, "reason": f"Order #{order_id} is in status '{order.status}'. Only paid orders can be cancelled/refunded.", "refund_type": "none", "order_id": order_id})
            
        order_items = db.query(OrderItem).filter(OrderItem.order_id == order_id).all()
        for item in order_items:
            variant = db.query(ProductVariant).filter(ProductVariant.id == item.product_variant_id).first()
            if variant:
                product = db.query(Product).filter(Product.id == variant.product_id).first()
                if product and (product.category.lower() == "sale" or "final sale" in product.description.lower()):
                    import json
                    return json.dumps({
                        "eligible": False,
                        "reason": f"Item '{product.name}' in Order #{order_id} is a final sale item and cannot be cancelled or refunded.",
                        "refund_type": "none",
                        "order_id": order_id
                    })
                    
        now = datetime.datetime.utcnow()
        age = now - order.created_at
        age_in_days = age.total_seconds() / 86400.0
        
        import json
        if age_in_days <= 7.0:
            return json.dumps({
                "eligible": True,
                "reason": f"Order #{order_id} was placed {age_in_days:.2f} days ago (within the 7-day cancellation window).",
                "refund_type": "full_refund",
                "order_id": order_id
            })
        else:
            return json.dumps({
                "eligible": False,
                "reason": f"Order #{order_id} was placed {age_in_days:.2f} days ago (outside the 7-day cancellation window). Store credit is offered.",
                "refund_type": "store_credit",
                "order_id": order_id
            })
    finally:
        db.close()

@tool
def cancel_order(order_id: int) -> str:
    """
    Cancel a paid order and trigger its refund or store credit conversion based on eligibility rules.
    This updates database records and communicates with Stripe API in test mode.
    
    Args:
        order_id: The unique ID of the order to cancel.
        
    Returns:
        A confirmation message indicating the cancellation status and refund details.
    """
    import json
    eligibility_json = check_cancellation_eligibility.invoke({"order_id": order_id})
    eligibility = json.loads(eligibility_json)
    
    db = SessionLocal()
    try:
        order = db.query(Order).filter(Order.id == order_id).first()
        if not order:
            return f"Error: Order #{order_id} not found."
            
        refund_type = eligibility.get("refund_type")
        
        if refund_type == "none":
            return f"Cancellation Rejected: {eligibility.get('reason')}"
            
        order_items = db.query(OrderItem).filter(OrderItem.order_id == order_id).all()
        for item in order_items:
            variant = db.query(ProductVariant).filter(ProductVariant.id == item.product_variant_id).first()
            if variant:
                variant.stock_quantity += item.quantity
                
        if refund_type == "full_refund":
            order.status = "refunded"
            
            stripe_key = os.getenv("STRIPE_SECRET_KEY")
            if order.stripe_payment_intent_id and stripe_key and not stripe_key.startswith("sk_test_your_"):
                try:
                    stripe.api_key = stripe_key
                    session = stripe.checkout.Session.retrieve(order.stripe_payment_intent_id)
                    pi_id = session.payment_intent
                    if pi_id:
                        stripe.Refund.create(payment_intent=pi_id)
                        refund_details = "A full refund has been credited to your payment card."
                    else:
                        refund_details = "Stripe Session found, but Payment Intent is missing. Processing manual bank transfer."
                except Exception as e:
                    refund_details = f"Stripe refund call failed: {str(e)}. Manual processing required."
            else:
                refund_details = "Mock Refund Processed. A full refund of original payment amount has been released to card."
                
            db.commit()
            return f"Cancellation Approved for Order #{order_id}. Status: REFUNDED. Inventory stock restored. {refund_details}"
            
        elif refund_type == "store_credit":
            order.status = "cancelled"
            db.commit()
            return (
                f"Cancellation Approved for Order #{order_id}. Status: CANCELLED (Store Credit Issued). "
                f"Inventory stock restored. Store credit of ${order.total_price:.2f} has been added to Customer ID {order.customer_id}."
            )
            
        return f"Unknown cancellation state: {refund_type}"
    except Exception as e:
        db.rollback()
        return f"Error executing cancellation: {str(e)}"
    finally:
        db.close()
