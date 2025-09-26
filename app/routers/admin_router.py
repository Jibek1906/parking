from fastapi import APIRouter, Request, Form, Body, HTTPException
from fastapi.responses import JSONResponse, RedirectResponse
from app.config import PARKING_CONFIG, save_parking_mode
from app.models import (
    get_whitelist, add_to_whitelist, update_whitelist_entry, delete_whitelist_entry
)
from pydantic import BaseModel
from typing import Optional, List
from datetime import datetime

router = APIRouter()

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

from app.db import get_db_connection
from datetime import datetime, date
from fastapi import Query
import subprocess

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