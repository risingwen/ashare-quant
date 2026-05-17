#!/usr/bin/env python3
"""
Quick start script to download last 1 year of A-share data

This is a convenience wrapper around the main download script.
"""
import subprocess
import sys
from datetime import datetime, timedelta


def main():
    # Calculate date range (last 1 year)
    end_date = datetime.now()
    start_date = end_date - timedelta(days=365)
    
    start_str = start_date.strftime("%Y-%m-%d")
    end_str = end_date.strftime("%Y-%m-%d")
    
    print("="*60)
    print("AShare Quant - Quick Start")
    print("="*60)
    print(f"Downloading A-share data from {start_str} to {end_str}")
    print("This will take approximately 1-2 hours depending on your network.")
    print("="*60)
    
    # Confirm
    response = input("\nProceed with download? (y/n): ")
    if response.lower() != 'y':
        print("Cancelled.")
        return
    
    # Run download script
    cmd = [
        sys.executable,
        "scripts/download_ashare_3y_to_parquet.py",
        "--start-date", start_str,
        "--end-date", end_str,
        "--config", "config.yaml"
    ]
    
    print("\nStarting download...")
    print(f"Command: {' '.join(cmd)}\n")
    
    subprocess.run(cmd)


if __name__ == "__main__":
    main()
