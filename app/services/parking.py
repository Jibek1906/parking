"""
Модуль бизнес-логики парковки с интеграцией оплаты (въезд/выезд/стоимость/платежи)
"""
from datetime import datetime, timedelta
from ..config import KYRGYZSTAN_TZ, PARKING_CONFIG, BAKAI_CONFIG
from ..db import get_db_connection
from .barrier import open_barrier
from app.models import get_whitelist
from datetime import datetime
from .camera import is_valid_plate
def is_plate_in_whitelist(plate: str) -> bool:
    """
    Проверяет, есть ли номер в белом списке с валидным сроком действия
    """
    from app.config import KYRGYZSTAN_TZ
    plate = plate.strip().upper()
    now = datetime.now(KYRGYZSTAN_TZ)
    whitelist = get_whitelist(active_only=True)
    for entry in whitelist:
        if entry["plate_number"].strip().upper() == plate:
            valid_from = entry["valid_from"]
            valid_until = entry["valid_until"]
            if valid_from and valid_from.tzinfo is None:
                from_zone = now.tzinfo
                valid_from = valid_from.replace(tzinfo=from_zone)
            if valid_until and valid_until.tzinfo is None:
                from_zone = now.tzinfo
                valid_until = valid_until.replace(tzinfo=from_zone)
            if valid_from and now < valid_from:
                continue
            if valid_until and now > valid_until:
                continue
            return True
    return False

def calculate_parking_cost(entry_time: datetime, exit_time: datetime) -> dict:
    """Рассчитывает стоимость парковки с использованием тарифов из БД"""
    conn = get_db_connection()
    cur = conn.cursor()
    
    try:
        cur.execute("""
            SELECT hourly_rate, night_rate, free_minutes, max_hours, name
            FROM parking_tariffs
            WHERE is_active = true
            AND (valid_until IS NULL OR valid_until >= CURRENT_DATE)
            ORDER BY created_at DESC
            LIMIT 1
        """)
        tariff = cur.fetchone()
        
        if tariff:
            hourly_rate, night_rate, free_minutes, max_hours, tariff_name = tariff
        else:
            hourly_rate = PARKING_CONFIG["hourly_rate"]
            night_rate = PARKING_CONFIG["night_rate"]
            free_minutes = PARKING_CONFIG["free_minutes"]
            max_hours = PARKING_CONFIG["max_hours"]
            tariff_name = "default"
            
    except Exception as e:
        print(f"Error getting tariff from DB: {e}")
        hourly_rate = PARKING_CONFIG["hourly_rate"]
        night_rate = PARKING_CONFIG["night_rate"]
        free_minutes = PARKING_CONFIG["free_minutes"]
        max_hours = PARKING_CONFIG["max_hours"]
        tariff_name = "default"
    finally:
        cur.close()
        conn.close()
    
    duration = exit_time - entry_time
    total_minutes = int(duration.total_seconds() / 60)
   
    if total_minutes <= free_minutes:
        return {
            "duration_minutes": total_minutes,
            "total_cost": 0.0,
            "free_time": True,
            "description": f"Бесплатно ({total_minutes} мин)",
            "tariff_used": tariff_name
        }
   
    billable_minutes = total_minutes - free_minutes
    hours = billable_minutes / 60
   
    entry_hour = entry_time.hour
    exit_hour = exit_time.hour
   
    is_night_parking = (entry_hour >= 22 or entry_hour <= 6) and (exit_hour >= 22 or exit_hour <= 6)
   
    if is_night_parking:
        rate = night_rate
        rate_type = "ночной"
    else:
        rate = hourly_rate
        rate_type = "дневной"
   
    billable_hours = max(1, int(hours) + (1 if hours % 1 > 0 else 0))
   
    if billable_hours > max_hours:
        billable_hours = max_hours
   
    total_cost = billable_hours * rate
   
    return {
        "duration_minutes": total_minutes,
        "billable_hours": billable_hours,
        "total_cost": total_cost,
        "rate": rate,
        "rate_type": rate_type,
        "free_time": False,
        "description": f"{billable_hours} ч × {rate} сом ({rate_type} тариф)",
        "tariff_used": tariff_name
    }

def format_duration(minutes: int) -> str:
    """Форматирует продолжительность в читаемый вид"""
    if minutes < 60:
        return f"{minutes} мин"
   
    hours = minutes // 60
    remaining_minutes = minutes % 60
   
    if remaining_minutes == 0:
        return f"{hours} ч"
    else:
        return f"{hours} ч {remaining_minutes} мин"

def close_expired_sessions():
    """Автоматически закрывает просроченные сессии"""
    conn = get_db_connection()
    cur = conn.cursor()
   
    try:
        cutoff_time = datetime.now(KYRGYZSTAN_TZ) - timedelta(hours=PARKING_CONFIG["session_timeout_hours"])
       
        cur.execute("""
            SELECT id, plate_number, entry_time
            FROM parking_visits
            WHERE visit_status = 'active' AND entry_time < %s
        """, (cutoff_time,))
       
        expired_sessions = cur.fetchall()
       
        for session_id, plate, entry_time in expired_sessions:
            timeout_time = entry_time + timedelta(hours=PARKING_CONFIG["session_timeout_hours"])
            cost_info = calculate_parking_cost(entry_time, timeout_time)
           
            cur.execute("""
                UPDATE parking_visits
                SET exit_time = %s,
                    duration_minutes = %s,
                    cost_amount = %s,
                    cost_description = %s,
                    visit_status = 'timeout',
                    notes = 'Автоматически закрыто по таймауту',
                    updated_at = %s
                WHERE id = %s
            """, (
                timeout_time, cost_info["duration_minutes"], cost_info["total_cost"],
                cost_info["description"] + " (таймаут)", datetime.now(KYRGYZSTAN_TZ), session_id
            ))
           
            print(f"⏰ Session {session_id} for {plate} closed by timeout")
       
        conn.commit()
        return len(expired_sessions)
       
    except Exception as e:
        conn.rollback()
        print(f"❌ Error closing expired sessions: {e}")
        return 0
    finally:
        cur.close()
        conn.close()

def process_entry(camera_ip: str, plate: str, event_id: int) -> dict:
    """Обработка въезда - ТОЛЬКО С ВАЛИДНЫМ НОМЕРОМ"""
    if not plate or not is_valid_plate(plate):
        print(f"❌ Entry denied - invalid or missing plate number: '{plate}'")
        return {
            "error": "No valid plate number detected",
            "barrier_opened": False,
            "message": f"Въезд заблокирован - номер не распознан или недействителен: '{plate}'"
        }

    if is_plate_in_whitelist(plate):
        barrier_opened = open_barrier(camera_ip)
        print(f"🚦 Белый список: въезд {plate} - шлагбаум открыт бесплатно")
        return {
            "action": "entry_whitelist",
            "plate": plate,
            "barrier_opened": barrier_opened,
            "message": f"Въезд: {plate} (белый список) - шлагбаум открыт бесплатно"
        }

    conn = get_db_connection()
    cur = conn.cursor()

    try:
        expired_count = close_expired_sessions()
        if expired_count > 0:
            print(f"⏰ Closed {expired_count} expired sessions")

        cur.execute("""
            SELECT id, entry_time FROM parking_visits
            WHERE plate_number = %s AND visit_status = 'active'
            ORDER BY entry_time DESC LIMIT 1
        """, (plate,))

        existing_session = cur.fetchone()

        if existing_session:
            session_id, entry_time = existing_session
            hours_since_entry = (datetime.now(KYRGYZSTAN_TZ) - entry_time).total_seconds() / 3600

            if hours_since_entry < 2:
                print(f"⚠️ Duplicate entry detected for {plate}")
                barrier_opened = open_barrier(camera_ip)

                return {
                    "action": "duplicate_entry",
                    "existing_session_id": session_id,
                    "entry_time": entry_time.isoformat(),
                    "hours_since_entry": round(hours_since_entry, 1),
                    "barrier_opened": barrier_opened,
                    "message": f"Повторный въезд {plate}" + (" - шлагбаум открыт" if barrier_opened else " - ошибка шлагбаума")
                }
            else:
                print(f"🔄 Force-closing old session for {plate}")

                exit_time = datetime.now(KYRGYZSTAN_TZ)
                cost_info = calculate_parking_cost(entry_time, exit_time)

                cur.execute("""
                    UPDATE parking_visits
                    SET exit_time = %s,
                        duration_minutes = %s,
                        cost_amount = %s,
                        cost_description = %s,
                        visit_status = 'manual',
                        notes = 'Принудительно закрыто из-за нового въезда',
                        updated_at = %s
                    WHERE id = %s
                """, (
                    exit_time, cost_info["duration_minutes"], cost_info["total_cost"],
                    cost_info["description"] + " (принуд. закрытие)", datetime.now(KYRGYZSTAN_TZ), session_id
                ))

        entry_time = datetime.now(KYRGYZSTAN_TZ)

        barrier_opened = open_barrier(camera_ip)
        print(f"🚪 BARRIER CONTROL: {barrier_opened} for valid plate {plate}")

        cur.execute("""
            INSERT INTO parking_visits
            (plate_number, entry_time, entry_camera_ip, entry_event_id,
             visit_status, entry_barrier_opened)
            VALUES (%s, %s, %s, %s, 'active', %s)
            RETURNING id
        """, (plate, entry_time, camera_ip, event_id, barrier_opened))

        session_id = cur.fetchone()[0]
        conn.commit()

        result = {
            "action": "entry",
            "session_id": session_id,
            "plate": plate,
            "entry_time": entry_time.isoformat(),
            "barrier_opened": barrier_opened,
            "message": f"Въезд: {plate}" + (" - шлагбаум открыт" if barrier_opened else " - ошибка шлагбаума")
        }

        print(f"✅ Entry processed: {result}")
        return result

    except Exception as e:
        conn.rollback()
        print(f"❌ Error processing entry: {e}")
        return {
            "error": str(e),
            "barrier_opened": False,
            "message": f"Ошибка въезда {plate} - шлагбаум заблокирован"
        }
    finally:
        cur.close()
        conn.close()

def process_exit(camera_ip: str, plate: str, event_id: int) -> dict:
    """Обработка выезда с ИНТЕГРАЦИЕЙ ПЛАТЕЖЕЙ или в режиме free"""
    if not plate or not is_valid_plate(plate):
        print(f"❌ Exit denied - invalid or missing plate number: '{plate}'")
        return {
            "error": "No valid plate number detected",
            "barrier_opened": False,
            "message": f"Выезд заблокирован - номер не распознан или недействителен: '{plate}'"
        }

    if is_plate_in_whitelist(plate):
        conn = get_db_connection()
        cur = conn.cursor()
        try:
            cur.execute("""
                SELECT id, entry_time FROM parking_visits
                WHERE plate_number = %s AND visit_status = 'active'
                ORDER BY entry_time DESC LIMIT 1
            """, (plate,))
            active_session = cur.fetchone()
            barrier_opened = open_barrier(camera_ip)
            if active_session:
                session_id, entry_time = active_session
                exit_time = datetime.now(KYRGYZSTAN_TZ)
                duration_minutes = int((exit_time - entry_time).total_seconds() / 60)
                cur.execute("""
                    UPDATE parking_visits
                    SET exit_time = %s,
                        duration_minutes = %s,
                        cost_amount = 0,
                        cost_description = 'Бесплатно (белый список)',
                        visit_status = 'completed',
                        exit_camera_ip = %s,
                        exit_event_id = %s,
                        exit_barrier_opened = %s,
                        payment_received = True,
                        updated_at = %s,
                        notes = 'Сессия завершена по белому списку'
                    WHERE id = %s
                """, (
                    exit_time, duration_minutes, camera_ip, event_id, barrier_opened,
                    datetime.now(KYRGYZSTAN_TZ), session_id
                ))
                conn.commit()
                return {
                    "action": "exit_whitelist",
                    "plate": plate,
                    "barrier_opened": barrier_opened,
                    "payment_required": False,
                    "message": f"Выезд: {plate} (белый список) - шлагбаум открыт бесплатно, сессия закрыта"
                }
            else:
                print(f"🚦 Белый список: выезд {plate} - активная сессия не найдена")
                return {
                    "action": "exit_whitelist",
                    "plate": plate,
                    "barrier_opened": barrier_opened,
                    "payment_required": False,
                    "message": f"Выезд: {plate} (белый список) - шлагбаум открыт бесплатно (активная сессия не найдена)"
                }
        finally:
            cur.close()
            conn.close()

    if PARKING_CONFIG.get("mode", "paid") == "free":
        print("🚦 Режим парковки: FREE — оплата не требуется, шлагбаум открывается автоматически")
        conn = get_db_connection()
        cur = conn.cursor()
        try:
            cur.execute("""
                SELECT id, entry_time FROM parking_visits
                WHERE plate_number = %s AND visit_status = 'active'
                ORDER BY entry_time DESC LIMIT 1
            """, (plate,))
            active_session = cur.fetchone()
            if not active_session:
                now = datetime.now(KYRGYZSTAN_TZ)
                barrier_opened = open_barrier(camera_ip)
                cur.execute("""
                    INSERT INTO parking_visits
                    (plate_number, entry_time, exit_time, duration_minutes, cost_amount,
                     cost_description, visit_status, exit_camera_ip, exit_event_id,
                     exit_barrier_opened, notes)
                    VALUES (%s, %s, %s, 0, 0, 'Выезд без въезда (free mode)', 'manual', %s, %s, %s,
                            'Сессия въезда не найдена (free mode)')
                    RETURNING id
                """, (
                    plate, now, now, camera_ip, event_id, barrier_opened
                ))
                manual_session_id = cur.fetchone()[0]
                conn.commit()
                return {
                    "action": "exit_without_entry",
                    "session_id": manual_session_id,
                    "plate": plate,
                    "barrier_opened": barrier_opened,
                    "payment_required": False,
                    "message": f"Выезд без въезда: {plate} (free mode) - шлагбаум открыт",
                    "warning": "Активная сессия въезда не найдена (free mode)"
                }
            session_id, entry_time = active_session
            exit_time = datetime.now(KYRGYZSTAN_TZ)
            cost_info = calculate_parking_cost(entry_time, exit_time)
            barrier_opened = open_barrier(camera_ip)
            cur.execute("""
                UPDATE parking_visits
                SET exit_time = %s,
                    duration_minutes = %s,
                    cost_amount = %s,
                    cost_description = %s,
                    visit_status = 'completed',
                    exit_camera_ip = %s,
                    exit_event_id = %s,
                    exit_barrier_opened = %s,
                    payment_received = True,
                    updated_at = %s,
                    notes = 'Сессия завершена в режиме free'
                WHERE id = %s
            """, (
                exit_time, cost_info["duration_minutes"], cost_info["total_cost"],
                cost_info["description"], camera_ip, event_id, barrier_opened,
                datetime.now(KYRGYZSTAN_TZ), session_id
            ))
            conn.commit()
            duration_str = format_duration(cost_info["duration_minutes"])
            result = {
                "action": "exit_free_mode",
                "session_id": session_id,
                "plate": plate,
                "entry_time": entry_time.isoformat(),
                "exit_time": exit_time.isoformat(),
                "duration": duration_str,
                "total_cost": float(cost_info["total_cost"]),
                "free_time": cost_info["free_time"],
                "description": cost_info["description"],
                "barrier_opened": barrier_opened,
                "payment_required": False,
                "message": f"Выезд: {plate} | {duration_str} | {cost_info['total_cost']} сом (free mode) - шлагбаум открыт"
            }
            print(f"✅ Exit processed (free mode): {result}")
            return result
        except Exception as e:
            conn.rollback()
            print(f"❌ Error processing exit (free mode): {e}")
            return {
                "error": str(e),
                "barrier_opened": False,
                "message": f"Ошибка выезда {plate} (free mode) - шлагбаум заблокирован"
            }
        finally:
            cur.close()
            conn.close()

    conn = get_db_connection()
    cur = conn.cursor()

    try:
        expired_count = close_expired_sessions()
        if expired_count > 0:
            print(f"⏰ Closed {expired_count} expired sessions")

        cur.execute("""
            SELECT id, entry_time FROM parking_visits
            WHERE plate_number = %s AND visit_status = 'active'
            ORDER BY entry_time DESC LIMIT 1
        """, (plate,))

        active_session = cur.fetchone()

        if not active_session:
            print(f"⚠️ No active session found for vehicle {plate}")

            barrier_opened = open_barrier(camera_ip)

            cur.execute("""
                INSERT INTO parking_visits
                (plate_number, entry_time, exit_time, duration_minutes, cost_amount,
                 cost_description, visit_status, exit_camera_ip, exit_event_id,
                 exit_barrier_opened, notes)
                VALUES (%s, %s, %s, 0, 0, 'Выезд без въезда', 'manual', %s, %s, %s,
                        'Сессия въезда не найдена')
                RETURNING id
            """, (
                plate, datetime.now(KYRGYZSTAN_TZ), datetime.now(KYRGYZSTAN_TZ),
                camera_ip, event_id, barrier_opened
            ))

            manual_session_id = cur.fetchone()[0]
            conn.commit()

            return {
                "action": "exit_without_entry",
                "session_id": manual_session_id,
                "plate": plate,
                "barrier_opened": barrier_opened,
                "message": f"Выезд без въезда: {plate}" + (" - шлагбаум открыт" if barrier_opened else " - ошибка шлагбаума"),
                "warning": "Активная сессия въезда не найдена"
            }

        session_id, entry_time = active_session
        exit_time = datetime.now(KYRGYZSTAN_TZ)

        cost_info = calculate_parking_cost(entry_time, exit_time)

        needs_payment = (
            BAKAI_CONFIG["enable_payment_flow"] and 
            cost_info["total_cost"] > 0 and 
            camera_ip == PARKING_CONFIG["exit_camera_ip"]
        )

        if needs_payment:
            cur.execute("""
                UPDATE parking_visits
                SET exit_time = %s,
                    duration_minutes = %s,
                    cost_amount = %s,
                    cost_description = %s,
                    visit_status = 'completed',
                    exit_camera_ip = %s,
                    exit_event_id = %s,
                    exit_barrier_opened = false,
                    payment_received = false,
                    notes = 'Требуется оплата для открытия шлагбаума',
                    updated_at = %s
                WHERE id = %s
            """, (
                exit_time, cost_info["duration_minutes"], cost_info["total_cost"],
                cost_info["description"], camera_ip, event_id,
                datetime.now(KYRGYZSTAN_TZ), session_id
            ))

            conn.commit()
            duration_str = format_duration(cost_info["duration_minutes"])

            print(f"💳 PAYMENT REQUIRED for {plate}: {cost_info['total_cost']} сом")

            result = {
                "action": "exit_payment_required",
                "session_id": session_id,
                "plate": plate,
                "entry_time": entry_time.isoformat(),
                "exit_time": exit_time.isoformat(),
                "duration": duration_str,
                "total_cost": float(cost_info["total_cost"]),
                "free_time": cost_info["free_time"],
                "description": cost_info["description"],
                "barrier_opened": False,
                "payment_required": True,
                "message": f"Выезд: {plate} | {duration_str} | {cost_info['total_cost']} сом | ТРЕБУЕТСЯ ОПЛАТА"
            }
        else:
            barrier_opened = open_barrier(camera_ip)
            print(f"🚪 EXIT BARRIER OPENED: {barrier_opened} for valid plate {plate}")

            cur.execute("""
                UPDATE parking_visits
                SET exit_time = %s,
                    duration_minutes = %s,
                    cost_amount = %s,
                    cost_description = %s,
                    visit_status = 'completed',
                    exit_camera_ip = %s,
                    exit_event_id = %s,
                    exit_barrier_opened = %s,
                    payment_received = %s,
                    updated_at = %s
                WHERE id = %s
            """, (
                exit_time, cost_info["duration_minutes"], cost_info["total_cost"],
                cost_info["description"], camera_ip, event_id, barrier_opened,
                True if cost_info["total_cost"] == 0 else False,
                datetime.now(KYRGYZSTAN_TZ), session_id
            ))

            conn.commit()
            duration_str = format_duration(cost_info["duration_minutes"])

            result = {
                "action": "exit",
                "session_id": session_id,
                "plate": plate,
                "entry_time": entry_time.isoformat(),
                "exit_time": exit_time.isoformat(),
                "duration": duration_str,
                "total_cost": float(cost_info["total_cost"]),
                "free_time": cost_info["free_time"],
                "description": cost_info["description"],
                "barrier_opened": barrier_opened,
                "payment_required": False,
                "message": f"Выезд: {plate} | {duration_str} | {cost_info['total_cost']} сом" + (" - шлагбаум открыт" if barrier_opened else " - ошибка шлагбаума")
            }

        print(f"✅ Exit processed: {result}")
        return result
       
    except Exception as e:
        conn.rollback()
        print(f"❌ Error processing exit: {e}")
        return {
            "error": str(e),
            "barrier_opened": False,
            "message": f"Ошибка выезда {plate} - шлагбаум заблокирован"
        }
    finally:
        cur.close()
        conn.close()

def create_payment_session(session_id: int) -> dict:
    """Создать платежную сессию для завершенного визита"""
    conn = get_db_connection()
    cur = conn.cursor()
    
    try:
        cur.execute("""
            SELECT plate_number, entry_time, exit_time, cost_amount, cost_description, payment_received
            FROM parking_visits
            WHERE id = %s AND visit_status = 'completed'
        """, (session_id,))
        
        session = cur.fetchone()
        if not session:
            return {"error": "Session not found or not completed"}
        
        plate, entry_time, exit_time, cost_amount, cost_description, payment_received = session
        
        if payment_received:
            return {"error": "Session already paid"}
            
        if cost_amount <= 0:
            return {"error": "No payment required"}
        
        return {
            "success": True,
            "session_id": session_id,
            "car_number": plate,
            "entry_time": entry_time.isoformat(),
            "exit_time": exit_time.isoformat() if exit_time else None,
            "cost_amount": float(cost_amount),
            "cost_description": cost_description
        }
        
    except Exception as e:
        return {"error": str(e)}
    finally:
        cur.close()
        conn.close()
