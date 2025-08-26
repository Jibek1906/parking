"""
Роутер для системной информации /system/*
"""
from fastapi import APIRouter, HTTPException
import os
import requests
from requests.auth import HTTPDigestAuth
from datetime import datetime
from ..config import KYRGYZSTAN_TZ, PARKING_CONFIG, CAMERA_CONFIG, BARRIER_CONFIG
from ..db import get_db_connection
from ..services.camera import is_valid_plate, get_plate_format_bonus
from ..services.parking import process_entry, process_exit
from ..services.barrier import open_barrier
from ..models import save_event

router = APIRouter(prefix="/system", tags=["system"])

@router.get("/health")
async def system_health():
    """Расширенная проверка здоровья системы"""
    try:
        conn = get_db_connection()
        cur = conn.cursor()
        cur.execute("SELECT 1")
        cur.fetchone()
        db_status = "ok"
        cur.close()
        conn.close()
    except Exception as e:
        db_status = f"error: {str(e)}"

    images_dir_exists = os.path.exists(CAMERA_CONFIG["images_dir"])
    images_dir_writable = os.access(CAMERA_CONFIG["images_dir"], os.W_OK) if images_dir_exists else False

    camera_status = {}
    for camera_name, camera_ip in [("entry", PARKING_CONFIG["entry_camera_ip"]), ("exit", PARKING_CONFIG["exit_camera_ip"])]:
        try:
            response = requests.get(f"http://{camera_ip}", timeout=5)
            camera_status[camera_name] = "reachable"
        except:
            camera_status[camera_name] = "unreachable"

    barrier_status = {}
    for barrier_name, barrier_config in [("entry", BARRIER_CONFIG["entry_barrier"]), ("exit", BARRIER_CONFIG["exit_barrier"])]:
        try:
            url = f"http://{barrier_config['ip']}:{barrier_config['port']}/ISAPI/System/deviceInfo"
            auth = HTTPDigestAuth(barrier_config['user'], barrier_config['password'])
            response = requests.get(url, auth=auth, timeout=5)
            barrier_status[barrier_name] = "reachable" if response.status_code in [200, 401] else "unreachable"
        except:
            barrier_status[barrier_name] = "unreachable"
    
    return {
        "timestamp": datetime.now(KYRGYZSTAN_TZ).isoformat(),
        "database": db_status,
        "images_directory": {
            "exists": images_dir_exists,
            "writable": images_dir_writable,
            "path": CAMERA_CONFIG["images_dir"]
        },
        "cameras": camera_status,
        "barriers": barrier_status,
        "configuration": {
            "entry_camera": PARKING_CONFIG["entry_camera_ip"],
            "exit_camera": PARKING_CONFIG["exit_camera_ip"],
            "hourly_rate": PARKING_CONFIG["hourly_rate"],
            "night_rate": PARKING_CONFIG["night_rate"],
            "free_minutes": PARKING_CONFIG["free_minutes"],
            "session_timeout_hours": PARKING_CONFIG["session_timeout_hours"],
            "min_plate_length": PARKING_CONFIG["min_plate_length"]
        },
        "security_status": {
            "plate_validation_active": True,
            "barrier_control_strict": True,
            "duplicate_event_prevention": True
        }
    }

@router.get("/stats")
async def get_system_stats():
    """Общая статистика системы"""
    try:
        conn = get_db_connection()
        cur = conn.cursor()

        cur.execute("SELECT COUNT(*) FROM camera")
        total_events = cur.fetchone()[0]
        
        cur.execute("SELECT COUNT(*) FROM camera WHERE plate_number != '' AND plate_number IS NOT NULL")
        events_with_plates = cur.fetchone()[0]

        cur.execute("SELECT COUNT(*) FROM alarm_images WHERE download_success = true")
        successful_images = cur.fetchone()[0]
        
        cur.execute("SELECT COUNT(*) FROM alarm_images")
        total_image_attempts = cur.fetchone()[0]

        cur.execute("""
            SELECT
                COUNT(*) FILTER (WHERE visit_status = 'active') as active_sessions,
                COUNT(*) FILTER (WHERE visit_status = 'completed') as completed_sessions,
                COUNT(*) FILTER (WHERE visit_status = 'timeout') as timeout_sessions,
                COUNT(*) FILTER (WHERE entry_barrier_opened = true) as successful_entries,
                COUNT(*) FILTER (WHERE exit_barrier_opened = true) as successful_exits
            FROM parking_visits
        """)
        parking_stats = cur.fetchone()

        cur.execute("""
            SELECT camera_key, COUNT(*) as event_count,
                   COUNT(*) FILTER (WHERE plate_number != '' AND plate_number IS NOT NULL) as plates_recognized
            FROM camera
            GROUP BY camera_key
        """)
        camera_breakdown = cur.fetchall()
        
        cur.close()
        conn.close()
        
        return {
            "total_events": total_events,
            "events_with_plates": events_with_plates,
            "plate_recognition_rate": f"{(events_with_plates/total_events*100):.1f}%" if total_events > 0 else "0%",
            "image_attempts": total_image_attempts,
            "successful_images": successful_images,
            "image_success_rate": f"{(successful_images/total_image_attempts*100):.1f}%" if total_image_attempts > 0 else "0%",
            "parking_sessions": {
                "active": parking_stats[0] or 0,
                "completed": parking_stats[1] or 0,
                "timeout": parking_stats[2] or 0,
                "successful_entries": parking_stats[3] or 0,
                "successful_exits": parking_stats[4] or 0
            },
            "camera_breakdown": [
                {
                    "camera": row[0],
                    "total_events": row[1],
                    "plates_recognized": row[2],
                    "recognition_rate": f"{(row[2]/row[1]*100):.1f}%" if row[1] > 0 else "0%"
                } for row in camera_breakdown
            ]
        }
        
    except Exception as e:
        return {"error": str(e)}

@router.post("/test/plate-validation")
async def test_plate_validation():
    """Тестирование валидации номеров"""
    test_plates = [
        "01008ABM",  # Валидный кыргызский
        "12345ABC",  # Валидный кыргызский  
        "T1234AB",   # Транзитный
        "AB123CD",   # Общий формат
        "TEST",      # Невалидный - слишком короткий
        "0000AAAA",  # Невалидный - подозрительный
        "123",       # Невалидный - слишком короткий
        "",          # Пустой
        "A1",        # Слишком короткий
        "ABCDEFGH"   # Только буквы
    ]
    
    results = []
    for plate in test_plates:
        is_valid = is_valid_plate(plate)
        bonus = get_plate_format_bonus(plate) if is_valid else 0
        results.append({
            "plate": plate,
            "valid": is_valid,
            "bonus_score": bonus,
            "length": len(plate)
        })
    
    return {
        "test_results": results,
        "validation_rules": {
            "min_length": PARKING_CONFIG["min_plate_length"],
            "max_length": 12,
            "requires_letters_and_digits": True,
            "blocks_suspicious_patterns": True,
            "blocks_repeating_characters": True
        }
    }

@router.post("/test/camera-event/{camera_ip}")
async def test_camera_event(camera_ip: str):
    """Тестирование событий от камеры с разными сценариями"""
    test_scenarios = [
        {
            "name": "Valid Kyrgyz Plate",
            "plate": "01008ABM",
            "should_open_barrier": True
        },
        {
            "name": "No Plate",
            "plate": "",
            "should_open_barrier": False
        },
        {
            "name": "Invalid Short Plate", 
            "plate": "ABC",
            "should_open_barrier": False
        },
        {
            "name": "Suspicious Plate",
            "plate": "0000AAAA",
            "should_open_barrier": False
        }
    ]
    
    results = []
    
    for scenario in test_scenarios:
        plate = scenario["plate"]
        expected = scenario["should_open_barrier"]

        event_id = save_event(f"test_{camera_ip}", "TEST_ANPR", plate, f"TEST_SCENARIO_{scenario['name']}")

        if camera_ip == PARKING_CONFIG["entry_camera_ip"]:
            result = process_entry(camera_ip, plate, event_id)
        elif camera_ip == PARKING_CONFIG["exit_camera_ip"]:
            result = process_exit(camera_ip, plate, event_id)
        else:
            result = {"barrier_opened": False, "message": "Unknown camera"}
        
        actual_opened = result.get("barrier_opened", False)
        
        results.append({
            "scenario": scenario["name"],
            "test_plate": plate,
            "expected_barrier_open": expected,
            "actual_barrier_open": actual_opened,
            "test_passed": actual_opened == expected,
            "result": result
        })
    
    passed_tests = sum(1 for r in results if r["test_passed"])
    
    return {
        "camera_ip": camera_ip,
        "total_tests": len(results),
        "passed_tests": passed_tests,
        "success_rate": f"{(passed_tests/len(results)*100):.1f}%",
        "test_results": results
    }

@router.post("/test/barrier-direct/{camera_ip}")
async def test_barrier_direct(camera_ip: str):
    """Прямое тестирование шлагбаума"""
    try:
        if camera_ip not in [PARKING_CONFIG["entry_camera_ip"], PARKING_CONFIG["exit_camera_ip"]]:
            return {"error": f"Camera {camera_ip} not configured for barrier control"}
        
        success = open_barrier(camera_ip)
        
        return {
            "status": "test_completed",
            "camera_ip": camera_ip,
            "barrier_opened": success,
            "message": f"Прямой тест шлагбаума для {camera_ip}: {'успешно' if success else 'неудача'}",
            "timestamp": datetime.now(KYRGYZSTAN_TZ).isoformat()
        }
        
    except Exception as e:
        return {"status": "test_failed", "error": str(e)}

@router.get("/config")
async def get_system_config():
    """Получить текущую конфигурацию системы"""
    return {
        "parking": {
            "entry_camera_ip": PARKING_CONFIG["entry_camera_ip"],
            "exit_camera_ip": PARKING_CONFIG["exit_camera_ip"],
            "hourly_rate": PARKING_CONFIG["hourly_rate"],
            "night_rate": PARKING_CONFIG["night_rate"],
            "free_minutes": PARKING_CONFIG["free_minutes"],
            "max_hours": PARKING_CONFIG["max_hours"],
            "session_timeout_hours": PARKING_CONFIG["session_timeout_hours"],
            "min_detection_interval_seconds": PARKING_CONFIG["min_detection_interval_seconds"],
            "min_plate_length": PARKING_CONFIG["min_plate_length"],
            "require_plate_for_barrier": PARKING_CONFIG["require_plate_for_barrier"]
        },
        "camera": {
            "username": CAMERA_CONFIG["username"],
            "timeout": CAMERA_CONFIG["timeout"],
            "images_dir": CAMERA_CONFIG["images_dir"],
            "max_retry_attempts": CAMERA_CONFIG["max_retry_attempts"],
            "retry_delay_seconds": CAMERA_CONFIG["retry_delay_seconds"]
        },
        "barriers": {
            "entry_barrier": {
                "ip": BARRIER_CONFIG["entry_barrier"]["ip"],
                "port": BARRIER_CONFIG["entry_barrier"]["port"],
                "channel": BARRIER_CONFIG["entry_barrier"]["channel"]
            },
            "exit_barrier": {
                "ip": BARRIER_CONFIG["exit_barrier"]["ip"],
                "port": BARRIER_CONFIG["exit_barrier"]["port"],
                "channel": BARRIER_CONFIG["exit_barrier"]["channel"]
            }
        }
    }