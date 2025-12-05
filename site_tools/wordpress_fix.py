# ============================================
# WordPress CLI - Redirect Link Düzeltme
# Basit search-replace yaklaşımı ile Elementor içeriklerini günceller
# ============================================

import subprocess
import json
import re
from typing import Optional, Dict, Tuple
from datetime import datetime
from pathlib import Path


class WordPressLinkFixer:
    """WordPress CLI ile redirect linkleri düzeltme"""
    
    def __init__(self, ssh_host: str, ssh_user: str, ssh_port: int, wp_path: str, wp_cli_path: str = "wp"):
        """
        Args:
            ssh_host: SSH host (örn: example.com)
            ssh_user: SSH user
            ssh_port: SSH port (default: 22)
            wp_path: WordPress root path (örn: /var/www/html)
            wp_cli_path: WP CLI path (default: "wp")
        """
        self.ssh_host = ssh_host
        self.ssh_user = ssh_user
        self.ssh_port = ssh_port
        self.wp_path = wp_path
        self.wp_cli_path = wp_cli_path
    
    def _run_ssh_command(self, command: str) -> Tuple[bool, str, str]:
        """
        SSH üzerinden komut çalıştır
        
        Returns:
            (success, stdout, stderr)
        """
        ssh_cmd = [
            "ssh",
            "-p", str(self.ssh_port),
            f"{self.ssh_user}@{self.ssh_host}",
            command
        ]
        
        try:
            result = subprocess.run(
                ssh_cmd,
                capture_output=True,
                text=True,
                timeout=30,
                check=False
            )
            return result.returncode == 0, result.stdout, result.stderr
        except subprocess.TimeoutExpired:
            return False, "", "SSH komutu zaman aşımına uğradı"
        except Exception as e:
            return False, "", str(e)
    
    def _run_wp_cli(self, wp_command: str) -> Tuple[bool, str, str]:
        """
        WP CLI komutu çalıştır
        
        Args:
            wp_command: WP CLI komutu (örn: "post list")
            
        Returns:
            (success, stdout, stderr)
        """
        full_command = f"cd {self.wp_path} && {self.wp_cli_path} {wp_command}"
        return self._run_ssh_command(full_command)
    
    def get_post_id_by_url(self, url: str) -> Optional[int]:
        """
        URL'den WordPress post ID'sini bul
        
        Args:
            url: Sayfa URL'i
            
        Returns:
            Post ID veya None
        """
        # URL'den slug çıkar
        from urllib.parse import urlparse
        parsed = urlparse(url)
        slug = parsed.path.strip('/').split('/')[-1]
        
        if not slug:
            return None
        
        # WP CLI ile post ID bul
        success, stdout, stderr = self._run_wp_cli(
            f"post list --name={slug} --format=json --fields=ID,post_name"
        )
        
        if not success:
            return None
        
        try:
            posts = json.loads(stdout)
            if posts and len(posts) > 0:
                return int(posts[0]['ID'])
        except (json.JSONDecodeError, KeyError, ValueError):
            pass
        
        return None
    
    def backup_elementor_data(self, post_id: int) -> Tuple[bool, Optional[str]]:
        """
        Elementor data'yı backup al
        
        Args:
            post_id: WordPress post ID
            
        Returns:
            (success, backup_file_path)
        """
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        backup_file = f"/tmp/elementor_backup_{post_id}_{timestamp}.json"
        
        success, stdout, stderr = self._run_wp_cli(
            f"post meta get {post_id} _elementor_data > {backup_file}"
        )
        
        if success:
            return True, backup_file
        return False, None
    
    def get_elementor_data(self, post_id: int) -> Tuple[bool, Optional[str]]:
        """
        Elementor data'yı al
        
        Args:
            post_id: WordPress post ID
            
        Returns:
            (success, elementor_json_string)
        """
        success, stdout, stderr = self._run_wp_cli(
            f"post meta get {post_id} _elementor_data"
        )
        
        if not success or not stdout.strip():
            return False, None
        
        # WP CLI direkt JSON string döndürüyor
        elementor_json = stdout.strip()
        
        # Eğer JSON formatında değilse (WP CLI bazen farklı format döndürebilir)
        # İlk karakter kontrolü yap
        if elementor_json.startswith('"') and elementor_json.endswith('"'):
            # Çift tırnak içindeyse decode et
            try:
                elementor_json = json.loads(elementor_json)
            except json.JSONDecodeError:
                pass
        
        # Eğer dict/list ise string'e çevir
        if isinstance(elementor_json, (dict, list)):
            elementor_json = json.dumps(elementor_json)
        
        return True, elementor_json
    
    def fix_link_in_elementor(self, post_id: int, old_url: str, new_url: str, dry_run: bool = False, logs: list = None) -> Dict:
        """
        Elementor içeriğindeki linki düzelt (basit search-replace)
        
        Args:
            post_id: WordPress post ID
            old_url: Eski URL (redirect olan)
            new_url: Yeni URL (final URL)
            dry_run: Sadece test et, değişiklik yapma
            
        Returns:
            {
                "success": bool,
                "message": str,
                "backup_file": str,
                "changes_count": int,
                "logs": list
            }
        """
        if logs is None:
            logs = []
        
        logs.append({"message": f"Post ID {post_id} için Elementor data alınıyor...", "type": "info"})
        
        # Elementor data'yı al
        success, elementor_json = self.get_elementor_data(post_id)
        if not success or not elementor_json:
            logs.append({"message": "❌ Elementor data alınamadı", "type": "error"})
            return {
                "success": False,
                "message": "Elementor data alınamadı",
                "backup_file": None,
                "changes_count": 0,
                "logs": logs
            }
        
        logs.append({"message": "✅ Elementor data başarıyla alındı", "type": "success"})
        logs.append({"message": "💾 Backup alınıyor...", "type": "info"})
        
        # Backup al
        backup_success, backup_file = self.backup_elementor_data(post_id)
        if not backup_success:
            logs.append({"message": "❌ Backup alınamadı", "type": "error"})
            return {
                "success": False,
                "message": "Backup alınamadı",
                "backup_file": None,
                "changes_count": 0,
                "logs": logs
            }
        
        logs.append({"message": f"✅ Backup alındı: {backup_file}", "type": "success"})
        
        # URL'leri normalize et (farklı formatları yakala)
        old_url_variants = [
            old_url,
            old_url.rstrip('/'),
            old_url + '/',
            f"https://{old_url.lstrip('/')}",
            f"http://{old_url.lstrip('/')}"
        ]
        
        # Regex ile sadece href attribute'larında değiştir
        # Pattern: href="..." veya href='...' içindeki URL
        changes_count = 0
        new_json = elementor_json
        
        for old_variant in old_url_variants:
            # Escape özel karakterler
            escaped_old = re.escape(old_variant)
            
            # Pattern: href="..." veya href='...' içinde eski URL
            pattern = rf'(href=["\'])([^"\']*{escaped_old}[^"\']*)(["\'])'
            
            def replace_func(match):
                nonlocal changes_count
                prefix = match.group(1)  # href=" veya href='
                url_part = match.group(2)  # URL kısmı
                suffix = match.group(3)  # " veya '
                
                # URL'i değiştir
                new_url_part = url_part.replace(old_variant, new_url)
                changes_count += 1
                return f"{prefix}{new_url_part}{suffix}"
            
            new_json = re.sub(pattern, replace_func, new_json)
        
        if changes_count == 0:
            logs.append({"message": "⚠️ Link bulunamadı (zaten düzeltilmiş olabilir)", "type": "warning"})
            return {
                "success": False,
                "message": "Link bulunamadı (zaten düzeltilmiş olabilir)",
                "backup_file": backup_file,
                "changes_count": 0,
                "logs": logs
            }
        
        logs.append({"message": f"✅ {changes_count} adet link bulundu", "type": "success"})
        
        if dry_run:
            logs.append({"message": "🔍 Dry-run modu: Değişiklik yapılmadı", "type": "info"})
            return {
                "success": True,
                "message": f"Dry-run: {changes_count} link bulundu (değişiklik yapılmadı)",
                "backup_file": backup_file,
                "changes_count": changes_count,
                "logs": logs
            }
        
        logs.append({"message": "📝 Elementor data güncelleniyor...", "type": "info"})
        
        # JSON'u geçici dosyaya yaz ve WP CLI ile oku
        temp_file = f"/tmp/elementor_update_{post_id}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
        
        # JSON'u dosyaya yaz (heredoc kullanarak)
        # JSON içindeki özel karakterleri escape et
        escaped_json = new_json.replace('$', '\\$').replace('`', '\\`').replace('"', '\\"')
        
        write_command = f"cat > {temp_file} << 'EOFMARKER'\n{new_json}\nEOFMARKER"
        write_success, _, _ = self._run_ssh_command(write_command)
        
        if not write_success:
            return {
                "success": False,
                "message": "Geçici dosya oluşturulamadı",
                "backup_file": backup_file,
                "changes_count": changes_count
            }
        
        # WP CLI ile meta'yı güncelle (dosyadan oku)
        success, stdout, stderr = self._run_ssh_command(
            f"cd {self.wp_path} && cat {temp_file} | {self.wp_cli_path} post meta update {post_id} _elementor_data --format=json"
        )
        
        # Geçici dosyayı sil
        self._run_ssh_command(f"rm -f {temp_file}")
        
        if not success:
            return {
                "success": False,
                "message": f"WP CLI hatası: {stderr}",
                "backup_file": backup_file,
                "changes_count": changes_count
            }
        
        # Elementor cache'i temizle
        self._run_wp_cli("elementor flush-cache")
        
        return {
            "success": True,
            "message": f"{changes_count} link başarıyla düzeltildi",
            "backup_file": backup_file,
            "changes_count": changes_count
        }
    
    def restore_from_backup(self, post_id: int, backup_file: str) -> Tuple[bool, str]:
        """
        Backup'tan geri yükle
        
        Args:
            post_id: WordPress post ID
            backup_file: Backup dosya yolu
            
        Returns:
            (success, message)
        """
        success, stdout, stderr = self._run_ssh_command(
            f"cat {backup_file} | cd {self.wp_path} && {self.wp_cli_path} post meta update {post_id} _elementor_data"
        )
        
        if success:
            return True, "Backup'tan geri yüklendi"
        return False, f"Hata: {stderr}"

