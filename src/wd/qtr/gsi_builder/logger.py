import json
import logging
import os
import threading
from datetime import datetime

import requests


class SplunkHECHandler(logging.Handler):
    def __init__(self, config, app_name="wd-qtr-gsi-builder"):
        super().__init__()
        splunk_config = config["splunk"]
        self.hec_url = splunk_config["hec_url"]
        self.hec_token = splunk_config["hec_token"]
        self.index = splunk_config.get("index")
        self.app_name = app_name
        env = os.getenv("ENV", "local").lower()
        job_name = config["app"].get("name", "wd-qtr-gsi-builder")
        self.source = f"{env}-{job_name}"
        self.sourcetype = f"{env}-wd-qtr-gsi"
        self.headers = {
            "Authorization": f"Splunk {self.hec_token}",
            "Content-Type": "application/json",
        }
        self.buffer = []
        self.buffer_lock = threading.Lock()
        self.flush_interval = 5
        self.buffer_size = 10
        self.timer = None
        self._closed = False
        self._flush_lock = threading.Lock()
        self._internal_logger = logging.getLogger("SplunkHECHandler")
        self._internal_logger.propagate = False
        self._start_timer()

    def _start_timer(self):
        with self.buffer_lock:
            if self._closed:
                return
            self.timer = threading.Timer(self.flush_interval, self._flush_buffer)
            self.timer.daemon = True
            self.timer.start()

    def emit(self, record):
        transaction_id = MDC.get("transactionId")
        job_id = MDC.get("jobId")
        run_id = MDC.get("runId")
        thread_id = MDC.get("threadId")
        chunk_id = MDC.get("chunkId")
        log_entry = {
            "time": record.created,
            "index": self.index,
            "source": self.source,
            "sourcetype": self.sourcetype,
            "event": {
                "timestamp": datetime.fromtimestamp(record.created).strftime(
                    "%Y-%m-%d %H:%M:%S,%f"
                )[:-3],
                "level": record.levelname,
                "message": record.getMessage(),
                "appName": self.app_name,
                "index": self.index,
                "source": self.source,
                "sourceType": self.sourcetype,
            },
        }
        if transaction_id:
            log_entry["event"]["transactionId"] = transaction_id
        if job_id:
            log_entry["event"]["jobId"] = job_id
        if run_id:
            log_entry["event"]["runId"] = run_id
        if thread_id:
            log_entry["event"]["threadId"] = thread_id
        if chunk_id:
            log_entry["event"]["chunkId"] = chunk_id
        should_flush = False
        with self.buffer_lock:
            if self._closed:
                return
            self.buffer.append(log_entry)
            if len(self.buffer) >= self.buffer_size:
                should_flush = True
        if should_flush:
            self._do_flush()

    def _flush_buffer(self):
        self._do_flush()
        self._start_timer()

    def _do_flush(self):
        if not self._flush_lock.acquire(blocking=False):
            return
        try:
            with self.buffer_lock:
                if not self.buffer:
                    return
                logs_to_send = self.buffer[:]
                self.buffer.clear()
            for log in logs_to_send:
                try:
                    requests.post(
                        self.hec_url,
                        headers=self.headers,
                        data=json.dumps(log),
                        timeout=5,
                    )
                except Exception as e:
                    self._internal_logger.error(
                        f"Failed to send logs to Splunk HEC: {e}"
                    )
        finally:
            self._flush_lock.release()

    def close(self):
        with self.buffer_lock:
            if self._closed:
                return
            self._closed = True
            if self.timer:
                self.timer.cancel()
                self.timer = None
        self._do_flush()
        super().close()


class ThreadAwareFormatter(logging.Formatter):
    def format(self, record):
        thread_id = MDC.get("threadId")
        chunk_id = MDC.get("chunkId")
        prefix_parts = []
        if chunk_id:
            prefix_parts.append(f"[{chunk_id}]")
        if thread_id:
            prefix_parts.append(f"[{thread_id}]")
        prefix = " ".join(prefix_parts)
        if prefix:
            prefix += " "
        original_msg = record.getMessage()
        record.msg = f"{prefix}{original_msg}"
        record.args = ()
        return super().format(record)


class MDC:
    _context = threading.local()

    @classmethod
    def put(cls, key, value):
        data = getattr(cls._context, "data", None)
        if data is None:
            cls._context.data = data = {}
        data[key] = value

    @classmethod
    def get(cls, key):
        return getattr(cls._context, "data", {}).get(key)

    @classmethod
    def remove(cls, key):
        data = getattr(cls._context, "data", None)
        if data and key in data:
            del data[key]

    @classmethod
    def clear(cls):
        if hasattr(cls._context, "data"):
            cls._context.data.clear()


class Logger:
    _config = None
    _lock = threading.Lock()
    _initialized_loggers = set()

    @classmethod
    def initialize(cls, config):
        with cls._lock:
            cls._config = config
            cls._initialized_loggers.clear()

    @classmethod
    def get_logger(cls, name, level=logging.INFO, app_name="wd-qtr-gsi-builder"):
        with cls._lock:
            if name in cls._initialized_loggers:
                return logging.getLogger(name)

            logger = logging.getLogger(name)
            logger.setLevel(level)
            logger.handlers.clear()

            console_handler = logging.StreamHandler()
            console_handler.setFormatter(
                ThreadAwareFormatter(
                    "%(asctime)s %(levelname)-5s %(name)s: %(message)s"
                )
            )
            logger.addHandler(console_handler)

            env = os.getenv("ENV", "local").lower()
            if env in ["dit", "fit", "iat", "prod"] and cls._config:
                try:
                    splunk_handler = SplunkHECHandler(cls._config, app_name)
                    splunk_handler.setFormatter(logging.Formatter("%(message)s"))
                    logger.addHandler(splunk_handler)
                except Exception as e:
                    print(f"Warning: Failed to initialize Splunk handler: {e}")

            cls._initialized_loggers.add(name)
            return logger
