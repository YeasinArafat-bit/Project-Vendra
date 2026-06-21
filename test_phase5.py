from database import SessionLocal
from models import Order
from tools import track_order

def main():
    print("--- Vendra Phase 5 Customer-Scope Tracking Test ---")
    
    db = SessionLocal()
    try:
        # Find any order in the DB (like the one created in Phase 4 test)
        order = db.query(Order).first()
        if not order:
            print("No orders found in database to run tracking tests. Please run test_phase4.py first!")
            return
            
        order_id = order.id
        owner_id = order.customer_id
        non_owner_id = owner_id + 1
        
        print(f"Testing tracking for Order ID: #{order_id} (Owned by Customer ID: {owner_id})")
        
        # Case 1: Owner tracks order (should pass)
        owner_res = track_order.invoke({"order_id": order_id, "customer_id": owner_id})
        print(f"\n[Case 1: Owner Tracking Request]\nResult:\n{owner_res}")
        assert "Order Tracking Details:" in owner_res, "Owner should have access to order details!"
        
        # Case 2: Non-owner tracks order (should fail/be refused)
        non_owner_res = track_order.invoke({"order_id": order_id, "customer_id": non_owner_id})
        print(f"\n[Case 2: Non-Owner Tracking Request (Customer {non_owner_id})]\nResult:\n{non_owner_res}")
        assert "Refused" in non_owner_res or "Access denied" in non_owner_res, "Non-owner should be refused access!"
        
        print("\nScope Tracking Test Passed Successfully!")
    finally:
        db.close()

if __name__ == "__main__":
    main()
