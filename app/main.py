"""
Главный файл приложения Smart Parking System v2.2
"""
from fastapi import FastAPI
from .models import init_database
from .services.images import init_images_directory
from .services.parking import close_expired_sessions
from .config import PARKING_CONFIG, CAMERA_CONFIG

from .routers import camera_router, parking_router, image_router, system_router

app = FastAPI(
    title="Smart Parking System",
    description="Система управления парковкой с распознаванием номеров",
    version="2.2"
)

app.include_router(camera_router.router)
app.include_router(parking_router.router)
app.include_router(image_router.router)
app.include_router(system_router.router)

@app.on_event("startup")
async def startup_event():
    init_database()
    
    init_images_directory()
    
    expired_count = close_expired_sessions()
    if expired_count > 0:
        print(f"⏰ Closed {expired_count} expired sessions on startup")
    
    print(f"🚀 Smart Parking System v2.2 - MODULAR VERSION started!")
    print(f"📍 Entry camera (12): {PARKING_CONFIG['entry_camera_ip']}")
    print(f"📍 Exit camera (11): {PARKING_CONFIG['exit_camera_ip']}")
    print(f"💰 Day rate: {PARKING_CONFIG['hourly_rate']} som/hour")
    print(f"🌙 Night rate: {PARKING_CONFIG['night_rate']} som/hour")
    print(f"⏱️ Free time: {PARKING_CONFIG['free_minutes']} minutes")
    print(f"⏰ Session timeout: {PARKING_CONFIG['session_timeout_hours']} hours")
    print(f"🖼️ Images directory: {CAMERA_CONFIG['images_dir']}")
    print(f"👤 Camera auth: {CAMERA_CONFIG['username']}")
    print(f"🚪 Barrier control enabled")
    print("✅ All systems ready!")

@app.get("/")
async def root():
    return {
        "message": "🚗 Smart Parking System v2.2 - Modular Version", 
        "status": "running",
        "architecture": "modular",
        "version": "2.2",
        "endpoints": {
            "camera": "/camera/event - обработка событий от камер",
            "parking": "/parking/* - управление парковкой",
            "images": "/images/* - работа с изображениями", 
            "system": "/system/* - системная информация"
        }
    }