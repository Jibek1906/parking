"""
Модуль для работы с Bakai OpenBanking API - генерация QR и проверка статуса
"""
import requests
import uuid
import logging
from datetime import datetime
from ..config import BAKAI_CONFIG
from ..db import get_db_connection

logger = logging.getLogger(__name__)

class BakaiPaymentService:
    def __init__(self):
        self.base_url = BAKAI_CONFIG["api_base_url"]
        self.token = BAKAI_CONFIG["token"]
        self.merchant_account = BAKAI_CONFIG["merchant_account"]
        self.timeout = BAKAI_CONFIG["timeout"]
    
    def generate_qr_code(self, amount: float, operation_id: str = None) -> dict:
        """
        Генерация QR кода для оплаты через Bakai OpenBanking
        
        Args:
            amount: Сумма к оплате
            operation_id: Уникальный ID операции (генерируется автоматически если None)
        
        Returns:
            dict: Результат генерации QR кода
        """
        if not operation_id:
            operation_id = str(uuid.uuid4())
        
        url = f"{self.base_url}/api/Qr/GenerateQR"
        
        payload = {
            "accountNo": self.merchant_account,
            "currencyId": 417,
            "amount": round(amount, 2),
            "operationID": operation_id
        }
        
        headers = {
            "Authorization": f"Bearer {self.token}",
            "Content-Type": "application/json"
        }
        
        try:
            logger.info(f"Generating QR code for amount: {amount}, operation: {operation_id}")
            
            response = requests.post(
                url, 
                json=payload, 
                headers=headers, 
                timeout=self.timeout
            )
            
            if response.status_code == 200:
                result = response.json()
                logger.info(f"QR code generated successfully: {operation_id}")
                return {
                    "success": True,
                    "operation_id": operation_id,
                    "qr_image": result.get("qrImage", ""),
                    "raw_response": result
                }
            else:
                error_msg = f"Bakai API error: {response.status_code} - {response.text}"
                logger.error(error_msg)
                return {
                    "success": False,
                    "error": error_msg,
                    "status_code": response.status_code
                }
                
        except requests.exceptions.Timeout:
            error_msg = "Bakai API timeout"
            logger.error(error_msg)
            return {"success": False, "error": error_msg}
        except requests.exceptions.RequestException as e:
            error_msg = f"Bakai API request error: {str(e)}"
            logger.error(error_msg)
            return {"success": False, "error": error_msg}
        except Exception as e:
            error_msg = f"Unexpected error in QR generation: {str(e)}"
            logger.error(error_msg)
            return {"success": False, "error": error_msg}
    
    def check_payment_status(self, operation_id: str) -> dict:
        """
        Проверка статуса оплаты по operation_id
        
        Args:
            operation_id: ID операции для проверки статуса
        
        Returns:
            dict: Статус оплаты
        """
        url = f"{self.base_url}/api/Qr/GetStatus"
        
        payload = {
            "operationID": operation_id
        }
        
        headers = {
            "Authorization": f"Bearer {self.token}",
            "Content-Type": "application/json"
        }
        
        try:
            logger.info(f"Checking payment status for operation: {operation_id}")
            
            response = requests.post(
                url, 
                json=payload, 
                headers=headers, 
                timeout=self.timeout
            )
            
            if response.status_code == 200:
                result = response.json()
                status = result.get("status", "").lower()
                
                logger.info(f"Payment status for {operation_id}: {status}")
                
                return {
                    "success": True,
                    "operation_id": operation_id,
                    "status": status,
                    "paid": status == "paid",
                    "raw_response": result
                }
            else:
                error_msg = f"Bakai status check error: {response.status_code} - {response.text}"
                logger.error(error_msg)
                return {
                    "success": False,
                    "error": error_msg,
                    "status_code": response.status_code
                }
                
        except requests.exceptions.Timeout:
            error_msg = "Bakai status check timeout"
            logger.error(error_msg)
            return {"success": False, "error": error_msg}
        except requests.exceptions.RequestException as e:
            error_msg = f"Bakai status check request error: {str(e)}"
            logger.error(error_msg)
            return {"success": False, "error": error_msg}
        except Exception as e:
            error_msg = f"Unexpected error in status check: {str(e)}"
            logger.error(error_msg)
            return {"success": False, "error": error_msg}

bakai_service = BakaiPaymentService()