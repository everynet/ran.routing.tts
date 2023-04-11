import logging
import logging.config

import structlog
from google.protobuf.json_format import MessageToDict


def configure_logging(log_level: str = "info", console_colors: bool = True, json: bool = False):
    timestamper = structlog.processors.TimeStamper(fmt="iso", utc=True)
    processor_chain = [
        # Adding contextvars to support "structlog.contextvars.bind_contextvars"
        structlog.contextvars.merge_contextvars,
        # Adding logger name
        structlog.stdlib.add_logger_name,
        # Adding log level
        structlog.stdlib.add_log_level,
        # Adding timestamp
        timestamper,
        # NOTE: All other processors required for json-logging
        # Useful when you want to attach a stack dump to a log entry without involving an exception.
        structlog.processors.StackInfoRenderer(),
        # Without this processors, traceback will be omitted from log entry
        structlog.processors.format_exc_info,
        # structlog.processors.CallsiteParameterAdder(set(structlog.processors.CallsiteParameter)),
    ]
    external_logger_processors = [
        *processor_chain,
        # Here you can add processors for external library loggers
    ]
    structlog_processors = [
        # This will filter structlog records by level before passing it to other processors
        structlog.stdlib.filter_by_level,
        *processor_chain,
        # Required to actually print log records from structlog loggers into logging
        structlog.stdlib.ProcessorFormatter.wrap_for_formatter,
    ]

    logging_config = {
        "version": 1,
        "disable_existing_loggers": False,
        "formatters": {
            "default": {
                "()": structlog.stdlib.ProcessorFormatter,
                # "processor": structlog.dev.ConsoleRenderer(colors=console_colors),  # For console (colored) output
                # "processor": structlog.processors.JSONRenderer(),  # For json output
                "foreign_pre_chain": external_logger_processors,
            },
        },
        "handlers": {
            "default": {"level": log_level.upper(), "class": "logging.StreamHandler", "formatter": "default"},
        },
        "loggers": {
            "": {"level": log_level.upper(), "handlers": ["default"], "propagate": True},
        },
    }

    if json:
        logging_config["formatters"]["default"]["processor"] = structlog.processors.JSONRenderer()
    else:
        logging_config["formatters"]["default"]["processor"] = structlog.dev.ConsoleRenderer(colors=console_colors)

    logging.config.dictConfig(logging_config)
    structlog.configure(
        processors=structlog_processors,  # type: ignore
        context_class=dict,
        logger_factory=structlog.stdlib.LoggerFactory(),
        wrapper_class=structlog.stdlib.BoundLogger,  # noqa
        cache_logger_on_first_use=True,
    )


class LazyFormat:
    __sentinel = object()

    def __init__(self, fn, *args, **kwargs) -> None:
        self._fn = fn
        self._args = args
        self._kwargs = kwargs
        self.__evaluated = self.__sentinel

    def __evaluate(self):
        if self.__evaluated is self.__sentinel:
            self.__evaluated = self._fn(*self._args, **self._kwargs)
        return self.__evaluated

    def __str__(self) -> str:
        return str(self.__evaluate())

    def __repr__(self):
        return repr(self.__evaluate())


def lazy_protobuf_fmt(struct):
    return LazyFormat(MessageToDict, struct)


def lazy_fmt(fn, *args, **kwargs):
    return LazyFormat(fn, *args, **kwargs)
