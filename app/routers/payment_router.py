"""
Роутер для платежей с QR-кодами /payment/*
Интеграция с Bakai OpenBanking API для генерации QR-кодов
ИСПРАВЛЕННАЯ ВЕРСИЯ - операции с operation_id
"""
from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel
from datetime import datetime
from typing import Optional, Dict, Any
import requests
import uuid
import json
import logging
from ..config import KYRGYZSTAN_TZ, BAKAI_CONFIG, PARKING_CONFIG
from ..db import get_async_db_connection
from ..services.barrier import open_barrier
from ..services.parking import format_duration

from app.ws_manager import screen_ws_manager

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/payment", tags=["payment"])

class QRPaymentRequest(BaseModel):
    plate_number: str
    session_id: Optional[int] = None

class QRResponse(BaseModel):
    car_number: str
    entry_time: str
    exit_time: str
    cost_amount: float
    qr_image: str
    operation_id: str
    payment_status: str = "pending"

def get_bakai_headers():
    """Получить заголовки для запросов к Bakai API"""
    return {
        "Authorization": f"Bearer {BAKAI_CONFIG['token']}",
        "Content-Type": "application/json",
        "Accept": "application/json"
    }

@router.get("/api/operation/{operation_id}")
async def get_operation_info(operation_id: str):
    """
    Получить информацию о платеже и визите по operation_id (transaction_id или bakai_operation_id)
    """
    async with await get_async_db_connection() as conn:
        row = await conn.fetchrow("""
            SELECT
                pv.plate_number,
                pv.entry_time,
                pv.exit_time,
                pv.duration_minutes,
                pv.cost_amount,
                pp.qr_image,
                pp.payment_status,
                pp.amount,
                pp.transaction_id,
                pp.bakai_operation_id
            FROM parking_payments pp
            JOIN parking_visits pv ON pp.session_id = pv.id
            WHERE pp.transaction_id = $1 OR pp.bakai_operation_id = $1
            ORDER BY pp.created_at DESC
            LIMIT 1
        """, operation_id)
        if not row:
            return {"error": "not_found", "operation_id": operation_id}
        return {
            "plate": row["plate_number"],
            "entry_time": row["entry_time"].isoformat() if row["entry_time"] else None,
            "exit_time": row["exit_time"].isoformat() if row["exit_time"] else None,
            "duration": f"{row['duration_minutes']} мин" if row["duration_minutes"] else None,
            "cost_amount": float(row["cost_amount"]) if row["cost_amount"] else None,
            "qr_image": row["qr_image"],
            "payment_status": row["payment_status"],
            "amount": float(row["amount"]) if row["amount"] else None,
            "transaction_id": row["transaction_id"],
            "bakai_operation_id": row["bakai_operation_id"],
        }
