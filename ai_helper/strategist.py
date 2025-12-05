# ============================================
# AI Helper - Strategist Module
# Module A: Sitemap analizi, clustering, gap tespiti
# ============================================

import httpx
import asyncio
from typing import List, Dict, Optional, Tuple
from bs4 import BeautifulSoup
from urllib.parse import urlparse
import json

from ai_helper.models import AIHelperProject, AIHelperCluster, AIHelperOpportunity, add_log
from services.gemini_ai import gemini_ai
from services.deepseek_ai import deepseek_ai
from core.database import get_setting


class Strategist:
    """Sitemap analizi ve semantic mapping"""
    
    def __init__(self, project_id: int, db_session, ai_provider: str = "gemini", ai_model: str = "gemini-flash-latest"):
        self.project_id = project_id
        self.db = db_session
        self.ai_provider = ai_provider  # gemini veya deepseek
        self.ai_model = ai_model
        
        # AI provider kontrolü
        try:
            if ai_provider == "gemini":
                api_key = get_setting(db_session, "GEMINI_API_KEY")
                if not api_key:
                    add_log(project_id, "WARNING", "STRATEGIST", "Gemini API key bulunamadı. Lütfen ayarlardan ekleyin.", {}, db_session)
            elif ai_provider == "deepseek":
                api_key = get_setting(db_session, "DEEPSEEK_API_KEY")
                if not api_key:
                    add_log(project_id, "WARNING", "STRATEGIST", "Deepseek API key bulunamadı. Lütfen ayarlardan ekleyin.", {}, db_session)
        except:
            pass
    
    async def analyze_sitemap_and_cluster(self, site_id: int) -> Dict:
        """
        Sitemap'i analiz et ve semantic kümeler oluştur
        
        Returns:
            {
                "total_urls": int,
                "clusters_created": int,
                "opportunities_found": int
            }
        """
        try:
            # Sistem durumunu güncelle
            self._update_system_status("Proje oluşturuldu, analiz başlatılıyor...")
            add_log(self.project_id, "INFO", "STRATEGIST", "✅ Proje oluşturuldu", {}, self.db)
            
            # Site bilgisini al
            from core.database import Site
            site = self.db.query(Site).filter(Site.id == site_id).first()
            if not site or not site.sitemap_url:
                raise ValueError("Site veya sitemap URL bulunamadı")
            
            add_log(self.project_id, "INFO", "STRATEGIST", f"📋 Site bilgisi alındı: {site.name}", {"site_id": site_id}, self.db)
            
            # Sitemap'i parse et
            self._update_system_status(f"Sitemap parse ediliyor: {site.sitemap_url}")
            add_log(self.project_id, "INFO", "STRATEGIST", f"🔍 Sitemap parse ediliyor: {site.sitemap_url}", {}, self.db)
            urls = await self._parse_sitemap(site.sitemap_url)
            add_log(self.project_id, "SUCCESS", "STRATEGIST", f"✅ Sitemap parse tamamlandı: {len(urls)} URL bulundu", {"url_count": len(urls)}, self.db)
            
            if not urls:
                raise ValueError("Sitemap'ten URL bulunamadı")
            
            # URL'leri önceden tanımlı kümelerine göre grupla
            self._update_system_status(f"URL'ler önceden tanımlı kümelerine göre gruplanıyor...")
            add_log(self.project_id, "INFO", "STRATEGIST", f"📋 {len(urls)} URL önceden tanımlı kümelerine göre gruplanıyor...", {"url_count": len(urls)}, self.db)
            clusters = self._manual_clustering(urls)
            add_log(self.project_id, "SUCCESS", "STRATEGIST", f"✅ Kümeleme tamamlandı: {len(clusters)} küme oluşturuldu", {"cluster_count": len(clusters), "clusters": list(clusters.keys())}, self.db)
            
            # Kümeleri DB'ye kaydet (duplicate kontrolü ile)
            self._update_system_status("Kümeler veritabanına kaydediliyor...")
            cluster_ids = []
            for cluster_name, cluster_urls in clusters.items():
                # Mevcut küme var mı kontrol et
                existing_cluster = self.db.query(AIHelperCluster).filter(
                    AIHelperCluster.project_id == self.project_id,
                    AIHelperCluster.cluster_name == cluster_name
                ).first()
                
                if existing_cluster:
                    # Mevcut küme varsa sadece URL'leri güncelle
                    existing_cluster.urls_json = cluster_urls
                    cluster_ids.append(existing_cluster.id)
                    add_log(self.project_id, "INFO", "STRATEGIST", f"🔄 Küme güncellendi: '{cluster_name}' ({len(cluster_urls)} URL)", {"cluster_name": cluster_name, "url_count": len(cluster_urls)}, self.db)
                else:
                    # Yeni küme oluştur
                    cluster = AIHelperCluster(
                        project_id=self.project_id,
                        cluster_name=cluster_name,
                        urls_json=cluster_urls
                    )
                    self.db.add(cluster)
                    self.db.flush()
                    cluster_ids.append(cluster.id)
                    add_log(self.project_id, "INFO", "STRATEGIST", f"💾 Küme kaydedildi: '{cluster_name}' ({len(cluster_urls)} URL)", {"cluster_name": cluster_name, "url_count": len(cluster_urls)}, self.db)
            
            self.db.commit()
            add_log(self.project_id, "SUCCESS", "STRATEGIST", f"✅ Tüm kümeler veritabanına kaydedildi", {"total_clusters": len(cluster_ids)}, self.db)
            
            # Gap analizi otomatik başlatılmayacak - kullanıcı manuel olarak "Denetle" butonuna basacak
            self._update_system_status("Kümeleme tamamlandı!")
            add_log(self.project_id, "INFO", "STRATEGIST", f"ℹ️ Kümeleme tamamlandı. Gap analizi için her kümenin yanındaki 'Denetle' butonunu kullanın.", {"cluster_count": len(clusters)}, self.db)
            
            self._update_system_status("Analiz tamamlandı!")
            add_log(self.project_id, "SUCCESS", "STRATEGIST", f"🎉 Kümeleme tamamlandı! {len(clusters)} küme oluşturuldu", {
                "total_urls": len(urls),
                "clusters_created": len(clusters),
                "opportunities_found": 0
            }, self.db)
            
            return {
                "total_urls": len(urls),
                "clusters_created": len(clusters),
                "opportunities_found": 0
            }
            
        except Exception as e:
            self._update_system_status(f"Hata: {str(e)}")
            add_log(self.project_id, "ERROR", "STRATEGIST", f"❌ Hata: {str(e)}", {"error": str(e)}, self.db)
            self.db.rollback()
            raise
    
    def _update_system_status(self, message: str):
        """Sistem durumunu güncelle (header'da gösterilmek için)"""
        try:
            from core.scheduler import background_scanner
            background_scanner.update_status(
                current_task=f"AI Helper: {message}",
                current_site="",
                current_url=""
            )
        except:
            pass  # Sistem durumu güncellenemezse sessizce devam et
    
    async def _generate_text(self, prompt: str) -> str:
        """AI provider'a göre metin üret"""
        try:
            if self.ai_provider == "gemini":
                response = await gemini_ai.generate(prompt, max_tokens=2000)
                if not response or not response.strip():
                    add_log(self.project_id, "WARNING", "STRATEGIST", f"Gemini boş response döndürdü. Prompt uzunluğu: {len(prompt)} karakter", {
                        "prompt_length": len(prompt),
                        "provider": "gemini"
                    }, self.db)
                return response or ""
            elif self.ai_provider == "deepseek":
                messages = [
                    {"role": "system", "content": "Sen bir SEO uzmanısın. Internal linking ve içerik optimizasyonu konusunda uzmanlaşmışsın."},
                    {"role": "user", "content": prompt}
                ]
                response = await deepseek_ai.chat(messages, max_tokens=2000)
                
                # Response'un string olduğundan emin ol
                if not isinstance(response, str):
                    add_log(self.project_id, "ERROR", "STRATEGIST", f"Deepseek response string değil: {type(response)}. Value: {str(response)[:200]}", {
                        "prompt_length": len(prompt),
                        "provider": "deepseek",
                        "response_type": str(type(response)),
                        "response_value": str(response)[:200]
                    }, self.db)
                    return ""
                
                if not response or not response.strip():
                    add_log(self.project_id, "WARNING", "STRATEGIST", f"Deepseek boş response döndürdü. Prompt uzunluğu: {len(prompt)} karakter", {
                        "prompt_length": len(prompt),
                        "provider": "deepseek"
                    }, self.db)
                return response or ""
            else:
                raise ValueError(f"Bilinmeyen AI provider: {self.ai_provider}")
        except Exception as e:
            error_msg = f"AI text generation hatası: {str(e)}"
            error_type = str(type(e).__name__)
            add_log(self.project_id, "ERROR", "STRATEGIST", error_msg, {
                "error": str(e),
                "error_type": error_type,
                "provider": self.ai_provider,
                "prompt_length": len(prompt)
            }, self.db)
            # Exception'ı yeniden fırlat ama önce logladık
            raise Exception(f"{error_msg} (Type: {error_type})") from e
    
    async def _parse_sitemap(self, sitemap_url: str) -> List[str]:
        """Sitemap'i parse et ve URL'leri çıkar"""
        try:
            async with httpx.AsyncClient(timeout=30.0) as client:
                response = await client.get(sitemap_url)
                if response.status_code != 200:
                    raise ValueError(f"Sitemap'e ulaşılamadı: {response.status_code}")
                
                soup = BeautifulSoup(response.content, 'xml')
                urls = []
                
                # Sitemap index mi kontrol et
                sitemapindex = soup.find('sitemapindex')
                if sitemapindex:
                    # Sitemap index ise, alt sitemap'leri de parse et
                    sitemaps = sitemapindex.find_all('sitemap')
                    for sitemap in sitemaps:
                        loc = sitemap.find('loc')
                        if loc:
                            sub_urls = await self._parse_sitemap(loc.text)
                            urls.extend(sub_urls)
                else:
                    # Normal sitemap
                    urlset = soup.find('urlset')
                    if urlset:
                        url_tags = urlset.find_all('url')
                        for url_tag in url_tags:
                            loc = url_tag.find('loc')
                            if loc:
                                urls.append(loc.text)
                
                return urls
        except Exception as e:
            add_log(self.project_id, "ERROR", "STRATEGIST", f"Sitemap parse hatası: {str(e)}", {"error": str(e)}, self.db)
            raise
    
    async def _create_clusters_with_ai(self, urls: List[str]) -> Dict[str, List[str]]:
        """
        AI ile semantic kümeler oluştur
        
        Returns:
            {
                "cluster_name": [url1, url2, ...],
                ...
            }
        """
        # URL'leri AI'a gönder
        urls_text = "\n".join([f"- {url}" for url in urls[:200]])  # İlk 200 URL (token limiti için)
        
        prompt = f"""Aşağıdaki URL'leri semantic olarak kümelerine ayır. Her küme benzer konuları içermeli (örnek: dental implant, veneers, orthodontics, vs.).

URL'ler:
{urls_text}

Lütfen URL'leri kümelerine ayır ve her küme için bir isim ver. Sadece JSON formatında cevap ver:

{{
  "cluster_name_1": ["url1", "url2", ...],
  "cluster_name_2": ["url3", "url4", ...],
  ...
}}

Sadece JSON döndür, başka açıklama yapma."""
        
        try:
            response = await self._generate_text(prompt)
            
            # JSON'u parse et
            # Response'dan JSON'u çıkar (markdown code block varsa)
            if "```json" in response:
                response = response.split("```json")[1].split("```")[0].strip()
            elif "```" in response:
                response = response.split("```")[1].split("```")[0].strip()
            
            clusters = json.loads(response)
            
            # URL'leri tam URL'lere eşleştir
            url_map = {url: url for url in urls}
            result_clusters = {}
            
            for cluster_name, cluster_urls in clusters.items():
                matched_urls = []
                for url in cluster_urls:
                    # URL eşleştirme (kısmi eşleşme de olabilir)
                    for full_url in urls:
                        if url in full_url or full_url.endswith(url):
                            matched_urls.append(full_url)
                            break
                
                if matched_urls:
                    result_clusters[cluster_name] = matched_urls
            
            return result_clusters
            
        except Exception as e:
            add_log(self.project_id, "ERROR", "STRATEGIST", f"AI clustering hatası: {str(e)}", {"error": str(e)}, self.db)
            # Fallback: Basit URL pattern'e göre kümeleme
            return self._fallback_clustering(urls)
    
    def _manual_clustering(self, urls: List[str]) -> Dict[str, List[str]]:
        """
        Önceden tanımlı kümelerine göre URL'leri grupla
        
        Kümeler:
        - Crowns
        - Implant
        - Orthodontic (Root Canal dahil)
        - Veneer
        - Whitening
        - Dental Holiday
        """
        # Önceden tanımlı kümeler
        predefined_clusters = {
            "crowns": ["crown", "crowns", "zirconia-crown", "porcelain-crown", "e-max"],
            "implant": ["implant", "implants", "dental-implant"],
            "orthodontic": ["orthodontic", "orthodontics", "root-canal", "root-canal-treatment", "braces", "invisalign"],
            "veneer": ["veneer", "veneers", "laminate-veneer", "porcelain-veneer", "lumineer"],
            "whitening": ["whitening", "teeth-whitening", "bleaching"],
            "dental_holiday": ["dental-holiday", "dental-tourism", "dental-turkey", "turkey-dentistry", "dental-package"]
        }
        
        clusters = {name: [] for name in predefined_clusters.keys()}
        
        for url in urls:
            path = urlparse(url).path.lower()
            url_lower = url.lower()
            matched = False
            
            # Her küme için anahtar kelimeleri kontrol et
            for cluster_name, keywords in predefined_clusters.items():
                for keyword in keywords:
                    if keyword in path or keyword in url_lower:
                        clusters[cluster_name].append(url)
                        matched = True
                        break
                if matched:
                    break
            
            # Eşleşme yoksa "dental_holiday" kümesine ekle (genel dental içerikler için)
            if not matched:
                # Dental ile ilgili genel terimler
                general_dental_keywords = ["dental", "dentist", "dentistry", "tooth", "teeth", "smile", "oral"]
                if any(kw in path or kw in url_lower for kw in general_dental_keywords):
                    clusters["dental_holiday"].append(url)
                else:
                    # Hiçbir şey eşleşmezse yine de dental_holiday'e ekle
                    clusters["dental_holiday"].append(url)
        
        # Boş kümeleri kaldır
        return {name: urls for name, urls in clusters.items() if urls}
    
    async def _find_gaps_with_ai(self, clusters: Dict[str, List[str]], site_id: int) -> List[Dict]:
        """
        Her küme için gap analizi yap
        
        Returns:
            [
                {
                    "cluster_id": int,
                    "source_url": str,
                    "target_url": str,
                    "target_keyword": str,
                    "confidence_score": float
                },
                ...
            ]
        """
        opportunities = []
        
        # Hub sayfalarını belirle (şimdilik tüm URL'ler hub olarak kabul edilir)
        # TODO: Kullanıcıdan hub seçimi alınacak
        
        # Her küme için
        for cluster_name, cluster_urls in clusters.items():
            # Küme ID'sini bul
            cluster = self.db.query(AIHelperCluster).filter(
                AIHelperCluster.project_id == self.project_id,
                AIHelperCluster.cluster_name == cluster_name
            ).first()
            
            if not cluster:
                continue
            
            # Kümedeki blogpost'ları ve hub'ları ayır
            # Şimdilik tüm URL'ler blogpost olarak kabul edilir
            blogposts = cluster_urls[:10]  # İlk 10 blogpost (test için)
            hubs = cluster_urls[10:] if len(cluster_urls) > 10 else []
            
            if not hubs:
                # Hub yoksa, kümedeki ilk URL'i hub yap
                hubs = [cluster_urls[0]] if cluster_urls else []
                blogposts = cluster_urls[1:] if len(cluster_urls) > 1 else []
            
            # Her blogpost için içerik çek ve AI'a sor
            add_log(self.project_id, "INFO", "STRATEGIST", f"📝 Küme '{cluster_name}': {len(blogposts)} blogpost analiz ediliyor...", {
                "cluster_name": cluster_name,
                "blogpost_count": len(blogposts),
                "hub_count": len(hubs)
            }, self.db)
            
            for idx, blogpost_url in enumerate(blogposts, 1):
                try:
                    add_log(self.project_id, "INFO", "STRATEGIST", f"  📄 Blogpost {idx}/{len(blogposts)}: {blogpost_url}", {}, self.db)
                    
                    # İçeriği çek (DB'den veya direkt)
                    content = await self._get_page_content(blogpost_url, site_id)
                    
                    if not content:
                        add_log(self.project_id, "WARNING", "STRATEGIST", f"  ⚠️ İçerik alınamadı: {blogpost_url}", {}, self.db)
                        continue
                    
                    add_log(self.project_id, "INFO", "STRATEGIST", f"  ✅ İçerik alındı ({len(content)} karakter)", {"content_length": len(content)}, self.db)
                    
                    # AI'a sor: Bu makalede internal linkler var mı? Eksik varsa nereye eklenebilir?
                    hub_urls_text = "\n".join([f"- {hub}" for hub in hubs[:5]])  # İlk 5 hub
                    
                    prompt = f"""Aşağıdaki blog yazısını analiz et:

URL: {blogpost_url}
İçerik: {content[:2000]}...

Potansiyel Hub Sayfaları:
{hub_urls_text}

Görev:
1. Bu makalede internal linkler var mı kontrol et
2. Eksik varsa, hangi Hub sayfasına link eklenebilir?
3. Anchor text ne olmalı?

Sadece JSON formatında cevap ver:
{{
  "has_internal_links": true/false,
  "needs_link": true/false,
  "target_hub_url": "hub_url_veya_null",
  "suggested_anchor": "anchor_text_veya_null",
  "confidence_score": 0-100
}}

Sadece JSON döndür, başka açıklama yapma."""
                    
                    add_log(self.project_id, "INFO", "STRATEGIST", f"  🤖 {self.ai_provider.upper()} gap analizi yapılıyor (Model: {self.ai_model})...", {"provider": self.ai_provider, "model": self.ai_model}, self.db)
                    response = await self._generate_text(prompt)
                    
                    # JSON'u parse et
                    if "```json" in response:
                        response = response.split("```json")[1].split("```")[0].strip()
                    elif "```" in response:
                        response = response.split("```")[1].split("```")[0].strip()
                    
                    ai_result = json.loads(response)
                    
                    if ai_result.get("needs_link") and ai_result.get("target_hub_url"):
                        # Hub URL'ini tam URL'e eşleştir
                        target_hub = None
                        for hub_url in hubs:
                            if ai_result["target_hub_url"] in hub_url or hub_url.endswith(ai_result["target_hub_url"]):
                                target_hub = hub_url
                                break
                        
                        if target_hub:
                            confidence = float(ai_result.get("confidence_score", 0))
                            opportunities.append({
                                "cluster_id": cluster.id,
                                "source_url": blogpost_url,
                                "target_url": target_hub,
                                "target_keyword": ai_result.get("suggested_anchor", ""),
                                "confidence_score": confidence
                            })
                            add_log(self.project_id, "SUCCESS", "STRATEGIST", f"  ✅ Gap bulundu: {blogpost_url} → {target_hub} (Confidence: {confidence}%)", {
                                "source_url": blogpost_url,
                                "target_url": target_hub,
                                "confidence": confidence
                            }, self.db)
                        else:
                            add_log(self.project_id, "WARNING", "STRATEGIST", f"  ⚠️ Hub URL eşleştirilemedi: {ai_result.get('target_hub_url')}", {}, self.db)
                    else:
                        add_log(self.project_id, "INFO", "STRATEGIST", f"  ℹ️ Gap bulunamadı (needs_link: {ai_result.get('needs_link')})", {}, self.db)
                
                except Exception as e:
                    add_log(self.project_id, "WARNING", "STRATEGIST", f"  ⚠️ Gap analizi hatası ({blogpost_url}): {str(e)}", {"error": str(e)}, self.db)
                    continue
            
            add_log(self.project_id, "INFO", "STRATEGIST", f"✅ Küme '{cluster_name}' analizi tamamlandı: {len([o for o in opportunities if o.get('cluster_id') == cluster.id])} gap", {
                "cluster_name": cluster_name
            }, self.db)
        
        return opportunities
    
    async def _get_page_content(self, url: str, site_id: int) -> Optional[str]:
        """Sayfa içeriğini al (DB'den veya direkt)"""
        # Önce DB'den kontrol et
        from core.database import Page
        page = self.db.query(Page).filter(
            Page.url == url,
            Page.site_id == site_id
        ).first()
        
        if page and page.last_content_text:
            return page.last_content_text
        
        # DB'de yoksa direkt çek
        try:
            async with httpx.AsyncClient(timeout=30.0) as client:
                response = await client.get(url)
                if response.status_code == 200:
                    soup = BeautifulSoup(response.content, 'html.parser')
                    # Sadece metin içeriği
                    return soup.get_text(strip=True)[:5000]  # İlk 5000 karakter
        except:
            pass
        
        return None
    
    async def audit_cluster(self, cluster_id: int, cluster_urls: List[str], site_id: int):
        """
        Küme içindeki sayfalar arasında internal link kontrolü yap
        Her URL için ayrı ayrı kontrol yapar: URL içeriği + sitemap URL listesi
        
        Args:
            cluster_id: Küme ID
            cluster_urls: Kümedeki URL'ler
            site_id: Site ID
        """
        add_log(self.project_id, "INFO", "STRATEGIST", f"🔍 Küme denetimi başlatıldı: {len(cluster_urls)} URL kontrol ediliyor...", {
            "cluster_id": cluster_id,
            "url_count": len(cluster_urls)
        }, self.db)
        
        if not cluster_urls or len(cluster_urls) == 0:
            add_log(self.project_id, "WARNING", "STRATEGIST", "Kümede URL bulunmuyor", {"cluster_id": cluster_id}, self.db)
            return
        
        # Sitemap'ten tüm URL'leri al (küme dışındakiler de dahil)
        from core.database import Site
        site = self.db.query(Site).filter(Site.id == site_id).first()
        if not site or not site.sitemap_url:
            add_log(self.project_id, "ERROR", "STRATEGIST", "Site veya sitemap URL bulunamadı", {"site_id": site_id}, self.db)
            return
        
        all_sitemap_urls = await self._parse_sitemap(site.sitemap_url)
        add_log(self.project_id, "INFO", "STRATEGIST", f"📋 Sitemap'ten {len(all_sitemap_urls)} URL alındı", {"total_urls": len(all_sitemap_urls)}, self.db)
        
        # Her URL için ayrı ayrı kontrol yap
        total_opportunities = 0
        for idx, source_url in enumerate(cluster_urls, 1):
            try:
                add_log(self.project_id, "INFO", "STRATEGIST", f"📄 URL {idx}/{len(cluster_urls)} kontrol ediliyor: {source_url}", {
                    "cluster_id": cluster_id,
                    "url_index": idx,
                    "total_urls": len(cluster_urls)
                }, self.db)
                
                # Bu URL'nin içeriğini al (küçük bir özet)
                content = await self._get_page_content(source_url, site_id)
                if not content:
                    add_log(self.project_id, "WARNING", "STRATEGIST", f"İçerik alınamadı: {source_url}", {"url": source_url}, self.db)
                    continue
                
                # İçeriği kısalt (ilk 1000 karakter yeterli)
                content_summary = content[:1000]
                
                # Sitemap URL'lerini liste olarak hazırla (kaynak URL hariç)
                other_urls = [url for url in all_sitemap_urls if url != source_url]
                urls_list = "\n".join([f"- {url}" for url in other_urls[:50]])  # İlk 50 URL (limit)
                
                # AI'a gönder: Bu makaleye hangi URL'lerden link eklenmeli?
                prompt = f"""Aşağıdaki bir makale içeriği ve sitemap'teki diğer URL'lerin listesi var. Bu makaleye aşağıdaki listeden hangilerini stratejik olarak yerleştirmeli?

MAKALE İÇERİĞİ:
{content_summary}

SİTEMAP'TEKİ DİĞER URL'LER:
{urls_list}

Lütfen şunları kontrol et:
1. Bu makaleye hangi URL'lerden internal link eklenmeli?
2. Her link için hangi anchor text kullanılmalı?
3. Linkler nerede (hangi paragrafta/cümlede) yerleştirilmeli?

Sadece JSON formatında cevap ver:
{{
  "recommended_links": [
    {{
      "target_url": "https://example.com/target-page",
      "anchor_text": "önerilen anchor text",
      "placement": "makalenin hangi kısmında yerleştirilmeli (kısa açıklama)",
      "reason": "neden bu link eklenmeli",
      "priority": "high/medium/low"
    }},
    ...
  ],
  "summary": "kısa özet"
}}

Sadece JSON döndür, başka açıklama yapma."""
                
                add_log(self.project_id, "INFO", "STRATEGIST", f"AI'a prompt gönderiliyor ({self.ai_provider}, model: {self.ai_model}, prompt uzunluğu: {len(prompt)} karakter)...", {
                    "cluster_id": cluster_id,
                    "url": source_url,
                    "provider": self.ai_provider,
                    "model": self.ai_model,
                    "prompt_length": len(prompt),
                    "prompt": prompt  # Prompt'u log'a ekle
                }, self.db)
                
                try:
                    response = await self._generate_text(prompt)
                except Exception as e:
                    add_log(self.project_id, "ERROR", "STRATEGIST", f"AI text generation exception ({source_url}): {str(e)}", {
                        "cluster_id": cluster_id,
                        "url": source_url,
                        "provider": self.ai_provider,
                        "model": self.ai_model,
                        "error": str(e),
                        "error_type": str(type(e).__name__)
                    }, self.db)
                    continue
                
                if not response or not response.strip():
                    add_log(self.project_id, "ERROR", "STRATEGIST", f"AI'dan boş response alındı ({source_url}). Provider: {self.ai_provider}, Model: {self.ai_model}", {
                        "cluster_id": cluster_id,
                        "url": source_url,
                        "provider": self.ai_provider,
                        "model": self.ai_model,
                        "prompt_preview": prompt[:200]
                    }, self.db)
                    continue
                
                # Response'un string olduğundan emin ol
                if not isinstance(response, str):
                    add_log(self.project_id, "ERROR", "STRATEGIST", f"AI response string değil ({source_url}): {type(response)}", {
                        "cluster_id": cluster_id,
                        "url": source_url,
                        "response_type": str(type(response))
                    }, self.db)
                    continue
                
                # JSON'u parse et
                response_clean = response.strip()
                if "```json" in response_clean:
                    response_clean = response_clean.split("```json")[1].split("```")[0].strip()
                elif "```" in response_clean:
                    response_clean = response_clean.split("```")[1].split("```")[0].strip()
                
                # JSON objesi içinde olabilir
                if response_clean.startswith("{") and response_clean.endswith("}"):
                    pass  # Zaten JSON formatında
                elif "{" in response_clean and "}" in response_clean:
                    # JSON'u çıkar
                    start = response_clean.find("{")
                    end = response_clean.rfind("}") + 1
                    response_clean = response_clean[start:end]
                
                if not response_clean or not response_clean.strip():
                    add_log(self.project_id, "ERROR", "STRATEGIST", f"AI response'undan JSON çıkarılamadı ({source_url})", {
                        "cluster_id": cluster_id,
                        "url": source_url,
                        "response_preview": response[:200]
                    }, self.db)
                    continue
                
                # AI'dan gelen cevabı logla
                add_log(self.project_id, "INFO", "STRATEGIST", f"AI'dan cevap alındı ({source_url})", {
                    "cluster_id": cluster_id,
                    "url": source_url,
                    "provider": self.ai_provider,
                    "model": self.ai_model,
                    "response": response,  # AI response'u log'a ekle
                    "response_length": len(response)
                }, self.db)
                
                # JSON parse dene
                ai_result = None
                try:
                    ai_result = json.loads(response_clean)
                except json.JSONDecodeError as e:
                    add_log(self.project_id, "ERROR", "STRATEGIST", f"JSON parse hatası ({source_url}): {str(e)}", {
                        "cluster_id": cluster_id,
                        "url": source_url,
                        "error": str(e),
                        "response_preview": response_clean[:500],
                        "raw_response": response  # Raw response'u da logla
                    }, self.db)
                    continue
                except Exception as e:
                    add_log(self.project_id, "ERROR", "STRATEGIST", f"JSON parse sırasında beklenmeyen hata ({source_url}): {str(e)}", {
                        "cluster_id": cluster_id,
                        "url": source_url,
                        "error": str(e),
                        "error_type": str(type(e).__name__)
                    }, self.db)
                    continue
                
                # ai_result'un dictionary olduğundan emin ol
                if ai_result is None or not isinstance(ai_result, dict):
                    add_log(self.project_id, "ERROR", "STRATEGIST", f"AI response dictionary değil ({source_url}): {type(ai_result)}", {
                        "cluster_id": cluster_id,
                        "url": source_url,
                        "response_type": str(type(ai_result))
                    }, self.db)
                    continue
                
                # Sonuçları logla ve opportunity olarak kaydet
                recommended_links = ai_result.get("recommended_links", [])
                
                # recommended_links'un liste olduğundan emin ol
                if not isinstance(recommended_links, list):
                    recommended_links = []
                
                if recommended_links:
                    add_log(self.project_id, "SUCCESS", "STRATEGIST", f"✅ {source_url} için {len(recommended_links)} link önerisi bulundu", {
                        "cluster_id": cluster_id,
                        "url": source_url,
                        "links_found": len(recommended_links),
                        "summary": ai_result.get("summary", "")
                    }, self.db)
                    
                    # Önerilen linkleri opportunity olarak kaydet
                    for link_rec in recommended_links:
                        # link_rec'un dictionary olduğundan emin ol
                        if not isinstance(link_rec, dict):
                            continue
                        
                        target_url = link_rec.get("target_url", "")
                        anchor_text = link_rec.get("anchor_text", "")
                        priority = link_rec.get("priority", "medium")
                        
                        # URL'in geçerli olduğundan emin ol
                        if not target_url:
                            continue
                        
                        # Priority'ye göre confidence score belirle
                        confidence_map = {"high": 90.0, "medium": 70.0, "low": 50.0}
                        confidence_score = confidence_map.get(priority.lower(), 70.0)
                        
                        opportunity = AIHelperOpportunity(
                            project_id=self.project_id,
                            cluster_id=cluster_id,
                            source_url=source_url,
                            target_url=target_url,
                            target_keyword=anchor_text,
                            confidence_score=confidence_score,
                            status="IN_POOL"
                        )
                        self.db.add(opportunity)
                        total_opportunities += 1
                else:
                    add_log(self.project_id, "INFO", "STRATEGIST", f"ℹ️ {source_url} için link önerisi bulunamadı", {
                        "cluster_id": cluster_id,
                        "url": source_url,
                        "summary": ai_result.get("summary", "")
                    }, self.db)
                
            except Exception as e:
                add_log(self.project_id, "ERROR", "STRATEGIST", f"URL denetimi hatası ({source_url}): {str(e)}", {
                    "error": str(e),
                    "cluster_id": cluster_id,
                    "url": source_url
                }, self.db)
                continue
        
        # Tüm opportunity'leri commit et
        self.db.commit()
        
        if total_opportunities > 0:
            add_log(self.project_id, "SUCCESS", "STRATEGIST", f"✅ Küme denetimi tamamlandı: {total_opportunities} opportunity kaydedildi", {
                "cluster_id": cluster_id,
                "opportunities_created": total_opportunities
            }, self.db)
        else:
            add_log(self.project_id, "INFO", "STRATEGIST", f"ℹ️ Küme denetimi tamamlandı: Link önerisi bulunamadı", {
                "cluster_id": cluster_id
            }, self.db)

