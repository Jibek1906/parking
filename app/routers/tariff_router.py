"""
Роутер для управления тарифами /tariffs/*
"""
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from datetime import datetime, date
from typing import Optional
from ..config import KYRGYZSTAN_TZ
from ..db import get_db_connection
from ..models import get_active_tariff, set_active_tariff, create_tariff

router = APIRouter(prefix="/tariffs", tags=["tariffs"])

class TariffCreate(BaseModel):0
    name: str
    hourly_rate: float
    night_rate: float
    free_minutes: int = 15
    max_hours: int = 24
    description: Optional[str] = None
    valid_from: Optional[date] = None
    valid_until: Optional[date] = None

class TariffUpdate(BaseModel):
    name: Optional[str] = None
    hourly_rate: Optional[float] = None
    night_rate: Optional[float] = None
    free_minutes: Optional[int] = None
    max_hours: Optional[int] = None
    description: Optional[str] = None
    valid_from: Optional[date] = None
    valid_until: Optional[date] = None

@router.get("/active")
async def get_current_active_tariff():
    """Получить текущий активный тариф"""
    tariff = get_active_tariff()
    if not tariff:
        raise HTTPException(status_code=404, detail="No active tariff found")
    
    return {
        "status": "success",
        "active_tariff": tariff,
        "timestamp": datetime.now(KYRGYZSTAN_TZ).isoformat()
    }

@router.get("/list")
async def list_all_tariffs():
    """Получить список всех тарифов"""
    conn = get_db_connection()
    cur = conn.cursor()
    
    try:
        cur.execute("""
            SELECT id, name, hourly_rate, night_rate, free_minutes, max_hours,
                   is_active, valid_from, valid_until, description, created_at
            FROM parking_tariffs
            ORDER BY created_at DESC
        """)
        
        tariffs = []
        for row in cur.fetchall():
            tariff_id, name, hourly_rate, night_rate, free_minutes, max_hours, is_active, valid_from, valid_until, description, created_at = row
            
            tariffs.append({
                "id": tariff_id,
                "name": name,
                "hourly_rate": float(hourly_rate),
                "night_rate": float(night_rate),
                "free_minutes": free_minutes,
                "max_hours": max_hours,
                "is_active": is_active,
                "valid_from": valid_from.isoformat() if valid_from else None,
                "valid_until": valid_until.isoformat() if valid_until else None,
                "description": description,
                "created_at": created_at.isoformat()
            })
        
        return {
            "status": "success",
            "tariffs": tariffs,
            "total_count": len(tariffs)
        }
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        cur.close()
        conn.close()

@router.post("/create")
async def create_new_tariff(tariff_data: TariffCreate):
    """Создать новый тариф"""
    try:
        tariff_id = create_tariff(
            name=tariff_data.name,
            hourly_rate=tariff_data.hourly_rate,
            night_rate=tariff_data.night_rate,
            free_minutes=tariff_data.free_minutes,
            max_hours=tariff_data.max_hours,
            description=tariff_data.description
        )
        
        if not tariff_id:
            raise HTTPException(status_code=500, detail="Failed to create tariff")
        
        return {
            "status": "success",
            "tariff_id": tariff_id,
            "message": f"Tariff '{tariff_data.name}' created successfully"
        }
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@router.post("/activate/{tariff_id}")
async def activate_tariff(tariff_id: int):
    """Активировать указанный тариф"""
    try:
        success = set_active_tariff(tariff_id)
        
        if not success:
            raise HTTPException(status_code=500, detail="Failed to activate tariff")
        
        conn = get_db_connection()
        cur = conn.cursor()
        
        cur.execute("""
            SELECT name, hourly_rate, night_rate FROM parking_tariffs
            WHERE id = %s
        """, (tariff_id,))
        
        tariff_info = cur.fetchone()
        cur.close()
        conn.close()
        
        if tariff_info:
            name, hourly_rate, night_rate = tariff_info
            return {
                "status": "success",
                "activated_tariff": {
                    "id": tariff_id,
                    "name": name,
                    "hourly_rate": float(hourly_rate),
                    "night_rate": float(night_rate)
                },
                "message": f"Tariff '{name}' activated successfully"
            }
        else:
            return {
                "status": "success",
                "message": "Tariff activated"
            }
            
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@router.put("/{tariff_id}")
async def update_tariff(tariff_id: int, tariff_data: TariffUpdate):
    """Обновить существующий тариф"""
    conn = get_db_connection()
    cur = conn.cursor()
    
    try:
        # Проверяем существование тарифа
        cur.execute("SELECT id FROM parking_tariffs WHERE id = %s", (tariff_id,))
        if not cur.fetchone():
            raise HTTPException(status_code=404, detail="Tariff not found")
        
        # Строим динамический UPDATE запрос
        update_fields = []
        update_values = []
        
        if tariff_data.name is not None:
            update_fields.append("name = %s")
            update_values.append(tariff_data.name)
        if tariff_data.hourly_rate is not None:
            update_fields.append("hourly_rate = %s")
            update_values.append(tariff_data.hourly_rate)
        if tariff_data.night_rate is not None:
            update_fields.append("night_rate = %s")
            update_values.append(tariff_data.night_rate)
        if tariff_data.free_minutes is not None:
            update_fields.append("free_minutes = %s")
            update_values.append(tariff_data.free_minutes)
        if tariff_data.max_hours is not None:
            update_fields.append("max_hours = %s")
            update_values.append(tariff_data.max_hours)
        if tariff_data.description is not None:
            update_fields.append("description = %s")
            update_values.append(tariff_data.description)
        if tariff_data.valid_from is not None:
            update_fields.append("valid_from = %s")
            update_values.append(tariff_data.valid_from)
        if tariff_data.valid_until is not None:
            update_fields.append("valid_until = %s")
            update_values.append(tariff_data.valid_until)
        
        if not update_fields:
            raise HTTPException(status_code=400, detail="No fields to update")
        
        update_fields.append("updated_at = %s")
        update_values.append(datetime.now(KYRGYZSTAN_TZ))
        update_values.append(tariff_id)
        
        query = f"UPDATE parking_tariffs SET {', '.join(update_fields)} WHERE id = %s"
        
        cur.execute(query, update_values)
        conn.commit()
        
        return {
            "status": "success",
            "tariff_id": tariff_id,
            "message": "Tariff updated successfully"
        }
        
    except Exception as e:
        conn.rollback()
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        cur.close()
        conn.close()

@router.delete("/{tariff_id}")
async def delete_tariff(tariff_id: int):
    """Удалить тариф (только неактивный)"""
    conn = get_db_connection()
    cur = conn.cursor()
    
    try:
        cur.execute("""
            SELECT name, is_active FROM parking_tariffs WHERE id = %s
        """, (tariff_id,))
        
        tariff = cur.fetchone()
        if not tariff:
            raise HTTPException(status_code=404, detail="Tariff not found")
        
        name, is_active = tariff
        if is_active:
            raise HTTPException(status_code=400, detail="Cannot delete active tariff")
        
        cur.execute("DELETE FROM parking_tariffs WHERE id = %s", (tariff_id,))
        conn.commit()
        
        return {
            "status": "success",
            "message": f"Tariff '{name}' deleted successfully"
        }
        
    except Exception as e:
        conn.rollback()
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        cur.close()
        conn.close()

@router.get("/stats")
async def get_tariff_usage_stats():
    """Статистика использования тарифов"""
    conn = get_db_connection()
    cur = conn.cursor()
    
    try:
        cur.execute("""
            SELECT 
                COUNT(*) as total_sessions,
                SUM(cost_amount) as total_revenue,
                AVG(cost_amount) as avg_cost,
                AVG(duration_minutes) as avg_duration
            FROM parking_visits
            WHERE visit_status IN ('completed', 'manual')
        """)
        
        total_stats = cur.fetchone()
        
        cur.execute("""
            SELECT 
                EXTRACT(DOW FROM entry_time) as day_of_week,
                COUNT(*) as session_count,
                AVG(cost_amount) as avg_cost
            FROM parking_visits
            WHERE visit_status IN ('completed', 'manual')
            AND entry_time >= CURRENT_DATE - INTERVAL '30 days'
            GROUP BY EXTRACT(DOW FROM entry_time)
            ORDER BY day_of_week
        """)
        
        weekly_stats = cur.fetchall()
        
        return {
            "status": "success",
            "total_statistics": {
                "total_sessions": total_stats[0] or 0,
                "total_revenue": float(total_stats[1]) if total_stats[1] else 0,
                "average_cost": float(total_stats[2]) if total_stats[2] else 0,
                "average_duration_minutes": float(total_stats[3]) if total_stats[3] else 0
            },
            "weekly_breakdown": [
                {
                    "day_of_week": int(row[0]),
                    "day_name": ["Sunday", "Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday"][int(row[0])],
                    "session_count": row[1],
                    "average_cost": float(row[2]) if row[2] else 0
                } for row in weekly_stats
            ]
        }
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        cur.close()
        conn.close()