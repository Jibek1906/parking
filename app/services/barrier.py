"""
Модуль управления шлагбаумом
"""
import requests
from requests.auth import HTTPDigestAuth
from ..config import BARRIER_CONFIG, PARKING_CONFIG


def open_barrier(camera_ip: str) -> bool:
    """Открывает шлагбаум для указанной камеры"""
    try:
        barrier_config = None
        if camera_ip == PARKING_CONFIG["entry_camera_ip"]:
            barrier_config = BARRIER_CONFIG["entry_barrier"]
        elif camera_ip == PARKING_CONFIG["exit_camera_ip"]:
            barrier_config = BARRIER_CONFIG["exit_barrier"]
        else:
            print(f"⚠️ No barrier configuration for camera {camera_ip}")
            return False
       
        IP = barrier_config["ip"]
        PORT = barrier_config["port"]
        USER = barrier_config["user"]
        PASS = barrier_config["password"]
        CHANNEL = barrier_config["channel"]
       
        URL = f"http://{IP}:{PORT}/ISAPI/Parking/channels/{CHANNEL}/barrierGate"
        AUTH = HTTPDigestAuth(USER, PASS)
        HEADERS = {"Content-Type": "application/xml"}
       
        xml_data = '''<?xml version="1.0" encoding="utf-8"?>
<BarrierGate><ctrlMode>open</ctrlMode></BarrierGate>'''
       
        print(f"🔄 Открываем шлагбаум для камеры {camera_ip}...")
       
        response = requests.put(
            URL,
            auth=AUTH,
            headers=HEADERS,
            data=xml_data.encode('utf-8'),
            timeout=10
        )
       
        print(f"📊 Код ответа: {response.status_code}")
        print(f"📝 Ответ: {response.text}")
       
        if response.status_code == 200:
            print(f"✅ Шлагбаум для камеры {camera_ip} успешно открыт!")
            return True
        elif response.status_code == 403:
            print("⚠️ Ошибка авторизации - проверьте логин/пароль")
        else:
            print(f"⚠️ Неожиданный код: {response.status_code}")
                   
        return False
           
    except Exception as e:
        print(f"❌ Ошибка открытия шлагбаума для {camera_ip}: {e}")
        return False