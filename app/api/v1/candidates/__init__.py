from fastapi import APIRouter

from .analytics import router as analytics_router
from .consent import router as consent_router
from .crud import router as crud_router
from .cv import router as cv_router
from .matching import router as matching_router
from .profile import router as profile_router

router = APIRouter(tags=["candidates"])

router.include_router(crud_router)
router.include_router(cv_router)
router.include_router(consent_router)
router.include_router(analytics_router)
router.include_router(profile_router)
router.include_router(matching_router)
