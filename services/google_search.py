# ============================================
# Rakip İçerik İstihbarat Sistemi V2
# Google Search API Servisi (RapidAPI)
# ============================================

import httpx
from typing import List, Dict, Optional
from dataclasses import dataclass

from config import settings
from core.database import SessionLocal, get_setting


@dataclass
class SearchResult:
    """Arama sonucu veri yapısı"""
    title: str
    url: str
    description: str
    position: int


class GoogleSearchService:
    """
    Google Search API servisi.
    RapidAPI üzerinden Google arama sonuçlarını çeker.
    """
    
    BASE_URL = "https://google-search116.p.rapidapi.com/"
    
    def __init__(self):
        self._api_key: Optional[str] = None
        self._api_host: Optional[str] = None
    
    async def _get_credentials(self) -> tuple:
        """API kimlik bilgilerini al (önce DB, sonra env)"""
        if self._api_key and self._api_host:
            return self._api_key, self._api_host
        
        db = SessionLocal()
        try:
            # Veritabanından al
            api_key = get_setting(db, "RAPIDAPI_KEY")
            api_host = get_setting(db, "RAPIDAPI_HOST")
            
            # Yoksa environment'tan al
            self._api_key = api_key or settings.RAPIDAPI_KEY
            self._api_host = api_host or settings.RAPIDAPI_HOST
            
            return self._api_key, self._api_host
        finally:
            db.close()
    
    def clear_cache(self):
        """Credential cache'ini temizle"""
        self._api_key = None
        self._api_host = None
    
    async def search(
        self, 
        query: str, 
        num_results: int = 10,
        language: str = "tr"
    ) -> List[SearchResult]:
        """
        Google'da arama yap.
        
        Args:
            query: Arama sorgusu
            num_results: İstenen sonuç sayısı
            language: Arama dili
        
        Returns:
            Arama sonuçları listesi
        """
        api_key, api_host = await self._get_credentials()
        
        if not api_key:
            raise ValueError("RapidAPI key ayarlanmamış!")
        
        headers = {
            "x-rapidapi-key": api_key,
            "x-rapidapi-host": api_host
        }
        
        params = {
            "query": query,
            "num": num_results,
            "hl": language
        }
        
        try:
            async with httpx.AsyncClient() as client:
                response = await client.get(
                    self.BASE_URL,
                    headers=headers,
                    params=params,
                    timeout=30.0
                )
                response.raise_for_status()
                data = response.json()
            
            results = []
            
            # API yanıt formatına göre parse et
            if "results" in data:
                for i, item in enumerate(data["results"][:num_results], 1):
                    results.append(SearchResult(
                        title=item.get("title", ""),
                        url=item.get("link", item.get("url", "")),
                        description=item.get("description", item.get("snippet", "")),
                        position=i
                    ))
            
            return results
        
        except httpx.HTTPStatusError as e:
            print(f"❌ Google Search API Hatası: {e.response.status_code}")
            raise
        except Exception as e:
            print(f"❌ Google Search Hatası: {e}")
            raise
    
    async def search_site(
        self, 
        domain: str, 
        query: str = "",
        num_results: int = 10
    ) -> List[SearchResult]:
        """
        Belirli bir sitede arama yap.
        
        Args:
            domain: Aranacak site domain'i
            query: Ek arama sorgusu (opsiyonel)
            num_results: İstenen sonuç sayısı
        
        Returns:
            Arama sonuçları
        """
        site_query = f"site:{domain}"
        if query:
            site_query += f" {query}"
        
        return await self.search(site_query, num_results)
    
    async def find_competitor_content(
        self, 
        keyword: str, 
        exclude_domains: List[str] = None,
        num_results: int = 20
    ) -> List[SearchResult]:
        """
        Belirli bir anahtar kelime için rakip içerikleri bul.
        
        Args:
            keyword: Anahtar kelime
            exclude_domains: Hariç tutulacak domain'ler
            num_results: İstenen sonuç sayısı
        
        Returns:
            Rakip içerik listesi
        """
        # Domain'leri exclude et
        query = keyword
        if exclude_domains:
            for domain in exclude_domains:
                query += f" -site:{domain}"
        
        return await self.search(query, num_results)


# Global service instance
google_search = GoogleSearchService()
