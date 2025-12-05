# ============================================
# OpenAI Service
# ============================================

import httpx
import json
from typing import Optional, Dict
from config import settings


class OpenAIService:
    """OpenAI API servisi"""
    
    BASE_URL = "https://api.openai.com/v1"
    
    def __init__(self):
        self.api_key = getattr(settings, 'OPENAI_API_KEY', None)
        if not self.api_key:
            # Ayarlardan al
            from core.database import SessionLocal, get_setting
            db = SessionLocal()
            try:
                self.api_key = get_setting(db, "OPENAI_API_KEY")
            finally:
                db.close()
    
    async def generate_text(self, prompt: str, model: str = "gpt-4o-mini", max_tokens: int = 2000) -> str:
        """
        OpenAI ile metin üret
        
        Args:
            prompt: Kullanıcı prompt'u
            model: Model adı (varsayılan: gpt-4o-mini)
            max_tokens: Maksimum token sayısı
        
        Returns:
            AI'dan gelen cevap
        """
        if not self.api_key:
            raise ValueError("OpenAI API key bulunamadı. Lütfen ayarlardan ekleyin.")
        
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json"
        }
        
        data = {
            "model": model,
            "messages": [
                {
                    "role": "system",
                    "content": "Sen bir SEO uzmanısın. Internal linking ve içerik optimizasyonu konusunda uzmanlaşmışsın."
                },
                {
                    "role": "user",
                    "content": prompt
                }
            ],
            "max_tokens": max_tokens,
            "temperature": 0.7
        }
        
        try:
            async with httpx.AsyncClient(timeout=60.0) as client:
                response = await client.post(
                    f"{self.BASE_URL}/chat/completions",
                    headers=headers,
                    json=data
                )
                
                if response.status_code == 200:
                    result = response.json()
                    return result["choices"][0]["message"]["content"]
                else:
                    error_msg = f"OpenAI API hatası: {response.status_code} - {response.text}"
                    raise Exception(error_msg)
        
        except httpx.TimeoutException:
            raise Exception("OpenAI API timeout hatası")
        except Exception as e:
            raise Exception(f"OpenAI API hatası: {str(e)}")

