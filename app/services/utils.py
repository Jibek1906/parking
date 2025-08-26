"""
Модуль вспомогательных функций (regex, форматирование времени)
"""
import re
from datetime import datetime
from typing import Optional

def clean_text_data(text: str) -> str:
    """Очищает текст от бинарных данных и проблемных символов"""
    if not text:
        return ""
    
    cleaned = text.replace('\x00', '').replace('\x01', '').replace('\x02', '')
    cleaned = ''.join(char for char in cleaned if ord(char) >= 32 or char in ['\n', '\r', '\t'])
    
    if len(cleaned) > 10000:
        cleaned = cleaned[:10000] + "... [truncated]"
    
    return cleaned

def format_timestamp(dt: datetime, format_str: str = "%Y-%m-%d %H:%M:%S") -> str:
    """Форматирует datetime в строку"""
    return dt.strftime(format_str)

def parse_timestamp(timestamp_str: str) -> Optional[datetime]:
    """Парсит строку в datetime"""
    try:
        return datetime.fromisoformat(timestamp_str)
    except ValueError:
        return None

def sanitize_filename(filename: str) -> str:
    """Очищает имя файла от недопустимых символов"""
    return re.sub(r'[^\w\-_.]', '_', filename)

def normalize_plate_number(plate: str) -> str:
    """Нормализует номерной знак (убирает пробелы, переводит в верхний регистр)"""
    if not plate:
        return ""
    return ''.join(c.upper() for c in plate if c.isalnum())

def extract_ip_from_request_info(client_host: str) -> str:
    """Извлекает IP адрес из информации о клиенте"""
    if not client_host:
        return "unknown"

    ip = client_host.split(':')[0]
    return ip

def calculate_hours_between(start_time: datetime, end_time: datetime) -> float:
    """Вычисляет количество часов между двумя датами"""
    duration = end_time - start_time
    return duration.total_seconds() / 3600

def is_night_time(hour: int) -> bool:
    """Проверяет, является ли час ночным временем"""
    return hour >= 22 or hour <= 6

def truncate_string(text: str, max_length: int = 100) -> str:
    """Обрезает строку до указанной длины с добавлением многоточия"""
    if len(text) <= max_length:
        return text
    return text[:max_length-3] + "..."