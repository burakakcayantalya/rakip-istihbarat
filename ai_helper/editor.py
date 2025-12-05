# ============================================
# AI Helper - Editor Module
# Module C: AI contextual injection (before/after HTML üretme)
# ============================================

from typing import Dict, Optional
from sqlalchemy.orm import Session
import json

from ai_helper.models import AIHelperOpportunity, AIHelperProposal, add_log
from services.gemini_ai import gemini_ai
from services.deepseek_ai import deepseek_ai


class Editor:
    """AI ile contextual link injection"""
    
    def __init__(self, project_id: int, db_session: Session, ai_provider: str = "gemini", ai_model: str = "gemini-flash-latest"):
        self.project_id = project_id
        self.db = db_session
        self.ai_provider = ai_provider
        self.ai_model = ai_model
    
    async def _generate_text(self, prompt: str) -> str:
        """AI provider'a göre metin üret"""
        if self.ai_provider == "gemini":
            return await gemini_ai.generate(prompt, max_tokens=2000)
        elif self.ai_provider == "deepseek":
            messages = [
                {"role": "system", "content": "Sen bir SEO uzmanısın. Internal linking ve içerik optimizasyonu konusunda uzmanlaşmışsın."},
                {"role": "user", "content": prompt}
            ]
            return await deepseek_ai.chat(messages, max_tokens=2000)
        else:
            raise ValueError(f"Bilinmeyen AI provider: {self.ai_provider}")
    
    async def generate_proposal(self, opportunity_id: int) -> AIHelperProposal:
        """
        Bir opportunity için AI ile before/after HTML üret
        
        Args:
            opportunity_id: Opportunity ID
        
        Returns:
            Oluşturulan proposal
        """
        opportunity = self.db.query(AIHelperOpportunity).filter(
            AIHelperOpportunity.id == opportunity_id,
            AIHelperOpportunity.project_id == self.project_id
        ).first()
        
        if not opportunity:
            raise ValueError("Opportunity bulunamadı")
        
        add_log(self.project_id, "INFO", "EDITOR", f"Proposal oluşturuluyor: {opportunity.source_url} → {opportunity.target_url}", {
            "opportunity_id": opportunity_id
        }, self.db)
        
        # Source URL'den içeriği çek
        source_content = await self._get_page_content(opportunity.source_url)
        
        if not source_content:
            raise ValueError(f"Source URL içeriği alınamadı: {opportunity.source_url}")
        
        add_log(self.project_id, "INFO", "EDITOR", f"İçerik alındı ({len(source_content)} karakter)", {}, self.db)
        
        # AI'a gönder ve contextual injection iste
        prompt = f"""Aşağıdaki blog yazısına internal link eklemen gerekiyor.

Kaynak URL: {opportunity.source_url}
Hedef URL: {opportunity.target_url}
Anchor Text: {opportunity.target_keyword or 'bu konu'}

İçerik:
{source_content[:3000]}...

Görev:
1. İçeriği oku ve en uygun paragrafı bul
2. O paragrafa doğal bir şekilde link ekle
3. Link anchor text'i "{opportunity.target_keyword or 'bu konu'}" olmalı
4. Orijinal paragrafı ve link eklenmiş paragrafı göster

Sadece JSON formatında cevap ver:
{{
  "original_paragraph": "Orijinal paragraf metni",
  "proposed_paragraph": "Link eklenmiş paragraf HTML'i",
  "insertion_point": "Paragrafın içerikteki konumu (açıklama)",
  "confidence_score": 0-100
}}

ÖNEMLİ: proposed_paragraph HTML formatında olmalı ve link şu şekilde olmalı:
<a href="{opportunity.target_url}">{opportunity.target_keyword or 'bu konu'}</a>

Sadece JSON döndür, başka açıklama yapma."""
        
        try:
                    add_log(self.project_id, "INFO", "EDITOR", f"{self.ai_provider.upper()} proposal isteği gönderiliyor (Model: {self.ai_model})...", {"provider": self.ai_provider, "model": self.ai_model}, self.db)
            response = await self._generate_text(prompt)
            
            # JSON'u parse et
            if "```json" in response:
                response = response.split("```json")[1].split("```")[0].strip()
            elif "```" in response:
                response = response.split("```")[1].split("```")[0].strip()
            
            ai_result = json.loads(response)
            
            # Proposal oluştur
            proposal = AIHelperProposal(
                opportunity_id=opportunity_id,
                original_snippet=ai_result.get("original_paragraph", ""),
                proposed_snippet=ai_result.get("proposed_paragraph", ""),
                ai_confidence_score=float(ai_result.get("confidence_score", 0))
            )
            self.db.add(proposal)
            self.db.commit()
            
            add_log(self.project_id, "SUCCESS", "EDITOR", f"Proposal oluşturuldu (Confidence: {proposal.ai_confidence_score}%)", {
                "proposal_id": proposal.id,
                "confidence": proposal.ai_confidence_score
            }, self.db)
            
            return proposal
            
        except Exception as e:
            add_log(self.project_id, "ERROR", "EDITOR", f"Proposal oluşturma hatası: {str(e)}", {"error": str(e)}, self.db)
            raise
    
    async def _get_page_content(self, url: str) -> Optional[str]:
        """Sayfa içeriğini al"""
        # Önce DB'den kontrol et
        from core.database import Page
        page = self.db.query(Page).filter(Page.url == url).first()
        
        if page and page.content:
            return page.content
        
        # DB'de yoksa direkt çek
        try:
            import httpx
            from bs4 import BeautifulSoup
            
            async with httpx.AsyncClient(timeout=30.0) as client:
                response = await client.get(url)
                if response.status_code == 200:
                    soup = BeautifulSoup(response.content, 'html.parser')
                    # Sadece metin içeriği
                    return soup.get_text(strip=True)[:5000]  # İlk 5000 karakter
        except Exception as e:
            add_log(self.project_id, "WARNING", "EDITOR", f"İçerik çekme hatası ({url}): {str(e)}", {"error": str(e)}, self.db)
        
        return None

