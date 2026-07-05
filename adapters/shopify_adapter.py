import os
import requests
from adapters.base import BaseAdapter, AdapterError

class ShopifyAdapter(BaseAdapter):
    def __init__(self) -> None:
        self.base_url: str = os.getenv("SHOPIFY_URL", "")
        self.access_token: str = os.getenv("SHOPIFY_API_KEY", "") # X-Shopify-Access-Token
        self.api_version: str = "2024-01"
        self.headers: dict = {
            "X-Shopify-Access-Token": self.access_token,
            "Content-Type": "application/json"
        }

    def _get_api_url(self, path: str) -> str:
        url = self.base_url.rstrip("/")
        if not url.startswith("http"):
            url = f"https://{url}"
        return f"{url}/admin/api/{self.api_version}/{path}"

    def get_products(self, query: str = None) -> list:
        url = self._get_api_url("products.json")
        params = {}
        if query:
            params["title"] = query
        try:
            response = requests.get(url, headers=self.headers, params=params, timeout=10)
            response.raise_for_status()
            products_data = response.json().get("products", [])
            
            mapped = []
            for p in products_data:
                mapped.append({
                    "id": str(p["id"]),
                    "name": p["title"],
                    "description": p.get("body_html", ""),
                    "category": p.get("product_type", "casual"),
                    "occasion_tags": p.get("tags", "").split(", "),
                    "mood_tags": [],
                    "price": float(p["variants"][0]["price"]) if p.get("variants") else 0.0,
                    "currency": "BDT",
                    "image_url": p.get("image", {}).get("src", "") if p.get("image") else ""
                })
            return mapped
        except Exception as e:
            raise AdapterError(f"Shopify product retrieval failed: {e}")

    def check_stock(self, product_id: str, size: str) -> int:
        url = self._get_api_url(f"products/{product_id}/variants.json")
        try:
            response = requests.get(url, headers=self.headers, timeout=10)
            response.raise_for_status()
            variants = response.json().get("variants", [])
            for var in variants:
                if str(var.get("option1", "")).strip() == str(size).strip() or \
                   str(var.get("option2", "")).strip() == str(size).strip():
                    return int(var.get("inventory_quantity", 0))
            return 0
        except Exception as e:
            raise AdapterError(f"Shopify stock check failed: {e}")

    def get_product_details(self, product_id: str) -> dict:
        url = self._get_api_url(f"products/{product_id}.json")
        try:
            response = requests.get(url, headers=self.headers, timeout=10)
            response.raise_for_status()
            p = response.json().get("product", {})
            if not p:
                return {}
            
            variants_list = []
            for var in p.get("variants", []):
                size_val = var.get("option1") or var.get("option2") or "default"
                variants_list.append({
                    "size": str(size_val),
                    "stock": int(var.get("inventory_quantity", 0))
                })
                
            return {
                "id": str(p["id"]),
                "name": p["title"],
                "description": p.get("body_html", ""),
                "category": p.get("product_type", "casual"),
                "occasion_tags": p.get("tags", "").split(", ") if p.get("tags") else [],
                "mood_tags": [],
                "price": float(p["variants"][0]["price"]) if p.get("variants") else 0.0,
                "currency": "BDT",
                "image_url": p.get("image", {}).get("src", "") if p.get("image") else "",
                "variants": variants_list
            }
        except Exception as e:
            raise AdapterError(f"Shopify product details retrieval failed: {e}")

    def create_order(self, customer_id: str, cart: list) -> dict:
        url = self._get_api_url("orders.json")
        line_items = []
        for item in cart:
            line_items.append({
                "variant_id": int(item["product_id"]), 
                "quantity": item["quantity"]
            })
            
        payload = {
            "order": {
                "line_items": line_items,
                "customer": {
                    "id": int(customer_id)
                },
                "financial_status": "pending"
            }
        }
        try:
            response = requests.post(url, headers=self.headers, json=payload, timeout=10)
            response.raise_for_status()
            order = response.json().get("order", {})
            return {
                "id": str(order["id"]),
                "customer_id": customer_id,
                "items": cart,
                "total": float(order.get("total_price", 0.0)),
                "status": "pending_payment",
                "stripe_payment_intent_id": None,
                "created_at": order.get("created_at")
            }
        except Exception as e:
            raise AdapterError(f"Failed to create Shopify order: {e}")

    def track_order(self, order_id: str, customer_id: str) -> dict:
        url = self._get_api_url(f"orders/{order_id}.json")
        try:
            response = requests.get(url, headers=self.headers, timeout=10)
            response.raise_for_status()
            order = response.json().get("order", {})
            
            actual_cust_id = str(order.get("customer", {}).get("id", ""))
            if actual_cust_id != str(customer_id):
                return {"error": "Refused: Access denied. You do not own this order."}
            
            fulfillments = order.get("fulfillments", [])
            tracking_number = "N/A"
            tracking_company = "N/A"
            status = "processing"
            
            if fulfillments:
                f = fulfillments[0]
                tracking_number = f.get("tracking_number", "N/A")
                tracking_company = f.get("tracking_company", "N/A")
                status = f.get("shipment_status", "in_transit")
            
            return {
                "order_id": order_id,
                "courier": tracking_company,
                "tracking_code": tracking_number,
                "status": status,
                "estimated_delivery": "N/A",
                "timeline": [
                    { "time": order.get("created_at"), "event": f"Order created. Status: {order.get('financial_status')}" }
                ]
            }
        except Exception as e:
            raise AdapterError(f"Failed to track Shopify order: {e}")

    def get_order(self, order_id: str) -> dict:
        url = self._get_api_url(f"orders/{order_id}.json")
        try:
            response = requests.get(url, headers=self.headers, timeout=10)
            response.raise_for_status()
            order = response.json().get("order", {})
            return {
                "id": str(order["id"]),
                "customer_id": str(order.get("customer", {}).get("id", "")),
                "items": [],
                "total": float(order.get("total_price", 0.0)),
                "status": "paid" if order.get("financial_status") == "paid" else "pending_payment",
                "stripe_payment_intent_id": None,
                "created_at": order.get("created_at")
            }
        except Exception as e:
            raise AdapterError(f"Failed to retrieve Shopify order: {e}")

    def cancel_order(self, order_id: str) -> bool:
        url = self._get_api_url(f"orders/{order_id}/cancel.json")
        try:
            response = requests.post(url, headers=self.headers, json={}, timeout=10)
            response.raise_for_status()
            return True
        except Exception as e:
            raise AdapterError(f"Failed to cancel Shopify order: {e}")

    def mark_refunded(self, order_id: str) -> bool:
        """
        No-op: Shopify order status is authoritative on Shopify's servers and is
        re-fetched fresh on every get_order() call, so there is no local object
        to mutate. The actual refund is issued via the Stripe API call in
        agent/tools.py; reflecting it back into Shopify would require a
        dedicated Shopify Refund API call, which is out of scope here.
        """
        return True

    def set_payment_intent(self, order_id: str, intent_id: str) -> None:
        """
        No-op for the same reason as mark_refunded: Shopify order objects are
        not cached locally, so there is nothing to persist the intent ID onto
        between calls.
        """
        return None

    def get_promotions(self) -> list:
        url = self._get_api_url("price_rules.json")
        try:
            response = requests.get(url, headers=self.headers, timeout=10)
            response.raise_for_status()
            rules = response.json().get("price_rules", [])
            mapped = []
            for r in rules:
                mapped.append({
                    "id": str(r["id"]),
                    "title": r["title"],
                    "description": f"Discount code: {r.get('code')}",
                    "discount_percent": abs(float(r.get("value", 0.0))),
                    "applies_to_categories": [],
                    "code": r.get("title"),
                    "valid_until": r.get("ends_at")
                })
            return mapped
        except Exception as e:
            raise AdapterError(f"Failed to retrieve Shopify promotions: {e}")

    def confirm_payment(self, order_id: str, stripe_event_id: str = None) -> str:
        return f"Order #{order_id} marked as paid on Shopify."

    def issue_store_credit(self, customer_id: str, amount: float) -> None:
        pass

    def get_store_credit(self, customer_id: str) -> float:
        return 0.0
