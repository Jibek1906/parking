"""
Модуль бизнес-логики парковки (въезд/выезд/стоимость)
"""
from datetime import datetime, timedelta
from ..config import KYRGYZSTAN_TZ, PARKING_CONFIG
from ..db import get_db_connection
from .barrier import open_barrier
from .camera import is_valid_plate


def calculate_parking_cost(entry_time: datetime, exit_time: datetime) -> dict:
    """Рассчитывает стоимость парковки"""
    duration = exit_time - entry_time
    total_minutes = int(duration.total_seconds() / 60)
   
    if total_minutes <= PARKING_CONFIG["free_minutes"]:
        return {
            "duration_minutes": total_minutes,
            "total_cost": 0.0,
            "free_time": True,
            "description": f"Бесплатно ({total_minutes} мин)"
        }
   
    billable_minutes = total_minutes - PARKING_CONFIG["free_minutes"]
    hours = billable_minutes / 60
   
    entry_hour = entry_time.hour
    exit_hour = exit_time.hour
   
    is_night_parking = (entry_hour >= 22 or entry_hour <= 6) and (exit_hour >= 22 or exit_hour <= 6)
   
    if is_night_parking:
        rate = PARKING_CONFIG["night_rate"]
        rate_type = "ночной"
    else:
        rate = PARKING_CONFIG["hourly_rate"]
        rate_type = "дневной"
   
    billable_hours = max(1, int(hours) + (1 if hours % 1 > 0 else 0))
   
    if billable_hours > PARKING_CONFIG["max_hours"]:
        billable_hours = PARKING_CONFIG["max_hours"]
   
    total_cost = billable_hours * rate
   
    return {
        "duration_minutes": total_minutes,
        "billable_hours": billable_hours,
        "total_cost": total_cost,
        "rate": rate,
        "rate_type": rate_type,
        "free_time": False,
        "description": f"{billable_hours} ч × {rate} сом ({rate_type} тариф)"
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
    """ИСПРАВЛЕННАЯ обработка выезда - ТОЛЬКО С НОМЕРОМ"""
    if not plate or not is_valid_plate(plate):
        print(f"❌ Exit denied - invalid or missing plate number: '{plate}'")
        return {
            "error": "No valid plate number detected",
            "barrier_opened": False,
            "message": f"Выезд заблокирован - номер не распознан или недействителен: '{plate}'"
        }
   
    barrier_opened = open_barrier(camera_ip)
    print(f"🚪 EXIT BARRIER OPENED: {barrier_opened} for valid plate {plate}")
   
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
                updated_at = %s
            WHERE id = %s
        """, (
            exit_time, cost_info["duration_minutes"], cost_info["total_cost"],
            cost_info["description"], camera_ip, event_id, barrier_opened,
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
            "message": f"Выезд: {plate} | {duration_str} | {cost_info['total_cost']} сом" + (" - шлагбаум открыт" if barrier_opened else " - ошибка шлагбаума")
        }
       
        print(f"✅ Exit processed: {result}")
        return result
       
    except Exception as e:
        conn.rollback()
        print(f"❌ Error processing exit: {e}")
        return {
            "error": str(e),
            "barrier_opened": barrier_opened,
            "message": f"Ошибка выезда {plate}" + (" - шлагбаум открыт" if barrier_opened else " - ошибка шлагбаума")
        }
    finally:
        cur.close()
        conn.close()
