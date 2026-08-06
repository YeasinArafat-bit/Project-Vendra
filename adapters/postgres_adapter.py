import os
import uuid
import datetime
import threading
from sqlalchemy import create_engine, select, func
from sqlalchemy.orm import sessionmaker, scoped_session
from sqlalchemy.exc import OperationalError, DBAPIError
from adapters.base import BaseAdapter, AdapterError
from adapters.models import (
    Base, Product, ProductInventory, Customer, Order, OrderItem,
    Tracking, TrackingEvent, Promotion, StoreCreditLedger, RefundRequest
)

class DBDictProxy:
    def __init__(self, get_all_func, set_item_func, del_item_func):
        self.get_all = get_all_func
        self.set_item = set_item_func
        self.del_item = del_item_func

    def _get_dict(self):
        return self.get_all()

    def __getitem__(self, key):
        return self._get_dict()[key]

    def __setitem__(self, key, value):
        self.set_item(key, value)

    def __delitem__(self, key):
        self.del_item(key)

    def __contains__(self, key):
        return key in self._get_dict()

    def get(self, key, default=None):
        return self._get_dict().get(key, default)

    def keys(self):
        return self._get_dict().keys()

    def values(self):
        return self._get_dict().values()

    def items(self):
        return self._get_dict().items()

    def clear(self):
        for key in list(self.keys()):
            self.del_item(key)

    def update(self, other):
        for k, v in other.items():
            self.set_item(k, v)

    def __repr__(self):
        return repr(self._get_dict())


class PostgresAdapter(BaseAdapter):
    _instance = None
    _lock = threading.Lock()

    def __new__(cls, *args, **kwargs):
        if not cls._instance:
            cls._instance = super(PostgresAdapter, cls).__new__(cls, *args, **kwargs)
            cls._instance.initialized = False
        return cls._instance

    def __init__(self) -> None:
        if getattr(self, 'initialized', False):
            return
        
        db_url = os.getenv("DATABASE_URL", "sqlite:///data/vendra.db")
        if db_url.startswith("postgres://"):
            db_url = db_url.replace("postgres://", "postgresql://", 1)
            
        self.engine = create_engine(
            db_url,
            connect_args={"check_same_thread": False} if "sqlite" in db_url else {}
        )
        self.Session = scoped_session(sessionmaker(bind=self.engine))
        self.lock = threading.Lock()
        
        # Ensure all tables exist (important for tests and initialization)
        Base.metadata.create_all(bind=self.engine)
        self.initialized = True

    def reset_state(self) -> None:
        """Clear all tables for test isolation."""
        with self.lock:
            session = self.Session()
            try:
                session.query(StoreCreditLedger).delete()
                session.query(RefundRequest).delete()
                session.query(TrackingEvent).delete()
                session.query(Tracking).delete()
                session.query(OrderItem).delete()
                session.query(Order).delete()
                session.query(Customer).delete()
                session.query(ProductInventory).delete()
                session.query(Product).delete()
                session.query(Promotion).delete()
                session.commit()
            except Exception as e:
                session.rollback()
                raise AdapterError(f"Database reset failed: {e}")
            finally:
                self.Session.remove()

    @property
    def customers(self):
        session = self.Session()
        try:
            customers = session.query(Customer).all()
            return [
                {
                    "id": c.id,
                    "name": c.name,
                    "email": c.email,
                    "phone": c.phone,
                    "address": c.address,
                    "store_credit": c.store_credit,
                    "password_hash": c.password_hash
                }
                for c in customers
            ]
        finally:
            self.Session.remove()

    @customers.setter
    def customers(self, value):
        with self.lock:
            session = self.Session()
            try:
                session.query(StoreCreditLedger).delete()
                session.query(Customer).delete()
                for item in value:
                    store_credit_val = float(item.get("store_credit", 0.0))
                    c = Customer(
                        id=item["id"],
                        name=item["name"],
                        email=item["email"],
                        phone=item.get("phone"),
                        address=item.get("address"),
                        store_credit=store_credit_val,
                        password_hash=item.get("password_hash")
                    )
                    session.add(c)
                    
                    if store_credit_val > 0.0:
                        ledger = StoreCreditLedger(
                            customer_id=item["id"],
                            amount=store_credit_val,
                            reason="Initial seeded balance",
                            timestamp=datetime.datetime.now(datetime.timezone.utc)
                        )
                        session.add(ledger)
                session.commit()
            except Exception as e:
                session.rollback()
                raise AdapterError(f"Failed to set customers: {e}")
            finally:
                self.Session.remove()

    @property
    def products(self):
        session = self.Session()
        try:
            products = session.query(Product).all()
            return [
                {
                    "id": p.id,
                    "name": p.name,
                    "description": p.description,
                    "category": p.category,
                    "occasion_tags": p.occasion_tags or [],
                    "mood_tags": p.mood_tags or [],
                    "price": p.price,
                    "currency": p.currency,
                    "image_url": p.image_url
                }
                for p in products
            ]
        finally:
            self.Session.remove()

    @products.setter
    def products(self, value):
        with self.lock:
            session = self.Session()
            try:
                session.query(Product).delete()
                for item in value:
                    p = Product(
                        id=item["id"],
                        name=item["name"],
                        description=item.get("description"),
                        category=item.get("category"),
                        occasion_tags=item.get("occasion_tags", []),
                        mood_tags=item.get("mood_tags", []),
                        price=item["price"],
                        currency=item.get("currency", "BDT"),
                        image_url=item.get("image_url")
                    )
                    session.add(p)
                session.commit()
            except Exception as e:
                session.rollback()
                raise AdapterError(f"Failed to set products: {e}")
            finally:
                self.Session.remove()

    @property
    def inventory(self):
        session = self.Session()
        try:
            items = session.query(ProductInventory).all()
            inv = {}
            for item in items:
                if item.product_id not in inv:
                    inv[item.product_id] = {}
                inv[item.product_id][item.size] = item.quantity
            return inv
        finally:
            self.Session.remove()

    @inventory.setter
    def inventory(self, value):
        with self.lock:
            session = self.Session()
            try:
                session.query(ProductInventory).delete()
                for product_id, sizes in value.items():
                    for size, qty in sizes.items():
                        inv = ProductInventory(
                            product_id=product_id,
                            size=str(size),
                            quantity=int(qty)
                        )
                        session.add(inv)
                session.commit()
            except Exception as e:
                session.rollback()
                raise AdapterError(f"Failed to set inventory: {e}")
            finally:
                self.Session.remove()

    def _get_all_orders(self):
        session = self.Session()
        try:
            orders = session.query(Order).all()
            res = {}
            for o in orders:
                items_list = []
                for item in o.items:
                    items_list.append({
                        "product_id": item.product_id,
                        "size": item.size,
                        "quantity": item.quantity,
                        "price": item.price
                    })
                res[o.id] = {
                    "id": o.id,
                    "customer_id": o.customer_id,
                    "items": items_list,
                    "total": o.total,
                    "status": o.status,
                    "stripe_payment_intent_id": o.stripe_payment_intent_id,
                    "stripe_event_id": o.stripe_event_id,
                    "created_at": o.created_at.isoformat() if isinstance(o.created_at, datetime.datetime) else o.created_at
                }
            return res
        finally:
            self.Session.remove()

    def _set_order(self, order_id, item):
        with self.lock:
            session = self.Session()
            try:
                session.query(OrderItem).filter_by(order_id=order_id).delete()
                o = session.query(Order).filter_by(id=order_id).first()
                
                created_at_val = item.get("created_at")
                if isinstance(created_at_val, str):
                    if created_at_val.endswith("Z"):
                        created_at_val = created_at_val[:-1] + "+00:00"
                    dt = datetime.datetime.fromisoformat(created_at_val)
                elif isinstance(created_at_val, datetime.datetime):
                    dt = created_at_val
                else:
                    dt = datetime.datetime.utcnow()
                    
                if not o:
                    o = Order(id=order_id)
                    session.add(o)
                    
                o.customer_id = item["customer_id"]
                o.total = item["total"]
                o.status = item["status"]
                o.stripe_payment_intent_id = item.get("stripe_payment_intent_id")
                o.stripe_event_id = item.get("stripe_event_id")
                o.created_at = dt
                
                for item_dict in item.get("items", []):
                    oi = OrderItem(
                        order_id=order_id,
                        product_id=item_dict["product_id"],
                        size=str(item_dict["size"]),
                        quantity=item_dict["quantity"],
                        price=item_dict["price"]
                    )
                    session.add(oi)
                session.commit()
            except Exception as e:
                session.rollback()
                raise AdapterError(f"Failed to set order {order_id}: {e}")
            finally:
                self.Session.remove()

    def _del_order(self, order_id):
        with self.lock:
            session = self.Session()
            try:
                session.query(OrderItem).filter_by(order_id=order_id).delete()
                session.query(Order).filter_by(id=order_id).delete()
                session.commit()
            except Exception as e:
                session.rollback()
                raise AdapterError(f"Failed to delete order {order_id}: {e}")
            finally:
                self.Session.remove()

    @property
    def orders(self):
        return DBDictProxy(
            self._get_all_orders,
            self._set_order,
            self._del_order
        )

    @orders.setter
    def orders(self, value):
        with self.lock:
            session = self.Session()
            try:
                session.query(OrderItem).delete()
                session.query(Order).delete()
                for order_id, item in value.items():
                    created_at_val = item.get("created_at")
                    if isinstance(created_at_val, str):
                        if created_at_val.endswith("Z"):
                            created_at_val = created_at_val[:-1] + "+00:00"
                        dt = datetime.datetime.fromisoformat(created_at_val)
                    elif isinstance(created_at_val, datetime.datetime):
                        dt = created_at_val
                    else:
                        dt = datetime.datetime.utcnow()
                    
                    o = Order(
                        id=order_id,
                        customer_id=item["customer_id"],
                        total=item["total"],
                        status=item["status"],
                        stripe_payment_intent_id=item.get("stripe_payment_intent_id"),
                        stripe_event_id=item.get("stripe_event_id"),
                        created_at=dt
                    )
                    session.add(o)
                    for item_dict in item.get("items", []):
                        oi = OrderItem(
                            order_id=order_id,
                            product_id=item_dict["product_id"],
                            size=str(item_dict["size"]),
                            quantity=item_dict["quantity"],
                            price=item_dict["price"]
                        )
                        session.add(oi)
                session.commit()
            except Exception as e:
                session.rollback()
                raise AdapterError(f"Failed to set orders: {e}")
            finally:
                self.Session.remove()

    def _get_all_tracking(self):
        session = self.Session()
        try:
            trackings = session.query(Tracking).all()
            res = {}
            for t in trackings:
                timeline = []
                for ev in t.events:
                    timeline.append({
                        "time": ev.timestamp,
                        "event": ev.details
                    })
                res[t.order_id] = {
                    "order_id": t.order_id,
                    "courier": t.courier,
                    "tracking_code": t.tracking_code,
                    "status": t.status,
                    "estimated_delivery": t.estimated_delivery,
                    "timeline": timeline
                }
            return res
        finally:
            self.Session.remove()

    def _set_tracking(self, order_id, item):
        with self.lock:
            session = self.Session()
            try:
                session.query(TrackingEvent).filter_by(tracking_id=order_id).delete()
                t = session.query(Tracking).filter_by(order_id=order_id).first()
                if not t:
                    t = Tracking(id=order_id, order_id=order_id)
                    session.add(t)
                t.courier = item.get("courier", "Pathao")
                t.tracking_code = item.get("tracking_code", "")
                t.status = item.get("status", "processing")
                t.estimated_delivery = item.get("estimated_delivery")
                
                for event in item.get("timeline", []):
                    ev = TrackingEvent(
                        tracking_id=order_id,
                        timestamp=event["time"],
                        location=event.get("location", "Dhaka Hub"),
                        details=event["event"]
                    )
                    session.add(ev)
                session.commit()
            except Exception as e:
                session.rollback()
                raise AdapterError(f"Failed to set tracking for {order_id}: {e}")
            finally:
                self.Session.remove()

    def _del_tracking(self, order_id):
        with self.lock:
            session = self.Session()
            try:
                session.query(TrackingEvent).filter_by(tracking_id=order_id).delete()
                session.query(Tracking).filter_by(order_id=order_id).delete()
                session.commit()
            except Exception as e:
                session.rollback()
                raise AdapterError(f"Failed to delete tracking for {order_id}: {e}")
            finally:
                self.Session.remove()

    @property
    def tracking(self):
        return DBDictProxy(
            self._get_all_tracking,
            self._set_tracking,
            self._del_tracking
        )

    @tracking.setter
    def tracking(self, value):
        with self.lock:
            session = self.Session()
            try:
                session.query(TrackingEvent).delete()
                session.query(Tracking).delete()
                for order_id, item in value.items():
                    t = Tracking(
                        id=order_id,
                        order_id=order_id,
                        courier=item.get("courier", "Pathao"),
                        tracking_code=item.get("tracking_code", ""),
                        status=item.get("status", "processing"),
                        estimated_delivery=item.get("estimated_delivery")
                    )
                    session.add(t)
                    for event in item.get("timeline", []):
                        ev = TrackingEvent(
                            tracking_id=order_id,
                            timestamp=event["time"],
                            location=event.get("location", "Dhaka Hub"),
                            details=event["event"]
                        )
                        session.add(ev)
                session.commit()
            except Exception as e:
                session.rollback()
                raise AdapterError(f"Failed to set tracking: {e}")
            finally:
                self.Session.remove()

    @property
    def promotions(self):
        session = self.Session()
        try:
            promotions = session.query(Promotion).all()
            return [
                {
                    "id": p.id,
                    "title": p.title,
                    "description": p.description,
                    "code": p.code,
                    "discount_percent": p.discount_percent,
                    "applies_to_categories": p.applies_to_categories or [],
                    "valid_until": p.valid_until,
                    "active": p.active
                }
                for p in promotions
            ]
        finally:
            self.Session.remove()

    @promotions.setter
    def promotions(self, value):
        with self.lock:
            session = self.Session()
            try:
                session.query(Promotion).delete()
                for item in value:
                    p = Promotion(
                        id=item["id"],
                        title=item.get("title"),
                        description=item.get("description"),
                        code=item["code"],
                        discount_percent=item["discount_percent"],
                        applies_to_categories=item.get("applies_to_categories", []),
                        valid_until=item.get("valid_until"),
                        active=item.get("active", True)
                    )
                    session.add(p)
                session.commit()
            except Exception as e:
                session.rollback()
                raise AdapterError(f"Failed to set promotions: {e}")
            finally:
                self.Session.remove()

    def get_products(self, query: str = None) -> list:
        return self.products

    def check_stock(self, product_id: str, size: str) -> int:
        session = self.Session()
        try:
            inv = session.query(ProductInventory).filter_by(product_id=product_id, size=str(size)).first()
            return inv.quantity if inv else 0
        finally:
            self.Session.remove()

    def get_product_details(self, product_id: str) -> dict:
        session = self.Session()
        try:
            p = session.query(Product).filter_by(id=product_id).first()
            if not p:
                return {}
            
            inv_items = session.query(ProductInventory).filter_by(product_id=product_id).all()
            variants = [{"size": item.size, "stock": item.quantity} for item in inv_items]
            
            return {
                "id": p.id,
                "name": p.name,
                "description": p.description,
                "category": p.category,
                "occasion_tags": p.occasion_tags or [],
                "mood_tags": p.mood_tags or [],
                "price": p.price,
                "currency": p.currency,
                "image_url": p.image_url,
                "variants": variants
            }
        finally:
            self.Session.remove()

    def create_order(self, customer_id: str, cart: list) -> dict:
        with self.lock:
            session = self.Session()
            try:
                customer = session.query(Customer).filter_by(id=customer_id).first()
                if not customer:
                    raise ValueError(f"Customer ID '{customer_id}' not found.")
                    
                items_list = []
                total = 0.0
                
                for item in cart:
                    prod_id = item["product_id"]
                    sz = str(item["size"])
                    qty = item["quantity"]
                    
                    query = session.query(ProductInventory).filter_by(product_id=prod_id, size=sz)
                    if session.bind.dialect.name == "postgresql":
                        query = query.with_for_update()
                    
                    inv_item = query.first()
                    if not inv_item:
                        raise ValueError(f"Product '{prod_id}' or size '{sz}' does not exist.")
                        
                    if inv_item.quantity < qty:
                        raise ValueError(
                            f"Insufficient stock for product '{prod_id}' size '{sz}'. "
                            f"Requested: {qty}, Available: {inv_item.quantity}"
                        )
                        
                    inv_item.quantity -= qty
                    
                    p = session.query(Product).filter_by(id=prod_id).first()
                    price = p.price if p else 0.0
                    
                    total += price * qty
                    items_list.append({
                        "product_id": prod_id,
                        "size": sz,
                        "quantity": qty,
                        "price": price
                    })
                    
                order_id = f"ORD{str(uuid.uuid4())[:8].upper()}"
                now = datetime.datetime.now(datetime.timezone.utc)
                
                new_order = Order(
                    id=order_id,
                    customer_id=customer_id,
                    total=total,
                    status="pending_payment",
                    created_at=now
                )
                session.add(new_order)
                
                for item_data in items_list:
                    oi = OrderItem(
                        order_id=order_id,
                        product_id=item_data["product_id"],
                        size=item_data["size"],
                        quantity=item_data["quantity"],
                        price=item_data["price"]
                    )
                    session.add(oi)
                    
                tracking_id = order_id
                tracking_code = f"PTH-{str(uuid.uuid4())[:8].upper()}"
                t = Tracking(
                    id=tracking_id,
                    order_id=order_id,
                    courier="Pathao",
                    tracking_code=tracking_code,
                    status="processing",
                    estimated_delivery=(now + datetime.timedelta(days=3)).isoformat()
                )
                session.add(t)
                
                te = TrackingEvent(
                    tracking_id=tracking_id,
                    timestamp=now.isoformat(),
                    location="Dhaka Hub",
                    details="Order created pending payment"
                )
                session.add(te)
                
                session.commit()
                
                return {
                    "id": order_id,
                    "customer_id": customer_id,
                    "items": items_list,
                    "total": total,
                    "status": "pending_payment",
                    "stripe_payment_intent_id": None,
                    "created_at": now.isoformat()
                }
            except ValueError as ve:
                session.rollback()
                raise ve
            except (OperationalError, DBAPIError) as e:
                session.rollback()
                raise
            except Exception as e:
                session.rollback()
                raise ValueError(str(e))
            finally:
                self.Session.remove()

    def track_order(self, order_id: str, customer_id: str) -> dict:
        session = self.Session()
        try:
            query_str = str(order_id).strip()
            normalized_query = query_str.replace(" ", "").replace("-", "").upper()
            
            orders = session.query(Order).all()
            resolved_order_id = None
            for o in orders:
                if o.id.replace(" ", "").replace("-", "").upper() == normalized_query:
                    resolved_order_id = o.id
                    break
                    
            if not resolved_order_id:
                trackings = session.query(Tracking).all()
                for t in trackings:
                    tc = t.tracking_code.replace(" ", "").replace("-", "").upper()
                    if tc == normalized_query:
                        resolved_order_id = t.order_id
                        break
                        
            if not resolved_order_id:
                return {"error": f"Order ID '{order_id}' not found."}
                
            order = session.query(Order).filter_by(id=resolved_order_id).first()
            if not order:
                return {"error": f"Order ID '{order_id}' not found."}
                
            if order.customer_id != customer_id:
                return {"error": "Refused: Access denied. You do not own this order."}
                
            tracking_info = session.query(Tracking).filter_by(order_id=resolved_order_id).first()
            if not tracking_info:
                return {}
                
            timeline = [
                {"time": ev.timestamp, "event": ev.details}
                for ev in tracking_info.events
            ]
            
            return {
                "order_id": tracking_info.order_id,
                "courier": tracking_info.courier,
                "tracking_code": tracking_info.tracking_code,
                "status": tracking_info.status,
                "estimated_delivery": tracking_info.estimated_delivery,
                "timeline": timeline
            }
        finally:
            self.Session.remove()

    def get_order(self, order_id: str) -> dict:
        session = self.Session()
        try:
            query_str = str(order_id).strip()
            normalized_query = query_str.replace(" ", "").replace("-", "").upper()
            orders = session.query(Order).all()
            for o in orders:
                if o.id.replace(" ", "").replace("-", "").upper() == normalized_query:
                    items_list = []
                    for item in o.items:
                        items_list.append({
                            "product_id": item.product_id,
                            "size": item.size,
                            "quantity": item.quantity,
                            "price": item.price
                        })
                    return {
                        "id": o.id,
                        "customer_id": o.customer_id,
                        "items": items_list,
                        "total": o.total,
                        "status": o.status,
                        "stripe_payment_intent_id": o.stripe_payment_intent_id,
                        "stripe_event_id": o.stripe_event_id,
                        "created_at": o.created_at.isoformat() if isinstance(o.created_at, datetime.datetime) else o.created_at
                    }
            return {}
        finally:
            self.Session.remove()

    def cancel_order(self, order_id: str) -> bool:
        with self.lock:
            session = self.Session()
            try:
                oid = str(order_id).strip()
                query = session.query(Order).filter_by(id=oid)
                if session.bind.dialect.name == "postgresql":
                    query = query.with_for_update()
                order = query.first()
                if not order:
                    return False
                    
                if order.status != "cancelled":
                    for item in order.items:
                        inv_query = session.query(ProductInventory).filter_by(product_id=item.product_id, size=item.size)
                        if session.bind.dialect.name == "postgresql":
                            inv_query = inv_query.with_for_update()
                        inv_item = inv_query.first()
                        if inv_item:
                            inv_item.quantity += item.quantity
                            
                order.status = "cancelled"
                
                tracking = session.query(Tracking).filter_by(order_id=oid).first()
                if tracking:
                    tracking.status = "cancelled"
                    te = TrackingEvent(
                        tracking_id=tracking.id,
                        timestamp=datetime.datetime.now(datetime.timezone.utc).isoformat(),
                        location="Dhaka Hub",
                        details="Order cancelled"
                    )
                    session.add(te)
                    
                session.commit()
                return True
            except (OperationalError, DBAPIError) as e:
                session.rollback()
                raise
            except Exception as e:
                session.rollback()
                raise AdapterError(f"Cancel order failed: {e}")
            finally:
                self.Session.remove()

    def confirm_payment(self, order_id: str, stripe_event_id: str = None) -> str:
        with self.lock:
            session = self.Session()
            try:
                oid = str(order_id).strip()
                query = session.query(Order).filter_by(id=oid)
                if session.bind.dialect.name == "postgresql":
                    query = query.with_for_update()
                order = query.first()
                
                if not order:
                    return f"Error: Order #{oid} not found."
                    
                if stripe_event_id and order.stripe_event_id == stripe_event_id:
                    return "Event already processed (idempotence)"
                    
                order.status = "paid"
                if stripe_event_id:
                    order.stripe_event_id = stripe_event_id
                    
                tracking = session.query(Tracking).filter_by(order_id=oid).first()
                if tracking:
                    tracking.status = "processing"
                    te = TrackingEvent(
                        tracking_id=tracking.id,
                        timestamp=datetime.datetime.now(datetime.timezone.utc).isoformat(),
                        location="Dhaka Hub",
                        details="Payment confirmed. Order status: paid"
                    )
                    session.add(te)
                    
                session.commit()
                return f"Order #{oid} marked as paid successfully."
            except (OperationalError, DBAPIError) as e:
                session.rollback()
                raise
            except Exception as e:
                session.rollback()
                raise AdapterError(f"Confirm payment failed: {e}")
            finally:
                self.Session.remove()

    def issue_store_credit(self, customer_id: str, amount: float) -> None:
        with self.lock:
            session = self.Session()
            try:
                query = session.query(Customer).filter_by(id=customer_id)
                if session.bind.dialect.name == "postgresql":
                    query = query.with_for_update()
                customer = query.first()
                if not customer:
                    raise ValueError(f"Customer ID '{customer_id}' not found.")
                    
                customer.store_credit = float(customer.store_credit or 0.0) + amount
                
                ledger = StoreCreditLedger(
                    customer_id=customer_id,
                    amount=amount,
                    reason="Cancellation refund or direct issue",
                    timestamp=datetime.datetime.now(datetime.timezone.utc)
                )
                session.add(ledger)
                
                session.commit()
            except ValueError as ve:
                session.rollback()
                raise ve
            except (OperationalError, DBAPIError) as e:
                session.rollback()
                raise
            except Exception as e:
                session.rollback()
                raise ValueError(str(e))
            finally:
                self.Session.remove()

    def get_store_credit(self, customer_id: str) -> float:
        # Note: Customer.store_credit is only a denormalized cache. The authoritative store credit
        # balance must always be calculated by summing the StoreCreditLedger entries.
        session = self.Session()
        try:
            ledger_sum = session.query(func.sum(StoreCreditLedger.amount)).filter_by(customer_id=customer_id).scalar()
            return float(ledger_sum) if ledger_sum is not None else 0.0
        finally:
            self.Session.remove()

    def mark_refunded(self, order_id: str) -> bool:
        with self.lock:
            session = self.Session()
            try:
                oid = str(order_id).strip()
                query = session.query(Order).filter_by(id=oid)
                if session.bind.dialect.name == "postgresql":
                    query = query.with_for_update()
                order = query.first()
                if not order:
                    return False
                    
                order.status = "refunded"
                session.commit()
                return True
            except (OperationalError, DBAPIError) as e:
                session.rollback()
                raise
            except Exception as e:
                session.rollback()
                return False
            finally:
                self.Session.remove()

    def set_payment_intent(self, order_id: str, intent_id: str) -> None:
        with self.lock:
            session = self.Session()
            try:
                oid = str(order_id).strip()
                query = session.query(Order).filter_by(id=oid)
                if session.bind.dialect.name == "postgresql":
                    query = query.with_for_update()
                order = query.first()
                if order:
                    order.stripe_payment_intent_id = intent_id
                    session.commit()
            except (OperationalError, DBAPIError) as e:
                session.rollback()
                raise
            except Exception as e:
                session.rollback()
            finally:
                self.Session.remove()

    def get_promotions(self) -> list:
        return self.promotions

    def release_abandoned_checkouts(self) -> None:
        with self.lock:
            session = self.Session()
            try:
                now = datetime.datetime.now(datetime.timezone.utc)
                orders = session.query(Order).filter_by(status="pending_payment").all()
                mutated = False
                
                for order in orders:
                    created_at = order.created_at
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
                        order.status = "cancelled"
                        mutated = True
                        
                        for item in order.items:
                            inv_item = session.query(ProductInventory).filter_by(product_id=item.product_id, size=item.size).first()
                            if inv_item:
                                inv_item.quantity += item.quantity
                                
                        tracking = session.query(Tracking).filter_by(order_id=order.id).first()
                        if tracking:
                            tracking.status = "cancelled"
                            te = TrackingEvent(
                                tracking_id=tracking.id,
                                timestamp=now.isoformat(),
                                location="Dhaka Hub",
                                details="Order cancelled automatically due to payment timeout"
                            )
                            session.add(te)
                            
                        print(f"[Failure-Mode Handling] Cancelled expired order #{order.id} and restored stock in DB.")
                        
                if mutated:
                    session.commit()
            except Exception as e:
                session.rollback()
                print(f"Error during expired orders cleanup: {e}")
            finally:
                self.Session.remove()

    def create_refund_request(self, order_id: str, customer_id: str, refund_type: str, eligibility_reason: str, thread_id: str) -> dict:
        with self.lock:
            session = self.Session()
            try:
                req_id = f"REF{str(uuid.uuid4())[:8].upper()}"
                req = RefundRequest(
                    id=req_id,
                    order_id=order_id,
                    customer_id=customer_id,
                    requested_at=datetime.datetime.utcnow(),
                    refund_type=refund_type,
                    eligibility_reason=eligibility_reason,
                    status="pending_review",
                    thread_id=thread_id
                )
                session.add(req)
                session.commit()
                return {
                    "id": req.id,
                    "order_id": req.order_id,
                    "customer_id": req.customer_id,
                    "requested_at": req.requested_at.isoformat(),
                    "refund_type": req.refund_type,
                    "eligibility_reason": req.eligibility_reason,
                    "status": req.status,
                    "reviewed_by": req.reviewed_by,
                    "reviewed_at": req.reviewed_at.isoformat() if req.reviewed_at else None,
                    "review_notes": req.review_notes,
                    "thread_id": req.thread_id
                }
            except (OperationalError, DBAPIError) as e:
                session.rollback()
                raise
            except Exception as e:
                session.rollback()
                raise AdapterError(f"Failed to create refund request: {e}")
            finally:
                self.Session.remove()

    def get_refund_request(self, request_id: str) -> dict:
        session = self.Session()
        try:
            req = session.query(RefundRequest).filter_by(id=request_id).first()
            if not req:
                return {}
            return {
                "id": req.id,
                "order_id": req.order_id,
                "customer_id": req.customer_id,
                "requested_at": req.requested_at.isoformat(),
                "refund_type": req.refund_type,
                "eligibility_reason": req.eligibility_reason,
                "status": req.status,
                "reviewed_by": req.reviewed_by,
                "reviewed_at": req.reviewed_at.isoformat() if req.reviewed_at else None,
                "review_notes": req.review_notes,
                "thread_id": req.thread_id
            }
        finally:
            self.Session.remove()

    def get_pending_refund_requests(self) -> list:
        session = self.Session()
        try:
            reqs = session.query(RefundRequest).filter_by(status="pending_review").all()
            results = []
            for req in reqs:
                results.append({
                    "id": req.id,
                    "order_id": req.order_id,
                    "customer_id": req.customer_id,
                    "requested_at": req.requested_at.isoformat(),
                    "refund_type": req.refund_type,
                    "eligibility_reason": req.eligibility_reason,
                    "status": req.status,
                    "reviewed_by": req.reviewed_by,
                    "reviewed_at": req.reviewed_at.isoformat() if req.reviewed_at else None,
                    "review_notes": req.review_notes,
                    "thread_id": req.thread_id
                })
            return results
        finally:
            self.Session.remove()

    def update_refund_request(self, request_id: str, status: str, reviewed_by: str, review_notes: str) -> bool:
        with self.lock:
            session = self.Session()
            try:
                query = session.query(RefundRequest).filter_by(id=request_id)
                if session.bind.dialect.name == "postgresql":
                    query = query.with_for_update()
                req = query.first()
                if not req:
                    return False
                req.status = status
                req.reviewed_by = reviewed_by
                req.reviewed_at = datetime.datetime.utcnow()
                req.review_notes = review_notes
                session.commit()
                return True
            except (OperationalError, DBAPIError) as e:
                session.rollback()
                raise
            except Exception as e:
                session.rollback()
                raise AdapterError(f"Failed to update refund request: {e}")
            finally:
                self.Session.remove()
