"""
Модуль скачивания и сохранения фото
"""
import os
import re
import requests
from requests.auth import HTTPDigestAuth
from datetime import datetime
from ..config import CAMERA_CONFIG
from ..models import save_image_record

def init_images_directory():
    """Создает директорию для изображений если её нет"""
    os.makedirs(CAMERA_CONFIG["images_dir"], exist_ok=True)
    print(f"✅ Images directory initialized: {CAMERA_CONFIG['images_dir']}")

def download_image_from_camera(picture_url, camera_ip):
    """Ускоренное скачивание изображений с меньшим количеством попыток"""
    try:
        print(f"🔄 Attempting to download image from camera {camera_ip}: {picture_url}")

        urls_to_try = []
        
        if picture_url and picture_url.startswith("http"):
            urls_to_try.append(picture_url)
        elif picture_url:
            urls_to_try.extend([
                f"http://{camera_ip}/{picture_url}",
                f"http://{camera_ip}/ISAPI/Streaming/channels/1/picture?{picture_url}",
                f"http://{camera_ip}/ISAPI/Streaming/channels/101/picture?{picture_url}",
            ])
        urls_to_try.extend([
            f"http://{camera_ip}/ISAPI/Streaming/channels/1/picture",
            f"http://{camera_ip}/ISAPI/Streaming/channels/101/picture",
            f"http://{camera_ip}/cgi-bin/snapshot.cgi",
            f"http://{camera_ip}/snapshot.jpg",
        ])
        
        auth = HTTPDigestAuth(CAMERA_CONFIG["username"], CAMERA_CONFIG["password"])
        
        for attempt, url in enumerate(urls_to_try[:6], 1):
            try:
                print(f"📡 Try {attempt}: {url}")
                
                response = requests.get(
                    url,
                    auth=auth,
                    timeout=CAMERA_CONFIG["timeout"],
                    stream=True,
                    verify=False,
                    headers={'User-Agent': 'Mozilla/5.0', 'Accept': 'image/*,*/*'}
                )
                
                if response.status_code == 200:
                    content_type = response.headers.get('content-type', '').lower()
                    
                    if 'image' in content_type or 'jpeg' in content_type or 'jpg' in content_type:
                        image_data = response.content
                        if len(image_data) > 500:
                            print(f"✅ Image downloaded successfully: {len(image_data)} bytes")
                            return image_data, url
                    else:
                        image_data = response.content
                        if len(image_data) > 500 and image_data[:4] == b'\xff\xd8\xff\xe0':
                            print(f"✅ JPEG image detected: {len(image_data)} bytes")
                            return image_data, url
                    
            except requests.exceptions.Timeout:
                print(f"⏱️ Timeout on attempt {attempt}")
                continue
            except requests.exceptions.RequestException as e:
                print(f"🌐 Network error on attempt {attempt}: {e}")
                continue
        
        print("❌ All download attempts failed")
        return None, None
        
    except Exception as e:
        print(f"💥 Download error: {e}")
        return None, None

def save_image_to_disk(image_data, event_id, camera_ip, plate, event_type):
    """Сохранить изображение на диск"""
    try:
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        safe_plate = re.sub(r'[^\w]', '', plate) if plate else "UNKNOWN"
        filename = f"{timestamp}_{camera_ip}_{safe_plate}_{event_type}_{event_id}.jpg"
        filepath = os.path.join(CAMERA_CONFIG["images_dir"], filename)
        
        with open(filepath, 'wb') as f:
            f.write(image_data)
        
        print(f"💾 Image saved to: {filepath}")
        return filename, filepath, len(image_data)
        
    except Exception as e:
        print(f"💥 Error saving image: {e}")
        return None, None, 0

def process_alarm_image(event_id, camera_ip, picture_url, plate, event_type):
    """Ускоренная обработка изображений с меньшим количеством попыток"""
    print(f"🖼️ Processing alarm image for event {event_id}")

    for attempt in range(1, 3):
        print(f"🔄 Image download attempt {attempt}/2")
        
        if not picture_url:
            image_data, actual_url = download_image_from_camera("", camera_ip)
        else:
            image_data, actual_url = download_image_from_camera(picture_url, camera_ip)
        
        if image_data:
            filename, filepath, file_size = save_image_to_disk(
                image_data, event_id, camera_ip, plate, event_type or "ANPR"
            )
            
            if filename:
                image_id = save_image_record(
                    event_id, camera_ip, plate, filename, filepath,
                    file_size, actual_url, True
                )
                
                return {
                    "success": True,
                    "image_id": image_id,
                    "filename": filename,
                    "size": file_size,
                    "url": actual_url,
                    "attempts": attempt
                }
        
        if attempt < 2:
            import time
            time.sleep(CAMERA_CONFIG['retry_delay_seconds'])
    
    save_image_record(
        event_id, camera_ip, plate, None, None,
        0, picture_url, False, f"Download failed after 2 attempts"
    )
    
    return {"success": False, "error": f"Failed to download image after 2 attempts"}