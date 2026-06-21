import os
from database import SessionLocal
from models import Cart, CartItem, ProductVariant, Order
from tools import create_order, create_payment_link
from fastapi.testclient import TestClient
from api import app

def main():
    print("--- Vendra Phase 4 Webhook and Checkout Test ---")
    
    # 1. Setup Test client for FastAPI webhook
    client = TestClient(app)
    
    db = SessionLocal()
    try:
        # Get Alice (Customer ID 1)
        customer_id = 1
        
        # Verify product variant stock
        # CloudWalk Runner (Product 3), Size 8
        variant = db.query(ProductVariant).filter(
            ProductVariant.product_id == 3,
            ProductVariant.size == "8"
        ).first()
        
        initial_stock = variant.stock_quantity
        print(f"Initial stock of CloudWalk Runner (Size 8): {initial_stock}")
        
        # Create a new active cart
        cart = Cart(customer_id=customer_id, status="active")
        db.add(cart)
        db.commit()
        db.refresh(cart)
        
        # Add 3 units of size 8 to cart
        cart_item = CartItem(cart_id=cart.id, product_variant_id=variant.id, quantity=3)
        db.add(cart_item)
        db.commit()
        
        print(f"Created cart #{cart.id} with 3 units of variant ID {variant.id}.")
        
        # 2. Call create_order tool (reserves stock)
        res = create_order.invoke({"customer_id": customer_id, "cart_id": cart.id})
        print(f"create_order result: {res}")
        
        # Retrieve the created order
        order = db.query(Order).filter(Order.cart_id == cart.id).first()
        assert order is not None, "Order was not created!"
        order_id = order.id
        print(f"Created Order ID: {order_id}, Status: {order.status}")
        
        # Verify stock subtraction
        db.refresh(variant)
        print(f"Stock after order creation: {variant.stock_quantity}")
        assert variant.stock_quantity == initial_stock - 3, "Stock was not properly reserved!"
        
        # 3. Call create_payment_link tool
        pay_res = create_payment_link.invoke({"order_id": order_id})
        print(f"create_payment_link result: {pay_res}")
        
        # 4. Trigger mock webhook (marks paid)
        event_id = "evt_test_checkout_complete_999"
        webhook_payload = {
            "order_id": order_id,
            "stripe_event_id": event_id,
            "mock": True
        }
        
        response = client.post("/webhook/stripe", json=webhook_payload)
        print(f"Webhook response: {response.json()}")
        
        db.refresh(order)
        print(f"Order status after webhook: {order.status}")
        assert order.status == "paid", "Order should be marked as paid!"
        assert order.stripe_event_id == event_id, "Stripe event ID was not saved!"
        
        # 5. Trigger webhook again with SAME event_id (idempotency check)
        dup_response = client.post("/webhook/stripe", json=webhook_payload)
        print(f"Duplicate Webhook response: {dup_response.json()}")
        assert "already processed" in dup_response.json()["message"] or "idempotent" in dup_response.json()["message"], "Duplicate event was not ignored!"
        
        print("Webhook and Checkout Test Passed Successfully!")
        
    finally:
        db.close()

if __name__ == "__main__":
    main()
