"""Aggregates the v1 routers into a single mountable router."""

from fastapi import APIRouter

from app.api.v1 import auth, bookings, centres, diagnostic_tests, payments

api_router = APIRouter()
api_router.include_router(auth.router)
api_router.include_router(centres.router)
api_router.include_router(diagnostic_tests.router)
api_router.include_router(bookings.router)
api_router.include_router(payments.router)
