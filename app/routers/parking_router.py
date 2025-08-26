"""
Роутер для эндпоинтов парковки /parking/*
"""
from fastapi import APIRouter, HTTPException
from datetime import datetime
from ..config import KYRGYZSTAN_TZ, PARKING_CONFIG
from ..db import get_db_connection
from ..services.parking import close_expired_sessions, calculate_parking_cost, format_duration
from ..services.barrier import open_barrier

router = APIRouter(prefix="/parking", tags=["parking"])

@router.post("/barrier/open/{camera_ip}")
async def manual_barrier_open(camera_ip: str):
    """Ручное открытие шлагбаума для указанной камеры"""
    try:
        if camera_ip not in [PARKING_CONFIG["entry_camera_ip"], PARKING_CONFIG["exit_camera_ip"]]:
            raise HTTPException(status_code=400, detail=f"Camera {camera_ip} is not configured for barrier control")
        
        success = open_barrier(camera_ip)
        
        return {
            "status": "success" if success else "failed",
            "camera_ip": camera_ip,
            "barrier_opened": success,
            "message": f"Шлагбаум для камеры {camera_ip} " + ("открыт" if success else "не открылся"),
            "timestamp": datetime.now(KYRGYZSTAN_TZ).isoformat()
        }
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@router.post("/close-session/{session_id}")
async def manual_close_session(session_id: int):
    """Ручное закрытие парковочной сессии"""
    conn = get_db_connection()
    cur = conn.cursor()
    
    try:
        cur.execute("""
            SELECT plate_number, entry_time FROM parking_visits
            WHERE id = %s AND visit_status = 'active'
        """, (session_id,))
        
        session = cur.fetchone()
        if not session:
            raise HTTPException(status_code=404, detail="Active session not found")
        
        plate, entry_time = session
        exit_time = datetime.now(KYRGYZSTAN_TZ)
        cost_info = calculate_parking_cost(entry_time, exit_time)
        
        cur.execute("""
            UPDATE parking_visits
            SET exit_time = %s,
                duration_minutes = %s,
                cost_amount = %s,
                cost_description = %s,
                visit_status = 'manual',
                notes = 'Закрыто вручную',
                updated_at = %s
            WHERE id = %s
        """, (
            exit_time, cost_info["duration_minutes"], cost_info["total_cost"],
            cost_info["description"] + " (ручное закрытие)", datetime.now(KYRGYZSTAN_TZ), session_id
        ))
        
        conn.commit()
        
        return {
            "status": "success",
            "session_id": session_id,
            "plate": plate,
            "duration": format_duration(cost_info["duration_minutes"]),
            "cost": float(cost_info["total_cost"]),
            "message": f"Сессия {session_id} для {plate} закрыта вручную"
        }
        
    except Exception as e:
        conn.rollback()
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        cur.close()
        conn.close()

@router.post("/cleanup-expired")
async def cleanup_expired_sessions():
    """Принудительная очистка просроченных сессий"""
    try:
        count = close_expired_sessions()
        return {
            "status": "success",
            "closed_sessions": count,
            "message": f"Закрыто {count} просроченных сессий"
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@router.get("/sessions/active")
async def get_active_sessions():
    """Получить список активных парковочных сессий"""
    conn = get_db_connection()
    cur = conn.cursor()
    
    try:
        cur.execute("""
            SELECT id, plate_number, entry_time, entry_camera_ip, 
                   entry_barrier_opened, notes, created_at
            FROM parking_visits
            WHERE visit_status = 'active'
            ORDER BY entry_time DESC
        """)
        
        sessions = []
        for row in cur.fetchall():
            session_id, plate, entry_time, camera_ip, barrier_opened, notes, created_at = row

            current_time = datetime.now(KYRGYZSTAN_TZ)
            duration_minutes = int((current_time - entry_time).total_seconds() / 60)
            
            sessions.append({
                "id": session_id,
                "plate": plate,
                "entry_time": entry_time.isoformat(),
                "entry_camera_ip": camera_ip,
                "entry_barrier_opened": barrier_opened,
                "current_duration": format_duration(duration_minutes),
                "duration_minutes": duration_minutes,
                "notes": notes,
                "created_at": created_at.isoformat()
            })
        
        return {
            "status": "success",
            "active_sessions": sessions,
            "total_count": len(sessions)
        }
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        cur.close()
        conn.close()

@router.get("/sessions/history")
async def get_sessions_history(limit: int = 50):
    """Получить историю парковочных сессий"""
    conn = get_db_connection()
    cur = conn.cursor()
    
    try:
        cur.execute("""
            SELECT id, plate_number, entry_time, exit_time, duration_minutes,
                   cost_amount, cost_description, visit_status, 
                   entry_camera_ip, exit_camera_ip, notes, created_at, updated_at
            FROM parking_visits
            WHERE visit_status IN ('completed', 'manual', 'timeout')
            ORDER BY created_at DESC
            LIMIT %s
        """, (limit,))
        
        sessions = []
        for row in cur.fetchall():
            (session_id, plate, entry_time, exit_time, duration_minutes, cost_amount, 
             cost_description, status, entry_camera, exit_camera, notes, created_at, updated_at) = row
            
            sessions.append({
                "id": session_id,
                "plate": plate,
                "entry_time": entry_time.isoformat(),
                "exit_time": exit_time.isoformat() if exit_time else None,
                "duration": format_duration(duration_minutes) if duration_minutes else None,
                "duration_minutes": duration_minutes,
                "cost": float(cost_amount) if cost_amount else 0,
                "cost_description": cost_description,
                "status": status,
                "entry_camera_ip": entry_camera,
                "exit_camera_ip": exit_camera,
                "notes": notes,
                "created_at": created_at.isoformat(),
                "updated_at": updated_at.isoformat() if updated_at else None
            })
        
        return {
            "status": "success",
            "sessions_history": sessions,
            "returned_count": len(sessions),
            "limit": limit
        }
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        cur.close()
        conn.close()

@router.get("/sessions/by-plate/{plate_number}")
async def get_sessions_by_plate(plate_number: str):
    """Получить все сессии для конкретного номера"""
    conn = get_db_connection()
    cur = conn.cursor()
    
    try:
        cur.execute("""
            SELECT id, plate_number, entry_time, exit_time, duration_minutes,
                   cost_amount, cost_description, visit_status, 
                   entry_camera_ip, exit_camera_ip, notes, created_at, updated_at
            FROM parking_visits
            WHERE plate_number = %s
            ORDER BY entry_time DESC
        """, (plate_number.upper(),))
        
        sessions = []
        total_cost = 0
        total_visits = 0
        
        for row in cur.fetchall():
            (session_id, plate, entry_time, exit_time, duration_minutes, cost_amount, 
             cost_description, status, entry_camera, exit_camera, notes, created_at, updated_at) = row
            
            sessions.append({
                "id": session_id,
                "plate": plate,
                "entry_time": entry_time.isoformat(),
                "exit_time": exit_time.isoformat() if exit_time else None,
                "duration": format_duration(duration_minutes) if duration_minutes else None,
                "duration_minutes": duration_minutes,
                "cost": float(cost_amount) if cost_amount else 0,
                "cost_description": cost_description,
                "status": status,
                "entry_camera_ip": entry_camera,
                "exit_camera_ip": exit_camera,
                "notes": notes,
                "created_at": created_at.isoformat(),
                "updated_at": updated_at.isoformat() if updated_at else None
            })
            
            if cost_amount:
                total_cost += float(cost_amount)
            total_visits += 1
        
        return {
            "status": "success",
            "plate_number": plate_number.upper(),
            "sessions": sessions,
            "statistics": {
                "total_visits": total_visits,
                "total_cost": total_cost,
                "active_sessions": len([s for s in sessions if s["status"] == "active"])
            }
        }
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        cur.close()
        conn.close()