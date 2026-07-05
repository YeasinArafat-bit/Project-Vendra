from abc import ABC, abstractmethod

class AdapterError(Exception):
    """Custom exception raised when an adapter operation fails."""
    pass

class BaseAdapter(ABC):
    @abstractmethod
    def get_products(self, query: str = None) -> list:
        """
        Query/search products.
        """
        pass

    @abstractmethod
    def check_stock(self, product_id: str, size: str) -> int:
        """
        Get stock quantity for a specific product ID and size.
        """
        pass

    @abstractmethod
    def get_product_details(self, product_id: str) -> dict:
        """
        Get full metadata of a product including price, description, etc.
        """
        pass

    @abstractmethod
    def create_order(self, customer_id: str, cart: list) -> dict:
        """
        Create a new order based on customer ID and cart items.
        Reserves/decrements stock atomically.
        """
        pass

    @abstractmethod
    def track_order(self, order_id: str, customer_id: str) -> dict:
        """
        Track shipment of an order, verifying that customer_id matches.
        """
        pass

    @abstractmethod
    def get_order(self, order_id: str) -> dict:
        """
        Retrieve order details directly.
        """
        pass

    @abstractmethod
    def cancel_order(self, order_id: str) -> bool:
        """
        Process order cancellation and trigger refund/credit.
        """
        pass

    @abstractmethod
    def get_promotions(self) -> list:
        """
        Retrieve current active promotions.
        """
        pass

    @abstractmethod
    def confirm_payment(self, order_id: str, stripe_event_id: str = None) -> str:
        """
        Receive webhook event. Marks order as paid, enforcing idempotency.
        """
        pass

    @abstractmethod
    def issue_store_credit(self, customer_id: str, amount: float) -> None:
        """
        Increment the customer's store credit.
        """
        pass

    @abstractmethod
    def get_store_credit(self, customer_id: str) -> float:
        """
        Retrieve the current store credit balance of the customer.
        """
        pass

    @abstractmethod
    def mark_refunded(self, order_id: str) -> bool:
        """
        Mark an order as refunded (thread-safe, persisted where applicable).
        """
        pass

    @abstractmethod
    def set_payment_intent(self, order_id: str, intent_id: str) -> None:
        """
        Store the Stripe payment/session intent ID against an order
        (thread-safe, persisted where applicable).
        """
        pass
