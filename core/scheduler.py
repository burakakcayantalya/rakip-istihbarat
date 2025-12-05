# ============================================
# Rakip İçerik İstihbarat Sistemi V2
# Scheduler - Arka Plan Görev Yönetimi
# AKILLI TARAMA: Sitemap lastmod tabanlı
# ============================================

import asyncio
from datetime import datetime, timedelta
from typing import Optional, Callable, List, Dict
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.interval import IntervalTrigger
from dataclasses import dataclass
import threading

from config import settings
from core.database import SessionLocal, Site, Page, Log, ScanJob, ScanStatus, ActionType
from core.scraper import scraper, PageContent, SitemapUrl
from core.diff_engine import diff_engine


@dataclass
class SystemStatus:
    """Sistem durumu veri yapısı"""
    current_task: str = "Boşta"
    current_site: str = ""
    current_url: str = ""
    queue_size: int = 0
    last_completed_task: str = ""
    last_completed_time: Optional[datetime] = None


# Global sistem durumu
system_status = SystemStatus()


class BackgroundScanner:
    """
    Arka plan tarama yöneticisi.
    AKILLI TARAMA: Sitemap lastmod tarihine göre sadece değişen sayfaları tarar.
    """
    
    def __init__(self):
        self.scheduler = AsyncIOScheduler()
        self._running_jobs: dict = {}  # site_id -> job_id mapping
        self._stop_flags: dict = {}  # site_id -> bool (iptal için)
        self._task_queue: List[str] = []  # Sıradaki görevler
    
    def start(self):
        """Scheduler'ı başlat"""
        if not self.scheduler.running:
            self.scheduler.start()
            print("✅ Arka plan scheduler başlatıldı.")
            self._add_periodic_scan_job()
    
    def shutdown(self):
        """Scheduler'ı durdur"""
        if self.scheduler.running:
            self.scheduler.shutdown(wait=False)
            print("🛑 Arka plan scheduler durduruldu.")
    
    def _add_periodic_scan_job(self):
        """Periyodik tarama görevi ekle"""
        interval_hours = settings.SCAN_INTERVAL_HOURS
        
        self.scheduler.add_job(
            self._periodic_scan_all_sites,
            trigger=IntervalTrigger(hours=interval_hours),
            id='periodic_scan',
            name='Periyodik Site Taraması',
            replace_existing=True,
            max_instances=1
        )
        print(f"⏰ Periyodik tarama ayarlandı: Her {interval_hours} saatte bir")
    
    async def _periodic_scan_all_sites(self):
        """Tüm aktif siteleri tara (periyodik)"""
        db = SessionLocal()
        try:
            sites = db.query(Site).filter(Site.is_active == True).all()
            
            for site in sites:
                if site.id not in self._running_jobs:
                    self._task_queue.append(f"Tarama: {site.name}")
                    asyncio.create_task(self.start_scan(site.id))
                    await asyncio.sleep(5)
        finally:
            db.close()
    
    def get_status(self) -> SystemStatus:
        """Sistem durumunu döndür"""
        system_status.queue_size = len(self._task_queue)
        return system_status
    
    def update_status(self, current_task: str = None, current_site: str = None, current_url: str = None, last_completed_task: str = None):
        """Sistem durumunu güncelle"""
        if current_task is not None:
            system_status.current_task = current_task
        if current_site is not None:
            system_status.current_site = current_site
        if current_url is not None:
            system_status.current_url = current_url
        if last_completed_task is not None:
            system_status.last_completed_task = last_completed_task
            system_status.last_completed_time = datetime.utcnow()
    
    async def start_scan(self, site_id: int, callback: Optional[Callable] = None) -> Optional[int]:
        """Site taramasını başlat"""
        if site_id in self._running_jobs:
            print(f"⚠️ Site {site_id} zaten taranıyor.")
            return None
        
        db = SessionLocal()
        try:
            site = db.query(Site).filter(Site.id == site_id).first()
            if not site:
                print(f"❌ Site bulunamadı: {site_id}")
                return None
            
            scan_job = ScanJob(
                site_id=site_id,
                status=ScanStatus.PENDING,
                created_at=datetime.utcnow()
            )
            db.add(scan_job)
            db.commit()
            db.refresh(scan_job)
            
            job_id = scan_job.id
            self._running_jobs[site_id] = job_id
            self._stop_flags[site_id] = False
            
            asyncio.create_task(
                self._execute_smart_scan(site_id, job_id, site.name, site.domain, site.sitemap_url, callback)
            )
            
            return job_id
        
        except Exception as e:
            print(f"❌ Tarama başlatma hatası: {e}")
            return None
        finally:
            db.close()
    
    async def _execute_smart_scan(
        self, 
        site_id: int, 
        job_id: int,
        site_name: str,
        domain: str, 
        sitemap_url: Optional[str],
        callback: Optional[Callable] = None
    ):
        """
        AKILLI TARAMA - Sitemap lastmod tabanlı.
        
        Mantık:
        1. Sitemap'i parse et (lastmod tarihleriyle)
        2. Her URL için:
           - Yeni sayfa mı? → Scrape et, kaydet
           - Var olan sayfa mı? → lastmod > last_checked_at ise scrape et
        3. lastmod yoksa → hash karşılaştırması yap
        
        Bu yaklaşım 100x daha hızlı!
        """
        global system_status
        db = SessionLocal()
        
        try:
            # Durumu güncelle
            system_status.current_task = "Tarama başlatılıyor"
            system_status.current_site = site_name
            
            # Job'ı RUNNING olarak güncelle
            job = db.query(ScanJob).filter(ScanJob.id == job_id).first()
            job.status = ScanStatus.RUNNING
            job.started_at = datetime.utcnow()
            db.commit()
            
            print(f"🔍 Akıllı tarama başladı: {domain}")
            
            # 1. Sitemap URL'ini bul
            system_status.current_task = "Sitemap aranıyor"
            
            if not sitemap_url:
                sitemaps = await scraper.find_sitemap(domain)
                if sitemaps:
                    sitemap_url = sitemaps[0]
                    site = db.query(Site).filter(Site.id == site_id).first()
                    site.sitemap_url = sitemap_url
                    db.commit()
            
            if not sitemap_url:
                job.status = ScanStatus.FAILED
                job.error_message = "Sitemap bulunamadı"
                job.finished_at = datetime.utcnow()
                db.commit()
                self._finish_scan(site_id, site_name, "Sitemap bulunamadı")
                return
            
            # 2. Sitemap'i parse et
            system_status.current_task = "Sitemap okunuyor"
            sitemap_result = await scraper.parse_sitemap(sitemap_url)
            sitemap_urls: List[SitemapUrl] = sitemap_result.urls
            
            if not sitemap_urls:
                job.status = ScanStatus.FAILED
                job.error_message = "Sitemap'te URL bulunamadı"
                job.finished_at = datetime.utcnow()
                db.commit()
                self._finish_scan(site_id, site_name, "Sitemap boş")
                return
            
            job.total_pages = len(sitemap_urls)
            db.commit()
            
            print(f"📄 {len(sitemap_urls)} URL bulundu: {domain}")
            
            # 3. Mevcut sayfaları al (hızlı lookup için)
            existing_pages = db.query(Page).filter(Page.site_id == site_id).all()
            existing_map: Dict[str, Page] = {p.url: p for p in existing_pages}
            
            # 4. Önce tüm sitemap URL'leri için sitemap_lastmod bilgisini güncelle
            for sitemap_url_obj in sitemap_urls:
                url = sitemap_url_obj.url
                lastmod = sitemap_url_obj.lastmod
                
                if url in existing_map:
                    existing_page = existing_map[url]
                    # Sitemap'teki lastmod bilgisini kaydet (timezone-aware ise normalize et)
                    if lastmod:
                        lastmod_naive = lastmod.replace(tzinfo=None) if lastmod.tzinfo else lastmod
                        existing_page.sitemap_lastmod = lastmod_naive
            
            # 5. Hangi sayfaların taranması gerektiğini belirle
            pages_to_scan: List[SitemapUrl] = []
            new_urls: List[SitemapUrl] = []
            
            for sitemap_url_obj in sitemap_urls:
                url = sitemap_url_obj.url
                lastmod = sitemap_url_obj.lastmod
                
                if url not in existing_map:
                    # Yeni sayfa - kesinlikle tara
                    new_urls.append(sitemap_url_obj)
                else:
                    # Mevcut sayfa - lastmod kontrolü
                    existing_page = existing_map[url]
                    
                    if lastmod:
                        # Sitemap'ta lastmod var - karşılaştır
                        # lastmod timezone-aware olabilir, karşılaştırma için normalize et
                        lastmod_naive = lastmod.replace(tzinfo=None) if lastmod.tzinfo else lastmod
                        last_checked = existing_page.last_checked_at
                        
                        if last_checked is None or lastmod_naive > last_checked:
                            pages_to_scan.append(sitemap_url_obj)
                        # else: lastmod eski, değişmemiş - atla
                    else:
                        # lastmod yok - her zaman kontrol et (hash karşılaştırması)
                        pages_to_scan.append(sitemap_url_obj)
            
            # Önce yeni sayfaları, sonra güncellenecekleri tara
            all_to_scan = new_urls + pages_to_scan
            
            skipped_count = len(sitemap_urls) - len(all_to_scan)
            print(f"⚡ Akıllı tarama: {len(new_urls)} yeni, {len(pages_to_scan)} kontrol edilecek, {skipped_count} atlandı")
            
            # 5. Tarama işlemi
            new_pages = 0
            updated_pages = 0
            
            system_status.current_task = f"Sayfa taranıyor (0/{len(all_to_scan)})"
            
            for i, sitemap_url_obj in enumerate(all_to_scan):
                url = sitemap_url_obj.url
                
                # İptal kontrolü
                if self._stop_flags.get(site_id, False):
                    job.status = ScanStatus.CANCELLED
                    job.finished_at = datetime.utcnow()
                    db.commit()
                    print(f"🛑 Tarama iptal edildi: {domain}")
                    self._finish_scan(site_id, site_name, "İptal edildi")
                    return
                
                # Durum güncelle
                system_status.current_task = f"Sayfa taranıyor ({i+1}/{len(all_to_scan)})"
                system_status.current_url = url[:60] + "..." if len(url) > 60 else url
                
                # Sayfayı çek
                page_content = await scraper.fetch_page(url)
                
                if page_content:
                    if url not in existing_map:
                        # YENİ SAYFA
                        # Sitemap'teki lastmod bilgisini al
                        sitemap_lastmod_naive = None
                        if sitemap_url_obj.lastmod:
                            sitemap_lastmod_naive = sitemap_url_obj.lastmod.replace(tzinfo=None) if sitemap_url_obj.lastmod.tzinfo else sitemap_url_obj.lastmod
                        
                        new_page = Page(
                            site_id=site_id,
                            url=url,
                            title=page_content.title,
                            content_hash=diff_engine.compute_hash(page_content.content),
                            last_content_text=page_content.content,
                            word_count=page_content.word_count,
                            first_seen_at=datetime.utcnow(),
                            last_checked_at=datetime.utcnow(),
                            sitemap_lastmod=sitemap_lastmod_naive,
                            check_count=1
                        )
                        db.add(new_page)
                        db.flush()
                        
                        # Yeni sayfa logu
                        log = Log(
                            page_id=new_page.id,
                            action_type=ActionType.NEW,
                            new_content_preview=page_content.content[:500] if page_content.content else "",
                            score=1
                        )
                        db.add(log)
                        
                        new_pages += 1
                        print(f"🆕 Yeni sayfa: {url[:50]}...")
                    
                    else:
                        # MEVCUT SAYFA - Değişiklik kontrolü
                        existing_page = existing_map[url]
                        
                        # Hash karşılaştırması (hızlı)
                        new_hash = diff_engine.compute_hash(page_content.content)
                        
                        if new_hash != existing_page.content_hash:
                            # Değişiklik var - detaylı diff
                            result = diff_engine.compare(
                                existing_page.last_content_text,
                                page_content.content
                            )
                            
                            if result.has_changes:
                                # Güncelleme logu
                                log = Log(
                                    page_id=existing_page.id,
                                    action_type=ActionType.UPDATE,
                                    diff_html=result.diff_html,
                                    old_content_preview=result.old_preview,
                                    new_content_preview=result.new_preview,
                                    change_percentage=result.change_percentage,
                                    words_added=result.words_added,
                                    words_removed=result.words_removed,
                                    score=1
                                )
                                db.add(log)
                                
                                # Sayfa güncelle
                                existing_page.content_hash = new_hash
                                existing_page.last_content_text = page_content.content
                                existing_page.title = page_content.title
                                existing_page.word_count = page_content.word_count
                                existing_page.last_changed_at = datetime.utcnow()
                                
                                updated_pages += 1
                                print(f"📝 Güncelleme: {url[:50]}... ({result.change_percentage:.1f}%)")
                        
                        existing_page.last_checked_at = datetime.utcnow()
                        existing_page.check_count += 1
                
                # İlerlemeyi güncelle
                job.scanned_pages = i + 1
                job.new_pages_found = new_pages
                job.updated_pages_found = updated_pages
                
                # Her 10 sayfada bir commit
                if (i + 1) % 10 == 0:
                    db.commit()
                
                # Callback
                if callback:
                    callback(i + 1, len(all_to_scan), new_pages, updated_pages)
                
                # Rate limiting
                await asyncio.sleep(settings.REQUEST_DELAY_SECONDS)
            
            # Final commit
            db.commit()
            
            # Tarama tamamlandı
            job.status = ScanStatus.COMPLETED
            job.finished_at = datetime.utcnow()
            
            site = db.query(Site).filter(Site.id == site_id).first()
            site.last_scan_at = datetime.utcnow()
            
            db.commit()
            
            summary = f"{new_pages} yeni, {updated_pages} güncelleme, {skipped_count} atlandı"
            print(f"✅ Tarama tamamlandı: {domain} - {summary}")
            self._finish_scan(site_id, site_name, summary)
        
        except Exception as e:
            print(f"❌ Tarama hatası: {e}")
            import traceback
            traceback.print_exc()
            
            job = db.query(ScanJob).filter(ScanJob.id == job_id).first()
            if job:
                job.status = ScanStatus.FAILED
                job.error_message = str(e)
                job.finished_at = datetime.utcnow()
                db.commit()
            
            self._finish_scan(site_id, site_name, f"Hata: {str(e)[:50]}")
        
        finally:
            if site_id in self._running_jobs:
                del self._running_jobs[site_id]
            if site_id in self._stop_flags:
                del self._stop_flags[site_id]
            
            db.close()
    
    def _finish_scan(self, site_id: int, site_name: str, result: str):
        """Tarama bittiğinde durumu güncelle"""
        global system_status
        
        system_status.last_completed_task = f"{site_name}: {result}"
        system_status.last_completed_time = datetime.utcnow()
        
        if self._task_queue:
            self._task_queue.pop(0)
        
        if not self._running_jobs:
            system_status.current_task = "Boşta"
            system_status.current_site = ""
            system_status.current_url = ""
    
    def stop_scan(self, site_id: int) -> bool:
        """Çalışan taramayı durdur"""
        if site_id in self._running_jobs:
            self._stop_flags[site_id] = True
            return True
        return False
    
    def get_running_jobs(self) -> dict:
        """Çalışan taramaların listesi"""
        return self._running_jobs.copy()
    
    def is_scanning(self, site_id: int) -> bool:
        """Site taranıyor mu?"""
        return site_id in self._running_jobs


# Global instances
background_scanner = BackgroundScanner()
