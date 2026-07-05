import os
import json
import stripe
import logging
from fastapi import FastAPI, Request, Header, HTTPException
from pydantic import BaseModel
from dotenv import load_dotenv

from agent.tools import confirm_payment

load_dotenv(override=True)

# Configure logger
logger = logging.getLogger("uvicorn.error")

app = FastAPI(title="Vendra API Backend", version="1.0.0")

stripe.api_key = os.getenv("STRIPE_SECRET_KEY")
STRIPE_WEBHOOK_SECRET = os.getenv("STRIPE_WEBHOOK_SECRET")

class MockWebhookPayload(BaseModel):
    order_id: str
    stripe_event_id: str
    mock: bool = True

@app.on_event("startup")
async def startup_event() -> None:
    mock_enabled = os.getenv("MOCK_WEBHOOK_ENABLED", "false").lower() == "true"
    is_production = os.getenv("ENV") == "production"
    if mock_enabled and not is_production:
        logger.warning("WARNING: Mock Stripe webhook mode is active. This configuration is UNSAFE for production.")

@app.get("/")
def read_root():
    return {"message": "Vendra API Backend is running."}

@app.post("/webhook/stripe")
async def stripe_webhook(request: Request, stripe_signature: str = Header(None)):
    """
    Stripe Webhook handler. Updates order status to 'paid' when checkout completes.
    Features signature verification and event idempotency check.
    """
    payload = await request.body()
    
    # 1. Check for mock test payload
    if not stripe_signature:
        mock_enabled = os.getenv("MOCK_WEBHOOK_ENABLED", "false").lower() == "true"
        is_production = os.getenv("ENV") == "production"
        
        # Secure endpoint: prevent signature bypass in production or when not explicitly enabled
        if not mock_enabled or is_production:
            raise HTTPException(status_code=400, detail="Missing stripe-signature header")
            
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
            print(f"Order #{order_id} marked as PAID via stripe event {event_id}")
            
    return {"status": "success"}
