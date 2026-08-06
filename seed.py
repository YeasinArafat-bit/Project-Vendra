import os
import sys
import json
import random
from datetime import datetime, timedelta

# Ensure the root directory is on the path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from agent.search_service import seed_vector_store
from adapters import get_adapter

def reset_default_json_files():
    base_dir = os.path.dirname(os.path.abspath(__file__))
    data_dir = os.path.join(base_dir, "data")
    
    # 1. Reset customers.json
    from agent.auth_utils import hash_password
    default_pw_hash = hash_password("password123")
    customers_data = [
        {"id": "C001", "name": "Alice Test", "email": "alice@test.com", "phone": "123", "address": "Alice St", "store_credit": 0.0},
        {"id": "C002", "name": "Bob Test", "email": "bob@test.com", "phone": "456", "address": "Bob St", "store_credit": 0.0},
        {"id": "C003", "name": "Imran Hossain", "email": "imran@email.bd", "phone": "01711223344", "address": "Dhanmondi, Dhaka", "store_credit": 0.0},
        {"id": "C004", "name": "Fahmida Rahman", "email": "fahmida@email.bd", "phone": "01811223344", "address": "Banani, Dhaka", "store_credit": 500.0},
        {"id": "C005", "name": "Tanvir Islam", "email": "tanvir@email.bd", "phone": "01911223344", "address": "GEC Circle, Chittagong", "store_credit": 0.0},
        {"id": "C006", "name": "Anika Tabassum", "email": "anika@email.bd", "phone": "01511223344", "address": "Zindabazar, Sylhet", "store_credit": 1000.0},
        {"id": "C007", "name": "Sajid Hasan", "email": "sajid@email.bd", "phone": "01611223344", "address": "Rajshahi Court, Rajshahi", "store_credit": 0.0},
        {"id": "C008", "name": "Nusrat Jahan", "email": "nusrat@email.bd", "phone": "01311223344", "address": "Sonadanga, Khulna", "store_credit": 0.0},
        {"id": "C009", "name": "Ariful Hoque", "email": "arif@email.bd", "phone": "01411223344", "address": "Chashara, Narayanganj", "store_credit": 0.0},
        {"id": "C010", "name": "Sabrina Yasmin", "email": "sabrina@email.bd", "phone": "01799887766", "address": "Uttara, Dhaka", "store_credit": 150.0},
        {"id": "C011", "name": "Mehedi Hasan", "email": "mehedi@email.bd", "phone": "01899887766", "address": "Halishahar, Chittagong", "store_credit": 0.0},
        {"id": "C012", "name": "Tasnim Akter", "email": "tasnim@email.bd", "phone": "01999887766", "address": "Shibganj, Sylhet", "store_credit": 0.0},
        {"id": "C013", "name": "Ashraful Islam", "email": "ashraful@email.bd", "phone": "01599887766", "address": "Sathkhira, Khulna", "store_credit": 200.0},
        {"id": "C014", "name": "Farhana Chowdhury", "email": "farhana@email.bd", "phone": "01699887766", "address": "Agrabad, Chittagong", "store_credit": 0.0},
        {"id": "C015", "name": "Mushfiqur Rahman", "email": "mushfiq@email.bd", "phone": "01399887766", "address": "Mirpur, Dhaka", "store_credit": 0.0},
        {"id": "C016", "name": "Jannatul Firdous", "email": "jannat@email.bd", "phone": "01499887766", "address": "Comilla Cantt, Comilla", "store_credit": 0.0},
        {"id": "C017", "name": "Mahmudul Hasan", "email": "mahmud@email.bd", "phone": "01722334455", "address": "Barisal Sadar, Barisal", "store_credit": 0.0},
        {"id": "C018", "name": "Rifat Ara", "email": "rifat@email.bd", "phone": "01822334455", "address": "Mymensingh Town, Mymensingh", "store_credit": 0.0},
        {"id": "C019", "name": "Niaz Morshed", "email": "niaz@email.bd", "phone": "01922334455", "address": "Cox's Bazar Sadar, Cox's Bazar", "store_credit": 0.0},
        {"id": "C020", "name": "Zarin Tasnim", "email": "zarin@email.bd", "phone": "01522334455", "address": "Bogra Sadar, Bogra", "store_credit": 350.0}
    ]
    for c in customers_data:
        c["password_hash"] = default_pw_hash
        
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
        product_ids = [f"P{i:03d}" for i in range(1, 71)]
        
    inventory_data = {}
    random.seed(42)
    for pid in product_ids:
        sizes = ["6", "7", "8", "9", "10", "11"]
        pid_stock = {}
        for sz in sizes:
            if pid == "P001" and sz == "9":
                pid_stock[sz] = 0
            elif pid == "P003" and sz == "11":
                pid_stock[sz] = 0
            else:
                pid_stock[sz] = random.randint(5, 20)
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
    
    products_list = []
    if os.path.exists(products_path):
        try:
            with open(products_path, "r", encoding="utf-8") as f:
                products_list = json.load(f)
        except Exception:
            pass
            
    if products_list:
        statuses = ["completed", "completed", "completed", "paid", "pending_payment", "cancelled"]
        start_date = datetime(2026, 6, 1)
        for i in range(4, 36):
            order_id = f"ORD{i:03d}"
            cust = random.choice(customers_data[2:])
            num_items = random.choice([1, 2])
            order_items = []
            total_price = 0.0
            chosen_prods = random.sample(products_list, num_items)
            for p in chosen_prods:
                size = random.choice(["7", "8", "9", "10"])
                qty = random.choice([1, 2])
                item_price = p["price"]
                total_price += item_price * qty
                order_items.append({
                    "product_id": p["id"],
                    "name": p["name"],
                    "size": size,
                    "quantity": qty,
                    "price": item_price
                })
            status = random.choice(statuses)
            stripe_id = f"pi_mock_{100 + i}" if status in ["paid", "completed", "cancelled"] else None
            days_offset = random.randint(0, 65)
            created_time = start_date + timedelta(days=days_offset, hours=random.randint(8, 20), minutes=random.randint(0, 59))
            orders_data[order_id] = {
                "id": order_id,
                "customer_id": cust["id"],
                "items": order_items,
                "total": total_price,
                "status": status,
                "stripe_payment_intent_id": stripe_id,
                "created_at": created_time.strftime("%Y-%m-%dT%H:%M:%SZ")
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
    
    couriers = ["Pathao", "Steadfast", "Redx", "eCourier"]
    for order_id, o in orders_data.items():
        if order_id in ["ORD002", "ORD003"]:
            continue
        status = o["status"]
        created_time = datetime.strptime(o["created_at"], "%Y-%m-%dT%H:%M:%SZ")
        courier = random.choice(couriers)
        prefix = "SF" if courier == "Steadfast" else "PTH" if courier == "Pathao" else "RDX" if courier == "Redx" else "EC"
        track_code = f"{prefix}-{random.randint(1000000, 9999999)}"
        est_delivery = created_time + timedelta(days=3)
        tracking_status = "processing"
        timeline = [{"time": o["created_at"], "event": "Order placed and payment confirmed" if status != "pending_payment" else "Order created pending payment"}]
        
        if status == "completed":
            tracking_status = "delivered"
            t1 = (created_time + timedelta(days=1)).strftime("%Y-%m-%dT%H:%M:%SZ")
            t2 = (created_time + timedelta(days=2)).strftime("%Y-%m-%dT%H:%M:%SZ")
            t3 = (created_time + timedelta(days=3)).strftime("%Y-%m-%dT%H:%M:%SZ")
            timeline.append({"time": t1, "event": "Package picked up by courier"})
            timeline.append({"time": t2, "event": "In transit to delivery hub"})
            timeline.append({"time": t3, "event": "Delivered to customer"})
        elif status == "paid":
            tracking_status = "in_transit"
            t1 = (created_time + timedelta(days=1)).strftime("%Y-%m-%dT%H:%M:%SZ")
            timeline.append({"time": t1, "event": "Package picked up by courier"})
        elif status == "cancelled":
            tracking_status = "cancelled"
            timeline.append({"time": o["created_at"], "event": "Order cancelled by customer or admin"})
            
        tracking_data[order_id] = {
            "order_id": order_id,
            "courier": courier,
            "tracking_code": track_code,
            "status": tracking_status,
            "estimated_delivery": est_delivery.strftime("%Y-%m-%dT%H:%M:%SZ"),
            "timeline": timeline
        }
        
    with open(os.path.join(data_dir, "tracking.json"), "w", encoding="utf-8") as f:
        json.dump(tracking_data, f, indent=2)

def main():
    from config import validate_config
    validate_config()
    
    # Drop old SQLite DB if it exists to refresh schema with password_hash column
    db_url = os.getenv("DATABASE_URL", "sqlite:///data/vendra.db")
    if "sqlite" in db_url.lower():
        db_path = db_url.replace("sqlite:///", "")
        if os.path.exists(db_path):
            try:
                os.remove(db_path)
                print(f"Removed old SQLite database at {db_path} to apply schema changes.")
            except Exception as e:
                print(f"Warning: Could not remove old SQLite database: {e}")
                
    print("Initializing Vendra Vector Store...")
    seed_vector_store()
    
    print("\nResetting default JSON database files...")
    reset_default_json_files()
    
    print("\nInitializing Adapter State...")
    adapter = get_adapter()
    adapter.reset_state()
    
    from adapters.postgres_adapter import PostgresAdapter
    if isinstance(adapter, PostgresAdapter):
        print("Seeding PostgreSQL/SQLite database from JSON files...")
        base_dir = os.path.dirname(os.path.abspath(__file__))
        data_dir = os.path.join(base_dir, "data")
        
        with open(os.path.join(data_dir, "products.json"), "r", encoding="utf-8") as f:
            adapter.products = json.load(f)
            
        with open(os.path.join(data_dir, "inventory.json"), "r", encoding="utf-8") as f:
            adapter.inventory = json.load(f)
            
        with open(os.path.join(data_dir, "customers.json"), "r", encoding="utf-8") as f:
            adapter.customers = json.load(f)
            
        with open(os.path.join(data_dir, "orders.json"), "r", encoding="utf-8") as f:
            adapter.orders = json.load(f)
            
        with open(os.path.join(data_dir, "tracking.json"), "r", encoding="utf-8") as f:
            adapter.tracking = json.load(f)
            
        with open(os.path.join(data_dir, "promotions.json"), "r", encoding="utf-8") as f:
            adapter.promotions = json.load(f)
            
        print("Database seeded successfully.")
    else:
        print("JSON Adapter state loaded successfully.")
    
    print("\nInitialization Complete!")

if __name__ == "__main__":
    main()
