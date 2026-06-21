import os
import json
import datetime
from database import SessionLocal
from models import Order, OrderItem, ProductVariant
from tools import retrieve_policy_text, check_cancellation_eligibility, cancel_order

def main():
    print("--- Vendra Phase 6 Policy and Cancellation Test ---")
    
    db = SessionLocal()
    try:
        customer_id = 1
        
        # We need a product variant to bind to orders
        variant = db.query(ProductVariant).filter(ProductVariant.product_id == 3, ProductVariant.size == "8").first()
        initial_stock = variant.stock_quantity
        print(f"Current stock of variant ID {variant.id}: {initial_stock}")
        
        # 1. Test retrieve_policy_text tool
        policy_res = retrieve_policy_text.invoke({"query": "cancellation window"})
        print(f"\n[Policy retrieval result for 'cancellation window']:\n{policy_res[:300]}...\n")
        assert "cancellation" in policy_res.lower() or "refund" in policy_res.lower(), "Policy search should yield return policy text!"
        
        # 2. Case 1: Order created 3 days ago (eligible for full refund)
        order_recent = Order(
            customer_id=customer_id,
            cart_id=998,
            total_price=85.00,
            status="paid",
            created_at=datetime.datetime.utcnow() - datetime.timedelta(days=3)
        )
        db.add(order_recent)
        db.flush()
        
        item_recent = OrderItem(order_id=order_recent.id, product_variant_id=variant.id, quantity=1, price_at_purchase=85.00)
        db.add(item_recent)
        db.commit()
        
        print(f"Created recent order #{order_recent.id} (placed 3 days ago).")
        
        # Check eligibility
        elig_recent = json.loads(check_cancellation_eligibility.invoke({"order_id": order_recent.id}))
        print(f"Recent order eligibility: {elig_recent}")
        assert elig_recent["eligible"] is True, "Recent order should be eligible for cancellation!"
        assert elig_recent["refund_type"] == "full_refund", "Recent order should yield full refund!"
        
        # Execute cancellation
        cancel_recent_res = cancel_order.invoke({"order_id": order_recent.id})
        print(f"Recent order cancellation output: {cancel_recent_res}")
        db.refresh(order_recent)
        assert order_recent.status == "refunded", "Recent order status should be refunded!"
        
        # Check stock restoration
        db.refresh(variant)
        print(f"Stock after recent order cancel: {variant.stock_quantity}")
        assert variant.stock_quantity == initial_stock + 1, "Stock was not restored!"
        
        # Reset stock check variable
        initial_stock = variant.stock_quantity
        
        # 3. Case 2: Order created 8 days ago (eligible for store credit)
        order_old = Order(
            customer_id=customer_id,
            cart_id=999,
            total_price=85.00,
            status="paid",
            created_at=datetime.datetime.utcnow() - datetime.timedelta(days=8)
        )
        db.add(order_old)
        db.flush()
        
        item_old = OrderItem(order_id=order_old.id, product_variant_id=variant.id, quantity=1, price_at_purchase=85.00)
        db.add(item_old)
        db.commit()
        
        print(f"\nCreated old order #{order_old.id} (placed 8 days ago).")
        
        # Check eligibility
        elig_old = json.loads(check_cancellation_eligibility.invoke({"order_id": order_old.id}))
        print(f"Old order eligibility: {elig_old}")
        assert elig_old["eligible"] is False, "Old order should NOT be eligible for full refund cancellation!"
        assert elig_old["refund_type"] == "store_credit", "Old order should yield store credit!"
        
        # Execute cancellation (cancel_order handles store_credit by marking status cancelled)
        cancel_old_res = cancel_order.invoke({"order_id": order_old.id})
        print(f"Old order cancellation output: {cancel_old_res}")
        db.refresh(order_old)
        assert order_old.status == "cancelled", "Old order status should be cancelled (store credit)!"
        
        # Check stock restoration
        db.refresh(variant)
        print(f"Stock after old order cancel: {variant.stock_quantity}")
        assert variant.stock_quantity == initial_stock + 1, "Stock was not restored!"
        
        print("\nPolicy and Cancellation Test Passed Successfully!")
        
    finally:
        db.close()

if __name__ == "__main__":
    main()
