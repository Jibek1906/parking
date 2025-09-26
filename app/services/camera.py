"""
Модуль работы с событиями камер и распознавания номеров
"""
import re
import hashlib
from datetime import datetime, timedelta
from ..config import KYRGYZSTAN_TZ, PARKING_CONFIG
from ..db import get_db_connection

recent_events_cache = {}


def is_duplicate_event(camera_ip: str, plate: str, raw_event: str) -> bool:
    """Проверяет, является ли событие дубликатом"""
    try:
        event_content = f"{camera_ip}_{plate}_{raw_event[:500]}"
        event_hash = hashlib.md5(event_content.encode()).hexdigest()
       
        current_time = datetime.now(KYRGYZSTAN_TZ)

        cache_key = f"{camera_ip}_{plate}"
        if cache_key in recent_events_cache:
            last_time = recent_events_cache[cache_key]
            if (current_time - last_time).total_seconds() < PARKING_CONFIG["min_detection_interval_seconds"]:
                print(f"⚠️ Duplicate event detected in cache for {camera_ip} plate {plate}")
                return True
       
        recent_events_cache[cache_key] = current_time

        conn = get_db_connection()
        cur = conn.cursor()

        cur.execute("""
            SELECT id FROM camera_events_log
            WHERE camera_ip = %s
            AND event_hash = %s
            AND event_time > %s
            LIMIT 1
        """, (camera_ip, event_hash, current_time - timedelta(seconds=30)))
       
        if cur.fetchone():
            print(f"⚠️ Duplicate event detected in DB for {camera_ip}")
            cur.close()
            conn.close()
            return True

        cur.execute("""
            INSERT INTO camera_events_log (camera_ip, event_hash, event_time, plate_number)
            VALUES (%s, %s, %s, %s)
        """, (camera_ip, event_hash, current_time, plate))
       
        conn.commit()
        cur.close()
        conn.close()
       
        return False
       
    except Exception as e:
        print(f"❌ Error checking duplicate event: {e}")
        return False


def is_valid_plate(plate: str) -> bool:
    """
    Более гибкая проверка валидности номера:
    - Разрешает номера с >=2 уникальными символами
    - Разрешает только буквы или только цифры если длина >= 6
    - По-прежнему блокирует подозрительные паттерны
    """
    if not plate or len(plate) < PARKING_CONFIG["min_plate_length"] or len(plate) > 12:
        return False

    suspicious = ['0000', '1111', '2222', 'AAAA', 'BBBB', 'XXXX', 'TEST', '00000', '11111']
    if any(sus in plate for sus in suspicious):
        return False

    unique_chars = set(plate)
    if len(unique_chars) < 2:
        return False

    has_letters = any(c.isalpha() for c in plate)
    has_digits = any(c.isdigit() for c in plate)

    if has_letters and has_digits:
        return True

    if (has_letters or has_digits) and len(plate) >= 6:
        return True

    return False


def find_plate_number(text):
    """
    Улучшенное распознавание номеров:
    - Возвращает лучший найденный номер даже если он не прошел строгую валидацию (для диагностики)
    - Логирует все кандидаты и причину отклонения
    """
    if not text:
        return ""
   
    print(f"🔍 Analyzing {len(text)} characters for plate numbers...")

    if len(text) > 1000:
        xml_parts = []
        json_parts = []

        xml_matches = re.finditer(r'<[^>]*plate[^>]*>.*?</[^>]*>', text, re.IGNORECASE | re.DOTALL)
        for match in xml_matches:
            xml_parts.append(match.group())

        json_matches = re.finditer(r'"[^"]*plate[^"]*"\s*:\s*"[^"]*"', text, re.IGNORECASE)
        for match in json_matches:
            json_parts.append(match.group())
       
        print(f"📋 Found {len(xml_parts)} XML plate sections, {len(json_parts)} JSON plate sections")

        analysis_text = " ".join(xml_parts + json_parts)
        if len(analysis_text) < 100:
            analysis_text = text[:2000]
    else:
        analysis_text = text

    plate_patterns = [
        (r'<plateNumber[^>]*>\s*([A-Z0-9]+)\s*</plateNumber>', 100),
        (r'<plateNo[^>]*>\s*([A-Z0-9]+)\s*</plateNo>', 95),
        (r'<licensePlate[^>]*>\s*([A-Z0-9]+)\s*</licensePlate>', 90),
        (r'<anprPlate[^>]*>\s*([A-Z0-9]+)\s*</anprPlate>', 85),

        (r'"plateNumber"\s*:\s*"([A-Z0-9]+)"', 80),
        (r'"plateNo"\s*:\s*"([A-Z0-9]+)"', 75),
        (r'"plate"\s*:\s*"([A-Z0-9]+)"', 70),
        (r'"licensePlate"\s*:\s*"([A-Z0-9]+)"', 65),

        (r'\b([0-9]{5}[A-Z]{1,3})\b', 90),
        (r'\b([0-9]{2}[A-Z]{3}[0-9]{2})\b', 85),
        (r'\b([0-9]{2}KG[0-9]{3}[A-Z]{3})\b', 80),
        (r'\b(T[0-9]{4}[A-Z]{2})\b', 75),
        (r'\b([CD|MO][0-9]{3,4})\b', 70),

        (r'\b([A-Z]{1,2}[0-9]{3,4}[A-Z]{1,3})\b', 60),
        (r'\b([0-9]{2,3}[A-Z]{2,3}[0-9]{2,3})\b', 55),
       
        (r'PlateResult[^>]*>([A-Z0-9]{4,10})<', 85),
        (r'RecognitionResult[^>]*>([A-Z0-9]{4,10})<', 80),
        (r'VehiclePlate[^>]*>([A-Z0-9]{4,10})<', 75),
        (r'"result"\s*:\s*"([A-Z0-9]{4,10})"', 70),
        (r'<result[^>]*>([A-Z0-9]{4,10})</result>', 75),
       
        (r'plate[^>]*=[\'"]*([A-Z0-9]{5,10})[\'"]*', 40),
        (r'number[^>]*=[\'"]*([A-Z0-9]{5,10})[\'"]*', 35),
        (r'Plate[:\s]*([A-Z0-9]{5,10})', 30),
        (r'License[:\s]*([A-Z0-9]{5,10})', 25),
    ]

    found_candidates = []
    all_candidates = []

    for i, (pattern, priority) in enumerate(plate_patterns):
        try:
            matches = re.findall(pattern, analysis_text, re.IGNORECASE | re.MULTILINE)
            for match in matches:
                if isinstance(match, tuple):
                    match = match[0] if match[0] else ""
               
                if match and len(match.strip()) >= PARKING_CONFIG["min_plate_length"]:
                    plate = match.strip().upper()
                    plate = ''.join(c for c in plate if c.isalnum())
                    all_candidates.append(plate)
                    if is_valid_plate(plate):
                        bonus = get_plate_format_bonus(plate)
                        final_score = priority + bonus
                        found_candidates.append((plate, final_score, i+1))
                        print(f"🎯 Pattern {i+1} found: '{plate}' (score: {final_score})")
                    else:
                        print(f"⚠️ Pattern {i+1} candidate rejected: '{plate}' (not valid by rules)")
        except Exception as e:
            print(f"⚠️ Pattern {i+1} error: {e}")
            continue

    if found_candidates:
        unique_candidates = {}
        for plate, score, pattern_num in found_candidates:
            if plate not in unique_candidates or unique_candidates[plate][1] < score:
                unique_candidates[plate] = (plate, score, pattern_num)

        sorted_candidates = sorted(unique_candidates.values(), key=lambda x: x[1], reverse=True)
        best_plate = sorted_candidates[0][0]
       
        print(f"✅ BEST PLATE: '{best_plate}' (score: {sorted_candidates[0][1]}, from {len(found_candidates)} total matches)")

        if len(sorted_candidates) > 1:
            alternatives = [f"'{cand[0]}'({cand[1]})" for cand in sorted_candidates[1:3]]
            print(f"🔄 Alternatives: {', '.join(alternatives)}")
       
        return best_plate

    if all_candidates:
        print(f"❗ No valid plate, but found candidates: {all_candidates}")
        return all_candidates[0]

    print("❌ No plate number found at all")
    return ""


def get_plate_format_bonus(plate: str) -> int:
    """Дает бонусные баллы за соответствие кыргызским форматам"""
    bonus = 0
   
    if re.match(r'^[0-9]{5}[A-Z]{1,3}$', plate):  # 01008ABM
        bonus += 50
    elif re.match(r'^[0-9]{2}[A-Z]{3}[0-9]{2}$', plate):  # 01ABC23
        bonus += 45
    elif re.match(r'^[0-9]{2}KG[0-9]{3}[A-Z]{3}$', plate):  # 01KG123ABC
        bonus += 40
    elif re.match(r'^T[0-9]{4}[A-Z]{2}$', plate):  # T1234AB
        bonus += 35
    elif re.match(r'^[CD|MO][0-9]{3,4}$', plate):  # CD1234
        bonus += 30
    elif re.match(r'^[A-Z]{1,2}[0-9]{3,4}[A-Z]{1,3}$', plate):  # B123ABC
        bonus += 20

    if 6 <= len(plate) <= 8:
        bonus += 10
    elif len(plate) == 5:
        bonus += 5
   
    return bonus


def find_event_type(text):
    """Ищет тип события"""
    if not text:
        return ""
   
    patterns = [
        r'<eventType[^>]*>([^<]+)</eventType>',
        r'"eventType"\s*:\s*"([^"]+)"',
        r'eventType["\s]*[:=]["\s]*["\']?([^"\'<>\s,]+)["\']?'
    ]
   
    for pattern in patterns:
        match = re.search(pattern, text, re.IGNORECASE)
        if match:
            return match.group(1).strip()
   
    if "ANPR" in text or "anpr" in text.lower():
        return "ANPR"
   
    return ""


def find_picture_url(text):
    """Поиск URL изображения - ускоренная версия"""
    if not text:
        return ""
   
    patterns = [
        r'<pictureURL[^>]*>([^<]+)</pictureURL>',
        r'"pictureURL"\s*:\s*"([^"]+)"',
        r'<filename[^>]*>([^<]+)</filename>',
        r'"filename"\s*:\s*"([^"]+)"',
        r'<picture[^>]*>([^<]+)</picture>',
        r'"picture"\s*:\s*"([^"]+)"',
        r'<image[^>]*>([^<]+)</image>',
        r'"image"\s*:\s*"([^"]+)"',
        r'<imageURL[^>]*>([^<]+)</imageURL>',
        r'"imageURL"\s*:\s*"([^"]+)"',
        r'<snapShotURL[^>]*>([^<]+)</snapShotURL>',
        r'"snapShotURL"\s*:\s*"([^"]+)"',
    ]
   
    for pattern in patterns:
        match = re.search(pattern, text, re.IGNORECASE)
        if match:
            url = match.group(1).strip()
            print(f"🖼️ Found picture URL: {url}")
            return url
   
    return ""
