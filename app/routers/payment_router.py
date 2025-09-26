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
from ..db import get_db_connection
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


@router.post("/generate-qr")
async def generate_payment_qr(request: QRPaymentRequest):
    """
    ИСПРАВЛЕННАЯ генерация QR-кода с правильным маппингом operation_id
    """
    if not BAKAI_CONFIG["enable_payment_flow"]:
        raise HTTPException(status_code=503, detail="Payment flow is disabled")
   
    if not BAKAI_CONFIG["token"]:
        raise HTTPException(status_code=500, detail="Bakai token not configured")

    conn = get_db_connection()
    cur = conn.cursor()
   
    try:
        if request.session_id:
            cur.execute("""
                SELECT id, plate_number, entry_time, cost_amount, duration_minutes
                FROM parking_visits
                WHERE id = %s AND visit_status = 'completed'
            """, (request.session_id,))
        else:
            cur.execute("""
                SELECT id, plate_number, entry_time, cost_amount, duration_minutes
                FROM parking_visits
                WHERE plate_number = %s AND visit_status = 'completed'
                ORDER BY exit_time DESC LIMIT 1
            """, (request.plate_number.upper(),))
       
        session = cur.fetchone()
        if not session:
            raise HTTPException(status_code=404, detail="No completed parking session found")
       
        session_id, plate_number, entry_time, cost_amount, duration_minutes = session
       
        if cost_amount <= 0:
            return {
                "message": "Free parking - no payment required",
                "car_number": plate_number,
                "cost_amount": 0,
                "payment_required": False
            }

        our_operation_id = str(uuid.uuid4())

        qr_payload = {
            "accountNo": BAKAI_CONFIG["merchant_account"],
            "currencyId": 417,
            "amount": float(cost_amount),
            "operationID": our_operation_id
        }
       
        headers = get_bakai_headers()
       
        logger.info(f"🔄 Generating QR for plate {plate_number}, amount {cost_amount} KGS")
        logger.info(f"📋 Our operation_id: {our_operation_id}")
       
        response = requests.post(
            f"{BAKAI_CONFIG['api_base_url']}/api/Qr/GenerateQR",
            json=qr_payload,
            headers=headers,
            timeout=BAKAI_CONFIG["timeout"]
        )
       
        logger.info(f"📡 Bakai QR API response status: {response.status_code}")
        logger.info(f"📡 Bakai QR API response: {response.text}")
       
        if response.status_code != 200:
            logger.error(f"❌ Bakai QR API error: {response.status_code} - {response.text}")
            raise HTTPException(
                status_code=500,
                detail=f"QR generation failed: {response.text}"
            )
       
        qr_result = response.json()
        qr_image = qr_result.get("qrImage")

        bank_operation_id = None
        possible_fields = ["operationID", "operation_id", "operationId", "transactionId", "transaction_id"]
        
        for field in possible_fields:
            if field in qr_result and qr_result[field]:
                bank_operation_id = str(qr_result[field])
                logger.info(f"📋 Bank returned operation_id in field '{field}': {bank_operation_id}")
                break

        if not qr_image:
            logger.error(f"❌ No QR image in response: {qr_result}")
            raise HTTPException(status_code=500, detail="No QR image in response")

        logger.info(f"💾 Saving payment with transaction_id: {our_operation_id}, bakai_operation_id: {bank_operation_id}")

        cur.execute("""
            INSERT INTO parking_payments
            (session_id, plate_number, amount, transaction_id, bakai_operation_id, qr_image, payment_link, payment_status)
            VALUES (%s, %s, %s, %s, %s, %s, %s, 'pending')
            RETURNING id
        """, (
            session_id,
            plate_number,
            cost_amount,
            our_operation_id,
            bank_operation_id if bank_operation_id else our_operation_id,
            qr_image,
            f"QR_PAYMENT_{our_operation_id}"
        ))

        payment_id = cur.fetchone()[0]
        conn.commit()

        cur.execute("""
            SELECT exit_time FROM parking_visits WHERE id = %s
        """, (session_id,))
       
        exit_time_result = cur.fetchone()
        exit_time = exit_time_result[0] if exit_time_result else datetime.now(KYRGYZSTAN_TZ)

        operation_id_to_use = bank_operation_id if bank_operation_id else our_operation_id
        result = {
            "car_number": plate_number,
            "entry_time": entry_time.isoformat(),
            "exit_time": exit_time.isoformat(),
            "duration": format_duration(duration_minutes) if duration_minutes else "N/A",
            "cost_amount": float(cost_amount),
            "qr_image": qr_image,
            "operation_id": operation_id_to_use,
            "payment_id": payment_id,
            "payment_status": "pending",
            "message": "QR code generated successfully",
            "debug_info": {
                "our_operation_id": our_operation_id,
                "bank_operation_id": bank_operation_id,
                "operation_id_to_use": operation_id_to_use
            }
        }
       
        logger.info(f"✅ QR generated successfully for {plate_number}")
        logger.info(f"🔍 Client should check status using operation_id: {operation_id_to_use}")
        return result
       
    except requests.exceptions.RequestException as e:
        logger.error(f"❌ Network error calling Bakai API: {e}")
        raise HTTPException(status_code=503, detail=f"Payment service unavailable: {str(e)}")
    except Exception as e:
        conn.rollback()
        logger.error(f"❌ Error generating QR: {e}")
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        cur.close()
        conn.close()

@router.get("/check-status/{operation_id}")
async def check_payment_status(operation_id: str):
    """
    ИСПРАВЛЕННАЯ проверка статуса с подробным логированием
    """
    if not BAKAI_CONFIG["enable_payment_flow"]:
        raise HTTPException(status_code=503, detail="Payment flow is disabled")
   
    logger.info(f"🔍 Checking payment status for operation_id: {operation_id}")
   
    conn = get_db_connection()
    cur = conn.cursor()
   
    try:
        cur.execute("""
            SELECT pp.id, pp.session_id, pp.plate_number, pp.amount, pp.payment_status,
                   pp.transaction_id, pp.bakai_operation_id, pv.exit_camera_ip,
                   pv.exit_barrier_opened,
                   pp.created_at, pp.updated_at
            FROM parking_payments pp
            JOIN parking_visits pv ON pp.session_id = pv.id
            WHERE pp.transaction_id = %s OR pp.bakai_operation_id = %s
        """, (operation_id, operation_id))
       
        payment = cur.fetchone()
        
        if not payment:
            logger.warning(f"❌ Payment not found in database for operation_id: {operation_id}")

            cur.execute("""
                SELECT transaction_id, bakai_operation_id, plate_number, payment_status 
                FROM parking_payments 
                WHERE transaction_id LIKE %s OR bakai_operation_id LIKE %s
                ORDER BY created_at DESC LIMIT 5
            """, (f"%{operation_id[:8]}%", f"%{operation_id[:8]}%"))
            
            similar_payments = cur.fetchall()
            if similar_payments:
                logger.info(f"🔍 Found similar payments for debugging:")
                for sp in similar_payments:
                    logger.info(f"   - transaction_id: {sp[0]}, bakai_id: {sp[1]}, plate: {sp[2]}, status: {sp[3]}")
            
            raise HTTPException(status_code=404, detail="Payment not found")
       
        (payment_id, session_id, plate_number, amount, current_status, 
         primary_id, secondary_id, exit_camera_ip, exit_barrier_opened, created_at, updated_at) = payment
        
        logger.info(f"💾 Found payment in DB:")
        logger.info(f"   - payment_id: {payment_id}")
        logger.info(f"   - plate: {plate_number}")
        logger.info(f"   - current_status: {current_status}")
        logger.info(f"   - primary_id: {primary_id}")
        logger.info(f"   - secondary_id: {secondary_id}")
        logger.info(f"   - searching_for: {operation_id}")
        logger.info(f"   - exit_barrier_opened: {exit_barrier_opened}")

        if current_status == "paid":
            logger.info(f"✅ Payment already paid for {plate_number}")
            barrier_opened = False
            if exit_camera_ip and not exit_barrier_opened:
                logger.info(f"🚧 Attempting to open barrier for camera {exit_camera_ip} (first time after paid)")
                barrier_opened = open_barrier(exit_camera_ip)
                cur.execute("""
                    UPDATE parking_visits
                    SET exit_barrier_opened = true, updated_at = %s
                    WHERE id = %s
                """, (datetime.now(KYRGYZSTAN_TZ), session_id))
                conn.commit()
            try:
                await screen_ws_manager.broadcast({"screen": "success"})
            except Exception as ws_ex:
                logger.error(f"WebSocket broadcast error: {ws_ex}")
            screen_ws_manager.last_payment_plate = None
            return {
                "operation_id": operation_id,
                "payment_status": "paid",
                "barrier_opened": barrier_opened,
                "message": "Payment already confirmed"
            }

        check_operation_id = operation_id

        headers = get_bakai_headers()
        
        logger.info(f"📡 Checking Bakai API status for: {check_operation_id}")
       
        status_response = requests.get(
            f"{BAKAI_CONFIG['api_base_url']}/api/Qr/GetStatus?operationID={check_operation_id}",
            headers=headers,
            timeout=BAKAI_CONFIG["timeout"]
        )
       
        logger.info(f"📡 Bakai status API response: {status_response.status_code}")
        logger.info(f"📡 Bakai status API response body: {status_response.text}")
       
        if status_response.status_code == 200:
            status_data = status_response.json()
            logger.info(f"📋 Parsed Bakai status data: {json.dumps(status_data, indent=2)}")

            payment_status = None

            status_fields = [
                "operationState", "status", "paymentStatus", "payment_status", "state",
                "isPaid", "success", "completed"
            ]
            
            for field in status_fields:
                if field in status_data:
                    if field in ["isPaid", "success", "completed"] and status_data[field]:
                        payment_status = "success"
                        break
                    elif isinstance(status_data[field], str):
                        payment_status = status_data[field].lower()
                        break
           
            if not payment_status:
                payment_status = current_status
                logger.warning(f"⚠️ Could not determine payment status from response, using current: {payment_status}")
           
            logger.info(f"📊 Determined payment status: {payment_status}")
           
            if payment_status in ["success", "paid", "completed", "approved"]:
                logger.info(f"✅ Payment confirmed via API check for {plate_number}")
  
                cur.execute("""
                    UPDATE parking_payments
                    SET payment_status = 'paid',
                        paid_at = %s,
                        updated_at = %s,
                        notes = COALESCE(notes, '') || ' | Confirmed via status check'
                    WHERE id = %s
                """, (datetime.now(KYRGYZSTAN_TZ), datetime.now(KYRGYZSTAN_TZ), payment_id))

                cur.execute("""
                    UPDATE parking_visits
                    SET payment_received = true,
                        updated_at = %s
                    WHERE id = %s
                """, (datetime.now(KYRGYZSTAN_TZ), session_id))
               
                conn.commit()
               
                barrier_opened = False
                if exit_camera_ip:
                    logger.info(f"🚧 Attempting to open barrier for camera {exit_camera_ip}")
                    barrier_opened = open_barrier(exit_camera_ip)
               
                logger.info(f"✅ Payment status updated to paid for {plate_number}, barrier opened: {barrier_opened}")
                try:
                    await screen_ws_manager.broadcast({"screen": "success"})
                except Exception as ws_ex:
                    logger.error(f"WebSocket broadcast error: {ws_ex}")
                screen_ws_manager.last_payment_plate = None
                return {
                    "operation_id": operation_id,
                    "payment_status": "paid",
                    "barrier_opened": barrier_opened,
                    "message": f"Payment confirmed for {plate_number}" +
                              (" - barrier opened" if barrier_opened else " - barrier error")
                }
            else:
                if payment_status != current_status:
                    logger.info(f"📝 Updating payment status from {current_status} to {payment_status}")
                    cur.execute("""
                        UPDATE parking_payments
                        SET payment_status = %s,
                            updated_at = %s
                        WHERE id = %s
                    """, (payment_status, datetime.now(KYRGYZSTAN_TZ), payment_id))
                    conn.commit()
               
                return {
                    "operation_id": operation_id,
                    "payment_status": payment_status,
                    "message": f"Payment status: {payment_status}"
                }
       
        elif status_response.status_code == 404:
            logger.warning(f"❌ Operation not found in Bakai system: {operation_id}")

            if current_status == "paid":
                return {
                    "operation_id": operation_id,
                    "payment_status": "paid",
                    "message": "Payment already confirmed locally"
                }
            else:
                if secondary_id and secondary_id != operation_id:
                    logger.info(f"🔄 Trying alternative operation_id: {secondary_id}")
                    
                    alt_response = requests.get(
                        f"{BAKAI_CONFIG['api_base_url']}/api/Qr/GetStatus?operationID={secondary_id}",
                        headers=headers,
                        timeout=BAKAI_CONFIG["timeout"]
                    )
                    
                    if alt_response.status_code == 200:
                        logger.info(f"✅ Found payment using alternative ID: {secondary_id}")
                        return await check_payment_status(secondary_id)
                
                return {
                    "operation_id": operation_id,
                    "payment_status": current_status,
                    "message": "Operation not found in payment system"
                }
        else:
            logger.warning(f"⚠️ Unexpected Bakai API response: {status_response.status_code} - {status_response.text}")
            return {
                "operation_id": operation_id,
                "payment_status": current_status,
                "message": f"Status check error: {status_response.status_code}"
            }
           
    except requests.exceptions.RequestException as e:
        logger.error(f"❌ Network error checking payment status: {e}")
        return {
            "operation_id": operation_id,
            "payment_status": current_status if 'current_status' in locals() else "pending",
            "error": "Payment service unavailable"
        }
    except Exception as e:
        conn.rollback()
        logger.error(f"❌ Error checking payment status: {e}")
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        cur.close()
        conn.close()

@router.post("/webhook")
async def handle_bakai_webhook(request: Request):
    """
    ИСПРАВЛЕННЫЙ ВЕБХУК для обработки уведомлений от Bakai OpenBanking
    URL для банка: http://217.76.63.75/payment/webhook
    """
    try:
        raw_body = await request.body()
        logger.info(f"🔔 Webhook received raw body: {raw_body}")

        client_ip = request.client.host if request.client else "unknown"
        logger.info(f"📍 Webhook from IP: {client_ip}")
 
        try:
            webhook_data = await request.json()
        except json.JSONDecodeError:
            form_data = await request.form()
            webhook_data = dict(form_data)
        
        logger.info(f"🔔 Parsed webhook data: {json.dumps(webhook_data, indent=2, default=str)}")

        operation_id = None
        payment_status = None
        
        possible_id_fields = ["operationID", "operation_id", "transactionId", "transaction_id", "id"]
        possible_status_fields = ["operationState", "status", "paymentStatus", "payment_status", "state"]
        
        for field in possible_id_fields:
            if field in webhook_data:
                operation_id = str(webhook_data[field])
                break
                
        for field in possible_status_fields:
            if field in webhook_data:
                payment_status = str(webhook_data[field]).upper()
                break
        
        if not operation_id:
            logger.error("❌ Webhook missing operation ID in any expected field")
            return {"status": "error", "message": "Missing operation ID"}
        
        if not payment_status:
            logger.warning("⚠️ Webhook missing payment status, assuming SUCCESS")
            payment_status = "SUCCESS"
        
        logger.info(f"📋 Processing webhook - operation_id: {operation_id}, status: {payment_status}")
        
        conn = get_db_connection()
        cur = conn.cursor()
        
        try:
            cur.execute("""
                SELECT pp.id, pp.session_id, pp.plate_number, pp.payment_status, pv.exit_camera_ip
                FROM parking_payments pp
                JOIN parking_visits pv ON pp.session_id = pv.id
                WHERE pp.transaction_id = %s OR pp.bakai_operation_id = %s
            """, (operation_id, operation_id))
            
            payment = cur.fetchone()
            if not payment:
                logger.error(f"❌ Payment not found for operation_id: {operation_id}")
                return {"status": "error", "message": f"Payment not found for operation_id: {operation_id}"}
            
            payment_id, session_id, plate_number, current_status, exit_camera_ip = payment
            logger.info(f"🚗 Found payment for plate: {plate_number}, current status: {current_status}")
            
            if current_status == "paid":
                logger.info(f"✅ Payment already processed for {plate_number}")
                return {
                    "status": "success",
                    "message": f"Payment already processed for {plate_number}",
                    "operation_id": operation_id
                }
            
            if payment_status in ["SUCCESS", "PAID", "COMPLETED", "APPROVED", "OK"]:
                logger.info(f"✅ Payment successful for {plate_number}")
                
                current_time = datetime.now(KYRGYZSTAN_TZ)
                
                cur.execute("""
                    UPDATE parking_payments
                    SET payment_status = 'paid',
                        paid_at = %s,
                        updated_at = %s,
                        notes = 'Confirmed via webhook'
                    WHERE id = %s
                """, (current_time, current_time, payment_id))
                
                cur.execute("""
                    UPDATE parking_visits
                    SET payment_received = true,
                        exit_barrier_opened = true,
                        updated_at = %s,
                        notes = COALESCE(notes, '') || ' | Payment confirmed via webhook'
                    WHERE id = %s
                """, (current_time, session_id))
                
                conn.commit()
                
                logger.info(f"✅ Webhook payment confirmed for {plate_number}, barrier open task started")
                try:
                    await screen_ws_manager.broadcast({"screen": "success"})
                except Exception as ws_ex:
                    logger.error(f"WebSocket broadcast error: {ws_ex}")

                if exit_camera_ip:
                    try:
                        result = open_barrier(exit_camera_ip)
                        if result:
                            logger.info(f"🚧 Barrier successfully opened for camera {exit_camera_ip}")
                        else:
                            logger.warning(f"⚠️ Failed to open barrier for camera {exit_camera_ip}")
                    except Exception as barrier_ex:
                        logger.error(f"❌ Barrier error for camera {exit_camera_ip}: {barrier_ex}")
                else:
                    logger.warning("⚠️ No exit camera IP found for barrier control")

                screen_ws_manager.last_payment_plate = None
                return {
                    "status": "success",
                    "operation_id": operation_id,
                    "payment_status": "paid",
                    "plate_number": plate_number,
                    "message": f"Payment confirmed via webhook for {plate_number} (barrier opening in background)"
                }
                
            elif payment_status in ["FAILED", "CANCELLED", "REJECTED", "ERROR"]:
                logger.info(f"❌ Payment failed for {plate_number}, status: {payment_status}")
                
                cur.execute("""
                    UPDATE parking_payments
                    SET payment_status = 'failed',
                        updated_at = %s,
                        notes = %s
                    WHERE id = %s
                """, (datetime.now(KYRGYZSTAN_TZ), f"Failed via webhook: {payment_status}", payment_id))
                
                conn.commit()
                
                return {
                    "status": "success",
                    "operation_id": operation_id,
                    "payment_status": "failed",
                    "plate_number": plate_number,
                    "message": f"Payment failed for {plate_number}: {payment_status}"
                }
                
            else:
                logger.info(f"📝 Unknown payment status '{payment_status}' for {plate_number}")
                
                cur.execute("""
                    UPDATE parking_payments
                    SET payment_status = %s,
                        updated_at = %s,
                        notes = %s
                    WHERE id = %s
                """, (payment_status.lower(), datetime.now(KYRGYZSTAN_TZ), 
                      f"Status updated via webhook: {payment_status}", payment_id))
                
                conn.commit()
                
                return {
                    "status": "success",
                    "operation_id": operation_id,
                    "payment_status": payment_status.lower(),
                    "plate_number": plate_number,
                    "message": f"Payment status updated to {payment_status} for {plate_number}"
                }
                
        except Exception as e:
            conn.rollback()
            logger.error(f"❌ Database error processing webhook: {e}")
            return {"status": "error", "message": f"Database error: {str(e)}"}
        finally:
            cur.close()
            conn.close()
            
    except Exception as e:
        logger.error(f"❌ Webhook processing error: {e}")
        return {"status": "error", "message": f"Webhook processing error: {str(e)}"}


@router.get("/history/{plate_number}")
async def get_payment_history(plate_number: str):
    """История платежей для конкретного номера"""
    conn = get_db_connection()
    cur = conn.cursor()
   
    try:
        cur.execute("""
            SELECT pp.id, pp.amount, pp.transaction_id, pp.payment_status,
                   pp.created_at, pp.paid_at, pv.entry_time, pv.exit_time,
                   pv.duration_minutes
            FROM parking_payments pp
            JOIN parking_visits pv ON pp.session_id = pv.id
            WHERE pp.plate_number = %s
            ORDER BY pp.created_at DESC LIMIT 20
        """, (plate_number.upper(),))
       
        payments = []
        for row in cur.fetchall():
            (payment_id, amount, transaction_id, status, created_at, paid_at,
             entry_time, exit_time, duration_minutes) = row
             
            payments.append({
                "payment_id": payment_id,
                "amount": float(amount),
                "transaction_id": transaction_id,
                "status": status,
                "created_at": created_at.isoformat(),
                "paid_at": paid_at.isoformat() if paid_at else None,
                "entry_time": entry_time.isoformat(),
                "exit_time": exit_time.isoformat() if exit_time else None,
                "duration": format_duration(duration_minutes) if duration_minutes else None
            })
       
        return {
            "plate_number": plate_number.upper(),
            "payments": payments,
            "total_count": len(payments)
        }
       
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        cur.close()
        conn.close()


@router.post("/manual-confirm/{operation_id}")
async def manual_payment_confirmation(operation_id: str):
    """Ручное подтверждение платежа (для администраторов)"""
    conn = get_db_connection()
    cur = conn.cursor()
   
    try:
        cur.execute("""
            SELECT pp.id, pp.session_id, pp.plate_number, pv.exit_camera_ip
            FROM parking_payments pp
            JOIN parking_visits pv ON pp.session_id = pv.id
            WHERE (pp.transaction_id = %s OR pp.bakai_operation_id = %s) AND pp.payment_status = 'pending'
        """, (operation_id, operation_id))
       
        payment = cur.fetchone()
        if not payment:
            raise HTTPException(status_code=404, detail="Pending payment not found")
       
        payment_id, session_id, plate_number, exit_camera_ip = payment
       
        cur.execute("""
            UPDATE parking_payments
            SET payment_status = 'paid',
                paid_at = %s,
                updated_at = %s,
                notes = 'Manually confirmed'
            WHERE id = %s
        """, (datetime.now(KYRGYZSTAN_TZ), datetime.now(KYRGYZSTAN_TZ), payment_id))
       
        cur.execute("""
            UPDATE parking_visits
            SET payment_received = true,
                exit_barrier_opened = true,
                updated_at = %s
            WHERE id = %s
        """, (datetime.now(KYRGYZSTAN_TZ), session_id))
       
        conn.commit()
       
        barrier_opened = False
        if exit_camera_ip:
            barrier_opened = open_barrier(exit_camera_ip)
       
        try:
            await screen_ws_manager.broadcast({"screen": "success"})
        except Exception as ws_ex:
            logger.error(f"WebSocket broadcast error: {ws_ex}")
        screen_ws_manager.last_payment_plate = None
        return {
            "operation_id": operation_id,
            "payment_status": "paid",
            "barrier_opened": barrier_opened,
            "message": f"Payment manually confirmed for {plate_number}"
        }
       
    except Exception as e:
        conn.rollback()
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        cur.close()
        conn.close()


@router.get("/webhook-test")
async def webhook_test():
    """Тестовый эндпоинт для проверки работы вебхука"""
    return {
        "message": "Webhook endpoint is working",
        "url": "http://217.76.63.75/payment/webhook",
        "expected_fields": [
            "operationID - идентификатор операции",
            "operationState - статус платежа (success/failed)"
        ],
        "supported_statuses": {
            "success": ["SUCCESS", "PAID", "COMPLETED", "APPROVED", "OK"],
            "failure": ["FAILED", "CANCELLED", "REJECTED", "ERROR"]
        }
    }

@router.get("/debug/{operation_id}")
async def debug_payment_status(operation_id: str):
    """Диагностика проблем с operation_id"""
    conn = get_db_connection()
    cur = conn.cursor()
    
    try:
        cur.execute("""
            SELECT id, session_id, plate_number, amount, payment_status,
                   transaction_id, bakai_operation_id, created_at, updated_at,
                   payment_link, notes
            FROM parking_payments
            WHERE transaction_id = %s OR bakai_operation_id = %s
            OR transaction_id LIKE %s OR bakai_operation_id LIKE %s
        """, (operation_id, operation_id, f"%{operation_id}%", f"%{operation_id}%"))
        
        payments = cur.fetchall()
        
        cur.execute("""
            SELECT transaction_id, bakai_operation_id, plate_number, payment_status, created_at
            FROM parking_payments
            ORDER BY created_at DESC LIMIT 10
        """, ())
        
        recent_payments = cur.fetchall()
        
        return {
            "search_operation_id": operation_id,
            "found_payments": [
                {
                    "id": p[0], "session_id": p[1], "plate": p[2], "amount": float(p[3]),
                    "status": p[4], "transaction_id": p[5], "bakai_operation_id": p[6],
                    "created_at": p[7].isoformat(), "updated_at": p[8].isoformat() if p[8] else None,
                    "payment_link": p[9], "notes": p[10]
                }
                for p in payments
            ],
            "recent_payments": [
                {
                    "transaction_id": p[0], "bakai_operation_id": p[1],
                    "plate": p[2], "status": p[3], "created_at": p[4].isoformat()
                }
                for p in recent_payments
            ]
        }
        
    finally:
        cur.close()
        conn.close()
