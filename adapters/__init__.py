from config import ADAPTER
from adapters.json_adapter import JSONAdapter
from adapters.shopify_adapter import ShopifyAdapter
from adapters.woocommerce_adapter import WooCommerceAdapter

def get_adapter():
    """
    Factory function to instantiate the correct adapter based on config.py.
    """
    adapter_name = str(ADAPTER).lower().strip()
    if adapter_name == "json":
        return JSONAdapter()
    elif adapter_name == "shopify":
        return ShopifyAdapter()
    elif adapter_name == "woocommerce":
        return WooCommerceAdapter()
    else:
        raise ValueError(f"Unknown ADAPTER type configured: '{ADAPTER}'")
