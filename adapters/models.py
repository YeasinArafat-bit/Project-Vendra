import datetime
from sqlalchemy import Column, String, Float, Integer, Boolean, DateTime, ForeignKey, JSON
from sqlalchemy.orm import declarative_base, relationship

Base = declarative_base()

class Product(Base):
    __tablename__ = 'products'
    id = Column(String, primary_key=True)
    name = Column(String, nullable=False)
    description = Column(String)
    category = Column(String)
    occasion_tags = Column(JSON, default=list)
    mood_tags = Column(JSON, default=list)
    price = Column(Float, nullable=False)
    currency = Column(String, default="BDT")
    image_url = Column(String)

    inventory = relationship("ProductInventory", back_populates="product", cascade="all, delete-orphan")

class ProductInventory(Base):
    __tablename__ = 'product_inventory'
    id = Column(Integer, primary_key=True, autoincrement=True)
    product_id = Column(String, ForeignKey('products.id'), nullable=False)
    size = Column(String, nullable=False)
    quantity = Column(Integer, default=0, nullable=False)

    product = relationship("Product", back_populates="inventory")

class Customer(Base):
    __tablename__ = 'customers'
    id = Column(String, primary_key=True)
    name = Column(String, nullable=False)
    email = Column(String, nullable=False)
    phone = Column(String)
    address = Column(String)
    # Note: store_credit is a denormalized cache only.
    # The authoritative balance is the sum of StoreCreditLedger records.
    store_credit = Column(Float, default=0.0, nullable=False)
    password_hash = Column(String, nullable=True)

class Order(Base):
    __tablename__ = 'orders'
    id = Column(String, primary_key=True)
    customer_id = Column(String, ForeignKey('customers.id'), nullable=False)
    total = Column(Float, nullable=False)
    status = Column(String, default="pending_payment", nullable=False)
    stripe_payment_intent_id = Column(String)
    stripe_event_id = Column(String)
    created_at = Column(DateTime, default=datetime.datetime.utcnow, nullable=False)

    items = relationship("OrderItem", back_populates="order", cascade="all, delete-orphan")
    tracking = relationship("Tracking", back_populates="order", uselist=False, cascade="all, delete-orphan")

class OrderItem(Base):
    __tablename__ = 'order_items'
    id = Column(Integer, primary_key=True, autoincrement=True)
    order_id = Column(String, ForeignKey('orders.id'), nullable=False)
    product_id = Column(String, ForeignKey('products.id'), nullable=False)
    size = Column(String, nullable=False)
    quantity = Column(Integer, nullable=False)
    price = Column(Float, nullable=False)

    order = relationship("Order", back_populates="items")

class Tracking(Base):
    __tablename__ = 'tracking'
    id = Column(String, primary_key=True)
    order_id = Column(String, ForeignKey('orders.id'), nullable=False)
    courier = Column(String, default="Pathao")
    tracking_code = Column(String, nullable=False)
    status = Column(String, default="processing", nullable=False)
    estimated_delivery = Column(String)

    order = relationship("Order", back_populates="tracking")
    events = relationship("TrackingEvent", back_populates="tracking", cascade="all, delete-orphan")

class TrackingEvent(Base):
    __tablename__ = 'tracking_events'
    id = Column(Integer, primary_key=True, autoincrement=True)
    tracking_id = Column(String, ForeignKey('tracking.id'), nullable=False)
    timestamp = Column(String, nullable=False)
    location = Column(String, nullable=False)
    details = Column(String, nullable=False)

    tracking = relationship("Tracking", back_populates="events")

class Promotion(Base):
    __tablename__ = 'promotions'
    id = Column(String, primary_key=True)
    title = Column(String)
    description = Column(String)
    code = Column(String, nullable=False)
    discount_percent = Column(Float, nullable=False)
    applies_to_categories = Column(JSON, default=list)
    valid_until = Column(String)
    active = Column(Boolean, default=True, nullable=False)

class StoreCreditLedger(Base):
    __tablename__ = 'store_credit_ledger'
    id = Column(Integer, primary_key=True, autoincrement=True)
    customer_id = Column(String, ForeignKey('customers.id'), nullable=False)
    amount = Column(Float, nullable=False)
    reason = Column(String, nullable=False)
    timestamp = Column(DateTime, default=datetime.datetime.utcnow, nullable=False)

class RefundRequest(Base):
    __tablename__ = 'refund_requests'
    id = Column(String, primary_key=True)
    order_id = Column(String, ForeignKey('orders.id'), nullable=False)
    customer_id = Column(String, ForeignKey('customers.id'), nullable=False)
    requested_at = Column(DateTime, default=datetime.datetime.utcnow, nullable=False)
    refund_type = Column(String, nullable=False)  # 'full_refund' / 'store_credit'
    eligibility_reason = Column(String)
    status = Column(String, default="pending_review", nullable=False)  # 'pending_review', 'approved', 'denied'
    reviewed_by = Column(String)
    reviewed_at = Column(DateTime)
    review_notes = Column(String)
    thread_id = Column(String)
