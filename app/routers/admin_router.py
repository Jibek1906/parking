from fastapi import APIRouter, Request, Form, Body, HTTPException, BackgroundTasks
from fastapi.responses import JSONResponse, RedirectResponse, StreamingResponse
from app.config import PARKING_CONFIG, save_parking_mode
from app.models import (
    get_whitelist, add_to_whitelist, update_whitelist_entry, delete_whitelist_entry
)
from app.services.parking import get_parking_analytics, get_plate_analytics, get_payment_analytics
import requests
from io import BytesIO
from PIL import Image
from pydantic import BaseModel
from typing import Optional, List
from datetime import datetime

router = APIRouter()

@router.post("/admin/heartbeat")
async def admin_heartbeat():
    """Пустой endpoint для heartbeat активности администратора"""
    return {"status": "ok"}

class WhitelistEntry(BaseModel):
    plate_number: str
    valid_from: datetime
    valid_until: Optional[datetime] = None
    comment: Optional[str] = None

class WhitelistUpdate(BaseModel):
    plate_number: Optional[str] = None
    valid_from: Optional[datetime] = None
    valid_until: Optional[datetime] = None
    comment: Optional[str] = None

@router.get("/admin/parking-mode")
async def get_parking_mode():
    """
    Получить текущий режим парковки (paid | free)
    """
    return {"mode": PARKING_CONFIG.get("mode", "paid")}

@router.post("/admin/parking-mode")
async def set_parking_mode(mode: str = Form(...)):
    """
    Установить режим парковки (paid | free)
    """
    if mode not in ("paid", "free"):
        return JSONResponse({"error": "Invalid mode"}, status_code=400)
    PARKING_CONFIG["mode"] = mode
    save_parking_mode(mode)
    return RedirectResponse(url="/admin", status_code=303)

@router.get("/admin/whitelist", response_model=List[dict])
async def api_get_whitelist(limit: int = 100, offset: int = 0, active_only: bool = False):
    """
    Получить список номеров из белого списка
    """
    return get_whitelist(limit=limit, offset=offset, active_only=active_only)

@router.post("/admin/whitelist")
async def api_add_to_whitelist(entry: WhitelistEntry):
    """
    Добавить номер в белый список
    """
    whitelist_id = add_to_whitelist(
        plate_number=entry.plate_number,
        valid_from=entry.valid_from,
        valid_until=entry.valid_until,
        comment=entry.comment
    )
    if not whitelist_id:
        raise HTTPException(status_code=500, detail="Failed to add to whitelist")
    return {"status": "success", "id": whitelist_id}

@router.put("/admin/whitelist/{entry_id}")
async def api_update_whitelist_entry(entry_id: int, entry: WhitelistUpdate):
    """
    Обновить запись белого списка
    """
    success = update_whitelist_entry(
        entry_id,
        plate_number=entry.plate_number,
        valid_from=entry.valid_from,
        valid_until=entry.valid_until,
        comment=entry.comment
    )
    if not success:
        raise HTTPException(status_code=500, detail="Failed to update whitelist entry")
    return {"status": "success"}

@router.delete("/admin/whitelist/{entry_id}")
async def api_delete_whitelist_entry(entry_id: int):
    """
    Удалить запись из белого списка
    """
    success = delete_whitelist_entry(entry_id)
    if not success:
        raise HTTPException(status_code=500, detail="Failed to delete whitelist entry")
    return {"status": "success"}
from fastapi.responses import JSONResponse
import httpx
import base64
from httpx import DigestAuth
import asyncio

@router.get("/admin/camera-snapshot/{camera_ip}")
async def get_camera_snapshot(camera_ip: str):
    """
    Получить снимок с камеры (base64 для JS, только при нажатии кнопки)
    """
    import httpx
    import base64
    from httpx import DigestAuth

    try:
        url = f"http://{camera_ip}/ISAPI/Streaming/channels/1/picture"
        async with httpx.AsyncClient(timeout=2.0, trust_env=False) as client:
            auth = DigestAuth("admin", "Deltatech2023")
            response = await client.get(url, auth=auth)
            if response.status_code == 200:
                image_base64 = base64.b64encode(response.content).decode('utf-8')
                return JSONResponse({
                    "success": True,
                    "image": f"data:image/jpeg;base64,{image_base64}"
                })
            elif response.status_code == 401:
                return JSONResponse({
                    "success": False,
                    "error": "Unauthorized: Check camera credentials"
                }, status_code=401)
            else:
                return JSONResponse({
                    "success": False,
                    "error": f"Camera returned status {response.status_code}"
                }, status_code=response.status_code)
    except httpx.TimeoutException:
        return JSONResponse({
            "success": False,
            "error": "Camera connection timeout"
        }, status_code=504)
    except httpx.ConnectError:
        return JSONResponse({
            "success": False,
            "error": f"Cannot connect to camera {camera_ip}"
        }, status_code=503)
    except Exception as e:
        return JSONResponse({
            "success": False,
            "error": f"Unexpected error: {e}"
        }, status_code=500)

from app.db import get_db_connection
from datetime import datetime, date
from fastapi import Query
import subprocess

@router.get("/admin/analytics/parking")
async def api_parking_analytics(days: int = 7):
    """
    Общая аналитика по парковке за последние days дней
    """
    return get_parking_analytics(days=days)

@router.get("/admin/analytics/payments")
async def api_payment_analytics(day: str = None):
    """
    Аналитика по оплатам за выбранный день (по умолчанию сегодня)
    """
    return get_payment_analytics(day=day)

@router.get("/admin/analytics/plates")
async def api_plate_analytics(days: int = 7):
    """
    Аналитика по номерам за последние days дней
    """
    return get_plate_analytics(days=days)

from app.services.barrier import open_barrier, close_barrier, get_barrier_state
from app.config import PARKING_CONFIG

@router.get("/admin/active-visits")
async def api_active_visits(
    plate: str = Query(None, description="Поиск по номеру (частичное совпадение)"),
    sort: str = Query("desc", description="Сортировка: desc (новые сверху) или asc (старые сверху)")
):
    """
    Получить список активных машин на парковке (visit_status='active'), 
    с фильтрацией по номеру и сортировкой
    """
    conn = get_db_connection()
    cur = conn.cursor()
    try:
        query = """
            SELECT id, plate_number, entry_time, entry_camera_ip
            FROM parking_visits
            WHERE visit_status = 'active'
        """
        params = []
        
        if plate:
            query += " AND plate_number ILIKE %s"
            params.append(f"%{plate}%")
        
        if sort and sort.lower() == "asc":
            query += " ORDER BY entry_time ASC"
        else:
            query += " ORDER BY entry_time DESC"
            
        cur.execute(query, tuple(params))
        rows = cur.fetchall()
        result = []
        for row in rows:
            result.append({
                "id": row[0],
                "plate_number": row[1],
                "entry_time": row[2],
                "entry_camera_ip": row[3]
            })
        return result
    finally:
        cur.close()
        conn.close()

from fastapi import Body

@router.get("/admin/barrier-state")
async def api_barrier_state(camera_ip: str = Query(..., description="IP камеры (въезд/выезд)")):
    """
    Получить состояние шлагбаума (open/closed/unknown/unreachable)
    """
    state = get_barrier_state(camera_ip)
    return {"state": state}

@router.post("/admin/barrier-open")
async def api_barrier_open(data: dict = Body(...)):
    """
    Открыть шлагбаум для указанной камеры
    """
    camera_ip = data.get("camera_ip")
    if not camera_ip:
        raise HTTPException(status_code=400, detail="camera_ip required")
    success = open_barrier(camera_ip)
    return {"success": success}

@router.post("/admin/barrier-open-default")
async def api_barrier_open_default():
    """
    Открыть шлагбаум по умолчанию (въезд)
    """
    camera_ip = PARKING_CONFIG.get("entry_camera_ip")
    if not camera_ip:
        raise HTTPException(status_code=500, detail="entry_camera_ip not configured")
    success = open_barrier(camera_ip)
    return {"success": success}

@router.post("/admin/barrier-close")
async def api_barrier_close(data: dict = Body(...)):
    """
    Закрыть шлагбаум для указанной камеры
    """
    camera_ip = data.get("camera_ip")
    if not camera_ip:
        raise HTTPException(status_code=400, detail="camera_ip required")
    success = close_barrier(camera_ip)
    return {"success": success}

@router.get("/admin/server-errors")
async def api_server_errors(lines: int = 50, level: str = "err"):
    """
    Получить последние логи сервера из systemd journal (ошибки или все)
    level: "err" (только ошибки), "info" (все логи)
    """
    try:
        if level == "info":
            cmd = [
                "journalctl", "-u", "parking.service", "-n", str(lines), "--no-pager"
            ]
        else:
            cmd = [
                "journalctl", "-u", "parking.service", "-p", level, "-n", str(lines), "--no-pager"
            ]
        result = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        if result.returncode == 0:
            return {"logs": result.stdout.splitlines()}
        else:
            return {"error": result.stderr}
    except Exception as e:
        return {"error": str(e)}

@router.get("/admin/visits-by-date")
async def api_visits_by_date(
    day: str = None,
    status: str = Query(None, description="Фильтр по статусу визита"),
    entry_from: str = Query(None, description="Въезд с (Y-m-d H:i)"),
    entry_to: str = Query(None, description="Въезд по (Y-m-d H:i)"),
    plate: str = Query(None, description="Поиск по номеру (частичное совпадение)"),
    sort: str = Query("desc", description="Сортировка: desc (новые сверху) или asc (старые сверху)")
):
    """
    Получить список всех визитов за выбранный день с расширенной фильтрацией и поиском
    """
    conn = get_db_connection()
    cur = conn.cursor()
    try:
        if not day:
            day = date.today().isoformat()
            
        query = """
            SELECT id, plate_number, entry_time, exit_time, visit_status
            FROM parking_visits
            WHERE DATE(entry_time) = %s
        """
        params = [day]
        
        if status:
            query += " AND visit_status = %s"
            params.append(status)
            
        if entry_from:
            query += " AND entry_time >= %s"
            params.append(entry_from)
            
        if entry_to:
            query += " AND entry_time <= %s"
            params.append(entry_to)
            
        if plate:
            query += " AND plate_number ILIKE %s"
            params.append(f"%{plate}%")
            
        if sort and sort.lower() == "asc":
            query += " ORDER BY entry_time ASC"
        else:
            query += " ORDER BY entry_time DESC"
            
        cur.execute(query, tuple(params))
        rows = cur.fetchall()
        result = []
        for row in rows:
            result.append({
                "id": row[0],
                "plate_number": row[1],
                "entry_time": row[2],
                "exit_time": row[3],
                "visit_status": row[4]
            })
        return result
    finally:
        cur.close()
        conn.close()
