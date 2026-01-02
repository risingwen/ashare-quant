#!/usr/bin/env python3
"""
Script name: download_ashare_3y_to_parquet.py

Download A-share stock historical data (last 2 years) to Parquet data lake.

Features:
- Fetch stock list from AkShare
- Download daily historical data with configurable date range
- Support forward/backward adjustment or no adjustment
- Rate limiting and retry with exponential backoff
- Data validation and deduplication
- Partitioned Parquet output (year/month)
- Progress tracking via manifest
- Resumable downloads

Usage:
    python scripts/download_ashare_3y_to_parquet.py \\
        --start-date 2023-01-01 \\
        --end-date 2026-01-02 \\
        --config config.yaml
"""

import argparse
import logging
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional

import akshare as ak
import pandas as pd
import yaml

# Add src to path
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from manifest import Manifest
from utils import RateLimiter, retry_on_exception, setup_logging
from validation import deduplicate_dataframe, validate_dataframe


logger = logging.getLogger(__name__)


class AShareDownloader:
    """A-share data downloader with Parquet output"""
    
    def __init__(self, config: Dict):
        """
        Initialize downloader with configuration
        
        Args:
            config: Configuration dictionary
        """
        self.config = config
        self.onedrive_root = Path(config["onedrive_root"])
        self.base_path = config["partition"]["base_path"]
        self.partition_strategy = config["partition"]["strategy"]
        self.adjust = config.get("adjust", "qfq")
        self.enable_popularity = config.get("enable_popularity", False)
        
        # Rate limiter
        rate = config["fetching"]["rate_limit"]
        self.rate_limiter = RateLimiter(rate)
        
        # Manifest
        manifest_path = config["manifest"]["path"]
        self.manifest = Manifest(manifest_path)
        
        # Validation settings
        self.validation_config = config.get("validation", {})
        
        # Cache for popularity data (updated daily)
        self._popularity_cache = None
        self._popularity_cache_date = None
    
    def get_stock_list(self) -> pd.DataFrame:
        """
        Get list of A-share stocks
        
        Returns:
            DataFrame with columns: code, name
        """
        logger.info("Fetching A-share stock list...")
        self.rate_limiter.wait()
        
        # Try multiple methods with better error handling
        methods = [
            ("stock_zh_a_spot_em", lambda: ak.stock_zh_a_spot_em()),
            ("stock_info_a_code_name", lambda: ak.stock_info_a_code_name()),
        ]
        
        for method_name, method_func in methods:
            try:
                logger.info(f"Trying method: {method_name}")
                df = method_func()
                
                if df is None or df.empty:
                    logger.warning(f"{method_name} returned empty data")
                    continue
                
                # Standardize columns
                if "代码" in df.columns:
                    df = df.rename(columns={"代码": "code", "名称": "name"})
                
                # Ensure required columns exist
                if "code" not in df.columns:
                    logger.warning(f"{method_name} missing 'code' column")
                    continue
                
                # Add name column if missing
                if "name" not in df.columns:
                    df["name"] = ""
                
                # Filter out invalid codes
                df = df[df["code"].notna() & (df["code"] != "")]
                
                logger.info(f"Retrieved {len(df)} stocks from {method_name}")
                return df
                
            except Exception as e:
                logger.warning(f"{method_name} failed: {str(e)}")
                continue
        
        raise Exception("All methods to get stock list failed")
    
    @retry_on_exception(max_retries=3, delay=2.0, backoff=2.0)
    def get_popularity_data(self) -> Optional[pd.DataFrame]:
        """
        Get real-time popularity (人气) data for all A-share stocks
        
        Returns:
            DataFrame with columns: code, popularity
        """
        from datetime import date
        
        today = date.today()
        
        # Return cached data if still valid (same day)
        if (self._popularity_cache is not None and 
            self._popularity_cache_date == today):
            return self._popularity_cache
        
        logger.info("Fetching real-time popularity data...")
        self.rate_limiter.wait()
        
        try:
            df = ak.stock_zh_a_spot_em()
            
            if df is None or df.empty:
                logger.warning("Failed to fetch popularity data")
                return None
            
            # Extract code and popularity columns
            column_mapping = {
                "代码": "code",
                "人气": "popularity"
            }
            
            if "人气" in df.columns:
                df = df[["代码", "人气"]].rename(columns=column_mapping)
                
                # Cache the result
                self._popularity_cache = df
                self._popularity_cache_date = today
                
                logger.info(f"Retrieved popularity data for {len(df)} stocks")
                return df
            else:
                logger.warning("Popularity column not found in spot data")
                return None
                
        except Exception as e:
            logger.error(f"Failed to fetch popularity data: {str(e)}")
            return None
    
    @retry_on_exception(max_retries=3, delay=2.0, backoff=2.0)
    def fetch_stock_history(
        self,
        code: str,
        start_date: str,
        end_date: str
    ) -> Optional[pd.DataFrame]:
        """
        Fetch historical data for a single stock
        
        Args:
            code: Stock code
            start_date: Start date in YYYY-MM-DD format
            end_date: End date in YYYY-MM-DD format
            
        Returns:
            DataFrame with standardized columns or None if failed
        """
        self.rate_limiter.wait()
        
        logger.debug(f"Fetching {code} from {start_date} to {end_date}")
        
        try:
            df = ak.stock_zh_a_hist(
                symbol=code,
                period="daily",
                start_date=start_date.replace("-", ""),
                end_date=end_date.replace("-", ""),
                adjust=self.adjust
            )
            
            if df is None or df.empty:
                logger.warning(f"No data returned for {code}")
                return None
            
            # Standardize column names (AkShare returns Chinese columns)
            column_mapping = {
                "日期": "date",
                "股票代码": "code",
                "开盘": "open",
                "收盘": "close",
                "最高": "high",
                "最低": "low",
                "成交量": "volume",
                "成交额": "amount",
                "振幅": "amplitude",
                "涨跌幅": "pct_change",
                "涨跌额": "change",
                "换手率": "turnover"
            }
            
            df = df.rename(columns=column_mapping)
            
            # Ensure code column exists
            if "code" not in df.columns:
                df["code"] = code
            
            # Convert date to datetime
            df["date"] = pd.to_datetime(df["date"])
            
            # Select required columns (extended with turnover)
            required_cols = ["date", "code", "open", "high", "low", "close", "volume", "amount", "turnover"]
            available_cols = [col for col in required_cols if col in df.columns]
            df = df[available_cols]
            
            # Add missing columns with NaN
            for col in required_cols:
                if col not in df.columns:
                    df[col] = None
            
            return df[required_cols]
            
        except Exception as e:
            logger.error(f"Failed to fetch {code}: {str(e)}")
            raise
    
    def get_partition_path(self, date: pd.Timestamp) -> Path:
        """
        Get partition path for a given date
        
        Args:
            date: Date timestamp
            
        Returns:
            Path object for partition directory
        """
        base = self.onedrive_root / self.base_path
        
        if self.partition_strategy == "year_month":
            return base / f"year={date.year}" / f"month={date.month:02d}"
        elif self.partition_strategy == "year":
            return base / f"year={date.year}"
        else:
            return base
    
    def save_to_parquet(self, df: pd.DataFrame, stock_code: str):
        """
        Save DataFrame to partitioned Parquet files
        
        Args:
            df: DataFrame to save
            stock_code: Stock code for logging
        """
        if df.empty:
            logger.warning(f"Empty DataFrame for {stock_code}, skipping save")
            return
        
        # Group by partition
        df["year"] = df["date"].dt.year
        df["month"] = df["date"].dt.month
        
        for (year, month), group in df.groupby(["year", "month"]):
            # Remove partition columns before saving
            group = group.drop(columns=["year", "month"])
            
            # Get partition path
            date_example = pd.Timestamp(year=year, month=month, day=1)
            partition_path = self.get_partition_path(date_example)
            partition_path.mkdir(parents=True, exist_ok=True)
            
            # File name: use timestamp to avoid conflicts
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            filename = f"{stock_code}_{timestamp}.parquet"
            filepath = partition_path / filename
            
            # Save to Parquet
            group.to_parquet(
                filepath,
                engine="pyarrow",
                compression="snappy",
                index=False
            )
            
            logger.debug(f"Saved {len(group)} rows to {filepath}")
    
    def process_stock(
        self,
        code: str,
        start_date: str,
        end_date: str
    ) -> Dict:
        """
        Process a single stock: fetch, validate, save
        
        Args:
            code: Stock code
            start_date: Start date
            end_date: End date
            
        Returns:
            Result dictionary with status and stats
        """
        result = {
            "code": code,
            "status": "success",
            "rows": 0,
            "error": None
        }
        
        try:
            # Fetch data
            df = self.fetch_stock_history(code, start_date, end_date)
            
            if df is None or df.empty:
                result["status"] = "no_data"
                result["error"] = "No data returned"
                return result
            
            # Deduplicate
            df = deduplicate_dataframe(df, subset=["code", "date"])
            
            # Validate
            validation = validate_dataframe(
                df,
                required_columns=["date", "code", "open", "high", "low", "close"],
                **self.validation_config
            )
            
            if not validation["valid"]:
                result["status"] = "invalid"
                result["error"] = "; ".join(validation["errors"])
                logger.warning(f"Validation failed for {code}: {result['error']}")
                return result
            
            # Log warnings
            for warning in validation.get("warnings", []):
                logger.warning(f"{code}: {warning}")
            
            # Save to Parquet
            self.save_to_parquet(df, code)
            
            # Update result
            result["rows"] = len(df)
            latest_date = df["date"].max().strftime("%Y-%m-%d")
            
            # Update manifest
            self.manifest.update_stock(
                code=code,
                latest_date=latest_date,
                status="success",
                row_count=result["rows"]
            )
            
            logger.info(f"✓ {code}: {result['rows']} rows, latest={latest_date}")
            
        except Exception as e:
            result["status"] = "failed"
            result["error"] = str(e)
            logger.error(f"✗ {code}: {str(e)}")
            
            # Update manifest with error
            self.manifest.update_stock(
                code=code,
                latest_date=start_date,
                status="failed",
                error=str(e)
            )
        
        return result
    
    def download_all(
        self,
        start_date: str,
        end_date: str,
        max_workers: int = 5,
        resume: bool = True
    ):
        """
        Download all A-share stocks
        
        Args:
            start_date: Start date in YYYY-MM-DD format
            end_date: End date in YYYY-MM-DD format
            max_workers: Number of concurrent workers
            resume: Whether to resume from manifest
        """
        logger.info("="*60)
        logger.info(f"Starting A-share data download")
        logger.info(f"Date range: {start_date} to {end_date}")
        logger.info(f"Adjust type: {self.adjust}")
        logger.info(f"Workers: {max_workers}")
        logger.info(f"Output: {self.onedrive_root / self.base_path}")
        logger.info("="*60)
        
        # Get stock list
        stock_list = self.get_stock_list()
        total_stocks = len(stock_list)
        logger.info(f"Total stocks to download: {total_stocks}")
        
        # Filter already completed if resume
        if resume:
            completed_codes = set()
            for code, info in self.manifest.data["stocks"].items():
                if info.get("status") == "success":
                    completed_codes.add(code)
            
            if completed_codes:
                stock_list = stock_list[~stock_list["code"].isin(completed_codes)]
                logger.info(f"Resuming: skipping {len(completed_codes)} completed stocks")
                logger.info(f"Remaining: {len(stock_list)} stocks")
        
        # Download with thread pool
        results = {
            "success": 0,
            "failed": 0,
            "no_data": 0,
            "invalid": 0
        }
        
        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            futures = {
                executor.submit(
                    self.process_stock,
                    row["code"],
                    start_date,
                    end_date
                ): row["code"]
                for _, row in stock_list.iterrows()
            }
            
            for i, future in enumerate(as_completed(futures), 1):
                result = future.result()
                status = result["status"]
                results[status] = results.get(status, 0) + 1
                
                # Progress log every 100 stocks
                if i % 100 == 0:
                    logger.info(f"Progress: {i}/{len(stock_list)} stocks processed")
                    logger.info(f"Stats: {results}")
                    self.manifest.save()
        
        # Final save
        self.manifest.save()
        
        # Summary
        logger.info("="*60)
        logger.info("Download completed!")
        logger.info(f"Total processed: {len(stock_list)}")
        logger.info(f"Success: {results.get('success', 0)}")
        logger.info(f"Failed: {results.get('failed', 0)}")
        logger.info(f"No data: {results.get('no_data', 0)}")
        logger.info(f"Invalid: {results.get('invalid', 0)}")
        logger.info("="*60)
        
        # Show manifest summary
        summary = self.manifest.get_summary()
        logger.info(f"Manifest summary: {summary}")


def load_config(config_path: str) -> Dict:
    """Load configuration from YAML file"""
    with open(config_path, "r", encoding="utf-8") as f:
        return yaml.safe_load(f)


def main():
    """Main entry point"""
    parser = argparse.ArgumentParser(
        description="Download A-share historical data to Parquet data lake",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Download last 2 years data
  python scripts/download_ashare_3y_to_parquet.py \\
      --start-date 2024-01-01 \\
      --end-date 2026-01-02 \\
      --config config.yaml
  
  # Custom workers and no resume
  python scripts/download_ashare_3y_to_parquet.py \\
      --start-date 2024-01-01 \\
      --end-date 2024-12-31 \\
      --workers 10 \\
      --no-resume \\
      --config config.yaml
        """
    )
    
    parser.add_argument(
        "--start-date",
        type=str,
        required=True,
        help="Start date in YYYY-MM-DD format"
    )
    parser.add_argument(
        "--end-date",
        type=str,
        required=True,
        help="End date in YYYY-MM-DD format"
    )
    parser.add_argument(
        "--config",
        type=str,
        default="config.yaml",
        help="Path to configuration file (default: config.yaml)"
    )
    parser.add_argument(
        "--workers",
        type=int,
        help="Number of concurrent workers (overrides config)"
    )
    parser.add_argument(
        "--adjust",
        type=str,
        choices=["", "qfq", "hfq"],
        help="Adjustment type: '' (none), 'qfq' (forward), 'hfq' (backward)"
    )
    parser.add_argument(
        "--no-resume",
        action="store_true",
        help="Do not resume from manifest, start fresh"
    )
    
    args = parser.parse_args()
    
    # Load config
    config = load_config(args.config)
    
    # Override config with CLI args
    if args.workers:
        config["fetching"]["workers"] = args.workers
    if args.adjust is not None:
        config["adjust"] = args.adjust
    
    # Setup logging
    log_config = config.get("logging", {})
    log_file = log_config.get("file", "logs/ashare_quant.log")
    Path(log_file).parent.mkdir(parents=True, exist_ok=True)
    
    setup_logging(
        level=log_config.get("level", "INFO"),
        log_file=log_file,
        log_format=log_config.get("format")
    )
    
    # Create downloader and run
    downloader = AShareDownloader(config)
    downloader.download_all(
        start_date=args.start_date,
        end_date=args.end_date,
        max_workers=config["fetching"]["workers"],
        resume=not args.no_resume
    )
    
    logger.info("All done!")


if __name__ == "__main__":
    main()
