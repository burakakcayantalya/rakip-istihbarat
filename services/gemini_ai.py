# ============================================
# Rakip İçerik İstihbarat Sistemi V2
# Gemini AI Servisi
# ============================================

import httpx
from typing import Optional, Dict, List
import json

from config import settings
from core.database import SessionLocal, get_setting


class GeminiService:
    """
    Google Gemini AI servisi.
    İçerik analizi ve öneriler için yapay zeka kullanır.
    """
    
    BASE_URL = "https://generativelanguage.googleapis.com/v1beta/models"
    
    def __init__(self):
        self._api_key: Optional[str] = None
        self._model: Optional[str] = None
    
    async def _get_credentials(self) -> tuple:
        """API kimlik bilgilerini al"""
        if self._api_key and self._model:
            return self._api_key, self._model
        
        db = SessionLocal()
        try:
            api_key = get_setting(db, "GEMINI_API_KEY")
            model = get_setting(db, "GEMINI_MODEL")
            
            self._api_key = api_key or settings.GEMINI_API_KEY
            self._model = model or settings.GEMINI_MODEL
            
            return self._api_key, self._model
        finally:
            db.close()
    
    def clear_cache(self):
        """Credential cache'ini temizle"""
        self._api_key = None
        self._model = None
    
    async def extract_entities(self, text: str, log_callback=None) -> List[str]:
        """
        Metinden entity'leri çıkar (tek kelimeler olarak)
        
        Args:
            text: Analiz edilecek metin (meta title, description, url)
            log_callback: Log mesajı göndermek için callback fonksiyonu (opsiyonel)
        
        Returns:
            Entity kelimeleri listesi
        """
        api_key, model = await self._get_credentials()
        
        if not api_key:
            raise ValueError("Gemini API key ayarlanmamış!")
        
        prompt = f"""Aşağıdaki metinden tüm önemli entity'leri çıkar. Entity'ler şunlar olabilir:
- Kişiler, yerler, kurumlar, ürünler, konseptler
- Tıbbi terimler, tedavi yöntemleri, prosedürler (örnek: dental, dentistry, implant, cosmetic, treatment, surgery, procedure)
- Sektör terimleri (örnek: dental, medical, healthcare, cosmetic)
- Hizmetler ve uygulamalar (örnek: full mouth, smile design, teeth whitening, veneer)
- Teknik terimler ve kavramlar

ÖNEMLİ: Dental sektörü için özellikle dikkat et:
- "dental", "dentistry", "dentist", "tooth", "teeth", "implant", "implant", "cosmetic", "treatment", "surgery", "procedure"
- "full mouth", "smile design", "whitening", "veneers", "crown", "bridge", "orthodontics", "periodontics"
- "turkey", "istanbul", "antalya" gibi lokasyonlar
- "clinic", "hospital", "center" gibi kurumlar

ÇIKTI FORMATIN ÇOK NET OLMALI:
- Her entity'yi TEK KELİME olarak üret.
- Tüm entity kelimelerini TEK SATIRDA ver.
- Şu formatta cevap ver: 
  Bulunan Entityler kelime1,kelime2,kelime3
- "Bulunan Entityler" ifadesinden sonra sadece entity kelimeleri olmalı.
- Entity kelimeleri arasında sadece virgül kullan, ARAYA BOŞLUK KOYMA.
- Başka hiçbir açıklama, cümle veya satır yazma.

Analiz edilecek metin:
{text}

Şimdi sadece şu formatta cevap ver:
Bulunan Entityler kelime1,kelime2,kelime3"""
        
        # Gemini'ye giden paketi log'a yazdır
        if log_callback:
            log_callback("info", f"🔵 Gemini'ye gönderilen paket:\n{prompt[:500]}...")

        try:
            url = f"{self.BASE_URL}/{model}:generateContent"
            headers = {
                "Content-Type": "application/json"
            }
            params = {
                "key": api_key
            }
            payload = {
                "contents": [{
                    "parts": [{
                        "text": prompt
                    }]
                }],
                "generationConfig": {
                    "temperature": 0.3,
                    "maxOutputTokens": 500
                }
            }
            
            async with httpx.AsyncClient() as client:
                response = await client.post(
                    url,
                    headers=headers,
                    params=params,
                    json=payload,
                    timeout=30.0
                )
                response.raise_for_status()
                data = response.json()
            
            # Gemini'nin cevabını parse et
            if "candidates" in data and len(data["candidates"]) > 0:
                content = data["candidates"][0].get("content", {})
                parts = content.get("parts", [])
                if parts and "text" in parts[0]:
                    response_text = parts[0]["text"].strip()
                    
                    # Cevaptan entity listesi çıkar
                    #
                    # Beklenen format:
                    #   Bulunan Entityler kelime1,kelime2,kelime3
                    #
                    # 1) Önce bu satırı yakalamaya çalış
                    entities_set = set()
                    lines = [l.strip() for l in response_text.split("\n") if l.strip()]
                    
                    target_prefix = "bulunan entityler"
                    for line in lines:
                        lower = line.lower()
                        if lower.startswith(target_prefix):
                            # "Bulunan Entityler" ifadesinden sonrasını al
                            parts = line.split(" ", 2)
                            if len(parts) >= 3:
                                entity_part = parts[2]
                            elif len(parts) == 2:
                                entity_part = parts[1]
                            else:
                                continue
                            
                            for raw_word in entity_part.split(","):
                                word = raw_word.strip().lower().strip(".,!?;:()[]{}\"'“”")
                                if word and len(word) >= 2:
                                    entities_set.add(word)
                    
                    # Eğer yukarıdaki format bulunamazsa, eski fallback mantığı kullan
                    if not entities_set:
                        for line in lines:
                            line = line.lstrip("0123456789.-) ").strip()
                            if not line or len(line) < 2:
                                continue
                            
                            for raw_word in line.split():
                                word = raw_word.strip().lower().strip(".,!?;:()[]{}\"'“”")
                                if word and len(word) >= 2:
                                    entities_set.add(word)
                    
                    return list(entities_set)
            
            return []
        
        except httpx.HTTPStatusError as e:
            print(f"❌ Gemini API Hatası: {e.response.status_code}")
            print(f"Response: {e.response.text}")
            return []
        except Exception as e:
            print(f"⚠️ Gemini Entity Extraction Hatası: {e}")
            return []
    
    async def generate(self, prompt: str, max_tokens: int = 1024) -> str:
        """
        Gemini'den yanıt üret.
        
        Args:
            prompt: Giriş metni
            max_tokens: Maksimum token sayısı
        
        Returns:
            Üretilen yanıt
        """
        api_key, model = await self._get_credentials()
        
        if not api_key:
            raise ValueError("Gemini API key ayarlanmamış!")
        
        url = f"{self.BASE_URL}/{model}:generateContent?key={api_key}"
        
        payload = {
            "contents": [
                {
                    "parts": [
                        {"text": prompt}
                    ]
                }
            ],
            "generationConfig": {
                "maxOutputTokens": max_tokens,
                "temperature": 0.7
            }
        }
        
        try:
            async with httpx.AsyncClient() as client:
                response = await client.post(
                    url,
                    json=payload,
                    timeout=60.0
                )
                response.raise_for_status()
                data = response.json()
            
            # Yanıtı parse et
            if "candidates" in data and len(data["candidates"]) > 0:
                candidate = data["candidates"][0]
                
                # Safety rating kontrolü
                if "safetyRatings" in candidate:
                    blocked = any(rating.get("blocked", False) for rating in candidate["safetyRatings"])
                    if blocked:
                        print(f"⚠️ Gemini: İçerik güvenlik nedeniyle engellendi")
                        return ""
                
                if "content" in candidate and "parts" in candidate["content"]:
                    text = candidate["content"]["parts"][0].get("text", "")
                    if text:
                        return text
                    else:
                        print(f"⚠️ Gemini: Yanıt içinde text bulunamadı. Candidate: {candidate}")
                        return ""
            else:
                # Hata mesajı kontrolü
                if "error" in data:
                    error_msg = data["error"].get("message", "Bilinmeyen hata")
                    print(f"❌ Gemini API Hatası: {error_msg}")
                    raise ValueError(f"Gemini API Hatası: {error_msg}")
                print(f"⚠️ Gemini: Yanıtta candidates bulunamadı. Response: {data}")
            
            return ""
        
        except httpx.HTTPStatusError as e:
            print(f"❌ Gemini API Hatası: {e.response.status_code}")
            raise
        except Exception as e:
            print(f"❌ Gemini Hatası: {e}")
            raise
    
    async def analyze_content_change(
        self, 
        old_content: str, 
        new_content: str,
        url: str = ""
    ) -> Dict:
        """
        İçerik değişikliğini analiz et.
        
        Args:
            old_content: Eski içerik
            new_content: Yeni içerik
            url: Sayfa URL'i
        
        Returns:
            Analiz sonucu
        """
        prompt = f"""
        Aşağıdaki içerik değişikliğini analiz et ve Türkçe olarak özetle:
        
        URL: {url}
        
        ESKİ İÇERİK:
        {old_content[:2000]}
        
        YENİ İÇERİK:
        {new_content[:2000]}
        
        Lütfen şunları belirt:
        1. Değişikliğin kısa özeti (1-2 cümle)
        2. Değişikliğin önemi (düşük/orta/yüksek)
        3. Değişikliğin türü (fiyat değişikliği, ürün güncellemesi, içerik düzeltmesi, vb.)
        4. SEO etkisi varsa belirt
        
        JSON formatında yanıt ver:
        {{"ozet": "...", "onem": "...", "tur": "...", "seo_etkisi": "..."}}
        """
        
        try:
            response = await self.generate(prompt)
            
            # JSON'u parse etmeye çalış
            try:
                # JSON bloğunu bul
                start = response.find("{")
                end = response.rfind("}") + 1
                if start >= 0 and end > start:
                    json_str = response[start:end]
                    return json.loads(json_str)
            except json.JSONDecodeError:
                pass
            
            # JSON parse edilemezse ham yanıtı döndür
            return {"ozet": response, "onem": "belirsiz", "tur": "belirsiz", "seo_etkisi": ""}
        
        except Exception as e:
            return {"error": str(e)}
    
    async def suggest_content_strategy(
        self, 
        competitor_activities: List[Dict]
    ) -> str:
        """
        Rakip aktivitelerine göre içerik stratejisi öner.
        
        Args:
            competitor_activities: Rakip aktivite listesi
        
        Returns:
            Strateji önerileri
        """
        activities_text = "\n".join([
            f"- {a.get('site', 'Bilinmeyen')}: {a.get('action', '')} - {a.get('description', '')}"
            for a in competitor_activities[:10]
        ])
        
        prompt = f"""
        Aşağıdaki rakip içerik aktivitelerini analiz et ve Türkçe olarak içerik stratejisi öner:
        
        RAKİP AKTİVİTELERİ:
        {activities_text}
        
        Lütfen şunları belirt:
        1. Rakiplerin genel içerik trendi
        2. Kaçırılan fırsatlar
        3. Önerilen içerik aksiyonları (öncelik sırasına göre)
        4. Dikkat edilmesi gereken noktalar
        
        Kısa ve aksiyon odaklı öneriler ver.
        """
        
        return await self.generate(prompt, max_tokens=1500)
    
    async def summarize_weekly_report(
        self, 
        stats: Dict
    ) -> str:
        """
        Haftalık rapor özeti oluştur.
        
        Args:
            stats: İstatistik verileri
        
        Returns:
            Haftalık rapor özeti
        """
        prompt = f"""
        Aşağıdaki verilere göre Türkçe haftalık içerik istihbarat raporu özeti yaz:
        
        VERİLER:
        - Yeni içerik sayısı: {stats.get('new_content_count', 0)}
        - Güncelleme sayısı: {stats.get('update_count', 0)}
        - Takip edilen site sayısı: {stats.get('active_sites', 0)}
        - Takip edilen sayfa sayısı: {stats.get('total_pages_tracked', 0)}
        - En aktif rakip: {stats.get('most_active_competitor', {}).get('site_name', 'Belirsiz')}
        
        3-4 paragraf halinde, yönetici özeti formatında yaz.
        Önemli trendleri ve dikkat edilmesi gereken noktaları vurgula.
        """
        
        return await self.generate(prompt, max_tokens=1000)


# Global service instance
gemini_ai = GeminiService()
