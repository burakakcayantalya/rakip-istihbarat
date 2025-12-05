# ============================================
# AI Helper - Advanced Auditor Module
# Gelişmiş internal linking denetimi
# ============================================

import httpx
import asyncio
from typing import List, Dict, Optional, Set
from bs4 import BeautifulSoup
from urllib.parse import urlparse, urljoin

from .models import AIHelperProject, AIHelperCluster, AIHelperOpportunity, add_log
from services.gemini_ai import GeminiService
from services.deepseek_ai import DeepseekService
from core.database import get_setting


class AdvancedAuditor:
    """Gelişmiş internal linking denetimi"""
    
    def __init__(self, project_id: int, db_session, ai_provider: str = "gemini", ai_model: str = "gemini-flash-latest"):
        self.project_id = project_id
        self.db = db_session
        self.ai_provider = ai_provider
        self.ai_model = ai_model
        
        # AI servisleri
        if ai_provider == "gemini":
            self.ai_service = GeminiService()
        elif ai_provider == "deepseek":
            self.ai_service = DeepseekService()
        else:
            raise ValueError(f"Geçersiz AI provider: {ai_provider}")
    
    async def audit_cluster(self, cluster: AIHelperCluster, site_id: int):
        """
        Cluster'ı denetle - YENİ MANTIK
        
        Kurallar:
        1. Her URL'de 4 hedef cluster'a ait linkler olmalı (Otorite, Tematik, Dolaylı, Zorunlu)
        2. Cluster kendi kümesine ait minimum 4 internal link olmalı
        3. Bu kuralları karşılayana kadar makale araştır ve önerilere havuzuna gönder
        4. Tüm kuralları karşılayan URL'ler "OK" olarak işaretlenir
        """
        add_log(self.project_id, "INFO", "ADVANCED_AUDITOR", f"Cluster denetimi başlatıldı: '{cluster.cluster_name}'", {
            "cluster_id": cluster.id,
            "cluster_name": cluster.cluster_name,
            "url_count": len(cluster.urls_json or [])
        }, self.db)
        
        # Hedef cluster'ları al
        target_clusters = self._get_target_clusters(cluster)
        if not target_clusters:
            add_log(self.project_id, "ERROR", "ADVANCED_AUDITOR", "Hedef cluster'lar bulunamadı", {}, self.db)
            return
        
        # Cluster'ın kendi URL'lerini al (minimum 4 link için)
        own_cluster_urls = cluster.urls_json or []
        
        # Her URL için analiz yap
        for url in cluster.urls_json or []:
            await self._audit_url(url, cluster, target_clusters, own_cluster_urls, site_id)
    
    def _get_target_clusters(self, cluster: AIHelperCluster) -> Dict[str, AIHelperCluster]:
        """Hedef cluster'ları getir"""
        targets = {}
        
        if cluster.authority_target_cluster_id:
            auth_cluster = self.db.query(AIHelperCluster).filter(
                AIHelperCluster.id == cluster.authority_target_cluster_id
            ).first()
            if auth_cluster:
                targets["authority"] = auth_cluster
        
        if cluster.thematic_target_cluster_id:
            them_cluster = self.db.query(AIHelperCluster).filter(
                AIHelperCluster.id == cluster.thematic_target_cluster_id
            ).first()
            if them_cluster:
                targets["thematic"] = them_cluster
        
        if cluster.indirect_target_cluster_id:
            ind_cluster = self.db.query(AIHelperCluster).filter(
                AIHelperCluster.id == cluster.indirect_target_cluster_id
            ).first()
            if ind_cluster:
                targets["indirect"] = ind_cluster
        
        if cluster.mandatory_target_cluster_id:
            mand_cluster = self.db.query(AIHelperCluster).filter(
                AIHelperCluster.id == cluster.mandatory_target_cluster_id
            ).first()
            if mand_cluster:
                targets["mandatory"] = mand_cluster
        
        return targets
    
    async def _audit_url(self, url: str, cluster: AIHelperCluster, target_clusters: Dict, own_cluster_urls: List[str], site_id: int):
        """Tek bir URL'yi denetle"""
        add_log(self.project_id, "INFO", "ADVANCED_AUDITOR", f"URL denetleniyor: {url}", {"url": url}, self.db)
        
        try:
            # HTML'i indir (footer/header hariç, sadece h, p, a href)
            html_content = await self._fetch_page_html(url)
            if not html_content:
                add_log(self.project_id, "ERROR", "ADVANCED_AUDITOR", f"HTML indirilemedi: {url}", {"url": url}, self.db)
                return
            
            # HTML'den linkleri çıkar
            found_links = self._extract_links(html_content, url)
            
            # Hedef cluster'lara ait linkleri kontrol et
            target_links_status = self._check_target_cluster_links(found_links, target_clusters)
            
            # Kendi cluster'ına ait linkleri kontrol et (minimum 4)
            own_cluster_links = self._check_own_cluster_links(found_links, own_cluster_urls)
            
            # Tüm kuralları kontrol et
            all_rules_met = (
                target_links_status["authority"] and
                target_links_status["thematic"] and
                target_links_status["indirect"] and
                target_links_status["mandatory"] and
                own_cluster_links >= 4
            )
            
            if all_rules_met:
                # URL'yi "OK" olarak işaretle
                self._mark_url_as_ok(url, cluster.id)
                add_log(self.project_id, "SUCCESS", "ADVANCED_AUDITOR", f"URL tüm kuralları karşılıyor: {url}", {
                    "url": url,
                    "own_cluster_links": own_cluster_links
                }, self.db)
            else:
                # Eksik linkleri bul ve AI'a gönder
                missing_targets = []
                if not target_links_status["authority"]:
                    missing_targets.append(("authority", target_clusters.get("authority")))
                if not target_links_status["thematic"]:
                    missing_targets.append(("thematic", target_clusters.get("thematic")))
                if not target_links_status["indirect"]:
                    missing_targets.append(("indirect", target_clusters.get("indirect")))
                if not target_links_status["mandatory"]:
                    missing_targets.append(("mandatory", target_clusters.get("mandatory")))
                
                # Eksik linkler için AI'a gönder
                for target_type, target_cluster in missing_targets:
                    if target_cluster:
                        await self._generate_link_suggestions(url, html_content, target_cluster, cluster.id, site_id)
                
                # Kendi cluster'ına ait link eksikse
                if own_cluster_links < 4:
                    await self._generate_own_cluster_links(url, html_content, own_cluster_urls, cluster.id, site_id, own_cluster_links)
        
        except Exception as e:
            add_log(self.project_id, "ERROR", "ADVANCED_AUDITOR", f"URL denetim hatası: {str(e)}", {"url": url, "error": str(e)}, self.db)
            import traceback
            traceback.print_exc()
    
    async def _fetch_page_html(self, url: str) -> Optional[str]:
        """Sayfa HTML'ini indir (footer/header hariç, sadece h, p, a href)"""
        try:
            async with httpx.AsyncClient(timeout=30.0) as client:
                response = await client.get(url)
                if response.status_code != 200:
                    return None
                
                soup = BeautifulSoup(response.content, 'html.parser')
                
                # Footer ve header'ı kaldır
                for tag in soup.find_all(['header', 'footer', 'nav']):
                    tag.decompose()
                
                # Sadece h, p, a href taglarını al
                main_content = soup.find('main') or soup.find('article') or soup.find('body')
                if not main_content:
                    return None
                
                # Sadece h1-h6, p, a taglarını topla
                allowed_tags = ['h1', 'h2', 'h3', 'h4', 'h5', 'h6', 'p', 'a']
                content_html = ""
                for tag in main_content.find_all(allowed_tags):
                    content_html += str(tag) + "\n"
                
                return content_html
        except Exception as e:
            add_log(self.project_id, "ERROR", "ADVANCED_AUDITOR", f"HTML indirme hatası: {str(e)}", {"url": url}, self.db)
            return None
    
    def _extract_links(self, html_content: str, base_url: str) -> Set[str]:
        """HTML'den tüm internal linkleri çıkar"""
        soup = BeautifulSoup(html_content, 'html.parser')
        links = set()
        
        base_domain = urlparse(base_url).netloc
        
        for a_tag in soup.find_all('a', href=True):
            href = a_tag['href']
            full_url = urljoin(base_url, href)
            parsed = urlparse(full_url)
            
            # Sadece internal linkler
            if parsed.netloc == base_domain or not parsed.netloc:
                links.add(full_url)
        
        return links
    
    def _check_target_cluster_links(self, found_links: Set[str], target_clusters: Dict) -> Dict[str, bool]:
        """Hedef cluster'lara ait linkleri kontrol et"""
        status = {
            "authority": False,
            "thematic": False,
            "indirect": False,
            "mandatory": False
        }
        
        for target_type, target_cluster in target_clusters.items():
            target_urls = set(target_cluster.urls_json or [])
            if found_links & target_urls:  # Set intersection
                status[target_type] = True
        
        return status
    
    def _check_own_cluster_links(self, found_links: Set[str], own_cluster_urls: List[str]) -> int:
        """Kendi cluster'ına ait link sayısını kontrol et"""
        own_urls_set = set(own_cluster_urls)
        return len(found_links & own_urls_set)
    
    def _mark_url_as_ok(self, url: str, cluster_id: int):
        """URL'yi 'OK' olarak işaretle (internal_link_status = 'OK')"""
        # Opportunity'lerde bu URL'yi 'OK' olarak işaretle
        opportunities = self.db.query(AIHelperOpportunity).filter(
            AIHelperOpportunity.source_url == url,
            AIHelperOpportunity.cluster_id == cluster_id,
            AIHelperOpportunity.project_id == self.project_id
        ).all()
        
        for opp in opportunities:
            opp.internal_link_status = "OK"
        
        self.db.commit()
    
    async def _generate_link_suggestions(self, url: str, html_content: str, target_cluster: AIHelperCluster, cluster_id: int, site_id: int):
        """Eksik hedef cluster için link önerileri oluştur"""
        target_urls = target_cluster.urls_json or []
        if not target_urls:
            return
        
        add_log(self.project_id, "INFO", "ADVANCED_AUDITOR", f"Eksik link için AI önerisi oluşturuluyor: {url} → {target_cluster.cluster_name}", {
            "url": url,
            "target_cluster": target_cluster.cluster_name,
            "target_urls_count": len(target_urls)
        }, self.db)
        
        # AI'a gönder
        prompt = f"""Aşağıdaki HTML içeriğinde, verilen URL listesinden birine internal link eklemeniz gerekiyor.

Mevcut HTML içeriği (sadece h, p, a tagları):
{html_content[:5000]}

Hedef URL'ler (bu URL'lerden birine link verilmeli):
{chr(10).join(target_urls[:20])}

Lütfen en uygun paragrafı bulun ve o paragrafa doğal bir şekilde link ekleyin. Link için anchor text önerin.

Cevap formatı:
```json
{{
    "paragraph_index": 0,
    "original_paragraph": "orijinal paragraf metni",
    "html_snippet": "<p>... <a href='target_url'>anchor text</a> ...</p>",
    "target_url": "seçilen hedef URL",
    "anchor_text": "anchor text"
}}
```"""
        
        try:
            # AI servislerinin metodunu kullan
            if self.ai_provider == "gemini":
                response = await self.ai_service.generate(prompt, max_tokens=2048)
            elif self.ai_provider == "deepseek":
                # Deepseek için messages formatı
                messages = [{"role": "user", "content": prompt}]
                response = await self.ai_service.chat(messages, max_tokens=2048)
            else:
                raise ValueError(f"Geçersiz AI provider: {self.ai_provider}")
            
            # JSON'u parse et
            import json
            import re
            
            # JSON'u çıkar
            json_match = re.search(r'```json\s*(\{.*?\})\s*```', response, re.DOTALL)
            if not json_match:
                json_match = re.search(r'\{.*\}', response, re.DOTALL)
            
            if json_match:
                result = json.loads(json_match.group(1))
                
                # Opportunity oluştur
                opportunity = AIHelperOpportunity(
                    project_id=self.project_id,
                    cluster_id=cluster_id,
                    source_url=url,
                    target_url=result.get("target_url", target_urls[0]),
                    target_keyword=result.get("anchor_text", ""),
                    html_snippet=result.get("html_snippet", ""),
                    paragraph_index=result.get("paragraph_index", 0),
                    original_paragraph=result.get("original_paragraph", ""),
                    status="IN_POOL",
                    confidence_score=80.0,
                    internal_link_status="PENDING"
                )
                self.db.add(opportunity)
                self.db.commit()
                
                add_log(self.project_id, "SUCCESS", "ADVANCED_AUDITOR", f"Link önerisi oluşturuldu: {url}", {
                    "url": url,
                    "target_cluster": target_cluster.cluster_name
                }, self.db)
        except Exception as e:
            add_log(self.project_id, "ERROR", "ADVANCED_AUDITOR", f"AI öneri hatası: {str(e)}", {"url": url, "error": str(e)}, self.db)
    
    async def _generate_own_cluster_links(self, url: str, html_content: str, own_cluster_urls: List[str], cluster_id: int, site_id: int, current_count: int):
        """Kendi cluster'ına ait eksik linkler için öneriler oluştur (minimum 4)"""
        needed = 4 - current_count
        if needed <= 0:
            return
        
        # Henüz link verilmemiş URL'leri bul
        soup = BeautifulSoup(html_content, 'html.parser')
        existing_links = set()
        for a_tag in soup.find_all('a', href=True):
            href = a_tag['href']
            existing_links.add(href)
        
        available_urls = [u for u in own_cluster_urls if u != url and u not in existing_links]
        
        if not available_urls:
            return
        
        # Eksik link sayısı kadar öneri oluştur
        for i in range(min(needed, len(available_urls))):
            target_url = available_urls[i]
            # Basit bir target cluster objesi oluştur
            class SimpleCluster:
                def __init__(self, urls, name):
                    self.urls_json = urls
                    self.cluster_name = name
            
            target_cluster = SimpleCluster([target_url], "Own Cluster")
            await self._generate_link_suggestions(url, html_content, target_cluster, cluster_id, site_id)

