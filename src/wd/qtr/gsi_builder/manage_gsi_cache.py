#!/usr/bin/env python3
"""GSI Mappings Cache Management Utility."""

import sys
import time


def clear_gsi_cache():
    try:
        print("=" * 60)
        print("GSI MAPPINGS CACHE MANAGEMENT")
        print("=" * 60)
        from wd.qtr.gsi_builder.cache_utils import gsi_mappings_cache
        from wd.qtr.gsi_builder.gsi_mappings import clear_all_caches

        cache_info = gsi_mappings_cache.get_cache_info()
        print("\nGSI Cache Info Before Clear:")
        print(f"  Total Entries: {cache_info['total_entries']}")
        print(f"  Valid Entries: {cache_info['valid_entries']}")
        print(f"  Expired Entries: {cache_info['expired_entries']}")
        print(f"  TTL Seconds: {cache_info['ttl_seconds']}")
        clear_all_caches()
        print("\nAll mapping caches cleared successfully")
        cache_info_after = gsi_mappings_cache.get_cache_info()
        print("\nGSI Cache Info After Clear:")
        print(f"  Total Entries: {cache_info_after['total_entries']}")
        return True
    except Exception as e:
        print(f"Error clearing caches: {e}")
        import traceback

        traceback.print_exc()
        return False


def show_cache_info():
    try:
        print("=" * 60)
        print("ALL MAPPINGS CACHE INFORMATION")
        print("=" * 60)
        from wd.qtr.gsi_builder.cache_utils import gsi_mappings_cache
        from wd.qtr.gsi_builder.gsi_mappings import get_all_cache_info

        gsi_cache_info = gsi_mappings_cache.get_cache_info()
        print("\n1. GSI FIELD MAPPINGS CACHE:")
        print(f"   Total Entries: {gsi_cache_info['total_entries']}")
        print(f"   Valid Entries: {gsi_cache_info['valid_entries']}")
        print(f"   Expired Entries: {gsi_cache_info['expired_entries']}")
        print(f"   TTL: {gsi_cache_info['ttl_seconds']} seconds ({gsi_cache_info['ttl_seconds']/3600:.1f} hours)")
        print("\n2. MODULE CACHE FLAGS:")
        for key, value in get_all_cache_info().items():
            print(f"   {key}: {value}")
        return True
    except Exception as e:
        print(f"Error getting cache info: {e}")
        return False


def test_cache_functionality():
    try:
        print("=" * 60)
        print("GSI MAPPINGS CACHE FUNCTIONALITY TEST")
        print("=" * 60)
        from pyspark.sql import SparkSession

        from wd.qtr.gsi_builder.config.loader import get_config
        from wd.qtr.gsi_builder.db_connection import PostgresConnection

        config = get_config()
        if "postgres" not in config:
            print("PostgreSQL configuration not available")
            return False
        spark = SparkSession.getActiveSession()
        if not spark:
            print("No active Spark session available")
            return False
        pg_conn = PostgresConnection(
            spark,
            config["postgres"]["host"],
            config["postgres"]["port"],
            config["postgres"]["database"],
            config["postgres"]["schema"],
            config["postgres"]["user"],
            config["postgres"]["password"],
        )
        start_time = time.time()
        df1 = pg_conn.query_gsi_field_mappings()
        count1 = df1.count()
        print(f"Retrieved {count1} records in {time.time() - start_time:.2f}s")
        return True
    except Exception as e:
        print(f"Error testing cache functionality: {e}")
        import traceback

        traceback.print_exc()
        return False


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage:")
        print("  python manage_gsi_cache.py clear    - Clear GSI mappings cache")
        print("  python manage_gsi_cache.py info     - Show cache information")
        print("  python manage_gsi_cache.py test     - Test cache functionality")
        sys.exit(1)

    command = sys.argv[1].lower()
    if command == "clear":
        success = clear_gsi_cache()
    elif command == "info":
        success = show_cache_info()
    elif command == "test":
        success = test_cache_functionality()
    else:
        print(f"Unknown command: {command}")
        success = False
    sys.exit(0 if success else 1)
