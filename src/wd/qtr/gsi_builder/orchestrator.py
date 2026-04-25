"""Parallel site processing using Spark-native distribution."""

from concurrent.futures import ThreadPoolExecutor, as_completed

from wd.qtr.gsi_builder.logger import Logger, MDC

logger = Logger.get_logger(__name__)


def process_sites_parallel(spark, queued_records, db_conn, s3_writer, email_notifier):
    """Process all queued sites using Spark-native parallelism."""
    from wd.qtr.gsi_builder.gsi_mappings import load_mappings
    from wd.qtr.gsi_builder.main import process_site_event

    gsi_mappings, address_mappings = load_mappings()

    try:
        num_workers = spark.sparkContext._jsc.sc().getExecutorMemoryStatus().size() - 1
        max_threads = max(1, min(len(queued_records), num_workers, 4))
    except Exception:
        max_threads = min(len(queued_records), 4)

    logger.info(f"Processing {len(queued_records)} sites with {max_threads} concurrent threads")
    results = []

    def _process_one(record):
        site_id = record["site_id"]
        MDC.put("threadId", f"site-{site_id}")
        try:
            result = process_site_event(
                record["batch_id"],
                site_id,
                record["year"],
                record["quarter"],
                record["window_start"],
                record["window_end"],
                gsi_mappings,
                address_mappings,
            )
            success = result.get("processed", False)
            return {"site_id": site_id, "success": success, "state": "COMPLETED" if success else "FAILED"}
        except Exception as e:
            logger.error(f"Site {site_id} failed: {e}")
            return {"site_id": site_id, "success": False, "state": str(e)}
        finally:
            MDC.remove("threadId")

    if max_threads == 1:
        for record in queued_records:
            results.append(_process_one(record))
    else:
        with ThreadPoolExecutor(max_workers=max_threads) as executor:
            future_map = {executor.submit(_process_one, rec): rec["site_id"] for rec in queued_records}
            for future in as_completed(future_map):
                site_id = future_map[future]
                try:
                    results.append(future.result())
                except Exception as e:
                    logger.error(f"Thread failed for site {site_id}: {e}")
                    results.append({"site_id": site_id, "success": False, "state": str(e)})
    return results
