"""
Роутер для эндпоинтов изображений /images/*
"""
from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse
import os
from ..config import CAMERA_CONFIG
from ..db import get_db_connection

router = APIRouter(prefix="/images", tags=["images"])

@router.get("/list")
async def list_images(limit: int = 50):
    """Получить список сохраненных изображений"""
    conn = get_db_connection()
    cur = conn.cursor()
    
    try:
        cur.execute("""
            SELECT ai.id, ai.image_filename, ai.image_path, ai.image_size,
                   ai.plate_number, ai.camera_ip, ai.download_success,
                   ai.created_at, c.event_type, c.event_time
            FROM alarm_images ai
            LEFT JOIN camera c ON ai.event_id = c.id
            ORDER BY ai.created_at DESC
            LIMIT %s
        """, (limit,))
        
        images = []
        for row in cur.fetchall():
            (img_id, filename, filepath, size, plate, camera_ip, success,
             created_at, event_type, event_time) = row
            
            images.append({
                "id": img_id,
                "filename": filename,
                "filepath": filepath,
                "size": size,
                "plate_number": plate,
                "camera_ip": camera_ip,
                "download_success": success,
                "event_type": event_type,
                "event_time": event_time.isoformat() if event_time else None,
                "created_at": created_at.isoformat()
            })
        
        return {
            "status": "success",
            "images": images,
            "total_returned": len(images),
            "limit": limit
        }
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        cur.close()
        conn.close()

@router.get("/download/{image_id}")
async def download_image(image_id: int):
    """Скачать изображение по ID"""
    conn = get_db_connection()
    cur = conn.cursor()
    
    try:
        cur.execute("""
            SELECT image_filename, image_path FROM alarm_images
            WHERE id = %s AND download_success = true
        """, (image_id,))
        
        result = cur.fetchone()
        if not result:
            raise HTTPException(status_code=404, detail="Image not found or download failed")
        
        filename, filepath = result

        if not os.path.exists(filepath):
            raise HTTPException(status_code=404, detail="Image file not found on disk")
        
        return FileResponse(
            filepath,
            media_type="image/jpeg",
            filename=filename
        )
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        cur.close()
        conn.close()

@router.get("/by-plate/{plate_number}")
async def get_images_by_plate(plate_number: str, limit: int = 20):
    """Получить изображения для конкретного номера"""
    conn = get_db_connection()
    cur = conn.cursor()
    
    try:
        cur.execute("""
            SELECT ai.id, ai.image_filename, ai.image_path, ai.image_size,
                   ai.plate_number, ai.camera_ip, ai.download_success,
                   ai.created_at, c.event_type, c.event_time
            FROM alarm_images ai
            LEFT JOIN camera c ON ai.event_id = c.id
            WHERE ai.plate_number = %s
            ORDER BY ai.created_at DESC
            LIMIT %s
        """, (plate_number.upper(), limit))
        
        images = []
        for row in cur.fetchall():
            (img_id, filename, filepath, size, plate, camera_ip, success,
             created_at, event_type, event_time) = row
            
            images.append({
                "id": img_id,
                "filename": filename,
                "filepath": filepath,
                "size": size,
                "plate_number": plate,
                "camera_ip": camera_ip,
                "download_success": success,
                "event_type": event_type,
                "event_time": event_time.isoformat() if event_time else None,
                "created_at": created_at.isoformat()
            })
        
        return {
            "status": "success",
            "plate_number": plate_number.upper(),
            "images": images,
            "total_returned": len(images)
        }
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        cur.close()
        conn.close()

@router.get("/by-camera/{camera_ip}")
async def get_images_by_camera(camera_ip: str, limit: int = 50):
    """Получить изображения для конкретной камеры"""
    conn = get_db_connection()
    cur = conn.cursor()
    
    try:
        cur.execute("""
            SELECT ai.id, ai.image_filename, ai.image_path, ai.image_size,
                   ai.plate_number, ai.camera_ip, ai.download_success,
                   ai.created_at, c.event_type, c.event_time
            FROM alarm_images ai
            LEFT JOIN camera c ON ai.event_id = c.id
            WHERE ai.camera_ip = %s
            ORDER BY ai.created_at DESC
            LIMIT %s
        """, (camera_ip, limit))
        
        images = []
        for row in cur.fetchall():
            (img_id, filename, filepath, size, plate, camera_ip, success,
             created_at, event_type, event_time) = row
            
            images.append({
                "id": img_id,
                "filename": filename,
                "filepath": filepath,
                "size": size,
                "plate_number": plate,
                "camera_ip": camera_ip,
                "download_success": success,
                "event_type": event_type,
                "event_time": event_time.isoformat() if event_time else None,
                "created_at": created_at.isoformat()
            })
        
        return {
            "status": "success",
            "camera_ip": camera_ip,
            "images": images,
            "total_returned": len(images)
        }
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        cur.close()
        conn.close()

@router.delete("/{image_id}")
async def delete_image(image_id: int):
    """Удалить изображение"""
    conn = get_db_connection()
    cur = conn.cursor()
    
    try:
        cur.execute("""
            SELECT image_filename, image_path FROM alarm_images
            WHERE id = %s
        """, (image_id,))
        
        result = cur.fetchone()
        if not result:
            raise HTTPException(status_code=404, detail="Image not found")
        
        filename, filepath = result

        if os.path.exists(filepath):
            os.remove(filepath)
            file_deleted = True
        else:
            file_deleted = False

        cur.execute("DELETE FROM alarm_images WHERE id = %s", (image_id,))
        conn.commit()
        
        return {
            "status": "success",
            "image_id": image_id,
            "filename": filename,
            "file_deleted_from_disk": file_deleted,
            "message": f"Image {filename} deleted successfully"
        }
        
    except Exception as e:
        conn.rollback()
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        cur.close()
        conn.close()

@router.get("/stats")
async def get_image_stats():
    """Статистика по изображениям"""
    conn = get_db_connection()
    cur = conn.cursor()
    
    try:
        cur.execute("""
            SELECT 
                COUNT(*) as total_images,
                COUNT(*) FILTER (WHERE download_success = true) as successful_downloads,
                COUNT(*) FILTER (WHERE download_success = false) as failed_downloads,
                SUM(image_size) as total_size_bytes
            FROM alarm_images
        """)
        
        total_stats = cur.fetchone()

        cur.execute("""
            SELECT camera_ip, 
                   COUNT(*) as image_count,
                   COUNT(*) FILTER (WHERE download_success = true) as successful_count,
                   SUM(image_size) as total_size
            FROM alarm_images
            GROUP BY camera_ip
            ORDER BY image_count DESC
        """)
        
        camera_stats = cur.fetchall()
        
        cur.execute("""
            SELECT DATE(created_at) as date,
                   COUNT(*) as image_count,
                   COUNT(*) FILTER (WHERE download_success = true) as successful_count
            FROM alarm_images
            WHERE created_at >= CURRENT_DATE - INTERVAL '7 days'
            GROUP BY DATE(created_at)
            ORDER BY date DESC
        """)
        
        daily_stats = cur.fetchall()
        
        return {
            "status": "success",
            "total_statistics": {
                "total_images": total_stats[0],
                "successful_downloads": total_stats[1],
                "failed_downloads": total_stats[2],
                "success_rate": f"{(total_stats[1]/total_stats[0]*100):.1f}%" if total_stats[0] > 0 else "0%",
                "total_size_mb": round(total_stats[3] / 1024 / 1024, 2) if total_stats[3] else 0
            },
            "camera_breakdown": [
                {
                    "camera_ip": row[0],
                    "image_count": row[1],
                    "successful_count": row[2],
                    "success_rate": f"{(row[2]/row[1]*100):.1f}%" if row[1] > 0 else "0%",
                    "total_size_mb": round(row[3] / 1024 / 1024, 2) if row[3] else 0
                } for row in camera_stats
            ],
            "daily_statistics": [
                {
                    "date": str(row[0]),
                    "image_count": row[1],
                    "successful_count": row[2],
                    "success_rate": f"{(row[2]/row[1]*100):.1f}%" if row[1] > 0 else "0%"
                } for row in daily_stats
            ]
        }
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        cur.close()
        conn.close()