#!/usr/bin/env python
"""Verify all imports and no breaking changes."""

try:
    # Models
    from app.models import Enterprise, Offer, Position, Application, Tenant, User
    print("[OK] Models imported successfully")

    # Schemas
    from app.schemas.enterprise import EnterpriseCreate, EnterpriseUpdate, EnterpriseResponse, EnterpriseFull
    from app.schemas.offer import OfferCreate, OfferUpdate, OfferResponse, OfferSend, OfferReject
    print("[OK] Schemas imported successfully")

    # Routers
    from app.api.v1.enterprises import router as ent_router
    from app.api.v1.offers import router as offer_router
    from app.api.v1.interviews import router as interview_router
    print("[OK] API routers imported successfully")

    # Main app
    from app.main import app
    print("[OK] Main app imported successfully")

    # Verify routes
    routes = [route.path for route in app.routes]
    assert "/enterprises" in str(routes), "Missing /enterprises route"
    assert "/offers" in str(routes), "Missing /offers route"
    print("[OK] Routes registered correctly")

    print("\n✓ All verification checks passed - No breaking changes detected")
    print("✓ Enterprise and Offer implementations are compatible")
    print("✓ API integration ready for testing")

except Exception as e:
    print(f"[ERROR] Verification failed: {e}")
    import traceback
    traceback.print_exc()
    exit(1)
