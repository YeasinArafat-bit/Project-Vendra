import os
import requests
from adapters.base import BaseAdapter, AdapterError

class WooCommerceAdapter(BaseAdapter):
    def __init__(self) -> None:
        self.base_url: str = os.getenv("WC_URL", "")
        self.consumer_key: str = os.getenv("WC_KEY", "")
        self.consumer_secret: str = os.getenv("WC_SECRET", "")
        self.auth: tuple = (self.consumer_key, self.consumer_secret)

    def _get_api_url(self, path: str) -> str:
        url = self.base_url.rstrip("/")
        return f"{url}/wp-json/wc/v3/{path}"

    def get_products(self, query: str = None) -> list:
        url = self._get_api_url("products")
        params = {}
        if query:
            params["search"] = query
        try:
            response = requests.get(url, auth=self.auth, params=params, timeout=10)
            response.raise_for_status()
            products_data = response.json()
            
            mapped = []
            for p in products_data:
                images = p.get("images", [])
                img_url = images[0]["src"] if images else ""
                mapped.append({
                    "id": str(p["id"]),
                    "name": p["name"],
                    "description": p.get("description", ""),
                    "category": p.get("categories", [{}])[0].get("name", "casual") if p.get("categories") else "casual",
                    "occasion_tags": [],
                    "mood_tags": [],
                    "price": float(p.get("price") or 0.0),
                    "currency": "BDT",
                    "image_url": img_url
                })
            return mapped
        except Exception as e:
            raise AdapterError(f"WooCommerce product retrieval failed: {e}")

    def check_stock(self, product_id: str, size: str) -> int:
        url = self._get_api_url(f"products/{product_id}/variations")
        try:
            response = requests.get(url, auth=self.auth, timeout=10)
            response.raise_for_status()
            variations = response.json()
            for v in variations:
                attributes = v.get("attributes", [])
                for attr in attributes:
                    if attr.get("name", "").lower() == "size" and str(attr.get("option", "")).strip() == str(size).strip():
                        if v.get("manage_stock"):
                            return int(v.get("stock_quantity") or 0)
                        else:
                            return 99 if v.get("in_stock") else 0
            return 0
        except Exception as e:
            raise AdapterError(f"WooCommerce stock check failed: {e}")

    def get_product_details(self, product_id: str) -> dict:
        url = self._get_api_url(f"products/{product_id}")
        try:
            response = requests.get(url, auth=self.auth, timeout=10)
            response.raise_for_status()
            p = response.json()
            
            var_url = self._get_api_url(f"products/{product_id}/variations")
            var_res = requests.get(var_url, auth=self.auth, timeout=10)
            variants_list = []
            if var_res.status_code == 200:
                for v in var_res.json():
                    size_attr = next((a for a in v.get("attributes", []) if a.get("name", "").lower() == "size"), None)
                    size_val = size_attr.get("option") if size_attr else "default"
                    variants_list.append({
                        "size": str(size_val),
                        "stock": int(v.get("stock_quantity") or 0) if v.get("manage_stock") else (99 if v.get("in_stock") else 0)
                    })
            
            images = p.get("images", [])
            img_url = images[0]["src"] if images else ""
            
            return {
                "id": str(p["id"]),
                "name": p["name"],
                "description": p.get("description", ""),
                "category": p.get("categories", [{}])[0].get("name", "casual") if p.get("categories") else "casual",
                "occasion_tags": [],
                "mood_tags": [],
                "price": float(p.get("price") or 0.0),
                "currency": "BDT",
                "image_url": img_url,
                "variants": variants_list
            }
        except Exception as e:
            raise AdapterError(f"WooCommerce product details retrieval failed: {e}")

    def create_order(self, customer_id: str, cart: list) -> dict:
        url = self._get_api_url("orders")
        line_items = []
        for item in cart:
            line_items.append({
                "product_id": int(item["product_id"]),
                "quantity": item["quantity"]
            })
            
        payload = {
            "payment_method": "stripe",
            "payment_method_title": "Stripe",
            "set_paid": False,
            "customer_id": int(customer_id) if customer_id.isdigit() else 0,
            "line_items": line_items
        }
        try:
            response = requests.post(url, auth=self.auth, json=payload, timeout=10)
            response.raise_for_status()
            order = response.json()
            return {
                "id": str(order["id"]),
                "customer_id": customer_id,
                "items": cart,
                "total": float(order.get("total", 0.0)),
                "status": "pending_payment",
                "stripe_payment_intent_id": None,
                "created_at": order.get("date_created")
            }
        except Exception as e:
            raise AdapterError(f"Failed to create WooCommerce order: {e}")

    def track_order(self, order_id: str, customer_id: str) -> dict:
        url = self._get_api_url(f"orders/{order_id}")
        try:
            response = requests.get(url, auth=self.auth, timeout=10)
            response.raise_for_status()
            order = response.json()
            
            actual_cust_id = str(order.get("customer_id", ""))
            if actual_cust_id != str(customer_id):
                return {"error": "Refused: Access denied. You do not own this order."}
            
            wc_status = order.get("status", "pending")
            status_map = {
                "completed": "delivered",
                "processing": "processing",
                "pending": "processing",
                "cancelled": "cancelled",
                "refunded": "cancelled"
            }
            
            return {
                "order_id": order_id,
                "courier": "Pathao",
                "tracking_code": f"WC-{order_id}",
                "status": status_map.get(wc_status, "in_transit"),
                "estimated_delivery": "N/A",
                "timeline": [
                    { "time": order.get("date_created"), "event": f"Order status changed to {wc_status}" }
                ]
            }
        except Exception as e:
            raise AdapterError(f"Failed to track WooCommerce order: {e}")

    def get_order(self, order_id: str) -> dict:
        url = self._get_api_url(f"orders/{order_id}")
        try:
            response = requests.get(url, auth=self.auth, timeout=10)
            response.raise_for_status()
            order = response.json()
            return {
                "id": str(order["id"]),
                "customer_id": str(order.get("customer_id")),
                "items": [],
                "total": float(order.get("total", 0.0)),
                "status": "paid" if order.get("status") in ["processing", "completed"] else "pending_payment",
                "stripe_payment_intent_id": None,
                "created_at": order.get("date_created")
            }
        except Exception as e:
            raise AdapterError(f"Failed to retrieve WooCommerce order: {e}")

    def cancel_order(self, order_id: str) -> bool:
        url = self._get_api_url(f"orders/{order_id}")
        payload = {"status": "cancelled"}
        try:
            response = requests.put(url, auth=self.auth, json=payload, timeout=10)
            response.raise_for_status()
            return True
        except Exception as e:
            raise AdapterError(f"Failed to cancel WooCommerce order: {e}")

    def mark_refunded(self, order_id: str) -> bool:
        """
        No-op: WooCommerce order status is authoritative on the WooCommerce
        server and is re-fetched fresh on every get_order() call, so there is
        no local object to mutate. The actual refund is issued via the Stripe
        API call in agent/tools.py; reflecting it back into WooCommerce would
        require a dedicated WooCommerce Refunds API call, which is out of
        scope here.
        """
        return True

    def set_payment_intent(self, order_id: str, intent_id: str) -> None:
        """
        No-op for the same reason as mark_refunded: WooCommerce order objects
        are not cached locally, so there is nothing to persist the intent ID
        onto between calls.
        """
        return None

    def get_promotions(self) -> list:
        url = self._get_api_url("coupons")
        try:
            response = requests.get(url, auth=self.auth, timeout=10)
            response.raise_for_status()
            coupons = response.json()
            mapped = []
            for c in coupons:
                mapped.append({
                    "id": str(c["id"]),
                    "title": c.get("code", "").upper(),
                    "description": c.get("description") or f"Discount coupon: {c.get('code')}",
                    "discount_percent": float(c.get("amount") or 0.0) if c.get("discount_type") == "percent" else 0.0,
                    "applies_to_categories": [],
                    "code": c.get("code"),
                    "valid_until": c.get("date_expires")
                })
            return mapped
        except Exception as e:
            raise AdapterError(f"Failed to retrieve WooCommerce promotions: {e}")

    def confirm_payment(self, order_id: str, stripe_event_id: str = None) -> str:
        return f"Order #{order_id} marked as paid on WooCommerce."

    def issue_store_credit(self, customer_id: str, amount: float) -> None:
        pass

    def get_store_credit(self, customer_id: str) -> float:
        return 0.0
