"""
Роутер для эндпоинтов камер /camera/* с интеграцией QR-оплаты
"""
from fastapi import APIRouter, Request, HTTPException, BackgroundTasks
from starlette.requests import ClientDisconnect
from datetime import datetime
from ..config import KYRGYZSTAN_TZ, PARKING_CONFIG, BAKAI_CONFIG, CAMERA_CONFIG
from ..models import save_event
from ..services.camera import (
    find_plate_number, find_event_type, find_picture_url,
    is_duplicate_event, is_valid_plate
)
from ..services.parking import process_entry, process_exit
from ..services.images import process_alarm_image
from ..db import get_db_connection
import requests
import uuid
import logging
from app.ws_manager import screen_ws_manager

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/camera", tags=["camera"])

@router.post("/event")
async def camera_event(req: Request, background_tasks: BackgroundTasks):
    """Обработка событий от камер с интеграцией QR-оплаты для выезда"""
    try:
        forwarded_for = req.headers.get("X-Forwarded-For")
        if forwarded_for:
            client_ip = forwarded_for.split(",")[0].strip()
        else:
            client_ip = req.client.host if req.client else "unknown"

        CAMERA_IP_MAP = {
            "212.112.126.251": "192.0.0.12",
            "212.112.126.252": "192.0.0.11",
            "46.251.204.46": "192.0.0.11",
        }
        client_ip_mapped = CAMERA_IP_MAP.get(client_ip, client_ip)

        raw_bytes = await req.body()

        from ..services.images import process_alarm_image
        from app.ws_manager import screen_ws_manager

        async def instant_photo_and_ws():
            image_result = process_alarm_image(
                0,
                client_ip,
                "",
                "INSTANT",
                "INSTANT"
            )
            if image_result and image_result.get("success"):
                await screen_ws_manager.broadcast({
                    "screen": "camera_instant",
                    "camera_ip": client_ip,
                    "image_url": f"/{CAMERA_CONFIG['images_dir']}/{image_result['filename']}",
                    "timestamp": datetime.now(KYRGYZSTAN_TZ).isoformat()
                })

        if client_ip in (PARKING_CONFIG["entry_camera_ip"], PARKING_CONFIG["exit_camera_ip"]):
            background_tasks.add_task(instant_photo_and_ws)
            instant_camera_ip = req.headers.get("X-Forwarded-For")
            if instant_camera_ip:
                instant_camera_ip = instant_camera_ip.split(",")[0].strip()
            else:
                instant_camera_ip = req.client.host if req.client else "unknown"
            print(f"📸 INSTANT SNAPSHOT (async): {instant_camera_ip}")
            import asyncio
            loop = asyncio.get_event_loop()
            from ..services.images import process_alarm_image
            loop.run_in_executor(
                None,
                process_alarm_image,
                0,
                instant_camera_ip,
                "",
                "",
                "INSTANT"
            )

        debug_dir = "/var/www/parking/parking/camera_debug"
        import os
        os.makedirs(debug_dir, exist_ok=True)
        debug_filename = os.path.join(
            debug_dir,
            f"event_{datetime.now().strftime('%Y%m%d_%H%M%S_%f')}.bin"
        )
        with open(debug_filename, "wb") as f:
            f.write(raw_bytes)

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
        print("📥 EVENT RECEIVED - QR PAYMENT INTEGRATION v2.5")
        print(f"📏 Data size: {len(raw_bytes)} bytes")
        print(f"📝 Raw event saved to: {debug_filename}")

        forwarded_for = req.headers.get("X-Forwarded-For")
        if forwarded_for:
            client_ip = forwarded_for.split(",")[0].strip()
        else:
            client_ip = req.client.host if req.client else "unknown"

        import re
        real_ip = None
        ip_match = re.search(r"<ipAddress>([^<]+)</ipAddress>", raw_text)
        if ip_match:
            real_ip = ip_match.group(1).strip()
        else:
            import json
            try:
                data = json.loads(raw_text)
                real_ip = data.get("ipAddress")
            except Exception:
                real_ip = None

        if real_ip:
            camera_ip = real_ip
        else:
            camera_ip = client_ip

        camera_key = f"camera_{camera_ip}"
        print(f"📍 Camera IP (from body): {camera_ip}")

        plate = find_plate_number(raw_text)
        event_type = find_event_type(raw_text)
        picture_url = find_picture_url(raw_text)

        if plate:
            print(f"✅ PLATE RECOGNIZED: '{plate}'")
        else:
            print("⚠️ No valid plate number found")

        if not plate or not is_valid_plate(plate):
            print("⛔️ Ignoring event: empty or invalid plate")
            return {
                "status": "ignored",
                "plate": plate or "",
                "plate_valid": False,
                "camera_ip": camera_ip,
                "timestamp": datetime.now(KYRGYZSTAN_TZ).isoformat(),
                "message": "Событие проигнорировано: номер не распознан или невалиден"
            }

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

        image_result = None
        if event_id and plate:
            print("🖼️ Processing image for valid plate event (ASYNC, BEFORE BARRIER)...")
            async def event_photo_and_ws():
                img_res = process_alarm_image(
                    event_id, camera_ip, picture_url, plate, event_type or "ANPR"
                )
                if img_res and img_res.get("success"):
                    await screen_ws_manager.broadcast({
                        "screen": "camera_event",
                        "camera_ip": camera_ip,
                        "event_id": event_id,
                        "plate": plate,
                        "image_url": f"/{CAMERA_CONFIG['images_dir']}/{img_res['filename']}",
                        "timestamp": datetime.now(KYRGYZSTAN_TZ).isoformat()
                    })
            background_tasks.add_task(event_photo_and_ws)
        else:
            print("ℹ️ Skipping image processing - no valid plate detected")

        parking_result = {"status": "event_saved"}

        if camera_ip == PARKING_CONFIG["exit_camera_ip"]:
            print("🚪 EXIT CAMERA 11 - QR PAYMENT INTEGRATION!")
            parking_result = process_exit(camera_ip, plate, event_id)

            if (parking_result.get("action") in ("exit", "exit_payment_required") and
                parking_result.get("total_cost", 0) > 0 and
                plate and
                BAKAI_CONFIG["enable_payment_flow"]):

                print(f"💳 Generating QR payment for {plate}, cost: {parking_result['total_cost']}")
                try:
                    qr_result = await generate_qr_for_parking(
                        session_id=parking_result["session_id"],
                        plate=plate,
                        cost=parking_result["total_cost"]
                    )

                    if qr_result:
                        parking_result["qr_payment"] = qr_result
                        parking_result["payment_required"] = True
                        print(f"✅ QR generated successfully for {plate}")
                        try:
                            logger.info(f"🔔 Sending payment screen event to idle.html for plate {plate}, operation_id: {qr_result.get('operation_id')}")
                            logger.info(f"WS BROADCAST: screen=payment, plate={plate}")
                            from app.ws_manager import screen_ws_manager
                            screen_ws_manager.last_payment_plate = plate
                            await screen_ws_manager.broadcast({
                                "screen": "payment",
                                "plate": plate
                            })
                        except Exception as ws_ex:
                            logger.error(f"WebSocket broadcast error: {ws_ex}")
                        # Скачивание фото — в фоне, не мешая переходу на оплату
                        # def async_photo():
                        #     try:
                        #         process_alarm_image(
                        #             event_id, camera_ip, picture_url, plate, event_type or "ANPR"
                        #         )
                        #     except Exception as e:
                        #         logger.error(f"Async image processing error: {e}")
                        # background_tasks.add_task(async_photo)
                    else:
                        parking_result["qr_payment_error"] = "Failed to generate QR"
                        parking_result["payment_required"] = False
                        print(f"❌ QR generation failed for {plate}")

                except Exception as qr_error:
                    logger.error(f"QR generation error for {plate}: {qr_error}")
                    parking_result["qr_payment_error"] = str(qr_error)
                    parking_result["payment_required"] = False
            else:
                parking_result["payment_required"] = False

        elif camera_ip == PARKING_CONFIG["entry_camera_ip"]:
            print("🚪 ENTRY CAMERA 12 - STANDARD PROCESSING!")
            parking_result = process_entry(camera_ip, plate, event_id)

        else:
            print(f"ℹ️ Unknown camera IP: {camera_ip} - no barrier control")
            parking_result = {
                "status": "unknown_camera",
                "barrier_opened": False,
                "message": f"Неизвестная камера {camera_ip} - шлагбаум не управляется"
            }

        result = {
            "status": "ok",
            "event_type": event_type or "ANPR",
            "plate": plate or "",
            "plate_valid": bool(plate and is_valid_plate(plate)),
            "camera_ip": camera_ip,
            "timestamp": datetime.now(KYRGYZSTAN_TZ).isoformat(),
            "event_id": event_id,
            "picture_url": picture_url,
            **parking_result
        }

        if event_id and plate:
            result["image_processing_scheduled"] = True
        else:
            result["image_processing_scheduled"] = False
            result["image_skip_reason"] = "No valid plate detected"

        print(f"📤 FINAL RESPONSE: {result}")
        print("="*80)

        return result

    except ClientDisconnect:
        client_ip = req.client.host if req.client else "unknown"
        logger.warning(f"Client disconnected before body could be read (IP: {client_ip})")
        return {
            "status": "client_disconnect",
            "message": "Клиент закрыл соединение до передачи данных",
            "plate": "",
            "camera_ip": client_ip,
            "barrier_opened": False,
            "timestamp": datetime.now(KYRGYZSTAN_TZ).isoformat(),
            "error_note": "Клиент отключился до передачи данных"
        }
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


async def generate_qr_for_parking(session_id: int, plate: str, cost: float) -> dict:
    """
    Внутренняя функция генерации QR для парковки.
    Если уже есть pending платеж для session_id/plate, возвращает его, иначе создает новый.
    """
    if not BAKAI_CONFIG["token"] or not BAKAI_CONFIG["merchant_account"]:
        logger.error("Bakai configuration incomplete")
        return None

    conn = get_db_connection()
    cur = conn.cursor()

    try:
        cur.execute("""
            SELECT id, transaction_id, bakai_operation_id, qr_image, amount, payment_status
            FROM parking_payments
            WHERE session_id = %s AND plate_number = %s AND payment_status = 'pending'
            ORDER BY created_at DESC LIMIT 1
        """, (session_id, plate))
        existing = cur.fetchone()
        if existing:
            payment_id, transaction_id, bakai_operation_id, qr_image, amount, payment_status = existing
            cur.execute("""
                SELECT entry_time, exit_time, duration_minutes
                FROM parking_visits 
                WHERE id = %s
            """, (session_id,))
            session_data = cur.fetchone()
            entry_time, exit_time, duration_minutes = session_data if session_data else (None, None, None)
            return {
                "car_number": plate,
                "entry_time": entry_time.isoformat() if entry_time else None,
                "exit_time": exit_time.isoformat() if exit_time else None,
                "cost_amount": float(amount),
                "qr_image": qr_image,
                "operation_id": bakai_operation_id if bakai_operation_id else transaction_id,
                "payment_id": payment_id
            }

        cur.execute("""
            SELECT entry_time, exit_time, duration_minutes
            FROM parking_visits 
            WHERE id = %s
        """, (session_id,))
        session_data = cur.fetchone()
        if not session_data:
            logger.error(f"Session {session_id} not found")
            return None

        entry_time, exit_time, duration_minutes = session_data

        operation_id = str(uuid.uuid4())

        qr_payload = {
            "accountNo": BAKAI_CONFIG["merchant_account"],
            "currencyId": 417,
            "amount": float(cost),
            "operationID": operation_id
        }

        headers = {
            "Authorization": f"Bearer {BAKAI_CONFIG['token']}",
            "Content-Type": "application/json"
        }

        response = requests.post(
            f"{BAKAI_CONFIG['api_base_url']}/api/Qr/GenerateQR",
            json=qr_payload,
            headers=headers,
            timeout=BAKAI_CONFIG["timeout"]
        )

        if response.status_code != 200:
            logger.error(f"Bakai QR API error: {response.status_code} - {response.text}")
            return None

        qr_result = response.json()
        qr_image = qr_result.get("qrImage")

        if not qr_image:
            logger.error("No QR image in Bakai response")
            return None

        bakai_operation_id = qr_result.get("operationID") or qr_result.get("operationId") or qr_result.get("transactionId") or operation_id

        local_operation_id = str(uuid.uuid4())
        cur.execute("""
            INSERT INTO parking_payments 
            (session_id, plate_number, amount, local_operation_id, bakai_operation_id, qr_image, transaction_id, payment_link, payment_status)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, 'pending')
            RETURNING id
        """, (
            session_id, 
            plate, 
            cost, 
            local_operation_id,
            bakai_operation_id,
            qr_image,
            operation_id,
            f"QR_PAYMENT_{operation_id}"
        ))

        payment_id = cur.fetchone()[0]
        conn.commit()

        return {
            "car_number": plate,
            "entry_time": entry_time.isoformat(),
            "exit_time": exit_time.isoformat(),
            "cost_amount": float(cost),
            "qr_image": qr_image,
            "operation_id": bakai_operation_id,
            "payment_id": payment_id
        }

    except requests.exceptions.RequestException as e:
        logger.error(f"Network error calling Bakai API: {e}")
        return None
    except Exception as e:
        conn.rollback()
        logger.error(f"Error generating QR: {e}")
        return None
    finally:
        cur.close()
        conn.close()

@router.get("/payment-page/{plate_number}")
async def get_payment_page_data(plate_number: str):
    """
    Получить данные для страницы оплаты по номеру автомобиля
    """
    conn = get_db_connection()
    cur = conn.cursor()
    
    try:
        cur.execute("""
            SELECT pv.id, pv.entry_time, pv.exit_time, pv.duration_minutes, 
                   pv.cost_amount, pp.transaction_id, pp.bakai_operation_id, pp.payment_status, pp.id as payment_id
            FROM parking_visits pv
            JOIN parking_payments pp ON pv.id = pp.session_id
            WHERE pv.plate_number = %s 
            AND pv.visit_status = 'completed'
            AND pp.payment_status = 'pending'
            ORDER BY pv.exit_time DESC
            LIMIT 1
        """, (plate_number.upper(),))
        
        result = cur.fetchone()
        if not result:
            raise HTTPException(status_code=404, detail="No pending payment found for this vehicle")
        
        (session_id, entry_time, exit_time, duration_minutes, 
         cost_amount, transaction_id, bakai_operation_id, payment_status, payment_id) = result

        operation_id_to_use = bakai_operation_id if bakai_operation_id else transaction_id
        
        qr_data = await generate_qr_for_parking(session_id, plate_number, float(cost_amount))
        
        if not qr_data:
            raise HTTPException(status_code=500, detail="Failed to generate QR code")
        
        return {
            "car_number": plate_number.upper(),
            "entry_time": entry_time.isoformat(),
            "exit_time": exit_time.isoformat(),
            "duration": f"{duration_minutes // 60}h {duration_minutes % 60}m" if duration_minutes else "N/A",
            "cost_amount": float(cost_amount),
            "qr_image": qr_data["qr_image"],
            "operation_id": operation_id_to_use,
            "payment_status": payment_status
        }
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        cur.close()
        conn.close()
