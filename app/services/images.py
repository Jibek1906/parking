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
    """[DISABLED] Downloading images from cameras is disabled."""
    print(f"[DISABLED] download_image_from_camera called for {camera_ip}, skipping download.")
    return None, None

def save_image_to_disk(image_data, event_id, camera_ip, plate, event_type, picture_url=None):
    """[DISABLED] Saving images to disk is disabled."""
    print(f"[DISABLED] save_image_to_disk called for {camera_ip}, skipping save.")
    return None, None, 0

def process_alarm_image(event_id, camera_ip, picture_url, plate, event_type):
    """[DISABLED] Alarm image processing is disabled."""
    print(f"[DISABLED] process_alarm_image called for event {event_id}, skipping all image processing.")
    return {"success": False, "disabled": True, "reason": "photo download disabled"}
