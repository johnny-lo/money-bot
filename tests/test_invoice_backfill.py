from models import InvoiceSyncState


def test_invoice_sync_state_table_and_columns():
    assert InvoiceSyncState.__tablename__ == "invoice_sync_state"
    cols = {c.name for c in InvoiceSyncState.__table__.columns}
    assert cols == {"id", "last_covered_date", "updated_at"}
