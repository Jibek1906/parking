"""
Главный файл приложения Smart Parking System v2.5
НОВЫЕ ВОЗМОЖНОСТИ QR-ОПЛАТЫ:
- Интеграция с Bakai OpenBanking API
- Автоматическая генерация QR-кодов при выезде
- Проверка статуса платежей
- Автоматическое открытие шлагбаума после оплаты
"""
import asyncio
from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from fastapi import WebSocket, WebSocketDisconnect
import psycopg2
import os
from typing import List
from app.ws_manager import screen_ws_manager
from .models import init_database
from .services.images import init_images_directory
from .services.parking import close_expired_sessions
from .config import PARKING_CONFIG, CAMERA_CONFIG, BAKAI_CONFIG

from .routers import (
    camera_router, parking_router, image_router,
    system_router, tariff_router, payment_router
)
from .routers import admin_router
from fastapi import Request
from fastapi.templating import Jinja2Templates

@asynccontextmanager
async def lifespan(app: FastAPI):
    """Управление жизненным циклом приложения"""
    init_database()
    init_images_directory()

    try:
        from app.services.camera_snapshot import start_snapshot_thread
        start_snapshot_thread()
        print("📸 Camera snapshot thread started (every 5 seconds)")
    except Exception as e:
        print(f"❌ Failed to start camera snapshot thread: {e}")
   
    expired_count = close_expired_sessions()
    if expired_count > 0:
        print(f"⏰ Closed {expired_count} expired sessions on startup")
   
    print("🚀 Smart Parking System v2.5 - QR PAYMENT INTEGRATION started!")
    print("✨ NEW QR PAYMENT FEATURES:")
    print("  • Bakai OpenBanking API integration")
    print("  • Automatic QR generation on exit")
    print("  • Real-time payment status checking")
    print("  • Automatic barrier control on payment confirmation")
    print("  • Payment history and management")
    print(f"📍 Entry camera (12): {PARKING_CONFIG['entry_camera_ip']}")
    print(f"📍 Exit camera (11): {PARKING_CONFIG['exit_camera_ip']} - QR PAYMENT ENABLED")
    print(f"🖼️ Images directory: {CAMERA_CONFIG['images_dir']}")
    print(f"💳 Payment integration: {'ENABLED' if BAKAI_CONFIG['enable_payment_flow'] else 'DISABLED'}")
    if BAKAI_CONFIG['enable_payment_flow']:
        print(f"🏪 Merchant account: {BAKAI_CONFIG['merchant_account']}")
        print(f"🔗 Bakai API: {BAKAI_CONFIG['api_base_url']}")
        print(f"🚧 Auto barrier control: ENABLED")
    print("✅ All systems ready with QR payment support!")
   
    yield
   
    print("🔄 Shutting down QR payment system...")
    print("✅ Shutdown complete")

app = FastAPI(
    title="Smart Parking System",
    description="Система управления парковкой с QR-оплатой через Bakai OpenBanking v2.5",
    version="2.5",
    lifespan=lifespan
)

from fastapi.staticfiles import StaticFiles
app.mount("/static", StaticFiles(directory="static"), name="static")

templates_dir = os.path.join(os.path.dirname(os.path.dirname(__file__)), "templates")
if os.path.exists(templates_dir):
    app.mount("/static", StaticFiles(directory=templates_dir), name="static")

app.include_router(camera_router.router)
app.include_router(parking_router.router)
app.include_router(image_router.router)
app.include_router(system_router.router)
app.include_router(tariff_router.router)
app.include_router(payment_router.router)
app.include_router(admin_router.router)

from app.ws_manager import screen_ws_manager
@app.get("/screen/next-payment")
async def get_next_payment_plate():
    """
    Возвращает plate для последней ожидающей оплаты (или null)
    """
    return {"plate": screen_ws_manager.last_payment_plate}

@app.post("/screen/clear-payment")
async def clear_next_payment_plate():
    """
    Сбросить plate для оплаты (например, после успешной оплаты)
    """
    screen_ws_manager.last_payment_plate = None
    return {"ok": True}

@app.websocket("/ws/screen")
async def screen_control_ws(websocket: WebSocket):
    await screen_ws_manager.connect(websocket)
    try:
        while True:
            await asyncio.sleep(60)
    except WebSocketDisconnect:
        screen_ws_manager.disconnect(websocket)
    except Exception:
        screen_ws_manager.disconnect(websocket)

@app.websocket("/ws/payment_status/{operation_id}")
async def payment_status_ws(websocket: WebSocket, operation_id: str):
    await websocket.accept()
    try:
        import time
        from .db import get_db_connection
        last_status = None
        while True:
            conn = get_db_connection()
            cur = conn.cursor()
            try:
                cur.execute(
                    "SELECT payment_status FROM parking_payments WHERE transaction_id = %s OR bakai_operation_id = %s",
                    (operation_id, operation_id)
                )
                row = cur.fetchone()
                if row:
                    status = row[0]
                    if status != last_status:
                        await websocket.send_json({"status": status})
                        last_status = status
                    if status == "paid":
                        break
                else:
                    await websocket.send_json({"status": "not_found"})
                    break
            finally:
                cur.close()
                conn.close()
            await asyncio.sleep(1)
    except WebSocketDisconnect:
        pass
    except Exception as e:
        try:
            await websocket.send_json({"error": str(e)})
        except RuntimeError:
            pass
    finally:
        try:
            await websocket.close()
        except RuntimeError:
            pass

templates = Jinja2Templates(directory=templates_dir)

@app.get("/admin")
async def admin_page(request: Request):
    """
    Страница админки (режимы работы, управление)
    """
    return templates.TemplateResponse("admin.html", {"request": request})

@app.get("/")
async def root():
    return {
        "message": "🚗 Smart Parking System v2.5 - QR Payment Integration",
        "status": "running",
        "architecture": "modular_enhanced_with_qr_payments",
        "version": "2.5",
        "new_features": [
            "🆕 Bakai OpenBanking QR integration",
            "🆕 Automatic QR generation on exit",
            "🆕 Real-time payment status checking",
            "🆕 Payment confirmation with barrier control",
            "🆕 Web payment interface",
            "Dynamic tariffs management",
            "Vehicle queue protection", 
            "Enhanced error handling"
        ],
        "endpoints": {
            "camera": "/camera/event - обработка событий от камер с QR-генерацией",
            "parking": "/parking/* - управление парковкой",
            "images": "/images/* - работа с изображениями",
            "system": "/system/* - системная информация",
            "tariffs": "/tariffs/* - управление тарифами",
            "payment": "/payment/* - QR-оплата через Bakai (NEW)",
            "admin": "/admin - админка (режимы работы)"
        },
        "payment_integration": {
            "enabled": BAKAI_CONFIG["enable_payment_flow"],
            "provider": "Bakai OpenBanking",
            "api_url": BAKAI_CONFIG["api_base_url"],
            "merchant_account": BAKAI_CONFIG["merchant_account"],
            "features": [
                "QR-код генерация при выезде",
                "Автоматическая проверка статуса",
                "Открытие шлагбаума после оплаты",
                "История платежей",
                "Ручное подтверждение платежей"
            ]
        }
    }

from fastapi.responses import RedirectResponse

@app.get("/pay")
async def payment_page(plate: str = None):
    """Страница оплаты парковки (старый маршрут, теперь редиректит на /2)"""
    print(f"!!! [DEBUG] /pay?plate={plate} — REDIRECT to /2")
    return RedirectResponse(url="/2", status_code=302)

@app.get("/1")
async def pretty_idle_page():
    """Красивый маршрут: idle (экран ожидания)"""
    idle_html_path = os.path.join(templates_dir, "idle.html")
    if os.path.exists(idle_html_path):
        return FileResponse(idle_html_path, media_type="text/html")
    else:
        return FileResponse(create_default_idle_page(), media_type="text/html")

@app.get("/2")
async def pretty_payment_page(plate: str = None):
    """Красивый маршрут: страница оплаты (можно передавать plate через query)"""
    payment_html_path = os.path.join(templates_dir, "payment.html")
    if os.path.exists(payment_html_path):
        return FileResponse(payment_html_path, media_type="text/html")
    else:
        return {"error": "Payment page not found", "path": payment_html_path}

@app.get("/3")
async def pretty_payment_success_page():
    """Красивый маршрут: страница успешной оплаты"""
    payment_success_path = os.path.join(templates_dir, "payment_success.html")
    if os.path.exists(payment_success_path):
        return FileResponse(payment_success_path, media_type="text/html")
    else:
        return {"error": "Payment success page not found", "path": payment_success_path}

@app.get("/payment_success.html")
async def payment_success_page():
    """Страница успешной оплаты"""
    payment_success_path = os.path.join(templates_dir, "payment_success.html")
    if os.path.exists(payment_success_path):
        return FileResponse(payment_success_path, media_type="text/html")
    else:
        return {"error": "Payment success page not found", "path": payment_success_path}

@app.get("/idle.html")
async def idle_page():
    """Статичная заставка для специального экрана"""
    idle_html_path = os.path.join(templates_dir, "idle.html")
    if os.path.exists(idle_html_path):
        return FileResponse(idle_html_path, media_type="text/html")
    else:
        return FileResponse(create_default_idle_page(), media_type="text/html")

@app.get("/screen/payment")
async def screen_payment_page():
    """Специальная страница оплаты для экрана (новая версия)"""
    screen_payment_path = os.path.join(templates_dir, "screen_payment.html")
    if os.path.exists(screen_payment_path):
        return FileResponse(screen_payment_path, media_type="text/html")
    else:
        payment_html_path = os.path.join(templates_dir, "payment.html")
        if os.path.exists(payment_html_path):
            return FileResponse(payment_html_path, media_type="text/html")
        else:
            return {"error": "Payment page not found"}

@app.get("/screen/success")
async def screen_success_page():
    """Специальная страница успеха для экрана (новая версия)"""
    screen_success_path = os.path.join(templates_dir, "screen_success.html")
    if os.path.exists(screen_success_path):
        return FileResponse(screen_success_path, media_type="text/html")
    else:
        success_html_path = os.path.join(templates_dir, "payment_success.html")
        if os.path.exists(success_html_path):
            return FileResponse(success_html_path, media_type="text/html")
        else:
            return {"error": "Success page not found"}

@app.get("/health")
async def health_check():
    """Быстрая проверка здоровья системы с QR-интеграцией"""
    return {
        "status": "healthy",
        "version": "2.5",
        "timestamp": "2025-09-04T12:00:00+06:00",
        "qr_payment": {
            "enabled": BAKAI_CONFIG["enable_payment_flow"],
            "api_configured": bool(BAKAI_CONFIG["token"] and BAKAI_CONFIG["merchant_account"]),
            "bakai_api": BAKAI_CONFIG["api_base_url"]
        },
        "cameras": {
            "entry": PARKING_CONFIG["entry_camera_ip"],
            "exit": PARKING_CONFIG["exit_camera_ip"] + " (QR-enabled)"
        }
    }

def create_default_idle_page():
    """Создает простую заставку если файл не найден"""
    idle_html = """<!DOCTYPE html>
<html lang="ru">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Smart Parking System</title>
    <style>
        body {
            margin: 0;
            padding: 0;
            background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
            height: 100vh;
            display: flex;
            justify-content: center;
            align-items: center;
            font-family: Arial, sans-serif;
            color: white;
            text-align: center;
        }
        .container {
            background: rgba(255, 255, 255, 0.1);
            padding: 40px;
            border-radius: 20px;
            backdrop-filter: blur(10px);
            box-shadow: 0 15px 35px rgba(0, 0, 0, 0.2);
        }
        h1 {
            font-size: 48px;
            margin-bottom: 20px;
            text-shadow: 2px 2px 4px rgba(0, 0, 0, 0.3);
        }
        .logo {
            font-size: 80px;
            margin-bottom: 30px;
            animation: pulse 2s infinite;
        }
        @keyframes pulse {
            0% { transform: scale(1); }
            50% { transform: scale(1.1); }
            100% { transform: scale(1); }
        }
        .status {
            font-size: 18px;
            margin-top: 20px;
            opacity: 0.8;
        }
    </style>
</head>
<body>
    <div class="container">
        <div class="logo">🚗🅿️</div>
        <h1>Smart Parking System</h1>
        <p>Система автоматической парковки с QR-оплатой</p>
        <p>Версия 2.5</p>
        <div class="status">Система активна и готова к работе</div>
    </div>
</body>
</html>"""
    
    temp_path = os.path.join(templates_dir, "idle_default.html")
    with open(temp_path, 'w', encoding='utf-8') as f:
        f.write(idle_html)
    
    return temp_path
