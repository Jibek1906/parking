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
    "force_barrier_on_any_event": False
}

CAMERA_CONFIG = {
    "username": os.getenv("CAMERA_USERNAME", "admin"),
    "password": os.getenv("CAMERA_PASSWORD", "Deltatech2023"),
    "timeout": int(os.getenv("CAMERA_TIMEOUT", 10)),
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