"""
Manifest management for tracking download progress
"""
import json
import logging
import threading
from datetime import datetime
from pathlib import Path
from typing import Dict, Optional


logger = logging.getLogger(__name__)


class Manifest:
    """Manage download progress tracking"""
    
    def __init__(self, manifest_path: str):
        """
        Initialize manifest
        
        Args:
            manifest_path: Path to manifest JSON file
        """
        self.manifest_path = Path(manifest_path)
        self.data = self._load()
        self._lock = threading.Lock()  # Thread-safe lock for concurrent access
    
    def _load(self) -> Dict:
        """Load manifest from file"""
        if self.manifest_path.exists():
            try:
                with open(self.manifest_path, "r", encoding="utf-8") as f:
                    return json.load(f)
            except Exception as e:
                logger.error(f"Failed to load manifest: {e}")
                return self._create_empty()
        else:
            return self._create_empty()
    
    def _create_empty(self) -> Dict:
        """Create empty manifest structure"""
        return {
            "metadata": {
                "created_at": datetime.now().isoformat(),
                "updated_at": datetime.now().isoformat(),
                "version": "1.0"
            },
            "stocks": {}
        }
    
    def save(self):
        """Save manifest to file"""
        with self._lock:
            self.data["metadata"]["updated_at"] = datetime.now().isoformat()
            self.manifest_path.parent.mkdir(parents=True, exist_ok=True)
            
            # Create a copy of data to avoid iteration issues during JSON dump
            data_copy = {
                "metadata": self.data["metadata"].copy(),
                "stocks": self.data["stocks"].copy()
            }
            
            with open(self.manifest_path, "w", encoding="utf-8") as f:
                json.dump(data_copy, f, indent=2, ensure_ascii=False)
            
            logger.debug(f"Manifest saved to {self.manifest_path}")
    
    def get_stock_info(self, code: str) -> Optional[Dict]:
        """Get information for a specific stock"""
        return self.data["stocks"].get(code)
    
    def update_stock(
        self,
        code: str,
        latest_date: str,
        status: str = "success",
        error: str = None,
        row_count: int = 0
    ):
        """
        Update stock information in manifest
        
        Args:
            code: Stock code
            latest_date: Latest date in YYYY-MM-DD format
            status: Status (success, failed, partial)
            error: Error message if any
            row_count: Number of rows processed
        """
        with self._lock:
            if code not in self.data["stocks"]:
                self.data["stocks"][code] = {
                    "first_seen": datetime.now().isoformat()
                }
            
            self.data["stocks"][code].update({
                "latest_date": latest_date,
                "status": status,
                "updated_at": datetime.now().isoformat(),
                "row_count": row_count
            })
            
            if error:
                self.data["stocks"][code]["last_error"] = error
            elif "last_error" in self.data["stocks"][code]:
                del self.data["stocks"][code]["last_error"]
    
    def get_failed_stocks(self) -> Dict[str, Dict]:
        """Get all stocks with failed status"""
        with self._lock:
            return {
                code: info.copy()
                for code, info in self.data["stocks"].items()
                if info.get("status") == "failed"
            }
    
    def get_summary(self) -> Dict:
        """Get summary statistics"""
        with self._lock:
            total = len(self.data["stocks"])
            success = sum(1 for s in self.data["stocks"].values() if s.get("status") == "success")
            failed = sum(1 for s in self.data["stocks"].values() if s.get("status") == "failed")
            
            return {
                "total_stocks": total,
                "success": success,
                "failed": failed,
                "updated_at": self.data["metadata"]["updated_at"]
            }
