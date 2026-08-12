import logging
import contextvars

# Context variables for tracing request journey
ctx_agent_name = contextvars.ContextVar("agent_name", default="main_system")
ctx_customer_id = contextvars.ContextVar("customer_id", default="N/A")
ctx_request_id = contextvars.ContextVar("request_id", default="N/A")
ctx_request_start_time = contextvars.ContextVar("request_start_time", default=0.0)

class StructuredFormatter(logging.Formatter):
    def __init__(self):
        super().__init__(
            fmt="%(asctime)s | %(levelname)-8s | agent=%(agent_name)s | customer=%(customer_id)s | request=%(request_id)s | %(name)s : %(message)s",
            datefmt="%Y-%m-%dT%H:%M:%SZ"
        )
        
    def format(self, record: logging.LogRecord) -> str:
        record.agent_name = ctx_agent_name.get()
        record.customer_id = ctx_customer_id.get()
        record.request_id = ctx_request_id.get()
        return super().format(record)

def setup_logging():
    # Configure root logger with StructuredFormatter
    root = logging.getLogger()
    
    # Avoid adding multiple handlers in testing/re-imports
    if not any(isinstance(h.formatter, StructuredFormatter) for h in root.handlers):
        # Clear existing handlers to prevent duplicate formatting output
        for h in list(root.handlers):
            root.removeHandler(h)
            
        handler = logging.StreamHandler()
        formatter = StructuredFormatter()
        handler.setFormatter(formatter)
        root.addHandler(handler)
        root.setLevel(logging.INFO)
        
    # Redirect uvicorn loggers to root handler
    for logger_name in ["uvicorn", "uvicorn.error", "uvicorn.access"]:
        u_logger = logging.getLogger(logger_name)
        u_logger.handlers = []
        u_logger.propagate = True
