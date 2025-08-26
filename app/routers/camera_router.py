"""
Роутер для эндпоинтов камер /camera/*
"""
from fastapi import APIRouter, Request, HTTPException
from datetime import datetime
from ..config import KYRGYZSTAN_TZ, PARKING_CONFIG
from ..models import save_event
from ..services.camera import (
    find_plate_number, find_event_type, find_picture_url,
    is_duplicate_event, is_valid_plate
)
from ..services.parking import process_entry, process_exit
from ..services.images import process_alarm_image


router = APIRouter(prefix="/camera", tags=["camera"])


@router.post("/event")
async def camera_event(req: Request):
    """Обработка событий от камер - СТРОГАЯ ВАЛИДАЦИЯ НОМЕРОВ"""
    try:
        raw_bytes = await req.body()

        raw_text = ""
        for encoding in ['utf-8', 'latin-1', 'ascii', 'cp1252']:
            try:
                raw_text = raw_bytes.decode(encoding, errors="ignore")
                break
            except:
                continue
       
        if not raw_text:
            raw_text = str(raw_bytes, errors="ignore")
       
        print("🔍" + "="*79)
        print("📥 EVENT RECEIVED - MODULAR VERSION v2.2 - PLATE VALIDATION REQUIRED")
        print(f"📏 Data size: {len(raw_bytes)} bytes")
       
        client_ip = req.client.host if req.client else "unknown"
        camera_key = f"camera_{client_ip}"
       
        print(f"📍 Camera IP: {client_ip}")

        plate = find_plate_number(raw_text)
        event_type = find_event_type(raw_text)
        picture_url = find_picture_url(raw_text)

        if plate:
            print(f"✅ PLATE RECOGNIZED: '{plate}'")
        else:
            print("⚠️ No valid plate number found")
           
        if event_type:
            print(f"📋 Event type: '{event_type}'")
        else:
            print("⚠️ Event type not identified")


        if picture_url:
            print(f"🖼️ Picture URL found: '{picture_url}'")
       
        if plate and is_duplicate_event(client_ip, plate, raw_text):
            print(f"⚠️ DUPLICATE EVENT IGNORED for {client_ip} plate {plate}")
            return {
                "status": "duplicate_ignored",
                "plate": plate,
                "camera_ip": client_ip,
                "message": "Событие проигнорировано как дублирующееся"
            }

        event_id = save_event(camera_key, event_type or "ANPR", plate or "", raw_text)

        parking_result = {"status": "event_saved"}
       
        if client_ip == PARKING_CONFIG["exit_camera_ip"]:
            print("🚪 EXIT CAMERA 11 - STRICT PLATE VALIDATION!")
            parking_result = process_exit(client_ip, plate, event_id)
               
        elif client_ip == PARKING_CONFIG["entry_camera_ip"]:
            print("🚪 ENTRY CAMERA 12 - STRICT PLATE VALIDATION!")
            parking_result = process_entry(client_ip, plate, event_id)
           
        else:
            print(f"ℹ️ Unknown camera IP: {client_ip} - no barrier control")
            parking_result = {
                "status": "unknown_camera",
                "barrier_opened": False,
                "message": f"Неизвестная камера {client_ip} - шлагбаум не управляется"
            }

        image_result = None
        if event_id and plate:
            print("🖼️ Processing image for valid plate event...")
            image_result = process_alarm_image(
                event_id, client_ip, picture_url, plate, event_type or "ANPR"
            )
        elif event_id:
            print("ℹ️ Skipping image processing - no valid plate detected")
       
        result = {
            "status": "ok",
            "event_type": event_type or "ANPR",
            "plate": plate or "",
            "plate_valid": bool(plate and is_valid_plate(plate)),
            "camera_ip": client_ip,
            "timestamp": datetime.now(KYRGYZSTAN_TZ).isoformat(),
            "event_id": event_id,
            "picture_url": picture_url,
            **parking_result
        }

        if image_result:
            result["image_processed"] = image_result["success"]
            if image_result["success"]:
                result["image_filename"] = image_result["filename"]
                result["image_id"] = image_result["image_id"]
                result["image_size"] = image_result["size"]
                result["download_attempts"] = image_result["attempts"]
            else:
                result["image_error"] = image_result.get("error", "Unknown error")
        else:
            result["image_processed"] = False
            result["image_skip_reason"] = "No valid plate detected"
       
        print(f"📤 FINAL RESPONSE: {result}")
        print("="*80)
       
        return result
       
    except Exception as e:
        print(f"💥 CRITICAL ERROR: {e}")
        import traceback
        traceback.print_exc()
       
        client_ip = req.client.host if req.client else "unknown"
       
        return {
            "status": "error",
            "message": str(e),
            "plate": "",
            "camera_ip": client_ip,
            "barrier_opened": False,
            "timestamp": datetime.now(KYRGYZSTAN_TZ).isoformat(),
            "error_note": "Шлагбаум заблокирован из-за ошибки системы"
            }