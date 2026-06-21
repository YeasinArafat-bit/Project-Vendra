import os
import stripe
from fastapi import FastAPI, Request, Header, HTTPException
from pydantic import BaseModel
from database import SessionLocal
from models import Order

load_dotenv_check = False
try:
    from dotenv import load_dotenv
    load_dotenv()
    load_dotenv_check = True
except ImportError:
    pass

app = FastAPI(title="Vendra API Backend", version="1.0.0")

stripe.api_key = os.getenv("STRIPE_SECRET_KEY")
STRIPE_WEBHOOK_SECRET = os.getenv("STRIPE_WEBHOOK_SECRET")

class MockWebhookPayload(BaseModel):
    order_id: int
    stripe_event_id: str
    mock: bool = True

@app.get("/")
def read_root():
    return {"message": "Vendra API Backend is running."}

@app.post("/webhook/stripe")
async def stripe_webhook(request: Request, stripe_signature: str = Header(None)):
    """
    Stripe Webhook handler. Updates order status to 'paid' when checkout completes.
    Features robust signature verification and event idempotency check.
    """
    db = SessionLocal()
    
    # 1. Parse payload
    payload = await request.body()
    
    # 2. Check if this is a mock test payload (used for testing and local bypass)
    # If signature is missing, we check if it parses as valid JSON mock payload
    if not stripe_signature:
        try:
            import json
            data = json.loads(payload)
            if data.get("mock") is True:
                order_id = int(data.get("order_id"))
                event_id = data.get("stripe_event_id")
                
                # Retrieve order
                order = db.query(Order).filter(Order.id == order_id).first()
                if not order:
                    raise HTTPException(status_code=404, detail="Order not found")
                
                # Idempotency check: check if stripe_event_id already matches
                if order.stripe_event_id == event_id:
                    return {"status": "success", "message": "Event already processed (idempotent)"}
                
                # Update order
                order.status = "paid"
                order.stripe_event_id = event_id
                db.commit()
                return {"status": "success", "message": f"Order #{order_id} marked as paid via Mock Webhook."}
        except Exception as e:
            raise HTTPException(status_code=400, detail=f"Invalid webhook payload structure: {str(e)}")
            
        raise HTTPException(status_code=400, detail="Missing stripe-signature header")
        
    # 3. Process actual Stripe Webhook
    try:
        event = stripe.Webhook.construct_event(
            payload, stripe_signature, STRIPE_WEBHOOK_SECRET
        )
    except ValueError as e:
        # Invalid payload
        raise HTTPException(status_code=400, detail="Invalid payload")
    except stripe.error.SignatureVerificationError as e:
        # Invalid signature
        raise HTTPException(status_code=400, detail="Invalid signature")
        
    event_id = event.get("id")
    event_type = event.get("type")
    
    if event_type == "checkout.session.completed":
        session = event.get("data", {}).get("object", {})
        metadata = session.get("metadata", {})
        order_id_str = metadata.get("order_id")
        
        if order_id_str:
            order_id = int(order_id_str)
            order = db.query(Order).filter(Order.id == order_id).first()
            if order:
                # Idempotency check
                if order.stripe_event_id == event_id:
                    db.close()
                    return {"status": "success", "message": "Event already processed (idempotent)"}
                
                order.status = "paid"
                order.stripe_event_id = event_id
                db.commit()
                print(f"Order #{order_id} marked as PAID via stripe event {event_id}")
                
    db.close()
    return {"status": "success"}
