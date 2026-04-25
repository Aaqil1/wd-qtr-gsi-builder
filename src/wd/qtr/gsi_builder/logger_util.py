from wd.qtr.gsi_builder.logger import Logger


class LoggerUtil:
    """Utility for structured logging."""

    @staticmethod
    def log_structured(logger_instance, level, **kwargs):
        message = " ".join([f"{k}={v}" for k, v in kwargs.items()])
        getattr(logger_instance, level)(message)

    @staticmethod
    def info(**kwargs):
        logger = Logger.get_logger(__name__)
        LoggerUtil.log_structured(logger, "info", **kwargs)

    @staticmethod
    def error(**kwargs):
        logger = Logger.get_logger(__name__)
        LoggerUtil.log_structured(logger, "error", **kwargs)
