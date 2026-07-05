import os
import json
import uuid
import datetime
import threading
from adapters.base import BaseAdapter, AdapterError

# File paths
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA_DIR = os.path.join(BASE_DIR, "data")

class JSONAdapter(BaseAdapter):
    _instance = None
    _lock = threading.Lock()

    def __new__(cls, *args, **kwargs):
        with cls._lock:
            if not cls._instance:
                cls._instance = super(JSONAdapter, cls).__new__(cls, *args, **kwargs)
                cls._instance.initialized = False
            return cls._instance

    def __init__(self) -> None:
        if getattr(self, 'initialized', False):
            return
        self.lock = threading.Lock()
        self.reset_state()
        self.initialized = True

    def reset_state(self) -> None:
        """
        Reload state from JSON files. Essential for test isolation.
        """
        with self.lock:
            # Load products
            with open(os.path.join(DATA_DIR, "products.json"), "r", encoding="utf-8") as f:
                self.products = json.load(f)
            
            # Load inventory
            with open(os.path.join(DATA_DIR, "inventory.json"), "r", encoding="utf-8") as f:
                self.inventory = json.load(f)
                
            # Load customers
            with open(os.path.join(DATA_DIR, "customers.json"), "r", encoding="utf-8") as f:
                self.customers = json.load(f)
                # Ensure store_credit field exists
                for c in self.customers:
                    if "store_credit" not in c:
                        c["store_credit"] = 0.0
                
            # Load orders
            with open(os.path.join(DATA_DIR, "orders.json"), "r", encoding="utf-8") as f:
                self.orders = json.load(f)
                
            # Load tracking
            with open(os.path.join(DATA_DIR, "tracking.json"), "r", encoding="utf-8") as f:
                self.tracking = json.load(f)
                
            # Load promotions
            with open(os.path.join(DATA_DIR, "promotions.json"), "r", encoding="utf-8") as f:
                self.promotions = json.load(f)

    def _atomic_save(self, filename: str, data: dict | list) -> None:
        """
        Write data atomically: write to a temp file, then rename/replace.
        """
        filepath = os.path.join(DATA_DIR, filename)
        temppath = filepath + ".tmp"
        try:
            with open(temppath, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=2, ensure_ascii=False)
            os.replace(temppath, filepath)
        except Exception as e:
            if os.path.exists(temppath):
                try:
                    os.remove(temppath)
                except Exception:
                    pass
            raise AdapterError(f"Atomic file write failed for {filename}: {e}")

    def _save_state_locked(self) -> None:
        """
        Write state back to files atomically. Must be called holding self.lock.
        """
        self._atomic_save("orders.json", self.orders)
        self._atomic_save("inventory.json", self.inventory)
        self._atomic_save("tracking.json", self.tracking)
        self._atomic_save("customers.json", self.customers)

    def get_products(self, query: str = None) -> list:
        # Return all products. Semantic filtering happens in vector search / search service
        return self.products

    def check_stock(self, product_id: str, size: str) -> int:
        size_str = str(size).strip()
        with self.lock:
            product_stock = self.inventory.get(product_id, {})
            return int(product_stock.get(size_str, 0))

    def get_product_details(self, product_id: str) -> dict:
        with self.lock:
            for p in self.products:
                if p["id"] == product_id:
                    stock_info = self.inventory.get(product_id, {})
                    p_copy = p.copy()
                    p_copy["variants"] = [{"size": sz, "stock": qty} for sz, qty in stock_info.items()]
                    return p_copy
            return {}

    def create_order(self, customer_id: str, cart: list) -> dict:
        """
        Thread-safe order creation with stock reservation.
        If stock is unavailable, raises a ValueError.
        """
        with self.lock:
            # Validate customer
            customer_exists = any(c["id"] == customer_id for c in self.customers)
            if not customer_exists:
                raise ValueError(f"Customer ID '{customer_id}' not found.")

            # Validate and check stock for all cart items atomically
            for item in cart:
                prod_id = item["product_id"]
                sz = str(item["size"])
                qty = item["quantity"]
                
                if prod_id not in self.inventory or sz not in self.inventory[prod_id]:
                    raise ValueError(f"Product '{prod_id}' or size '{sz}' does not exist.")
                
                available_stock = self.inventory[prod_id][sz]
                if available_stock < qty:
                    raise ValueError(f"Insufficient stock for product '{prod_id}' size '{sz}'. Requested: {qty}, Available: {available_stock}")

            # Decrement stock for all items
            items_list = []
            total = 0.0
            for item in cart:
                prod_id = item["product_id"]
                sz = str(item["size"])
                qty = item["quantity"]
                
                # Decrement inventory stock
                self.inventory[prod_id][sz] -= qty
                
                # Fetch product price
                price = 0.0
                for p in self.products:
                    if p["id"] == prod_id:
                        price = p["price"]
                        break
                
                total += price * qty
                items_list.append({
                    "product_id": prod_id,
                    "size": sz,
                    "quantity": qty,
                    "price": price
                })

            # Create Order
            order_id = f"ORD{str(uuid.uuid4())[:8].upper()}"
            now = datetime.datetime.now(datetime.timezone.utc).isoformat()
            
            new_order = {
                "id": order_id,
                "customer_id": customer_id,
                "items": items_list,
                "total": total,
                "status": "pending_payment",
                "stripe_payment_intent_id": None,
                "created_at": now
            }
            
            # Save in-memory
            self.orders[order_id] = new_order
            
            # Create default tracking record
            self.tracking[order_id] = {
                "order_id": order_id,
                "courier": "Pathao",
                "tracking_code": f"PTH-{str(uuid.uuid4())[:8].upper()}",
                "status": "processing",
                "estimated_delivery": (datetime.datetime.now(datetime.timezone.utc) + datetime.timedelta(days=3)).isoformat(),
                "timeline": [
                    { "time": now, "event": "Order created pending payment" }
                ]
            }
            
            # Persist mutations to disk
            self._save_state_locked()
            
            return new_order

    def track_order(self, order_id: str, customer_id: str) -> dict:
        """
        Track order, verifying that customer_id matches the order owner.
        Allows lookup by normalized order ID or courier tracking code.
        """
        with self.lock:
            query_str = str(order_id).strip()
            normalized_query = query_str.replace(" ", "").replace("-", "").upper()
            
            resolved_order_id = None
            
            # 1. Search in orders by normalized ID
            for oid in self.orders.keys():
                if oid.replace(" ", "").replace("-", "").upper() == normalized_query:
                    resolved_order_id = oid
                    break
                    
            # 2. If not found, search in tracking by normalized tracking code
            if not resolved_order_id:
                for oid, track in self.tracking.items():
                    track_code = str(track.get("tracking_code", "")).strip().replace(" ", "").replace("-", "").upper()
                    if track_code == normalized_query:
                        resolved_order_id = oid
                        break
                        
            if not resolved_order_id:
                return {"error": f"Order ID '{order_id}' not found."}
                
            order = self.orders.get(resolved_order_id)
            if not order:
                return {"error": f"Order ID '{order_id}' not found."}
            
            if order["customer_id"] != customer_id:
                return {"error": "Refused: Access denied. You do not own this order."}
            
            tracking_info = self.tracking.get(resolved_order_id, {})
            return tracking_info

    def get_order(self, order_id: str) -> dict:
        with self.lock:
            query_str = str(order_id).strip()
            normalized_query = query_str.replace(" ", "").replace("-", "").upper()
            for oid in self.orders.keys():
                if oid.replace(" ", "").replace("-", "").upper() == normalized_query:
                    return self.orders[oid]
            return {}

    def cancel_order(self, order_id: str) -> bool:
        """
        Mark order as cancelled.
        """
        with self.lock:
            order_id_str = str(order_id)
            if order_id_str not in self.orders:
                return False
            
            order = self.orders[order_id_str]
            
            # Return stock to active inventory if order was pending_payment or paid
            if order["status"] != "cancelled":
                for item in order["items"]:
                    prod_id = item["product_id"]
                    sz = str(item["size"])
                    qty = item["quantity"]
                    if prod_id in self.inventory and sz in self.inventory[prod_id]:
                        self.inventory[prod_id][sz] += qty
            
            order["status"] = "cancelled"
            
            # Update tracking
            if order_id_str in self.tracking:
                self.tracking[order_id_str]["status"] = "cancelled"
                self.tracking[order_id_str]["timeline"].append({
                    "time": datetime.datetime.now(datetime.timezone.utc).isoformat(),
                    "event": "Order cancelled"
                })
            
            # Persist mutations to disk
            self._save_state_locked()
            
            return True

    def get_promotions(self) -> list:
        return self.promotions

    def confirm_payment(self, order_id: str, stripe_event_id: str = None) -> str:
        """
        Receive webhook event. Marks order as paid, enforcing idempotency.
        """
        with self.lock:
            oid = str(order_id).strip()
            if oid not in self.orders:
                return f"Error: Order #{oid} not found."
                
            order = self.orders[oid]
            current_event_id = order.get("stripe_event_id")
            if stripe_event_id and current_event_id == stripe_event_id:
                return "Event already processed (idempotence)"
                
            order["status"] = "paid"
            if stripe_event_id:
                order["stripe_event_id"] = stripe_event_id
                
            if oid in self.tracking:
                self.tracking[oid]["status"] = "processing"
                self.tracking[oid]["timeline"].append({
                    "time": datetime.datetime.now(datetime.timezone.utc).isoformat(),
                    "event": "Payment confirmed. Order status: paid"
                })
            
            # Persist mutations to disk
            self._save_state_locked()
            
            return f"Order #{oid} marked as paid successfully."

    def issue_store_credit(self, customer_id: str, amount: float) -> None:
        with self.lock:
            for c in self.customers:
                if c["id"] == customer_id:
                    c["store_credit"] = float(c.get("store_credit", 0.0)) + amount
                    self._save_state_locked()
                    return
            raise ValueError(f"Customer ID '{customer_id}' not found.")

    def get_store_credit(self, customer_id: str) -> float:
        with self.lock:
            for c in self.customers:
                if c["id"] == customer_id:
                    return float(c.get("store_credit", 0.0))
            return 0.0

    def mark_refunded(self, order_id: str) -> bool:
        """
        Mark an order as refunded, thread-safely, and persist immediately.
        """
        with self.lock:
            oid = str(order_id).strip()
            if oid not in self.orders:
                return False
            self.orders[oid]["status"] = "refunded"
            self._save_state_locked()
            return True

    def set_payment_intent(self, order_id: str, intent_id: str) -> None:
        """
        Store the Stripe payment/session intent ID against an order, thread-safely, and persist.
        """
        with self.lock:
            oid = str(order_id).strip()
            if oid in self.orders:
                self.orders[oid]["stripe_payment_intent_id"] = intent_id
                self._save_state_locked()

    def release_abandoned_checkouts(self) -> None:
        """
        Scans orders and automatically cancels those in pending_payment status older than 15 minutes,
        returning their reserved stock.
        """
        with self.lock:
            now = datetime.datetime.now(datetime.timezone.utc)
            mutated = False
            for oid, order in list(self.orders.items()):
                if order["status"] == "pending_payment":
                    created_at = order["created_at"]
                    if isinstance(created_at, str):
                        if created_at.endswith("Z"):
                            created_at = created_at[:-1] + "+00:00"
                        created_at_dt = datetime.datetime.fromisoformat(created_at)
                    else:
                        created_at_dt = created_at
                    
                    if created_at_dt.tzinfo is None:
                        created_at_dt = created_at_dt.replace(tzinfo=datetime.timezone.utc)
                        
                    diff = now - created_at_dt
                    if diff.total_seconds() > 900.0:  # 15 minutes
                        order["status"] = "cancelled"
                        mutated = True
                        # Return stock
                        for item in order["items"]:
                            prod_id = item["product_id"]
                            sz = str(item["size"])
                            qty = item["quantity"]
                            if prod_id in self.inventory and sz in self.inventory[prod_id]:
                                self.inventory[prod_id][sz] += qty
                        # Update tracking
                        if oid in self.tracking:
                            self.tracking[oid]["status"] = "cancelled"
                            self.tracking[oid]["timeline"].append({
                                "time": now.isoformat(),
                                "event": "Order cancelled automatically due to payment timeout"
                            })
                        print(f"[Failure-Mode Handling] Cancelled expired order #{oid} and restored stock in-memory.")
            
            if mutated:
                self._save_state_locked()
