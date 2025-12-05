# ============================================
# Rakip İçerik İstihbarat Sistemi V2
# Deepseek AI Servisi (RapidAPI)
# ============================================

import httpx
import json
from typing import Optional, List

from config import settings
from core.database import SessionLocal, get_setting


class DeepseekService:
    """
    Deepseek AI servisi (RapidAPI üzerinden).
    Entity çıkarma ve içerik analizi için kullanılır.
    """

    BASE_URL = "https://deepseek-all-in-one.p.rapidapi.com"

    def __init__(self):
        self._api_key: Optional[str] = None
        self._host: Optional[str] = None

    async def _get_credentials(self) -> tuple:
        """API kimlik bilgilerini al"""
        if self._api_key and self._host:
            return self._api_key, self._host

        db = SessionLocal()
        try:
            api_key = get_setting(db, "DEEPSEEK_API_KEY")
            host = get_setting(db, "DEEPSEEK_HOST")

            self._api_key = api_key or settings.DEEPSEEK_API_KEY
            self._host = host or settings.DEEPSEEK_HOST

            return self._api_key, self._host
        finally:
            db.close()

    def clear_cache(self):
        """Credential cache'ini temizle"""
        self._api_key = None
        self._host = None

    async def extract_entities(self, text: str, log_callback=None) -> List[str]:
        """
        Metinden entity'leri çıkar (tek kelimeler olarak)

        Args:
            text: Analiz edilecek metin (meta title, description, url)
            log_callback: Log mesajı göndermek için callback fonksiyonu (opsiyonel)

        Returns:
            Entity kelimeleri listesi
        """
        api_key, host = await self._get_credentials()

        if not api_key:
            raise ValueError("Deepseek API key ayarlanmamış!")

        # Prompt hazırlama
        system_prompt = "SEO Entity Analyser"
        user_prompt = f"""Just list entities from the content below. Do not do any explanation, just list entity words separated by commas.

IMPORTANT:
- Extract only important entities like: people, places, organizations, products, concepts
- Medical terms, treatment methods, procedures (example: dental, dentistry, implant, cosmetic, treatment, surgery)
- Sector terms (example: dental, medical, healthcare, cosmetic)
- Services and applications (example: full mouth, smile design, teeth whitening, veneer)
- Technical terms and concepts
- Return entities as single words
- Only output comma-separated words, no other text

Content to analyze:
{text}

Output only: word1,word2,word3"""

        # Deepseek'e giden paketi log'a yazdır
        if log_callback:
            log_callback("info", f"🔵 Deepseek'e gönderilen paket:\n{user_prompt[:500]}...")

        try:
            url = f"{self.BASE_URL}/chat"
            headers = {
                "x-rapidapi-key": api_key,
                "x-rapidapi-host": host,
                "Content-Type": "application/json"
            }
            payload = {
                "messages": [
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt}
                ]
            }

            async with httpx.AsyncClient() as client:
                response = await client.post(
                    url,
                    headers=headers,
                    json=payload,
                    timeout=30.0
                )
                response.raise_for_status()
                data = response.json()

            # Deepseek yanıtını parse et
            # Beklenen format: {"choices": [{"message": {"content": "word1,word2,word3"}}]}
            if "choices" in data and len(data["choices"]) > 0:
                message = data["choices"][0].get("message", {})
                content = message.get("content", "").strip()

                if log_callback:
                    log_callback("info", f"🟢 Deepseek yanıtı: {content[:200]}...")

                # Virgülle ayrılmış entity'leri parse et
                entities_set = set()

                # Satırları kontrol et
                lines = [l.strip() for l in content.split("\n") if l.strip()]

                for line in lines:
                    # Her satırdaki virgülle ayrılmış kelimeleri al
                    for raw_word in line.split(","):
                        word = raw_word.strip().lower().strip(".,!?;:()[]{}\"'""")
                        if word and len(word) >= 2:
                            # Sayı değilse ekle
                            if not word.isdigit():
                                entities_set.add(word)

                return list(entities_set)

            return []

        except httpx.HTTPStatusError as e:
            error_msg = f"Deepseek API Hatası: {e.response.status_code}"
            if log_callback:
                log_callback("error", error_msg)
            print(f"❌ {error_msg}")
            print(f"Response: {e.response.text}")
            return []
        except Exception as e:
            error_msg = f"Deepseek Entity Extraction Hatası: {e}"
            if log_callback:
                log_callback("error", error_msg)
            print(f"⚠️ {error_msg}")
            return []

    async def chat(self, messages: List[dict], max_tokens: int = 1024) -> str:
        """
        Deepseek ile sohbet et.

        Args:
            messages: Mesaj listesi [{"role": "system/user/assistant", "content": "..."}]
            max_tokens: Maksimum token sayısı (kullanılmıyor, Deepseek otomatik belirliyor)

        Returns:
            AI yanıtı
        """
        api_key, host = await self._get_credentials()

        if not api_key:
            raise ValueError("Deepseek API key ayarlanmamış!")

        url = f"{self.BASE_URL}/chat"

        headers = {
            "x-rapidapi-key": api_key,
            "x-rapidapi-host": host,
            "Content-Type": "application/json"
        }
        payload = {
            "messages": messages
        }

        try:
            async with httpx.AsyncClient() as client:
                response = await client.post(
                    url,
                    headers=headers,
                    json=payload,
                    timeout=60.0
                )
                response.raise_for_status()
                data = response.json()

            # Yanıtı parse et
            if "choices" in data and len(data["choices"]) > 0:
                message = data["choices"][0].get("message", {})
                content = message.get("content", "")
                if content:
                    return content
                else:
                    print(f"⚠️ Deepseek: Yanıt içinde content bulunamadı. Message: {message}")
                    return ""
            else:
                # Hata mesajı kontrolü
                if "error" in data:
                    error_msg = data["error"].get("message", "Bilinmeyen hata")
                    print(f"❌ Deepseek API Hatası: {error_msg}")
                    raise ValueError(f"Deepseek API Hatası: {error_msg}")
                print(f"⚠️ Deepseek: Yanıtta choices bulunamadı. Response: {data}")

            return ""

        except httpx.HTTPStatusError as e:
            print(f"❌ Deepseek API Hatası: {e.response.status_code}")
            raise
        except Exception as e:
            print(f"❌ Deepseek Hatası: {e}")
            raise


# Global service instance
deepseek_ai = DeepseekService()
