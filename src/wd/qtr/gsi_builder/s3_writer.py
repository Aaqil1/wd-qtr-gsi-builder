from wd.qtr.gsi_builder.logger import Logger

logger = Logger.get_logger(__name__)


class S3Writer:
    HEADER_LENGTH = 160
    TIMESTAMP_LENGTH = 12
    WDQTRRECON_LENGTH = 10
    YYQ_LENGTH = 3

    def __init__(self, spark, volume_path, program_start_time):
        self.spark = spark
        self.volume_path = volume_path
        self.program_start_time = program_start_time

    def write_gsi_dataframe(self, output_df, year, quarter, site_id, coalesce_partitions=1):
        """Write GSI DataFrame directly to volume."""
        try:
            filename = f"GSI_{site_id}_Q{quarter}_{year}_{self.program_start_time.strftime('%Y%m%d_%H%M%S')}.txt"
            filepath = self.volume_path + filename
            temp_path = filepath.replace(".txt", "_temp")
            record_count = output_df.count()
            logger.info(f"Writing {record_count} lines to {filepath}")
            output_df.show(5, truncate=False)

            if "value" not in output_df.columns:
                logger.error(f"DataFrame columns: {output_df.columns}")
                raise Exception("DataFrame must have a 'value' column for text format")

            output_df.coalesce(coalesce_partitions).write.mode("overwrite").text(temp_path)

            from pyspark.dbutils import DBUtils

            dbutils = DBUtils(self.spark)
            files = dbutils.fs.ls(temp_path)
            part_files = [f for f in files if f.name.startswith("part-") and f.size > 0]
            if not part_files:
                logger.error("No non-empty part files found")
                sample_data = output_df.limit(10).collect()
                for i, row in enumerate(sample_data):
                    logger.error(f"Row {i}: {row}")
                raise Exception("No non-empty part files found in temporary directory")

            if len(part_files) == 1:
                dbutils.fs.mv(part_files[0].path, filepath)
            else:
                import os
                import tempfile

                with tempfile.TemporaryDirectory() as temp_dir:
                    temp_local_path = os.path.join(temp_dir, "combined.txt")
                    for i, part_file in enumerate(sorted(part_files, key=lambda f: f.name)):
                        local_part = os.path.join(temp_dir, f"part_{i}.txt")
                        dbutils.fs.cp(part_file.path, f"file:{local_part}")
                        with open(local_part, "r", encoding="utf-8") as part_content:
                            with open(temp_local_path, "a", encoding="utf-8") as combined_file:
                                combined_file.write(part_content.read())
                    dbutils.fs.cp(f"file:{temp_local_path}", filepath)
            dbutils.fs.rm(temp_path, recurse=True)
            logger.info(f"Written to: {filepath}")
            return filepath
        except Exception as e:
            logger.error(f"Error writing to volume: {e}")
            import traceback

            logger.error(traceback.format_exc())
            return None

    def generate_gsi_header(self, year, quarter):
        """Generate GSI file header (160 chars)."""
        timestamp = self.program_start_time.strftime("%y%m%d%H%M%S")
        yy = str(year)[-2:]
        yyq = f"{yy}{quarter}"
        header = (
            " " * 12
            + timestamp
            + "WDQTRRECON"
            + yyq
            + " " * 11
            + "Q"
            + " " * 111
        )
        return header

    def generate_organization_header(self, branch, company):
        """Generate organization header (160 chars)."""
        branch_str = (branch or "").ljust(2)[:2]
        company_str = (company or "").ljust(4)[:4]
        prefix_padding = 6
        suffix = "10000NN"
        middle_padding = 13
        indicator = "Y"
        used_length = prefix_padding + 2 + 4 + len(suffix) + middle_padding + 1
        remaining_padding = self.HEADER_LENGTH - used_length
        return (
            " " * prefix_padding
            + branch_str
            + company_str
            + suffix
            + " " * middle_padding
            + indicator
            + " " * remaining_padding
        )

    def generate_trailer_record(self, line_count):
        """Generate trailer record with line count."""
        return "999999999999" + str(line_count).zfill(7)
