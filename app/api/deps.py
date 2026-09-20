"""Dependencias compartidas de la API."""

from __future__ import annotations

from collections.abc import Iterator

from sqlalchemy.orm import Session

from app.database import SessionLocal
from app.services.generator_service import GeneratorService
from app.services.masking_service import MaskingService
from app.services.pool_service import PoolService
from app.services.reservation_service import ReservationService
from app.services.tdm_service import TDMService

generator_service = GeneratorService()
masking_service = MaskingService()
tdm_service = TDMService(masking_service)
reservation_service = ReservationService(generator_service)
pool_service = PoolService(generator_service, masking_service, reservation_service)


def get_db() -> Iterator[Session]:
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
