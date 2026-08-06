import pytest
import os
import datetime
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from adapters.postgres_adapter import PostgresAdapter
from adapters.models import StoreCreditLedger, Customer

@pytest.fixture(scope="function")
def db_adapter():
    # Make sure we use a test SQLite database for testing the postgres adapter
    os.environ["DATABASE_URL"] = "sqlite:///data/test_vendra.db"
    adapter = PostgresAdapter()
    adapter.reset_state()
    
    # Seed mock customers
    adapter.customers = [
        {"id": "C_DB_001", "name": "DB Customer", "email": "db@test.com", "phone": "123", "address": "St", "store_credit": 0.0}
    ]
    yield adapter
    
    # Clean up test DB file
    adapter.reset_state()
    if os.path.exists("data/test_vendra.db"):
        try:
            os.remove("data/test_vendra.db")
        except Exception:
            pass

def test_store_credit_ledger_append_only(db_adapter):
    """Verify that store credit is tracked as an append-only ledger."""
    customer_id = "C_DB_001"
    
    # 1. Check initial credit is 0
    assert db_adapter.get_store_credit(customer_id) == 0.0
    
    # 2. Issue 100 BDT store credit
    db_adapter.issue_store_credit(customer_id, 100.0)
    assert db_adapter.get_store_credit(customer_id) == 100.0
    
    # 3. Issue another 50 BDT store credit
    db_adapter.issue_store_credit(customer_id, 50.0)
    assert db_adapter.get_store_credit(customer_id) == 150.0
    
    # 4. Check that there are two distinct entries in the ledger
    session = db_adapter.Session()
    try:
        ledger_entries = session.query(StoreCreditLedger).filter_by(customer_id=customer_id).all()
        assert len(ledger_entries) == 2
        assert ledger_entries[0].amount == 100.0
        assert ledger_entries[1].amount == 50.0
    finally:
        db_adapter.Session.remove()

def test_store_credit_seeded_with_additional(db_adapter):
    """Verify seeded store credit balance and additional issued balance are summed correctly."""
    customer_id = "C_DB_SEEDED"
    
    # Seed customer with non-zero store credit
    db_adapter.customers = [
        {
            "id": customer_id,
            "name": "Seeded Customer",
            "email": "seeded@test.com",
            "phone": "999",
            "address": "Road 1",
            "store_credit": 150.0
        }
    ]
    
    # 1. Check initial credit is the seeded 150.0
    assert db_adapter.get_store_credit(customer_id) == 150.0
    
    # 2. Issue an additional 50.0 store credit
    db_adapter.issue_store_credit(customer_id, 50.0)
    
    # 3. Assert total is the sum of both (200.0)
    assert db_adapter.get_store_credit(customer_id) == 200.0
    
    # 4. Assert ledger has both entries
    session = db_adapter.Session()
    try:
        ledger_entries = session.query(StoreCreditLedger).filter_by(customer_id=customer_id).all()
        assert len(ledger_entries) == 2
        assert ledger_entries[0].amount == 150.0
        assert ledger_entries[0].reason == "Initial seeded balance"
        assert ledger_entries[1].amount == 50.0
    finally:
        db_adapter.Session.remove()
