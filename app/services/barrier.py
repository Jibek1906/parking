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

        try:
            response = requests.put(
                URL,
                auth=AUTH,
                headers=HEADERS,
                data=xml_data.encode('utf-8'),
                timeout=10
            )
        except requests.exceptions.Timeout:
            print(f"⏱️ Таймаут: шлагбаум {camera_ip} не отвечает (timeout)")
            return False
        except requests.exceptions.ConnectionError:
            print(f"🌐 Нет соединения: шлагбаум {camera_ip} физически недоступен (connection error)")
            return False
        except Exception as e:
            print(f"❌ Ошибка сети при открытии шлагбаума {camera_ip}: {e}")
            return False

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

def close_barrier(camera_ip: str) -> bool:
    """Закрывает шлагбаум для указанной камеры"""
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
<BarrierGate><ctrlMode>close</ctrlMode></BarrierGate>'''

        print(f"🔄 Закрываем шлагбаум для камеры {camera_ip}...")

        try:
            response = requests.put(
                URL,
                auth=AUTH,
                headers=HEADERS,
                data=xml_data.encode('utf-8'),
                timeout=10
            )
        except requests.exceptions.Timeout:
            print(f"⏱️ Таймаут: шлагбаум {camera_ip} не отвечает (timeout)")
            return False
        except requests.exceptions.ConnectionError:
            print(f"🌐 Нет соединения: шлагбаум {camera_ip} физически недоступен (connection error)")
            return False
        except Exception as e:
            print(f"❌ Ошибка сети при закрытии шлагбаума {camera_ip}: {e}")
            return False

        print(f"📊 Код ответа: {response.status_code}")
        print(f"📝 Ответ: {response.text}")

        if response.status_code == 200:
            print(f"✅ Шлагбаум для камеры {camera_ip} успешно закрыт!")
            return True
        elif response.status_code == 403:
            print("⚠️ Ошибка авторизации - проверьте логин/пароль")
        else:
            print(f"⚠️ Неожиданный код: {response.status_code}")

        return False

    except Exception as e:
        print(f"❌ Ошибка закрытия шлагбаума для {camera_ip}: {e}")
        return False

def get_barrier_state(camera_ip: str) -> str:
    """Получает состояние шлагбаума для указанной камеры"""
    try:
        barrier_config = None
        if camera_ip == PARKING_CONFIG["entry_camera_ip"]:
            barrier_config = BARRIER_CONFIG["entry_barrier"]
        elif camera_ip == PARKING_CONFIG["exit_camera_ip"]:
            barrier_config = BARRIER_CONFIG["exit_barrier"]
        else:
            print(f"⚠️ No barrier configuration for camera {camera_ip}")
            return "unknown"

        IP = barrier_config["ip"]
        PORT = barrier_config["port"]
        USER = barrier_config["user"]
        PASS = barrier_config["password"]
        CHANNEL = barrier_config["channel"]

        URL = f"http://{IP}:{PORT}/ISAPI/Parking/channels/{CHANNEL}/barrierGate/status"
        AUTH = HTTPDigestAuth(USER, PASS)

        print(f"🔄 Получаем состояние шлагбаума для камеры {camera_ip}...")

        try:
            response = requests.get(
                URL,
                auth=AUTH,
                timeout=10
            )
        except requests.exceptions.Timeout:
            print(f"⏱️ Таймаут: шлагбаум {camera_ip} не отвечает (timeout)")
            return "timeout"
        except requests.exceptions.ConnectionError:
            print(f"🌐 Нет соединения: шлагбаум {camera_ip} физически недоступен (connection error)")
            return "connection_error"
        except Exception as e:
            print(f"❌ Ошибка сети при получении состояния шлагбаума {camera_ip}: {e}")
            return "error"

        print(f"📊 Код ответа: {response.status_code}")
        print(f"📝 Ответ: {response.text}")

        if response.status_code == 200:
            import xml.etree.ElementTree as ET
            try:
                root = ET.fromstring(response.text)
                state = root.findtext("barrierState")
                print(f"✅ Состояние шлагбаума: {state}")
                return state if state else "unknown"
            except Exception as e:
                print(f"❌ Ошибка парсинга XML: {e}")
                return "parse_error"
        elif response.status_code == 403:
            print("⚠️ Ошибка авторизации - проверьте логин/пароль")
            return "auth_error"
        else:
            print(f"⚠️ Неожиданный код: {response.status_code}")
            return "unexpected_code"

    except Exception as e:
        print(f"❌ Ошибка получения состояния шлагбаума для {camera_ip}: {e}")
        return "error"
