"""
Data validation utilities
"""
import logging
import pandas as pd
from typing import Dict, List


logger = logging.getLogger(__name__)


def validate_dataframe(
    df: pd.DataFrame,
    required_columns: List[str],
    check_duplicates: bool = True,
    check_nulls: bool = True,
    check_negative_prices: bool = True
) -> Dict[str, any]:
    """
    Validate DataFrame for common data quality issues
    
    Args:
        df: DataFrame to validate
        required_columns: List of required column names
        check_duplicates: Check for duplicate rows
        check_nulls: Check for null values
        check_negative_prices: Check for negative price values
        
    Returns:
        Dictionary with validation results
    """
    results = {
        "valid": True,
        "errors": [],
        "warnings": [],
        "stats": {}
    }
    
    # Check if DataFrame is empty
    if df.empty:
        results["errors"].append("DataFrame is empty")
        results["valid"] = False
        return results
    
    # Check required columns
    missing_cols = set(required_columns) - set(df.columns)
    if missing_cols:
        results["errors"].append(f"Missing required columns: {missing_cols}")
        results["valid"] = False
        return results
    
    # Check for duplicates
    if check_duplicates and "code" in df.columns and "date" in df.columns:
        duplicates = df.duplicated(subset=["code", "date"], keep=False)
        dup_count = duplicates.sum()
        if dup_count > 0:
            results["warnings"].append(f"Found {dup_count} duplicate (code, date) pairs")
            results["stats"]["duplicates"] = int(dup_count)
    
    # Check for null values
    if check_nulls:
        null_counts = df[required_columns].isnull().sum()
        if null_counts.sum() > 0:
            null_cols = null_counts[null_counts > 0].to_dict()
            results["warnings"].append(f"Null values found: {null_cols}")
            results["stats"]["null_values"] = null_cols
    
    # Check for negative prices
    if check_negative_prices:
        price_cols = [col for col in ["open", "high", "low", "close"] if col in df.columns]
        for col in price_cols:
            negative_count = (df[col] < 0).sum()
            if negative_count > 0:
                results["errors"].append(f"Found {negative_count} negative values in {col}")
                results["valid"] = False
    
    # Basic statistics
    results["stats"]["row_count"] = len(df)
    if "code" in df.columns:
        results["stats"]["unique_codes"] = df["code"].nunique()
    if "date" in df.columns:
        results["stats"]["date_range"] = {
            "min": str(df["date"].min()),
            "max": str(df["date"].max())
        }
    
    return results


def deduplicate_dataframe(df: pd.DataFrame, subset: List[str] = None) -> pd.DataFrame:
    """
    Remove duplicate rows from DataFrame
    
    Args:
        df: DataFrame to deduplicate
        subset: Columns to consider for identifying duplicates
        
    Returns:
        Deduplicated DataFrame
    """
    if subset is None:
        subset = ["code", "date"]
    
    before_count = len(df)
    df_dedup = df.drop_duplicates(subset=subset, keep="last")
    after_count = len(df_dedup)
    
    if before_count > after_count:
        logger.info(f"Removed {before_count - after_count} duplicate rows")
    
    return df_dedup
