""" 
Конфигурация системы парковки v2.2
""" 
import os
from zoneinfo import ZoneInfo

KYRGYZSTAN_TZ = ZoneInfo("Asia/Bishkek")

DB_PARAMS = {
    "host": os.getenv("DB_HOST", "localhost"),
    "port": int(os.getenv("DB_PORT", 5432)),
    "dbname": os.getenv("DB_NAME", "test"),
    "user": os.getenv("DB_USER", "postgres"),
    "password": os.getenv("DB_PASSWORD", "1234")
}

BAKAI_CONFIG = {
    "api_base_url": os.getenv("BAKAI_API_URL", "https://openbanking-api.bakai.kg"),
    "token": os.getenv("BAKAI_TOKEN", ""),
    "merchant_account": os.getenv("BAKAI_MERCHANT_ACCOUNT", "1240040002323627"),
    "timeout": int(os.getenv("BAKAI_TIMEOUT", 15)),
    "success_redirect_base": os.getenv("SUCCESS_REDIRECT_URL", "https://217.76.63.75:8000"),
    "qr_service": "https://api.qrserver.com/v1/create-qr-code/",
    "enable_payment_flow": bool(os.getenv("ENABLE_PAYMENT_FLOW", "true").lower() == "true")
}

import json

PARKING_MODE_FILE = "config_parking_mode.json"

def save_parking_mode(mode: str):
    try:
        with open(PARKING_MODE_FILE, "w") as f:
            json.dump({"mode": mode}, f)
    except Exception as e:
        print(f"❌ Error saving parking mode: {e}")

def load_parking_mode():
    try:
        with open(PARKING_MODE_FILE, "r") as f:
            data = json.load(f)
            return data.get("mode")
    except Exception:
        return None

PARKING_CONFIG = {
    "entry_camera_ip": os.getenv("ENTRY_CAMERA_IP", "192.0.0.12"),
    "exit_camera_ip": os.getenv("EXIT_CAMERA_IP", "192.0.0.11"),
    "hourly_rate": float(os.getenv("HOURLY_RATE", 50.0)),
    "free_minutes": int(os.getenv("FREE_MINUTES", 15)),
    "max_hours": int(os.getenv("MAX_HOURS", 24)),
    "night_rate": float(os.getenv("NIGHT_RATE", 30.0)),
    "session_timeout_hours": int(os.getenv("SESSION_TIMEOUT", 12)),
    "min_detection_interval_seconds": int(os.getenv("MIN_DETECTION_INTERVAL", 10)),
    "min_plate_length": int(os.getenv("MIN_PLATE_LENGTH", 4)),
    "require_plate_for_barrier": True,
    "force_barrier_on_any_event": False,
    "mode": load_parking_mode() or os.getenv("PARKING_MODE", "paid")
}

PARKING_CAMERAS = {
    "192.0.0.12": {
        "role": "entry",
        "barrier": True,
        "name": "Въезд 1"
    },
    "192.0.0.11": {
        "role": "exit",
        "barrier": True,
        "name": "Выезд 1"
    },
    "46.251.204.46": {
        "role": "entry",
        "barrier": True,
        "name": "Въезд 2 (реальный IP)"
    }
}

CAMERA_CONFIG = {
    "username": os.getenv("CAMERA_USERNAME", "admin"),
    "password": os.getenv("CAMERA_PASSWORD", "Deltatech2023"),
    "timeout": int(os.getenv("CAMERA_TIMEOUT", 5)),
    "images_dir": os.getenv("IMAGES_DIR", "alarm_images"),
    "max_retry_attempts": int(os.getenv("MAX_RETRY_ATTEMPTS", 3)),
    "retry_delay_seconds": int(os.getenv("RETRY_DELAY", 1))
}

BARRIER_CONFIG = {
    "entry_barrier": {
        "ip": os.getenv("ENTRY_BARRIER_IP", "192.0.0.12"),
        "port": int(os.getenv("ENTRY_BARRIER_PORT", 80)),
        "user": os.getenv("ENTRY_BARRIER_USER", "admin"), 
        "password": os.getenv("ENTRY_BARRIER_PASSWORD", "Deltatech2023"),
        "channel": int(os.getenv("ENTRY_BARRIER_CHANNEL", 1))
    },
    "exit_barrier": {
        "ip": os.getenv("EXIT_BARRIER_IP", "192.0.0.11"), 
        "port": int(os.getenv("EXIT_BARRIER_PORT", 80)),
        "user": os.getenv("EXIT_BARRIER_USER", "admin"),
        "password": os.getenv("EXIT_BARRIER_PASSWORD", "Deltatech2023"), 
        "channel": int(os.getenv("EXIT_BARRIER_CHANNEL", 1))
    }
}
