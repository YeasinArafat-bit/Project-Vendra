import os
import sys
import json

# Ensure the root directory is on the path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from agent.search_service import seed_vector_store
from adapters import get_adapter

def reset_default_json_files():
    base_dir = os.path.dirname(os.path.abspath(__file__))
    data_dir = os.path.join(base_dir, "data")
    
    # 1. Reset customers.json
    customers_data = [
        {"id": "C001", "name": "Alice Test", "email": "alice@test.com", "phone": "123", "address": "Alice St", "store_credit": 0.0},
        {"id": "C002", "name": "Bob Test", "email": "bob@test.com", "phone": "456", "address": "Bob St", "store_credit": 0.0}
    ]
    with open(os.path.join(data_dir, "customers.json"), "w", encoding="utf-8") as f:
        json.dump(customers_data, f, indent=2)
        
    # 2. Reset inventory.json based on products.json
    products_path = os.path.join(data_dir, "products.json")
    product_ids = []
    if os.path.exists(products_path):
        try:
            with open(products_path, "r", encoding="utf-8") as f:
                prods = json.load(f)
                product_ids = [p["id"] for p in prods]
        except Exception:
            pass
    if not product_ids:
        product_ids = [f"P{i:03d}" for i in range(1, 21)]
        
    inventory_data = {}
    for pid in product_ids:
        sizes = ["6", "7", "8", "9", "10", "11"]
        pid_stock = {}
        for sz in sizes:
            if pid == "P001" and sz == "9":
                pid_stock[sz] = 0
            elif pid == "P003" and sz == "11":
                pid_stock[sz] = 0
            else:
                pid_stock[sz] = 10
        inventory_data[pid] = pid_stock
        
    with open(os.path.join(data_dir, "inventory.json"), "w", encoding="utf-8") as f:
        json.dump(inventory_data, f, indent=2)
        
    # 3. Reset orders.json
    orders_data = {
        "ORD002": {
            "id": "ORD002",
            "customer_id": "C001",
            "items": [
                {"product_id": "P001", "size": "10", "quantity": 1, "price": 4500.0}
            ],
            "total": 4500.0,
            "status": "paid",
            "stripe_payment_intent_id": "pi_mock_222",
            "created_at": "2026-07-01T15:00:00Z"
        },
        "ORD003": {
            "id": "ORD003",
            "customer_id": "C001",
            "items": [
                {"product_id": "P002", "size": "8", "quantity": 1, "price": 5500.0}
            ],
            "total": 5500.0,
            "status": "pending_payment",
            "stripe_payment_intent_id": None,
            "created_at": "2026-07-05T12:00:00Z"
        }
    }
    with open(os.path.join(data_dir, "orders.json"), "w", encoding="utf-8") as f:
        json.dump(orders_data, f, indent=2)
        
    # 4. Reset tracking.json
    tracking_data = {
        "ORD002": {
            "order_id": "ORD002",
            "courier": "Steadfast",
            "tracking_code": "SF-9982718",
            "status": "in_transit",
            "estimated_delivery": "2026-07-04T18:00:00Z",
            "timeline": [
                {"time": "2026-07-01T15:00:00Z", "event": "Order placed and payment confirmed"},
                {"time": "2026-07-02T10:00:00Z", "event": "Package picked up by courier"}
            ]
        },
        "ORD003": {
            "order_id": "ORD003",
            "courier": "Pathao",
            "tracking_code": "PTH-882718A",
            "status": "processing",
            "estimated_delivery": "2026-07-08T18:00:00Z",
            "timeline": [
                {"time": "2026-07-05T12:00:00Z", "event": "Order created pending payment"}
            ]
        }
    }
    with open(os.path.join(data_dir, "tracking.json"), "w", encoding="utf-8") as f:
        json.dump(tracking_data, f, indent=2)

def main():
    print("Initializing Vendra Vector Store...")
    seed_vector_store()
    
    print("\nResetting default JSON database files...")
    reset_default_json_files()
    
    print("\nInitializing JSON Adapter State...")
    adapter = get_adapter()
    adapter.reset_state()
    print("JSON Adapter state loaded successfully.")
    
    print("\nInitialization Complete!")

if __name__ == "__main__":
    main()
