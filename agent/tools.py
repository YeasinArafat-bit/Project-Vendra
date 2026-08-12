import os
import json
import datetime
import stripe
import re
import logging
from typing import Optional
from langchain_core.tools import tool
from langchain_core.runnables import RunnableConfig
from adapters import get_adapter
from adapters.base import AdapterError
import pybreaker
from tenacity import retry, stop_after_attempt, wait_exponential, retry_if_exception_type
from sqlalchemy.exc import OperationalError, DBAPIError, TimeoutError as SATimeoutError

# Configure logger
logger = logging.getLogger("vendra.tools")

def validate_product_id(product_id: str) -> bool:
    if not product_id:
        return False
    return bool(re.match(r"^[a-zA-Z0-9\s-]+$", str(product_id).strip()))

def validate_order_id(order_id: str) -> bool:
    if not order_id:
        return False
    return bool(re.match(r"^[a-zA-Z0-9\s-]+$", str(order_id).strip()))

def validate_shoe_size(size: str) -> bool:
    if not size:
        return False
    return bool(re.match(r"^[a-zA-Z0-9\s.-]+$", str(size).strip()))

# Circuit Breakers
llm_breaker = pybreaker.CircuitBreaker(fail_max=5, reset_timeout=30)
stripe_breaker = pybreaker.CircuitBreaker(fail_max=3, reset_timeout=30)
db_breaker = pybreaker.CircuitBreaker(fail_max=5, reset_timeout=30)

@retry(
    stop=stop_after_attempt(3),
    wait=wait_exponential(multiplier=1, min=1, max=5),
    retry=retry_if_exception_type((OperationalError, DBAPIError, SATimeoutError)),
    reraise=True
)
def _call_adapter_func(func, *args, **kwargs):
    return func(*args, **kwargs)

def safe_db_call(func, *args, **kwargs):
    try:
        return db_breaker.call(_call_adapter_func, func, *args, **kwargs)
    except pybreaker.CircuitBreakerError as e:
        logger.error("Database Circuit Breaker is OPEN.")
        raise AdapterError("Database service is temporarily unavailable due to high load or maintenance.") from e

class CircuitBreakerAdapterProxy:
    def __init__(self, target):
        super().__setattr__("_target", target)

    def __getattr__(self, name):
        if name == "_target":
            return super().__getattribute__("_target")
        attr = getattr(self._target, name)
        if callable(attr):
            def wrapper(*args, **kwargs):
                try:
                    return db_breaker.call(_call_adapter_func, attr, *args, **kwargs)
                except pybreaker.CircuitBreakerError as e:
                    logger.error(f"Database Circuit Breaker is OPEN during {name}().")
                    raise AdapterError("Database service is temporarily unavailable due to high load or maintenance.") from e
            return wrapper
        return attr

    def __setattr__(self, name, value):
        if name == "_target":
            super().__setattr__(name, value)
        else:
            setattr(self._target, name, value)

    def __delattr__(self, name):
        if name == "_target":
            super().__delattr__(name)
        else:
            delattr(self._target, name)

# Active adapter instance wrapped in circuit breaker proxy
adapter_instance = get_adapter()
adapter = CircuitBreakerAdapterProxy(adapter_instance)

# Redis-backed Stateless Cart Store and Caching Proxy with memory fallback
class RedisCartProxy:
    def __init__(self):
        self._local_carts = {}
        self._local_activity = {}
        self.redis_url = os.getenv("REDIS_URL")
        self.redis_client = None
        self._connect_redis()

    def _connect_redis(self):
        if self.redis_url:
            try:
                import redis
                # Use connection pooling with timeout to prevent blocking startup
                pool = redis.ConnectionPool.from_url(self.redis_url, socket_timeout=2.0, decode_responses=True)
                self.redis_client = redis.Redis(connection_pool=pool)
                self.redis_client.ping()
                logger.info("Stateless Redis Cart Store connected successfully.")
            except Exception as e:
                logger.warning(f"Failed to connect to Redis server ({e}). Operating in memory-only fallback mode.")
                self.redis_client = None

    def _get_key(self, cart_id: str) -> str:
        return f"vendra:cart:{cart_id}"

    def get(self, key: str, default=None):
        if self.redis_client:
            try:
                val = self.redis_client.get(self._get_key(key))
                if val:
                    return json.loads(val)
                return default
            except Exception as e:
                logger.error(f"Redis get failed: {e}")
        return self._local_carts.get(key, default)

    def __getitem__(self, key: str):
        if self.redis_client:
            try:
                val = self.redis_client.get(self._get_key(key))
                if val:
                    return json.loads(val)
                raise KeyError(key)
            except Exception as e:
                logger.error(f"Redis getitem failed: {e}")
        return self._local_carts[key]

    def __setitem__(self, key: str, value):
        if self.redis_client:
            try:
                # Set with 24 hours TTL (86400 seconds)
                self.redis_client.set(self._get_key(key), json.dumps(value), ex=86400)
                return
            except Exception as e:
                logger.error(f"Redis setitem failed: {e}")
        self._local_carts[key] = value

    def __contains__(self, key: str) -> bool:
        if self.redis_client:
            try:
                return bool(self.redis_client.exists(self._get_key(key)))
            except Exception as e:
                logger.error(f"Redis contains failed: {e}")
        return key in self._local_carts

    def pop(self, key: str, default=None):
        if self.redis_client:
            try:
                val = self.get(key, default)
                self.redis_client.delete(self._get_key(key))
                return val
            except Exception as e:
                logger.error(f"Redis pop failed: {e}")
        return self._local_carts.pop(key, default)

    def keys(self):
        if self.redis_client:
            try:
                keys = self.redis_client.keys("vendra:cart:*")
                return [k.replace("vendra:cart:", "") for k in keys]
            except Exception as e:
                logger.error(f"Redis keys failed: {e}")
        return self._local_carts.keys()

    def clear(self):
        if self.redis_client:
            try:
                keys = self.redis_client.keys("vendra:cart:*")
                if keys:
                    self.redis_client.delete(*keys)
                return
            except Exception as e:
                logger.error(f"Redis clear failed: {e}")
        self._local_carts.clear()

CARTS = RedisCartProxy()
CART_LAST_ACTIVITY = {}

def update_cart_activity(cart_id: str) -> None:
    if not CARTS.redis_client:
        CART_LAST_ACTIVITY[cart_id] = datetime.datetime.now(datetime.timezone.utc)

def prune_inactive_carts(hours: float = 24.0) -> None:
    """
    Remove carts that have been inactive for more than N hours.
    """
    if CARTS.redis_client:
        return # Handled by Redis TTL natively
    now = datetime.datetime.now(datetime.timezone.utc)
    inactive_threshold = datetime.timedelta(hours=hours)
    for cid in list(CARTS.keys()):
        last_active = CART_LAST_ACTIVITY.get(cid)
        if last_active:
            if now - last_active > inactive_threshold:
                CARTS.pop(cid, None)
                CART_LAST_ACTIVITY.pop(cid, None)
        else:
            CART_LAST_ACTIVITY[cid] = now

# Caching Helpers with no-op fallback
def get_cached_catalog_value(key: str) -> Optional[str]:
    if CARTS.redis_client:
        try:
            return CARTS.redis_client.get(f"vendra:catalog:{key}")
        except Exception as e:
            logger.error(f"Redis catalog cache get failed: {e}")
    return None

def set_cached_catalog_value(key: str, value: str, ttl: int = 300) -> None:
    if CARTS.redis_client:
        try:
            CARTS.redis_client.set(f"vendra:catalog:{key}", value, ex=ttl)
        except Exception as e:
            logger.error(f"Redis catalog cache set failed: {e}")

def invalidate_catalog_cache(product_id: str = None) -> None:
    if CARTS.redis_client:
        try:
            if product_id:
                CARTS.redis_client.delete(f"vendra:catalog:product:{product_id}")
            keys = CARTS.redis_client.keys("vendra:catalog:search:*")
            if keys:
                CARTS.redis_client.delete(*keys)
        except Exception as e:
            logger.error(f"Redis cache invalidation failed: {e}")

@tool
def search_products(
    query: str, 
    top_k: int = 4, 
    category: Optional[str] = None, 
    max_price: Optional[float] = None, 
    min_price: Optional[float] = None,
    size: Optional[str] = None
) -> str:
    """
    Search the shoe catalog using hybrid search and metadata filtering.
    Use this tool when customers describe the kind of shoes they are looking for, optionally specifying a category, size, or price range.
    
    Args:
        query: Semantic query string describing desired shoes.
        top_k: Number of products to retrieve (default is 4).
        category: Optional category filter (e.g., 'casual', 'sport', 'formal', 'sale').
        max_price: Optional maximum price filter in BDT.
        min_price: Optional minimum price filter in BDT.
        size: Optional shoe size filter (e.g., '5', '6', '7', '8', '9', '10', '11').
    """
    try:
        import hashlib
        param_str = f"search:{query}:{top_k}:{category}:{max_price}:{min_price}:{size}"
        cache_key = f"search:{hashlib.md5(param_str.encode('utf-8')).hexdigest()}"
        cached = get_cached_catalog_value(cache_key)
        if cached:
            return cached

        # Retrieve more candidates initially in case we filter some out due to size stock constraint
        retrieval_k = top_k * 2 if size else top_k
        results = search_products_text(
            query=query, 
            top_k=retrieval_k, 
            category=category, 
            max_price=max_price, 
            min_price=min_price
        )
        
        if not results:
            return "No matching shoes found in catalog."
            
        output = []
        promos = adapter.get_promotions()
        if promos:
            for pr in promos[:2]:
                output.append(f"🏷️ Active offer: {pr['title']} — {pr['description']} with code {pr['code']}\n")
                
        output.append("Found these matching items:")
        matching_count = 0
        for res in results:
            if matching_count >= top_k:
                break
                
            p_id = res["product_id"]
            doc = res["document"]
            metadata = res["metadata"]
            
            # Check stock if size filter is specified
            if size:
                qty = adapter.check_stock(p_id, size)
                if qty <= 0:
                    continue  # Skip items that are out of stock for the requested size
                    
            details = adapter.get_product_details(p_id)
            price = details.get("price", metadata.get("price", "N/A"))
            
            mood_tags = details.get("mood_tags", []) if details.get("mood_tags") else []
            occasion_tags = details.get("occasion_tags", []) if details.get("occasion_tags") else []
            all_tags = list(set(mood_tags + occasion_tags))
            
            output.append(
                f"- **{details.get('name', metadata.get('name', 'Shoe'))}** (ID: {p_id})\n"
                f"  Price: {price} BDT\n"
                f"  Tags: {', '.join(all_tags)}\n"
                f"  {details.get('description', doc)}\n"
                f"  Image: {details.get('image_url', '')}\n"
            )
            matching_count += 1
            
        if matching_count == 0:
            ret_val = f"No matching shoes found in size {size}." if size else "No matching shoes found in catalog."
            set_cached_catalog_value(cache_key, ret_val, ttl=300)
            return ret_val
            
        ret_val = "\n".join(output)
        set_cached_catalog_value(cache_key, ret_val, ttl=300)
        return ret_val
    except AdapterError as e:
        logger.error(f"Adapter error in search_products: {e}", exc_info=True)
        return "Error: Vendra's external integration service is temporarily unavailable. Please try again later."
    except Exception as e:
        logger.error(f"Error searching products: {e}", exc_info=True)
        return f"Error searching products: {str(e)}"

@tool
def search_products_by_image(
    image_bytes: bytes, 
    query: Optional[str] = None,
    top_k: int = 4, 
    category: Optional[str] = None, 
    max_price: Optional[float] = None, 
    min_price: Optional[float] = None,
    size: Optional[str] = None
) -> str:
    """
    Search the shoe catalog visually using uploaded image bytes, combined with optional text search and metadata filters.
    Use this tool when a customer uploads a photo and optionally describes additional constraints (e.g. category, size, price, or description).
    
    Args:
        image_bytes: Raw binary bytes of the uploaded shoe image.
        query: Optional text refinement/description describing what to look for relative to the image (e.g., 'blue', 'leather').
        top_k: Number of products to retrieve (default is 4).
        category: Optional category filter (e.g., 'casual', 'sport', 'formal', 'sale').
        max_price: Optional maximum price filter in BDT.
        min_price: Optional minimum price filter in BDT.
        size: Optional shoe size filter (e.g., '5', '6', '7', '8', '9', '10', '11').
    """
    # Resolve image_bytes if it's a string placeholder (e.g. from LLM)
    if isinstance(image_bytes, str) or not isinstance(image_bytes, (bytes, bytearray)):
        try:
            import streamlit as st
            if "uploaded_image_bytes" in st.session_state and st.session_state["uploaded_image_bytes"]:
                image_bytes = st.session_state["uploaded_image_bytes"]
            else:
                return "Error: No uploaded image found in the active session."
        except Exception as e:
            logger.error(f"Error parsing image bytes: {e}", exc_info=True)
            return "Error: Invalid image bytes format."

    try:
        retrieval_k = top_k * 2 if size else top_k
        results = search_products_image(
            image_bytes=image_bytes, 
            top_k=retrieval_k, 
            query=query, 
            category=category, 
            max_price=max_price, 
            min_price=min_price
        )
        if not results:
            return "No matching shoes found for this image."
        
        output = ["Visual match results:"]
        matching_count = 0
        for res in results:
            if matching_count >= top_k:
                break
                
            p_id = res["product_id"]
            
            # Filter by size if size constraint is provided
            if size:
                qty = adapter.check_stock(p_id, size)
                if qty <= 0:
                    continue
                    
            details = adapter.get_product_details(p_id)
            if details:
                mood_tags = details.get("mood_tags", []) if details.get("mood_tags") else []
                occasion_tags = details.get("occasion_tags", []) if details.get("occasion_tags") else []
                all_tags = list(set(mood_tags + occasion_tags))
                
                output.append(
                    f"- **{details['name']}** (ID: {p_id})\n"
                    f"  Price: {details['price']} BDT\n"
                    f"  Tags: {', '.join(all_tags)}\n"
                    f"  Description: {details['description']}\n"
                    f"  Image: {details.get('image_url', '')}\n"
                )
                matching_count += 1
                
        if matching_count == 0:
            if size:
                return f"No matching shoes found in size {size}."
            return "No matching shoes found for this image."
            
        return "\n".join(output)
    except AdapterError as e:
        logger.error(f"Adapter error in search_products_by_image: {e}", exc_info=True)
        return "Error: Vendra's external integration service is temporarily unavailable. Please try again later."
    except Exception as e:
        logger.error(f"Error during visual search: {e}", exc_info=True)
        return f"Error during visual search: {str(e)}"

@tool
def check_stock(product_id: str, size: str) -> str:
    """
    Check exact stock count of a specific shoe product ID and size.
    Always call this tool before promising stock availability to the customer.
    
    Args:
        product_id: The unique ID of the product (e.g. P001).
        size: The shoe size (e.g., '6', '7', '8', '9', '10', '11').
    """
    p_id = str(product_id).strip()
    sz_str = str(size).strip()
    if not validate_product_id(p_id) or not validate_shoe_size(sz_str):
        return "Error: Invalid product_id or size format."
    try:
        details = adapter.get_product_details(p_id)
        if not details:
            return f"Product ID '{p_id}' not found."
            
        qty = adapter.check_stock(p_id, sz_str)
        if qty > 0:
            return f"Product '{details['name']}' (ID: {p_id}) in size {sz_str} is in stock. Units available: {qty}."
        else:
            return f"Product '{details['name']}' (ID: {p_id}) in size {sz_str} is currently OUT OF STOCK."
    except AdapterError as e:
        logger.error(f"Adapter error in check_stock: {e}", exc_info=True)
        return "Error: Vendra's external integration service is temporarily unavailable. Please try again later."
    except Exception as e:
        logger.error(f"Error checking stock: {e}", exc_info=True)
        return f"Error checking stock: {str(e)}"

@tool
def get_product_details(product_id: str) -> str:
    """
    Retrieve full product details, including description, price, category, and size availability/stock.
    Use this tool when the customer asks for specifications, price, or size range of a product.
    
    Args:
        product_id: The unique ID of the product.
    """
    p_id = str(product_id).strip()
    if not validate_product_id(p_id):
        normalized_query = p_id.lower().replace("-", " ").replace("_", " ")
        query_terms = [t for t in normalized_query.split() if t not in ["sku", "id", "product", "find"]]
        found_id = None
        if query_terms:
            try:
                for p in adapter.get_products():
                    p_name_lower = p.get("name", "").lower()
                    if all(term in p_name_lower for term in query_terms):
                        found_id = p["id"]
                        break
            except Exception:
                pass
        if found_id:
            p_id = found_id
        else:
            return "Error: Invalid Product ID format. Expected format like P001."
            
    cache_key = f"product:{p_id}"
    cached = get_cached_catalog_value(cache_key)
    if cached:
        return cached

    try:
        details = adapter.get_product_details(p_id)
        if not details:
            return f"Product ID '{product_id}' not found."
            
        variants_str = "\n".join(
            f"- Size {v['size']}: {v['stock']} units in stock" for v in details.get("variants", [])
        )
        
        ret_val = (
            f"Product Details:\n"
            f"Name: {details['name']}\n"
            f"ID: {p_id}\n"
            f"Category: {details.get('category', 'casual')}\n"
            f"Price: {details['price']} BDT\n"
            f"Description: {details['description']}\n"
            f"\nAvailable Stock by Size:\n{variants_str}"
        )
        set_cached_catalog_value(cache_key, ret_val, ttl=300)
        return ret_val
    except AdapterError as e:
        logger.error(f"Adapter error in get_product_details: {e}", exc_info=True)
        return "Error: Vendra's external integration service is temporarily unavailable. Please try again later."
    except Exception as e:
        logger.error(f"Error fetching product details: {e}", exc_info=True)
        return f"Error fetching product details: {str(e)}"

@tool
def add_to_cart(cart_id: str, product_id: str, size: str, customer_id: str, quantity: int = 1) -> str:
    """
    Add a specific shoe product ID and size to a shopping cart. Checks stock availability first.
    
    Args:
        cart_id: Unique identifier for the customer's shopping session cart.
        product_id: The product ID to add.
        size: The shoe size.
        customer_id: The customer ID requesting this add.
        quantity: Quantity of the item to add (default is 1).
    """
    cid = str(cart_id).strip()
    pid = str(product_id).strip()
    sz = str(size).strip()
    cust_id = str(customer_id).strip()
    
    if not validate_product_id(pid) or not validate_shoe_size(sz):
        return "Error: Invalid product_id or size format."
    
    from agent.logging_config import ctx_customer_id
    verified_cust_id = ctx_customer_id.get()
    if verified_cust_id != "N/A":
        cust_id = verified_cust_id
        cid = f"cart_{verified_cust_id}"
    
    if cid != f"cart_{cust_id}":
        return "Refused: Access denied. You do not own this cart."
        
    update_cart_activity(cid)
    
    try:
        details = adapter.get_product_details(pid)
        if not details:
            return f"Error: Product ID '{pid}' not found."
            
        available = adapter.check_stock(pid, sz)
        
        cart_items = CARTS.get(cid, [])
        current_qty_in_cart = sum(item["quantity"] for item in cart_items if item["product_id"] == pid and item["size"] == sz)
        total_requested = current_qty_in_cart + quantity
        
        if available < total_requested:
            return (
                f"Error: Cannot add {quantity} units of '{details['name']}' (Size {sz}) to cart. "
                f"You already have {current_qty_in_cart} in cart, and there are only {available} units available in stock."
            )
            
        if cid not in CARTS:
            CARTS[cid] = []
            
        updated = False
        for item in CARTS[cid]:
            if item["product_id"] == pid and item["size"] == sz:
                item["quantity"] = total_requested
                item["price"] = details.get("price", 0.0)
                item["subtotal"] = total_requested * item["price"]
                item["name"] = details.get("name", "Shoe")
                updated = True
                break
        
        if not updated:
            price = details.get("price", 0.0)
            CARTS[cid].append({
                "product_id": pid,
                "name": details.get("name", "Shoe"),
                "size": sz,
                "quantity": quantity,
                "price": price,
                "subtotal": quantity * price
            })
            
        return f"Successfully added {quantity} units of '{details['name']}' (Size {sz}) to cart."
    except AdapterError as e:
        logger.error(f"Adapter error in add_to_cart: {e}", exc_info=True)
        return "Error: Vendra's external integration service is temporarily unavailable. Please try again later."
    except Exception as e:
        logger.error(f"Error adding to cart: {e}", exc_info=True)
        return f"Error adding to cart: {str(e)}"

@tool
def view_cart(cart_id: str, customer_id: str) -> str:
    """
    View items in the cart and see the running total.
    
    Args:
        cart_id: Unique identifier of the shopping cart.
        customer_id: The customer ID requesting this view.
    """
    cid = str(cart_id).strip()
    cust_id = str(customer_id).strip()
    
    from agent.logging_config import ctx_customer_id
    verified_cust_id = ctx_customer_id.get()
    if verified_cust_id != "N/A":
        cust_id = verified_cust_id
        cid = f"cart_{verified_cust_id}"
    
    if cid != f"cart_{cust_id}":
        return "Refused: Access denied. You do not own this cart."
        
    update_cart_activity(cid)
    
    try:
        cart_items = CARTS.get(cid, [])
        if not cart_items:
            return "Your shopping cart is empty."
            
        output = [f"Shopping Cart (ID: {cid}):"]
        total = 0.0
        
        for idx, item in enumerate(cart_items, 1):
            pid = item["product_id"]
            sz = item["size"]
            qty = item["quantity"]
            
            details = adapter.get_product_details(pid)
            price = details.get("price", 0.0)
            item_total = price * qty
            total += item_total
            
            output.append(
                f"{idx}. **{details.get('name', 'Shoe')}** (ID: {pid}) - Size {sz} x{qty}\n"
                f"   Price: {price} BDT each (Subtotal: {item_total} BDT)"
            )
            
        output.append(f"\n**Running Total: {total} BDT**")
        return "\n".join(output)
    except AdapterError as e:
        logger.error(f"Adapter error in view_cart: {e}", exc_info=True)
        return "Error: Vendra's external integration service is temporarily unavailable. Please try again later."
    except Exception as e:
        logger.error(f"Error viewing cart: {e}", exc_info=True)
        return f"Error viewing cart: {str(e)}"

@tool
def remove_from_cart(cart_id: str, product_id: str, customer_id: str, size: Optional[str] = None) -> str:
    """
    Remove items (matching product ID and optionally size) from the cart.
    
    Args:
        cart_id: Unique identifier of the shopping cart.
        product_id: The product ID to remove.
        customer_id: The customer ID requesting this removal.
        size: Optional shoe size to remove. If omitted, all sizes of this product are removed.
    """
    cid = str(cart_id).strip()
    pid = str(product_id).strip()
    cust_id = str(customer_id).strip()
    
    if not validate_product_id(pid):
        return "Error: Invalid product_id format."
    
    from agent.logging_config import ctx_customer_id
    verified_cust_id = ctx_customer_id.get()
    if verified_cust_id != "N/A":
        cust_id = verified_cust_id
        cid = f"cart_{verified_cust_id}"
    
    if cid != f"cart_{cust_id}":
        return "Refused: Access denied. You do not own this cart."
        
    update_cart_activity(cid)
    
    try:
        if cid not in CARTS or not CARTS[cid]:
            return "Your shopping cart is already empty."
            
        details = adapter.get_product_details(pid)
        product_name = details.get("name", f"ID: {pid}")
        
        original_len = len(CARTS[cid])
        if size:
            sz = str(size).strip()
            CARTS[cid] = [item for item in CARTS[cid] if not (item["product_id"] == pid and item["size"] == sz)]
        else:
            CARTS[cid] = [item for item in CARTS[cid] if item["product_id"] != pid]
            
        if len(CARTS[cid]) < original_len:
            size_str = f" (Size {size})" if size else ""
            return f"Removed '{product_name}'{size_str} from your cart."
        else:
            size_str = f" with size {size}" if size else ""
            return f"Item '{product_name}'{size_str} was not found in your cart."
    except AdapterError as e:
        logger.error(f"Adapter error in remove_from_cart: {e}", exc_info=True)
        return "Error: Vendra's external integration service is temporarily unavailable. Please try again later."
    except Exception as e:
        logger.error(f"Error removing from cart: {e}", exc_info=True)
        return f"Error removing from cart: {str(e)}"

@tool
def create_order(customer_id: str, cart_id: str) -> str:
    """
    Convert cart items into a formal order and reserve product stock.
    Ensure to view the cart first and confirm all details with the customer.
    
    Args:
        customer_id: Unique identifier of the customer (e.g. C001).
        cart_id: Unique identifier of the shopping cart.
    """
    cid = str(cart_id).strip()
    cust_id = str(customer_id).strip()
    
    from agent.logging_config import ctx_customer_id
    verified_cust_id = ctx_customer_id.get()
    if verified_cust_id != "N/A":
        cust_id = verified_cust_id
        cid = f"cart_{verified_cust_id}"
    
    if cid != f"cart_{cust_id}":
        return "Refused: Access denied. You do not own this cart."
        
    cart_items = CARTS.get(cid, [])
    if not cart_items:
        return "Checkout Failed: Your cart is empty."
        
    try:
        new_order = adapter.create_order(cust_id, cart_items)
        CARTS[cid] = []
        update_cart_activity(cid)
        # Invalidate catalog cache for all ordered items to refresh stock displays
        for item in cart_items:
            invalidate_catalog_cache(item["product_id"])
        return (
            f"Order #{new_order['id']} has been created successfully.\n"
            f"Total: {new_order['total']} BDT\n"
            f"Status: pending_payment\n"
            f"Stock reserved successfully."
        )
    except AdapterError as e:
        logger.error(f"Adapter error in create_order: {e}", exc_info=True)
        return "Error: Vendra's external integration service is temporarily unavailable. Please try again later."
    except Exception as e:
        logger.error(f"Checkout Failed: {e}", exc_info=True)
        return f"Checkout Failed: {str(e)}"

@tool
def create_payment_link(order_id: str, customer_id: str) -> str:
    """
    Generate a Stripe Checkout payment link for the given order ID and customer ID.
    
    Args:
        order_id: Unique ID of the created order (e.g. ORD123).
        customer_id: Unique ID of the customer requesting the link.
    """
    oid = str(order_id).strip()
    cid = str(customer_id).strip()
    
    if not validate_order_id(oid):
        return "Error: Invalid order_id format."
        
    from agent.logging_config import ctx_customer_id
    verified_cust_id = ctx_customer_id.get()
    if verified_cust_id != "N/A":
        cid = verified_cust_id
    try:
        order = adapter.get_order(oid)
        if not order:
            return f"Error: Order ID '{oid}' not found."
            
        if order.get("customer_id") != cid:
            return "Refused: Access denied. You do not own this order."
            
        if order["status"] != "pending_payment":
            return f"Error: Order #{oid} cannot be paid because status is '{order['status']}'."
            
        stripe_key = os.getenv("STRIPE_SECRET_KEY")
        if not stripe_key or stripe_key.startswith("sk_test_your_"):
            mock_url = f"https://checkout.stripe.com/pay/cs_test_mock_{oid}"
            return f"Payment Link: {mock_url} (Stripe keys not set, mock mode)"
            
        stripe.api_key = stripe_key
        try:
            session = stripe_breaker.call(
                lambda: stripe.checkout.Session.create(
                    payment_method_types=["card"],
                    line_items=[{
                        "price_data": {
                            "currency": "bdt",
                            "product_data": {
                                "name": f"Vendra Order #{oid}",
                            },
                            "unit_amount": int(order["total"] * 100),
                        },
                        "quantity": 1,
                    }],
                    mode="payment",
                    success_url=f"http://localhost:8501/?payment_success=true&order_id={oid}",
                    cancel_url="http://localhost:8501/?payment_cancelled=true",
                    metadata={"order_id": oid}
                )
            )
        except pybreaker.CircuitBreakerError:
            logger.error("Stripe Circuit Breaker is OPEN.")
            return "Error: The payment gateway is temporarily offline. Please try again in a few moments."
        
        adapter.set_payment_intent(oid, session.id)
        return f"Payment Link: {session.url}"
    except AdapterError as e:
        logger.error(f"Adapter error in create_payment_link: {e}", exc_info=True)
        return "Error: Vendra's external integration service is temporarily unavailable. Please try again later."
    except Exception as e:
        logger.error(f"Error creating payment link: {e}", exc_info=True)
        return f"Error creating payment link: {str(e)}"

def confirm_payment(order_id: str, stripe_event_id: str = None) -> str:
    """
    Receive webhook event. Marks order as paid, enforcing idempotency.
    """
    oid = str(order_id).strip()
    try:
        return adapter.confirm_payment(oid, stripe_event_id)
    except AdapterError as e:
        logger.error(f"Adapter error in confirm_payment: {e}", exc_info=True)
        return "Error: Vendra's external integration service is temporarily unavailable. Please try again later."
    except Exception as e:
        logger.error(f"Error confirming payment: {e}", exc_info=True)
        return f"Error confirming payment: {str(e)}"

@tool
def track_order(order_id: str, customer_id: str) -> str:
    """
    Track order status and courier delivery timeline. Checks order ownership first.
    
    Args:
        order_id: Unique order ID to track (e.g. ORD123).
        customer_id: Customer ID requesting tracking (for privacy verification).
    """
    oid = str(order_id).strip()
    cid = str(customer_id).strip()
    
    if not validate_order_id(oid):
        return "Error: Invalid order_id format."
        
    from agent.logging_config import ctx_customer_id
    verified_cust_id = ctx_customer_id.get()
    if verified_cust_id != "N/A":
        cid = verified_cust_id
    
    try:
        tracking_info = adapter.track_order(oid, cid)
        # Adapter may return None or an empty dict for a not-found order
        if not tracking_info:
            return f"Error: Order #{oid} not found. Please check the order ID and try again."
        if isinstance(tracking_info, dict) and "error" in tracking_info:
            err = tracking_info["error"]
            # Normalise access-denied vs not-found for clean LLM messaging
            if "access" in str(err).lower() or "denied" in str(err).lower():
                return "Refused: Access denied. You do not own this order."
            return f"Error: Order #{oid} not found. Please check the order ID and try again."
            
        timeline_str = "\n".join(
            f"- [{t['time'][:16].replace('T', ' ')}] {t['event']}" for t in tracking_info.get("timeline", [])
        )
        
        return (
            f"Order Tracking Details (ID: {oid}, Customer ID: {cid}):\n"
            f"Courier: {tracking_info.get('courier', 'N/A')}\n"
            f"Tracking Code: {tracking_info.get('tracking_code', 'N/A')}\n"
            f"Status: {tracking_info.get('status', 'N/A').upper()}\n"
            f"Estimated Delivery: {tracking_info.get('estimated_delivery', 'N/A')}\n"
            f"\nTimeline:\n{timeline_str}"
        )
    except AdapterError as e:
        logger.error(f"Adapter error in track_order: {e}", exc_info=True)
        return "Error: Vendra's external integration service is temporarily unavailable. Please try again later."
    except Exception as e:
        logger.error(f"Error tracking order {oid}: {e}", exc_info=True)
        return f"Error: Order #{oid} not found. Please check the order ID and try again."

@tool
def get_order_status(order_id: str, customer_id: str) -> str:
    """
    Retrieve details of a specific order (status, items, total, date) for the customer.
    Checks order ownership first.
    
    Args:
        order_id: Unique order ID (e.g. ORD123).
        customer_id: Customer ID requesting the details (for privacy verification).
    """
    oid = str(order_id).strip()
    cid = str(customer_id).strip()
    
    if not validate_order_id(oid):
        return "Error: Invalid order_id format."
        
    from agent.logging_config import ctx_customer_id
    verified_cust_id = ctx_customer_id.get()
    if verified_cust_id != "N/A":
        cid = verified_cust_id
    try:
        order = adapter.get_order(oid)
        if not order:
            return f"Error: Order #{oid} not found."
            
        if order.get("customer_id") != cid:
            return "Refused: Access denied. You do not own this order."
            
        items_str = ", ".join(f"{item['quantity']}x product {item['product_id']} (size {item['size']})" for item in order.get("items", []))
        return (
            f"Order Details (ID: {oid}, Customer ID: {cid}):\n"
            f"Date: {order.get('created_at')}\n"
            f"Status: {order.get('status').upper()}\n"
            f"Items: [{items_str}]\n"
            f"Total: {order.get('total'):.2f} BDT"
        )
    except AdapterError as e:
        logger.error(f"Adapter error in get_order_status: {e}", exc_info=True)
        return "Error: Vendra's external integration service is temporarily unavailable. Please try again later."
    except Exception as e:
        logger.error(f"Error fetching order status: {e}", exc_info=True)
        return f"Error fetching order status: {str(e)}"

@tool
def check_cancellation_eligibility(order_id: str, customer_id: str) -> str:
    """
    Deterministic evaluation of order cancellation eligibility based on store policy.
    Checks ownership verification, cancellation window (7 days), final-sale items, and current status.
    
    Args:
        order_id: Unique ID of the order.
        customer_id: Customer ID requesting cancellation (for privacy verification).
        
    Returns:
        JSON string containing:
        {
          "eligible": boolean,
          "reason": string,
          "refund_type": "full_refund" | "store_credit" | "none",
          "order_id": str
        }
    """
    oid = str(order_id).strip()
    cid = str(customer_id).strip()
    
    if not validate_order_id(oid):
        return json.dumps({
            "eligible": False,
            "reason": "Error: Invalid order_id format.",
            "refund_type": "none",
            "order_id": oid
        })
        
    from agent.logging_config import ctx_customer_id
    verified_cust_id = ctx_customer_id.get()
    if verified_cust_id != "N/A":
        cid = verified_cust_id
    try:
        order = adapter.get_order(oid)
        if not order:
            return json.dumps({
                "eligible": False,
                "reason": f"Order #{oid} not found.",
                "refund_type": "none",
                "order_id": oid
            })
            
        # Hard Programmatic Ownership Validation
        if order.get("customer_id") != cid:
            return json.dumps({
                "eligible": False,
                "reason": "Refused: Access denied. You do not own this order.",
                "refund_type": "none",
                "order_id": oid
            })
            
        if order["status"] in ["cancelled", "refunded"]:
            return json.dumps({
                "eligible": False,
                "reason": f"Order #{oid} is already '{order['status']}'.",
                "refund_type": "none",
                "order_id": oid
            })
            
        if order["status"] != "paid":
            return json.dumps({
                "eligible": False,
                "reason": f"Order #{oid} is in status '{order['status']}'. Only paid orders can be cancelled/refunded.",
                "refund_type": "none",
                "order_id": oid
            })
            
        for item in order.get("items", []):
            prod_details = adapter.get_product_details(item["product_id"])
            if prod_details:
                cat = str(prod_details.get("category", "")).lower()
                desc = str(prod_details.get("description", "")).lower()
                if cat == "sale" or "final sale" in desc:
                    return json.dumps({
                        "eligible": False,
                        "reason": f"Item '{prod_details['name']}' in Order #{oid} is a final sale item and cannot be cancelled or refunded.",
                        "refund_type": "none",
                        "order_id": oid
                    })
                    
        created_at = order.get("created_at")
        if isinstance(created_at, str):
            if created_at.endswith("Z"):
                created_at = created_at[:-1] + "+00:00"
            created_at_dt = datetime.datetime.fromisoformat(created_at)
        else:
            created_at_dt = created_at
            
        if created_at_dt.tzinfo is not None:
            now = datetime.datetime.now(datetime.timezone.utc)
        else:
            now = datetime.datetime.now(datetime.timezone.utc).replace(tzinfo=None)
            
        age_delta = now - created_at_dt
        age_in_days = age_delta.total_seconds() / 86400.0
        
        if age_in_days <= 7.0:
            return json.dumps({
                "eligible": True,
                "reason": f"Order #{oid} was placed {age_in_days:.2f} days ago (within the 7-day cancellation window).",
                "refund_type": "full_refund",
                "order_id": oid
            })
        else:
            current_credit = adapter.get_store_credit(cid)
            return json.dumps({
                "eligible": False,
                "reason": f"Order #{oid} was placed {age_in_days:.2f} days ago (outside the 7-day cancellation window). Store credit is offered.",
                "refund_type": "store_credit",
                "order_id": oid,
                "current_store_credit": current_credit
            })
    except AdapterError as e:
        logger.error(f"Adapter error in check_cancellation_eligibility: {e}", exc_info=True)
        return json.dumps({
            "eligible": False,
            "reason": "Error: Vendra's external integration service is temporarily unavailable. Please try again later.",
            "refund_type": "none",
            "order_id": oid
        })
    except Exception as e:
        logger.error(f"Error checking cancellation eligibility: {e}", exc_info=True)
        return json.dumps({
            "eligible": False,
            "reason": f"Error determining eligibility: {str(e)}",
            "refund_type": "none",
            "order_id": oid
        })

@tool
def cancel_order(order_id: str, customer_id: str, config: RunnableConfig = None) -> str:
    """
    Submit a refund or cancellation request for admin approval.
    Checks customer ownership verification and cancellation eligibility before submitting.
    
    Args:
        order_id: Unique order ID to cancel.
        customer_id: Customer ID requesting cancellation (for privacy verification).
    """
    oid = str(order_id).strip()
    cid = str(customer_id).strip()
    
    if not validate_order_id(oid):
        return "Error: Invalid order_id format."
        
    from agent.logging_config import ctx_customer_id
    verified_cust_id = ctx_customer_id.get()
    if verified_cust_id != "N/A":
        cid = verified_cust_id
    try:
        elig_res_json = check_cancellation_eligibility.invoke({"order_id": oid, "customer_id": cid})
        eligibility = json.loads(elig_res_json)
        
        refund_type = eligibility.get("refund_type")
        if refund_type == "none":
            return f"Cancellation Rejected: {eligibility.get('reason')}"
            
        order = adapter.get_order(oid)
        if not order:
            return f"Error: Order #{oid} not found."
            
        # Get thread_id from run config
        thread_id = "default_thread"
        if config:
            configurable = config.get("configurable", {})
            thread_id = configurable.get("thread_id", "default_thread")
            
        # Create refund request record in DB
        eligibility_reason = eligibility.get("reason", "Eligible for refund")
        req = adapter.create_refund_request(
            order_id=oid,
            customer_id=cid,
            refund_type=refund_type,
            eligibility_reason=eligibility_reason,
            thread_id=thread_id
        )
        
        return (
            f"Your request to cancel Order #{oid} (Refund Type: {refund_type.upper()}) "
            f"has been submitted for review. Request ID: {req['id']}. "
            f"You will be notified once our admin team approves or denies your request. "
            f"Please note that the refund will not be processed automatically until approved."
        )
    except AdapterError as e:
        logger.error(f"Adapter error in cancel_order: {e}", exc_info=True)
        return "Error: Vendra's external integration service is temporarily unavailable. Please try again later."
    except Exception as e:
        logger.error(f"Error submitting cancellation request: {e}", exc_info=True)
        return f"Error submitting cancellation: {str(e)}"

@tool
def retrieve_policy_text(query: str) -> str:
    """
    Search and retrieve return and cancellation policies from the store handbook.
    Uses Corrective RAG (CRAG) grading and fallback reformulation to verify policy relevance.
    Use this tool to explain the refund or cancellation rules to customers. Do not make up rules.
    
    Args:
        query: Specific topic of query (e.g., return window, sale policy).
    """
    try:
        # Step 1: Initial Retrieval (K=3)
        results = search_policies(query, top_k=3)
        
        # Check if API keys are configured. If not, bypass grading (Simulation/Test mode)
        groq_key = os.getenv("GROQ_API_KEY")
        has_keys = groq_key and not groq_key.startswith("your_")
        
        if not has_keys:
            # Bypass grading when no keys are available
            if not results:
                return "No matching policy text found."
            output = ["Relevant Policy Clauses (Bypassed Grading):"]
            for idx, res in enumerate(results, 1):
                output.append(f"{idx}. {res['text']}")
            return "\n\n".join(output)
            
        from langchain_groq import ChatGroq
        from langchain_core.messages import SystemMessage, HumanMessage
        
        groq_model = os.getenv("GROQ_MODEL", "llama-3.1-8b-instant")
        secondary_model = os.getenv("SECONDARY_GROQ_MODEL", "llama-3.3-70b-versatile")
        llm = ChatGroq(model=groq_model, temperature=0, groq_api_key=groq_key)
        
        llm_fallback = None
        if secondary_model:
            llm_fallback = ChatGroq(model=secondary_model, temperature=0, groq_api_key=groq_key)
            
        def run_llm(messages):
            try:
                return llm.invoke(messages)
            except Exception as primary_e:
                if llm_fallback:
                    logger.warning(f"Primary model {groq_model} failed in retrieve_policy_text: {primary_e}. Falling back to {secondary_model}.")
                    return llm_fallback.invoke(messages)
                raise primary_e
        
        # Step 2: Grade retrieved chunks
        relevant_results = []
        for res in results:
            grader_system = (
                "You are an expert document relevance grader for an e-commerce store.\n"
                "Determine if the retrieved policy chunk is relevant and helpful to answer the customer query.\n"
                "Respond with exactly 'YES' or 'NO'."
            )
            grader_user = f"Customer Query: {query}\n\nRetrieved Policy Chunk:\n{res['text']}"
            try:
                grade_res = run_llm([
                    SystemMessage(content=grader_system),
                    HumanMessage(content=grader_user)
                ])
                grade = str(grade_res.content).strip().upper()
                if "YES" in grade:
                    relevant_results.append(res)
            except Exception as e:
                logger.error(f"Grading failed for chunk: {e}", exc_info=True)
                relevant_results.append(res) # Fallback to keeping it on failure
                
        # Step 3: If no chunks are relevant, perform Query Reformulation (CRAG)
        if not relevant_results:
            reformulate_system = (
                "You are a search query optimizer for e-commerce return policies.\n"
                "Reformulate the customer's query into a simple, broad keyword search query (e.g., 'return window', 'sale items', 'refund method').\n"
                "Respond with only the reformulated search string and nothing else."
            )
            reformulate_user = f"Original Query: {query}"
            
            try:
                reform_res = run_llm([
                    SystemMessage(content=reformulate_system),
                    HumanMessage(content=reformulate_user)
                ])
                new_query = str(reform_res.content).strip()
                print(f"CRAG: Reformulated query from '{query}' to '{new_query}'")
                
                # Retrieve again with new query
                new_results = search_policies(new_query, top_k=2)
                for res in new_results:
                    # Grade new results
                    grade_res = run_llm([
                        SystemMessage(content=grader_system),
                        HumanMessage(content=f"Customer Query: {query}\n\nRetrieved Policy Chunk:\n{res['text']}")
                    ])
                    grade = str(grade_res.content).strip().upper()
                    if "YES" in grade:
                        relevant_results.append(res)
            except Exception as e:
                logger.error(f"Query reformulation or re-grading failed: {e}", exc_info=True)
                
        # Step 4: Fallback to General/Intro chunks if still empty
        if not relevant_results:
            print("CRAG: No relevant chunks found. Falling back to policy introduction.")
            # Search for "return policy introduction rules" or general terms
            fallback_results = search_policies("return policy introduction rules", top_k=2)
            relevant_results.extend(fallback_results)
            
        if not relevant_results:
            return "No matching policy text found."
            
        output = ["Relevant Policy Clauses (Graded & Verified):"]
        for idx, res in enumerate(relevant_results, 1):
            output.append(f"{idx}. {res['text']}")
            
        return "\n\n".join(output)
    except AdapterError as e:
        logger.error(f"Adapter error in retrieve_policy_text: {e}", exc_info=True)
        return "Error: Vendra's external integration service is temporarily unavailable. Please try again later."
    except Exception as e:
        logger.error(f"Error retrieving policy text: {e}", exc_info=True)
        return f"Error retrieving policy text: {str(e)}"

# Direct imports from search_service at the bottom to avoid circular dependencies
from agent.search_service import (
    search_products_text,
    search_products_image,
    search_policies
)
