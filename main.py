import os
import json
import stripe
import logging
from typing import Optional
from fastapi import FastAPI, Request, Header, HTTPException, Depends, status
from pydantic import BaseModel
from dotenv import load_dotenv
from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.util import get_remote_address
from slowapi.errors import RateLimitExceeded

from agent.tools import confirm_payment

from agent.logging_config import setup_logging
setup_logging()

# Configure logger
logger = logging.getLogger("vendra")

limiter = Limiter(key_func=get_remote_address)
app = FastAPI(title="Vendra API Backend", version="1.0.0")
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

# CORS middleware
from fastapi.middleware.cors import CORSMiddleware
allowed_origins_env = os.getenv("ALLOWED_ORIGINS", "http://localhost:8501,http://localhost:3000")
allowed_origins = [orig.strip() for orig in allowed_origins_env.split(",") if orig.strip()]
app.add_middleware(
    CORSMiddleware,
    allow_origins=allowed_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

from fastapi.staticfiles import StaticFiles
app.mount("/static", StaticFiles(directory="static"), name="static")

import uuid
from agent.logging_config import ctx_customer_id, ctx_request_id, ctx_agent_name
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from agent.auth_utils import decode_jwt_token, hash_password, check_password, create_jwt_token

security = HTTPBearer(auto_error=False)

async def get_current_customer_id(credentials: Optional[HTTPAuthorizationCredentials] = Depends(security)) -> str:
    if not credentials:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Session token missing. Please log in."
        )
    token = credentials.credentials
    customer_id = decode_jwt_token(token)
    if not customer_id:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Session token is invalid or expired. Please log in again."
        )
    return customer_id

@app.middleware("http")
async def add_logging_context(request: Request, call_next):
    ctx_agent_name.set("api_gateway")
    req_id = request.headers.get("X-Request-ID") or str(uuid.uuid4())[:8]
    ctx_request_id.set(req_id)
    
    customer_id = "N/A"
    path = request.url.path
    if "cart_" in path:
        parts = path.split("cart_")
        if len(parts) > 1:
            customer_id = parts[1].split("/")[0]
            
    ctx_customer_id.set(customer_id)
    
    response = await call_next(request)
    response.headers["X-Request-ID"] = req_id
    return response

stripe.api_key = os.getenv("STRIPE_SECRET_KEY")
STRIPE_WEBHOOK_SECRET = os.getenv("STRIPE_WEBHOOK_SECRET")

from fastapi.exceptions import RequestValidationError
from starlette.exceptions import HTTPException as StarletteHTTPException
from fastapi.responses import JSONResponse

@app.exception_handler(Exception)
async def unhandled_exception_handler(request: Request, exc: Exception):
    if isinstance(exc, StarletteHTTPException):
        return JSONResponse(
            status_code=exc.status_code,
            content={"detail": exc.detail}
        )
    if isinstance(exc, RequestValidationError):
        return JSONResponse(
            status_code=422,
            content={"detail": exc.errors()}
        )
        
    logger.error(f"Unhandled system error: {exc}", exc_info=True)
    return JSONResponse(
        status_code=500,
        content={"detail": "An internal server error occurred. Please try again later."}
    )

@app.on_event("startup")
async def startup_event() -> None:
    from config import validate_config
    validate_config()

    db_url = os.getenv("DATABASE_URL", "sqlite:///data/vendra.db")
    if "sqlite" in db_url.lower():
        logger.warning(
            "⚠️ WARNING: Running on SQLite with multiple uvicorn workers is UNSAFE. "
            "SQLite file-level locking does not support concurrent multi-process writes. "
            "For multi-worker production configurations, you must configure ADAPTER=postgres."
        )

    mock_enabled = os.getenv("MOCK_WEBHOOK_ENABLED", "false").lower() == "true"
    is_production = os.getenv("ENV") == "production"
    if mock_enabled and not is_production:
        logger.warning("WARNING: Mock Stripe webhook mode is active. This configuration is UNSAFE for production.")

class SignupRequest(BaseModel):
    email: str
    password: str
    name: str
    phone: Optional[str] = ""
    address: Optional[str] = ""

class LoginRequest(BaseModel):
    email: str
    password: str

@app.post("/api/auth/signup")
@limiter.limit("10/minute")
def signup_endpoint(payload: SignupRequest, request: Request):
    from agent.tools import adapter
    existing = adapter.customers
    if any(c["email"].lower() == payload.email.lower() for c in existing):
        raise HTTPException(status_code=400, detail="A customer with this email already exists.")
        
    max_num = 20
    for c in existing:
        id_str = c["id"]
        if id_str.startswith("C"):
            try:
                num = int(id_str[1:])
                if num > max_num:
                    max_num = num
            except ValueError:
                pass
    new_id = f"C{max_num + 1:03d}"
    
    hashed = hash_password(payload.password)
    new_customer = {
        "id": new_id,
        "name": payload.name,
        "email": payload.email,
        "phone": payload.phone,
        "address": payload.address,
        "store_credit": 0.0,
        "password_hash": hashed
    }
    adapter.customers = existing + [new_customer]
    
    token = create_jwt_token(new_id)
    return {
        "status": "success",
        "token": token,
        "customer_id": new_id,
        "name": payload.name
    }

@app.post("/api/auth/login")
@limiter.limit("5/minute")
def login_endpoint(payload: LoginRequest, request: Request):
    from agent.tools import adapter
    existing = adapter.customers
    customer = next((c for c in existing if c["email"].lower() == payload.email.lower()), None)
    
    if not customer or not check_password(payload.password, customer.get("password_hash")):
        raise HTTPException(status_code=401, detail="Invalid email or password.")
        
    token = create_jwt_token(customer["id"])
    return {
        "status": "success",
        "token": token,
        "customer_id": customer["id"],
        "name": customer["name"]
    }

@app.get("/")
def read_root():
    return {"message": "Vendra API Backend is running."}

@app.get("/health")
@limiter.limit("30/minute")
async def health_check(request: Request):
    from fastapi.responses import JSONResponse
    from adapters import get_adapter
    db_ok = False
    db_error = None
    try:
        adapter = get_adapter()
        adapter.get_promotions()
        db_ok = True
    except Exception as e:
        db_error = str(e)
        
    redis_ok = True
    redis_error = None
    redis_url = os.getenv("REDIS_URL")
    if redis_url:
        try:
            import redis
            r = redis.Redis.from_url(redis_url, socket_connect_timeout=1)
            r.ping()
        except Exception as e:
            redis_ok = False
            redis_error = str(e)
            
    status_code = status.HTTP_200_OK if (db_ok and redis_ok) else status.HTTP_503_SERVICE_UNAVAILABLE
    
    return JSONResponse(
        status_code=status_code,
        content={
            "status": "healthy" if (db_ok and redis_ok) else "unhealthy",
            "database": {"status": "connected" if db_ok else "disconnected", "error": db_error},
            "redis": {"status": "connected" if redis_ok else "disconnected", "error": redis_error} if redis_url else {"status": "disabled"}
        }
    )

@app.get("/metrics")
@limiter.limit("30/minute")
def metrics_endpoint(request: Request):
    from fastapi import Response
    from agent.metrics import METRICS
    from adapters import get_adapter
    
    refund_queue_depth = 0
    try:
        adapter = get_adapter()
        refund_queue_depth = len(adapter.get_pending_refund_requests())
    except Exception:
        pass
        
    lines = []
    
    lines.append("# HELP vendra_subagent_requests_total Total requests processed by sub-agent")
    lines.append("# TYPE vendra_subagent_requests_total counter")
    for agent, count in METRICS.subagent_requests.items():
        lines.append(f'vendra_subagent_requests_total{{agent="{agent}"}} {count}')
        
    lines.append("# HELP vendra_subagent_errors_total Total errors processed by sub-agent")
    lines.append("# TYPE vendra_subagent_errors_total counter")
    for agent, count in METRICS.subagent_errors.items():
        lines.append(f'vendra_subagent_errors_total{{agent="{agent}"}} {count}')
        
    lines.append("# HELP vendra_subagent_latency_seconds_sum Sum of latency in seconds for sub-agent execution")
    lines.append("# TYPE vendra_subagent_latency_seconds_sum counter")
    for agent, latency in METRICS.subagent_latency_sum.items():
        lines.append(f'vendra_subagent_latency_seconds_sum{{agent="{agent}"}} {latency:.4f}')
        
    lines.append("# HELP vendra_subagent_latency_seconds_count Count of latency measurements for sub-agent execution")
    lines.append("# TYPE vendra_subagent_latency_seconds_count counter")
    for agent, count in METRICS.subagent_latency_count.items():
        lines.append(f'vendra_subagent_latency_seconds_count{{agent="{agent}"}} {count}')
        
    lines.append("# HELP vendra_refund_request_queue_depth Current depth of the pending refund request queue")
    lines.append("# TYPE vendra_refund_request_queue_depth gauge")
    lines.append(f"vendra_refund_request_queue_depth {refund_queue_depth}")
    
    return Response(content="\n".join(lines) + "\n", media_type="text/plain")

@app.post("/webhook/stripe")
@limiter.limit("120/minute")
async def stripe_webhook(request: Request, stripe_signature: str = Header(None)):
    """
    Stripe Webhook handler. Updates order status to 'paid' when checkout completes.
    Features signature verification and event idempotency check.
    """
    payload = await request.body()
    
    # Secure validation: Check if payload specifies mock mode and enforce production lockout
    try:
        data = json.loads(payload)
        if data.get("mock") is True:
            mock_enabled = os.getenv("MOCK_WEBHOOK_ENABLED", "false").lower() == "true"
            is_production = os.getenv("ENV") == "production"
            if is_production or not mock_enabled:
                raise HTTPException(status_code=400, detail="Missing stripe-signature header")
    except json.JSONDecodeError:
        pass

    # 1. Check for mock test payload
    if not stripe_signature:
        try:
            data = json.loads(payload)
            if data.get("mock") is True:
                order_id = str(data.get("order_id"))
                event_id = data.get("stripe_event_id")
                
                # Update order status via tool
                res = confirm_payment(order_id, event_id)
                if "Error" in res:
                    raise HTTPException(status_code=404, detail=res)
                
                if "already processed" in res or "idempotence" in res:
                    return {"status": "success", "message": "Event already processed (idempotent)"}
                
                return {"status": "success", "message": f"Order #{order_id} marked as paid via Mock Webhook."}
        except HTTPException:
            raise
        except Exception as e:
            raise HTTPException(status_code=400, detail=f"Invalid webhook payload structure: {str(e)}")
            
        raise HTTPException(status_code=400, detail="Missing stripe-signature header")
        
    # 2. Process actual Stripe Webhook
    try:
        event = stripe.Webhook.construct_event(
            payload, stripe_signature, STRIPE_WEBHOOK_SECRET
        )
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid payload")
    except stripe.error.SignatureVerificationError:
        raise HTTPException(status_code=400, detail="Invalid signature")
        
    event_id = event.get("id")
    event_type = event.get("type")
    
    if event_type == "checkout.session.completed":
        session = event.get("data", {}).get("object", {})
        metadata = session.get("metadata", {})
        order_id = metadata.get("order_id")
        
        if order_id:
            res = confirm_payment(order_id, event_id)
            if "already processed" in res or "idempotence" in res:
                return {"status": "success", "message": "Event already processed (idempotent)"}
            logger.info(f"Order #{order_id} marked as PAID via stripe event {event_id}")
            
    return {"status": "success"}

# Secure Admin API Auth Check
async def verify_admin_key(x_admin_api_key: str | None = Header(None, alias="X-Admin-API-Key")):
    expected_key = os.getenv("ADMIN_API_KEY")
    if not expected_key or not x_admin_api_key or x_admin_api_key != expected_key:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or missing X-Admin-API-Key"
        )

@app.get("/api/refunds/pending")
@limiter.limit("30/minute")
async def get_pending_refunds(request: Request, admin: None = Depends(verify_admin_key)):
    from adapters import get_adapter
    adapter = get_adapter()
    return adapter.get_pending_refund_requests()

@app.post("/api/refunds/{request_id}/approve")
@limiter.limit("30/minute")
async def approve_refund(request_id: str, request: Request, admin: None = Depends(verify_admin_key)):
    from adapters import get_adapter
    adapter = get_adapter()
    req = adapter.get_refund_request(request_id)
    if not req:
        raise HTTPException(status_code=404, detail="Refund request not found")
    if req["status"] != "pending_review":
        raise HTTPException(status_code=400, detail=f"Refund request is in status {req['status']}, cannot approve")
        
    # 1. Update status in database
    success = adapter.update_refund_request(
        request_id=request_id,
        status="approved",
        reviewed_by="admin",
        review_notes="Approved via admin API"
    )
    if not success:
        raise HTTPException(status_code=500, detail="Failed to update database record")
        
    # 2. Resume graph execution via Command(resume=...)
    from agent.graph import graph
    from langgraph.types import Command
    
    thread_id = req.get("thread_id", "default_thread")
    config = {"configurable": {"thread_id": thread_id}}
    
    try:
        graph.invoke(Command(resume={"action": "approve", "notes": "Approved via admin API"}), config)
    except Exception as e:
        logger.error(f"Failed to resume graph for approved refund: {e}", exc_info=True)
        
    return {"message": "Refund request approved successfully", "request_id": request_id}

@app.post("/api/refunds/{request_id}/deny")
@limiter.limit("30/minute")
async def deny_refund(request_id: str, request: Request, review_notes: str = "Denied via admin API", admin: None = Depends(verify_admin_key)):
    from adapters import get_adapter
    adapter = get_adapter()
    req = adapter.get_refund_request(request_id)
    if not req:
        raise HTTPException(status_code=404, detail="Refund request not found")
    if req["status"] != "pending_review":
        raise HTTPException(status_code=400, detail=f"Refund request is in status {req['status']}, cannot deny")
        
    # 1. Update status in database
    success = adapter.update_refund_request(
        request_id=request_id,
        status="denied",
        reviewed_by="admin",
        review_notes=review_notes
    )
    if not success:
        raise HTTPException(status_code=500, detail="Failed to update database record")
        
    # 2. Resume graph execution via Command(resume=...)
    from agent.graph import graph
    from langgraph.types import Command
    
    thread_id = req.get("thread_id", "default_thread")
    config = {"configurable": {"thread_id": thread_id}}
    
    try:
        graph.invoke(Command(resume={"action": "deny", "notes": review_notes}), config)
    except Exception as e:
        logger.error(f"Failed to resume graph for denied refund: {e}", exc_info=True)
        
    return {"message": "Refund request denied successfully", "request_id": request_id}

class ChatRequest(BaseModel):
    message: str
    history: list[dict]
    customer_id: Optional[str] = ""
    current_order_id: Optional[str] = ""
    active_node: Optional[str] = "general"
    intent: Optional[str] = "general"
    image_bytes: Optional[str] = None

@app.post("/api/chat")
@limiter.limit("60/minute")
async def chat_endpoint(request: Request, payload: ChatRequest, customer_id: str = Depends(get_current_customer_id)):
    if payload.message and len(payload.message) > 3000:
        raise HTTPException(status_code=400, detail="Message exceeds maximum allowed length of 3000 characters.")
        
    ctx_customer_id.set(customer_id)
    ctx_agent_name.set("orchestrator")
    from langchain_core.messages import HumanMessage, AIMessage, SystemMessage, ToolMessage
    
    # Reconstruct messages from history and current message
    messages_to_parse = list(payload.history)
    if payload.message:
        messages_to_parse.append({"role": "user", "content": payload.message})
        
    parsed_messages = []
    for m in messages_to_parse:
        role = m.get("role")
        content = m.get("content", "")
        if role == "user":
            parsed_messages.append(HumanMessage(content=content))
        elif role == "assistant":
            parsed_messages.append(AIMessage(content=content))
        elif role == "system":
            parsed_messages.append(SystemMessage(content=content))
        elif role == "tool":
            parsed_messages.append(ToolMessage(content=content, name=m.get("name", "tool"), tool_call_id=m.get("tool_call_id", "")))
            
    # Decode base64 image bytes if present
    image_bytes = None
    if payload.image_bytes:
        try:
            import base64
            image_bytes = base64.b64decode(payload.image_bytes)
        except Exception as e:
            logger.error(f"Failed to decode base64 image_bytes: {e}")
            
    from agent.graph import graph
    
    cart_id = f"cart_{customer_id}"
    
    state_input = {
        "messages": parsed_messages,
        "customer_id": customer_id,
        "cart_id": cart_id,
        "current_order_id": payload.current_order_id,
        "image_bytes": image_bytes,
        "active_node": payload.active_node,
        "intent": payload.intent
    }
    
    thread_id = f"thread_{customer_id}"
    config = {"configurable": {"thread_id": thread_id}}
    
    try:
        output = graph.invoke(state_input, config)
    except Exception as e:
        logger.error(f"Graph invocation failed in API: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Agent graph execution failed: {str(e)}")
        
    serialized_messages = []
    for m in output.get("messages", []):
        if isinstance(m, HumanMessage):
            serialized_messages.append({"role": "user", "content": m.content})
        elif isinstance(m, AIMessage):
            serialized_messages.append({"role": "assistant", "content": m.content})
        elif isinstance(m, SystemMessage):
            serialized_messages.append({"role": "system", "content": m.content})
        elif isinstance(m, ToolMessage):
            serialized_messages.append({"role": "tool", "content": m.content, "name": m.name, "tool_call_id": m.tool_call_id})
            
    return {
        "messages": serialized_messages,
        "active_node": output.get("active_node"),
        "intent": output.get("intent"),
        "current_order_id": output.get("current_order_id")
    }

# --- REST API Endpoints for Frontend Decoupling ---

@app.get("/api/cart/{cart_id}")
@limiter.limit("60/minute")
def get_cart(cart_id: str, request: Request, customer_id: str = Depends(get_current_customer_id)):
    if cart_id != f"cart_{customer_id}":
        raise HTTPException(status_code=403, detail="Forbidden: You do not own this cart.")
    from agent.tools import CARTS
    return {"cart_id": cart_id, "items": CARTS.get(cart_id, [])}

class CartAddRequest(BaseModel):
    product_id: str
    size: str
    quantity: int = 1

@app.post("/api/cart/{cart_id}/add")
@limiter.limit("60/minute")
def add_to_cart_endpoint(cart_id: str, payload: CartAddRequest, request: Request, customer_id: str = Depends(get_current_customer_id)):
    if cart_id != f"cart_{customer_id}":
        raise HTTPException(status_code=403, detail="Forbidden: You do not own this cart.")
    from agent.tools import CARTS, update_cart_activity, adapter
    cid = cart_id.strip()
    pid = payload.product_id.strip()
    size = payload.size.strip()
    qty = payload.quantity
    
    # Verify stock
    stock = adapter.check_stock(pid, size)
    if stock <= 0:
        raise HTTPException(status_code=400, detail=f"Size {size} for product {pid} is out of stock.")
         
    if cid not in CARTS:
        CARTS[cid] = []
        
    # Get product details for name/price
    details = adapter.get_product_details(pid)
    name = details.get("name", "Shoe")
    price = details.get("price", 0.0)
    
    # Check if item already exists
    existing = next((item for item in CARTS[cid] if item["product_id"] == pid and item["size"] == size), None)
    if existing:
        if existing["quantity"] + qty > stock:
            raise HTTPException(status_code=400, detail=f"Cannot add {qty} more units. Total quantity in cart would exceed available stock.")
        existing["quantity"] += qty
        existing["subtotal"] = existing["quantity"] * existing["price"]
    else:
        CARTS[cid].append({
            "product_id": pid,
            "name": name,
            "size": size,
            "quantity": qty,
            "price": price,
            "subtotal": qty * price
        })
    update_cart_activity(cid)
    return {"status": "success", "cart": CARTS.get(cid, [])}

@app.post("/api/cart/{cart_id}/remove")
@limiter.limit("60/minute")
def remove_from_cart_endpoint(cart_id: str, product_id: str, request: Request, customer_id: str = Depends(get_current_customer_id)):
    if cart_id != f"cart_{customer_id}":
        raise HTTPException(status_code=403, detail="Forbidden: You do not own this cart.")
    from agent.tools import CARTS, update_cart_activity
    cid = cart_id.strip()
    pid = product_id.strip()
    if cid in CARTS:
        CARTS[cid] = [item for item in CARTS[cid] if item["product_id"] != pid]
        update_cart_activity(cid)
    return {"status": "success", "cart": CARTS.get(cid, [])}

@app.get("/api/customers/{customer_id}")
@limiter.limit("60/minute")
def get_customer(customer_id: str, request: Request, authenticated_customer_id: str = Depends(get_current_customer_id)):
    if customer_id != authenticated_customer_id:
        raise HTTPException(status_code=403, detail="Forbidden: You cannot view another customer's profile.")
    from agent.tools import adapter
    cust = next((c for c in adapter.customers if c["id"] == customer_id), None)
    if not cust:
        raise HTTPException(status_code=404, detail="Customer not found")
    cust_copy = dict(cust)
    cust_copy.pop("password_hash", None)
    return cust_copy

@app.get("/api/products/{product_id}/details")
@limiter.limit("60/minute")
def get_product_details_endpoint(product_id: str, request: Request):
    from agent.tools import adapter
    details = adapter.get_product_details(product_id)
    if not details:
        raise HTTPException(status_code=404, detail="Product not found")
    return details

@app.get("/api/inventory")
@limiter.limit("60/minute")
def get_inventory(request: Request):
    from agent.tools import adapter
    return getattr(adapter, "inventory", {})

@app.get("/api/orders")
@limiter.limit("60/minute")
def list_orders(customer_id: str, request: Request, authenticated_customer_id: str = Depends(get_current_customer_id)):
    if customer_id != authenticated_customer_id:
        raise HTTPException(status_code=403, detail="Forbidden: You cannot view another customer's orders.")
    from agent.tools import adapter
    orders_list = list(adapter.orders.values())
    filtered = [o for o in orders_list if o["customer_id"] == customer_id]
    return {"orders": filtered}

@app.get("/api/orders/{order_id}/tracking")
@limiter.limit("60/minute")
def get_order_tracking(order_id: str, request: Request, authenticated_customer_id: str = Depends(get_current_customer_id)):
    from agent.tools import adapter
    tracking_data = adapter.track_order(order_id, authenticated_customer_id)
    if "error" in tracking_data:
        if "Access denied" in tracking_data["error"] or "Refused" in tracking_data["error"]:
            raise HTTPException(status_code=403, detail=tracking_data["error"])
        else:
            raise HTTPException(status_code=404, detail=tracking_data["error"])
            
    if not tracking_data:
        # Fallback tracking info if not in db but exists
        orders_dict = adapter.orders
        ord_obj = orders_dict.get(order_id)
        if not ord_obj:
            raise HTTPException(status_code=404, detail=f"Order {order_id} not found.")
        if ord_obj.get("customer_id") != authenticated_customer_id:
            raise HTTPException(status_code=403, detail="Access denied. You do not own this order.")
        return {
            "order_id": order_id,
            "courier": "Pending",
            "tracking_code": "Pending",
            "status": ord_obj.get("status", "pending_payment"),
            "estimated_delivery": None,
            "timeline": [
                {"time": ord_obj.get("created_at"), "event": "Order placed, awaiting processing."}
            ]
        }
    return tracking_data
