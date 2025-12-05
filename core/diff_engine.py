# ============================================
# Rakip İçerik İstihbarat Sistemi V2
# Diff Engine - İçerik Karşılaştırma Motoru
# ============================================

import difflib
import hashlib
import re
from typing import Tuple, Optional, Dict
from dataclasses import dataclass


@dataclass
class DiffResult:
    """Diff sonucu veri yapısı"""
    has_changes: bool
    change_percentage: float
    words_added: int
    words_removed: int
    diff_html: str
    old_preview: str
    new_preview: str


class DiffEngine:
    """
    İçerik karşılaştırma motoru.
    İki metin arasındaki farkları bulur ve HTML formatında raporlar.
    """
    
    def __init__(self, threshold_percent: float = 5.0):
        """
        Args:
            threshold_percent: Minimum değişim yüzdesi eşiği.
                              Bu değerin altındaki değişimler "değişmedi" sayılır.
        """
        self.threshold_percent = threshold_percent
    
    @staticmethod
    def compute_hash(text: str) -> str:
        """Metin için MD5 hash hesapla"""
        if not text:
            return ""
        return hashlib.md5(text.encode('utf-8')).hexdigest()
    
    @staticmethod
    def clean_text(text: str) -> str:
        """Metni temizle ve normalize et"""
        if not text:
            return ""
        
        # Çoklu boşlukları tek boşluğa çevir
        text = re.sub(r'\s+', ' ', text)
        # Baştaki ve sondaki boşlukları temizle
        text = text.strip()
        return text
    
    @staticmethod
    def split_into_sentences(text: str) -> list:
        """Metni cümlelere ayır"""
        if not text:
            return []
        
        # Basit cümle ayırıcı (nokta, soru işareti, ünlem)
        sentences = re.split(r'(?<=[.!?])\s+', text)
        return [s.strip() for s in sentences if s.strip()]
    
    @staticmethod
    def count_words(text: str) -> int:
        """Kelime sayısını hesapla"""
        if not text:
            return 0
        return len(text.split())
    
    def calculate_change_percentage(self, old_text: str, new_text: str) -> float:
        """
        İki metin arasındaki değişim yüzdesini hesapla.
        SequenceMatcher kullanarak benzerlik oranını bulur.
        """
        if not old_text and not new_text:
            return 0.0
        
        if not old_text or not new_text:
            return 100.0
        
        # Benzerlik oranını hesapla
        ratio = difflib.SequenceMatcher(None, old_text, new_text).ratio()
        
        # Değişim yüzdesi = 100 - (benzerlik * 100)
        change_percent = (1 - ratio) * 100
        return round(change_percent, 2)
    
    def generate_diff_html(self, old_text: str, new_text: str) -> str:
        """
        İki metin arasındaki farkları HTML formatında göster.
        Silinen: kırmızı arka plan
        Eklenen: yeşil arka plan
        """
        if not old_text:
            old_text = ""
        if not new_text:
            new_text = ""
        
        # Cümlelere ayır
        old_sentences = self.split_into_sentences(old_text)
        new_sentences = self.split_into_sentences(new_text)
        
        # Diff oluştur
        differ = difflib.unified_diff(
            old_sentences,
            new_sentences,
            lineterm='',
            n=0
        )
        
        # HTML oluştur
        html_parts = ['<div class="diff-container">']
        
        # Side-by-side diff için HtmlDiff kullan
        html_diff = difflib.HtmlDiff(wrapcolumn=80)
        
        try:
            table_html = html_diff.make_table(
                old_sentences,
                new_sentences,
                fromdesc='Eski Versiyon',
                todesc='Yeni Versiyon',
                context=True,
                numlines=3
            )
            
            # Özel stil ekle
            styled_html = f"""
            <style>
                .diff-table {{ width: 100%; border-collapse: collapse; font-family: monospace; font-size: 13px; }}
                .diff-table td, .diff-table th {{ padding: 8px; border: 1px solid #ddd; vertical-align: top; }}
                .diff-table th {{ background-color: #f5f5f5; font-weight: bold; }}
                .diff_header {{ background-color: #e0e0e0; }}
                .diff_next {{ background-color: #f0f0f0; }}
                .diff_add {{ background-color: #d4edda; color: #155724; }}
                .diff_chg {{ background-color: #fff3cd; color: #856404; }}
                .diff_sub {{ background-color: #f8d7da; color: #721c24; }}
            </style>
            {table_html}
            """
            html_parts.append(styled_html)
        except Exception as e:
            # Fallback: basit diff gösterimi
            html_parts.append(self._generate_simple_diff_html(old_text, new_text))
        
        html_parts.append('</div>')
        return '\n'.join(html_parts)
    
    def _generate_simple_diff_html(self, old_text: str, new_text: str) -> str:
        """Basit diff HTML gösterimi (fallback)"""
        old_words = old_text.split() if old_text else []
        new_words = new_text.split() if new_text else []
        
        matcher = difflib.SequenceMatcher(None, old_words, new_words)
        
        html_parts = ['<div class="simple-diff">']
        
        for opcode, i1, i2, j1, j2 in matcher.get_opcodes():
            if opcode == 'equal':
                html_parts.append(f'<span class="unchanged">{" ".join(old_words[i1:i2])}</span> ')
            elif opcode == 'delete':
                html_parts.append(f'<span class="removed" style="background-color: #f8d7da; color: #721c24; text-decoration: line-through; padding: 2px 4px; border-radius: 3px;">{" ".join(old_words[i1:i2])}</span> ')
            elif opcode == 'insert':
                html_parts.append(f'<span class="added" style="background-color: #d4edda; color: #155724; padding: 2px 4px; border-radius: 3px;">{" ".join(new_words[j1:j2])}</span> ')
            elif opcode == 'replace':
                html_parts.append(f'<span class="removed" style="background-color: #f8d7da; color: #721c24; text-decoration: line-through; padding: 2px 4px; border-radius: 3px;">{" ".join(old_words[i1:i2])}</span> ')
                html_parts.append(f'<span class="added" style="background-color: #d4edda; color: #155724; padding: 2px 4px; border-radius: 3px;">{" ".join(new_words[j1:j2])}</span> ')
        
        html_parts.append('</div>')
        return ''.join(html_parts)
    
    def generate_inline_diff(self, old_text: str, new_text: str) -> str:
        """
        Satır içi (inline) diff gösterimi.
        Tek bir metin bloğunda eklenen ve silinen kısımları gösterir.
        """
        if not old_text:
            return f'<span class="added" style="background-color: #d4edda; padding: 2px 4px;">{new_text}</span>'
        
        if not new_text:
            return f'<span class="removed" style="background-color: #f8d7da; text-decoration: line-through; padding: 2px 4px;">{old_text}</span>'
        
        return self._generate_simple_diff_html(old_text, new_text)
    
    def compare(self, old_text: str, new_text: str) -> DiffResult:
        """
        İki metni karşılaştır ve sonuç döndür.
        
        Args:
            old_text: Eski metin (veritabanındaki)
            new_text: Yeni metin (yeni çekilen)
        
        Returns:
            DiffResult: Karşılaştırma sonucu
        """
        # Temizle
        old_clean = self.clean_text(old_text or "")
        new_clean = self.clean_text(new_text or "")
        
        # Hash karşılaştırması (hızlı kontrol)
        old_hash = self.compute_hash(old_clean)
        new_hash = self.compute_hash(new_clean)
        
        # Eğer hash'ler aynıysa, değişiklik yok
        if old_hash == new_hash:
            return DiffResult(
                has_changes=False,
                change_percentage=0.0,
                words_added=0,
                words_removed=0,
                diff_html="",
                old_preview=old_clean[:500] if old_clean else "",
                new_preview=new_clean[:500] if new_clean else ""
            )
        
        # Değişim yüzdesini hesapla
        change_percentage = self.calculate_change_percentage(old_clean, new_clean)
        
        # Eşik kontrolü
        if change_percentage < self.threshold_percent:
            return DiffResult(
                has_changes=False,
                change_percentage=change_percentage,
                words_added=0,
                words_removed=0,
                diff_html="",
                old_preview=old_clean[:500] if old_clean else "",
                new_preview=new_clean[:500] if new_clean else ""
            )
        
        # Kelime sayılarını hesapla
        old_word_count = self.count_words(old_clean)
        new_word_count = self.count_words(new_clean)
        
        # Eklenen ve silinen kelime sayıları (yaklaşık)
        old_words = set(old_clean.split()) if old_clean else set()
        new_words = set(new_clean.split()) if new_clean else set()
        
        words_added = len(new_words - old_words)
        words_removed = len(old_words - new_words)
        
        # Diff HTML oluştur
        diff_html = self.generate_diff_html(old_clean, new_clean)
        
        return DiffResult(
            has_changes=True,
            change_percentage=change_percentage,
            words_added=words_added,
            words_removed=words_removed,
            diff_html=diff_html,
            old_preview=old_clean[:500] if old_clean else "",
            new_preview=new_clean[:500] if new_clean else ""
        )
    
    def quick_check(self, old_hash: str, new_text: str) -> bool:
        """
        Hızlı değişiklik kontrolü (sadece hash karşılaştırması).
        
        Args:
            old_hash: Eski içeriğin hash'i
            new_text: Yeni metin
        
        Returns:
            bool: True ise değişiklik var
        """
        new_hash = self.compute_hash(self.clean_text(new_text))
        return old_hash != new_hash


# Global diff engine instance
diff_engine = DiffEngine()
