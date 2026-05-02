#!/usr/bin/env python3
"""
Script name: update_daily_incremental.py

Incrementally update A-share data by fetching only missing trading days.

Features:
- Read manifest to find latest date for each stock
- Only fetch missing date range (latest_date+1 to today)
- Deduplicate and append to existing Parquet partitions
- Skip if current day is not a trading day
- Generate daily report with statistics

Usage:
    python scripts/update_daily_incremental.py --config config.yaml
"""

import argparse
import logging
import sys
from datetime import datetime, timedelta
from pathlib import Path
from typing import Dict, List, Optional

import pandas as pd
import yaml

# Add src to path
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from manifest import Manifest
from utils import setup_logging

# Import from download script (reuse logic)
from download_ashare_3y_to_parquet import AShareDownloader


logger = logging.getLogger(__name__)


class IncrementalUpdater(AShareDownloader):
    """Incremental updater extends downloader with delta logic"""
    
    def update_incremental(
        self,
        end_date: Optional[str] = None,
        max_workers: int = 5
    ):
        """
        Update stocks incrementally
        
        Args:
            end_date: End date (default: today)
            max_workers: Number of concurrent workers
        """
        if end_date is None:
            end_date = datetime.now().strftime("%Y-%m-%d")
        
        logger.info("="*60)
        logger.info(f"Starting incremental update")
        logger.info(f"End date: {end_date}")
        logger.info(f"Workers: {max_workers}")
        logger.info("="*60)
        
        # Get stock list
        stock_list = self.get_stock_list()
        total_stocks = len(stock_list)
        logger.info(f"Total stocks in market: {total_stocks}")
        
        # Determine what needs updating
        update_tasks = []
        
        for _, row in stock_list.iterrows():
            code = row["code"]
            stock_info = self.manifest.get_stock_info(code)
            
            if stock_info is None:
                # New stock, fetch from 2 years ago
                start_date = (datetime.now() - timedelta(days=2*365)).strftime("%Y-%m-%d")
                update_tasks.append({
                    "code": code,
                    "start_date": start_date,
                    "end_date": end_date,
                    "reason": "new"
                })
            else:
                latest_date = stock_info.get("latest_date")
                if latest_date:
                    # Calculate next date
                    latest_dt = datetime.strptime(latest_date, "%Y-%m-%d")
                    next_date = (latest_dt + timedelta(days=1)).strftime("%Y-%m-%d")
                    
                    # Only update if there's a gap
                    if next_date <= end_date:
                        update_tasks.append({
                            "code": code,
                            "start_date": next_date,
                            "end_date": end_date,
                            "reason": "update"
                        })
                else:
                    # Has record but no latest_date
                    start_date = (datetime.now() - timedelta(days=2*365)).strftime("%Y-%m-%d")
                    update_tasks.append({
                        "code": code,
                        "start_date": start_date,
                        "end_date": end_date,
                        "reason": "retry"
                    })
        
        logger.info(f"Stocks to update: {len(update_tasks)}")
        
        if not update_tasks:
            logger.info("No updates needed. All stocks are up to date.")
            return
        
        # Group by reason
        by_reason = {}
        for task in update_tasks:
            reason = task["reason"]
            by_reason[reason] = by_reason.get(reason, 0) + 1
        logger.info(f"Update breakdown: {by_reason}")
        
        # Process updates
        results = {
            "success": 0,
            "failed": 0,
            "no_data": 0,
            "invalid": 0,
            "total_rows": 0
        }
        
        from concurrent.futures import ThreadPoolExecutor, as_completed
        
        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            futures = {
                executor.submit(
                    self.process_stock,
                    task["code"],
                    task["start_date"],
                    task["end_date"]
                ): task
                for task in update_tasks
            }
            
            for i, future in enumerate(as_completed(futures), 1):
                result = future.result()
                status = result["status"]
                results[status] = results.get(status, 0) + 1
                results["total_rows"] += result.get("rows", 0)
                
                # Progress log
                if i % 50 == 0:
                    logger.info(f"Progress: {i}/{len(update_tasks)} stocks processed")
                    self.manifest.save()
        
        # Final save
        self.manifest.save()
        
        # Generate report
        self._generate_report(results, len(update_tasks), end_date)
    
    def _generate_report(self, results: Dict, total: int, end_date: str):
        """Generate and log daily update report"""
        logger.info("="*60)
        logger.info("DAILY UPDATE REPORT")
        logger.info("="*60)
        logger.info(f"Update date: {end_date}")
        logger.info(f"Total stocks processed: {total}")
        logger.info(f"Success: {results.get('success', 0)}")
        logger.info(f"Failed: {results.get('failed', 0)}")
        logger.info(f"No data: {results.get('no_data', 0)}")
        logger.info(f"Invalid: {results.get('invalid', 0)}")
        logger.info(f"Total rows added: {results.get('total_rows', 0)}")
        logger.info("="*60)
        
        # Show failed stocks
        failed_stocks = self.manifest.get_failed_stocks()
        if failed_stocks:
            logger.warning(f"Failed stocks ({len(failed_stocks)}):")
            for code, info in list(failed_stocks.items())[:10]:
                error = info.get("last_error", "Unknown")
                logger.warning(f"  - {code}: {error}")
            if len(failed_stocks) > 10:
                logger.warning(f"  ... and {len(failed_stocks) - 10} more")
        
        # Manifest summary
        summary = self.manifest.get_summary()
        logger.info(f"Overall manifest: {summary}")


def load_config(config_path: str) -> Dict:
    """Load configuration from YAML file"""
    with open(config_path, "r", encoding="utf-8") as f:
        return yaml.safe_load(f)


def main():
    """Main entry point"""
    parser = argparse.ArgumentParser(
        description="Incrementally update A-share data",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Update to today
  python scripts/update_daily_incremental.py --config config.yaml
  
  # Update to specific date
  python scripts/update_daily_incremental.py \\
      --end-date 2026-01-02 \\
      --config config.yaml
        """
    )
    
    parser.add_argument(
        "--config",
        type=str,
        default="config.yaml",
        help="Path to configuration file (default: config.yaml)"
    )
    parser.add_argument(
        "--end-date",
        type=str,
        help="End date in YYYY-MM-DD format (default: today)"
    )
    parser.add_argument(
        "--workers",
        type=int,
        help="Number of concurrent workers (overrides config)"
    )
    
    args = parser.parse_args()
    
    # Load config
    config = load_config(args.config)
    
    # Override config with CLI args
    if args.workers:
        config["fetching"]["workers"] = args.workers
    
    # Setup logging
    log_config = config.get("logging", {})
    log_file = log_config.get("file", "logs/ashare_quant.log")
    Path(log_file).parent.mkdir(parents=True, exist_ok=True)
    
    setup_logging(
        level=log_config.get("level", "INFO"),
        log_file=log_file,
        log_format=log_config.get("format")
    )
    
    # Create updater and run
    updater = IncrementalUpdater(config)
    updater.update_incremental(
        end_date=args.end_date,
        max_workers=config["fetching"]["workers"]
    )
    
    logger.info("Incremental update completed!")


if __name__ == "__main__":
    main()
