"""
Сервис отложенной обработки изображений
Для снижения нагрузки на основной поток обработки событий
"""
import asyncio
import logging
from datetime import datetime, timedelta
from ..config import KYRGYZSTAN_TZ
from ..db import get_db_connection
from ..services.images import download_image_from_camera, save_image_to_disk
from ..models import save_image_record

logger = logging.getLogger(__name__)

class ImageProcessorService:
    def __init__(self):
        self.is_running = False
        self.queue = asyncio.Queue()
        
    async def start_image_processor_task(self):
        """Запуск фоновой задачи обработки изображений"""
        self.is_running = True
        logger.info("📸 Starting delayed image processor...")
        
        try:
            while self.is_running:
                try:
                    await self.process_pending_images()
                    await asyncio.sleep(30)
                    
                except asyncio.CancelledError:
                    logger.info("📸 Image processor task cancelled")
                    break
                except Exception as e:
                    logger.error(f"📸 Error in image processor: {e}")
                    await asyncio.sleep(60)
                    
        except asyncio.CancelledError:
            logger.info("📸 Image processor shutting down")
        finally:
            self.is_running = False

    async def process_pending_images(self):
        """Обработка изображений, которые не удалось скачать сразу"""
        conn = get_db_connection()
        cur = conn.cursor()
        
        try:
            cutoff_time = datetime.now(KYRGYZSTAN_TZ) - timedelta(hours=2)
            
            cur.execute("""
                SELECT ai.id, ai.event_id, ai.camera_ip, ai.plate_number, 
                       ai.image_url, c.event_type, ai.created_at
                FROM alarm_images ai
                JOIN camera c ON ai.event_id = c.id
                WHERE ai.download_success = false
                AND ai.created_at > %s
                AND (ai.error_message NOT LIKE '%404%' OR ai.error_message IS NULL)
                ORDER BY ai.created_at DESC
                LIMIT 10
            """, (cutoff_time,))
            
            pending_images = cur.fetchall()
            
            if pending_images:
                logger.info(f"📸 Found {len(pending_images)} pending images to retry")
                
                for image_record in pending_images:
                    (image_id, event_id, camera_ip, plate, image_url, 
                     event_type, created_at) = image_record
                    
                    logger.info(f"📸 Retrying image download for event {event_id}")

                    image_data, actual_url = download_image_from_camera(image_url or "", camera_ip)
                    
                    if image_data:
                        filename, filepath, file_size = save_image_to_disk(
                            image_data, event_id, camera_ip, plate, event_type or "ANPR"
                        )
                        
                        if filename:
                            cur.execute("""
                                UPDATE alarm_images
                                SET image_filename = %s, image_path = %s, image_size = %s,
                                    download_success = true, error_message = null,
                                    image_url = %s
                                WHERE id = %s
                            """, (filename, filepath, file_size, actual_url, image_id))
                            
                            logger.info(f"✅ Successfully downloaded delayed image for event {event_id}")
                        else:
                            cur.execute("""
                                UPDATE alarm_images 
                                SET error_message = 'Failed to save to disk after retry'
                                WHERE id = %s
                            """, (image_id,))
                    else:
                        cur.execute("""
                            UPDATE alarm_images 
                            SET error_message = COALESCE(error_message, '') || ' | Retry failed'
                            WHERE id = %s
                        """, (image_id,))

                    await asyncio.sleep(2)
                
                conn.commit()
            
        except Exception as e:
            conn.rollback()
            logger.error(f"📸 Error processing pending images: {e}")
        finally:
            cur.close()
            conn.close()

    async def cleanup_old_failed_images(self):
        """Очистка старых неуспешных записей"""
        conn = get_db_connection()
        cur = conn.cursor()
        
        try:
            cutoff_time = datetime.now(KYRGYZSTAN_TZ) - timedelta(hours=24)
            
            cur.execute("""
                DELETE FROM alarm_images
                WHERE download_success = false
                AND created_at < %s
            """, (cutoff_time,))
            
            deleted_count = cur.rowcount
            conn.commit()
            
            if deleted_count > 0:
                logger.info(f"📸 Cleaned up {deleted_count} old failed image records")
                
        except Exception as e:
            conn.rollback()
            logger.error(f"📸 Error cleaning up old images: {e}")
        finally:
            cur.close()
            conn.close()

image_processor = ImageProcessorService()

async def start_image_processor_task():
    """Функция для запуска из main.py"""
    await image_processor.start_image_processor_task()