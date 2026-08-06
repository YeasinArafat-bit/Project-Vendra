import threading
import time
from functools import wraps

class MetricsStore:
    def __init__(self):
        self._lock = threading.Lock()
        # subagent requests: {agent_name: count}
        self.subagent_requests = {}
        # subagent errors: {agent_name: count}
        self.subagent_errors = {}
        # subagent latency sum: {agent_name: total_seconds}
        self.subagent_latency_sum = {}
        # subagent latency count: {agent_name: count}
        self.subagent_latency_count = {}
        
    def increment_request(self, agent_name: str):
        with self._lock:
            self.subagent_requests[agent_name] = self.subagent_requests.get(agent_name, 0) + 1
            
    def increment_error(self, agent_name: str):
        with self._lock:
            self.subagent_errors[agent_name] = self.subagent_errors.get(agent_name, 0) + 1
            
    def observe_latency(self, agent_name: str, seconds: float):
        with self._lock:
            self.subagent_latency_sum[agent_name] = self.subagent_latency_sum.get(agent_name, 0.0) + seconds
            self.subagent_latency_count[agent_name] = self.subagent_latency_count.get(agent_name, 0) + 1

METRICS = MetricsStore()

def track_node_metrics(agent_name: str):
    """
    Decorator to automatically track request counts, execution errors,
    and processing latency for a sub-agent node in the LangGraph graph.
    """
    def decorator(func):
        @wraps(func)
        def wrapper(state, *args, **kwargs):
            METRICS.increment_request(agent_name)
            start_time = time.time()
            try:
                result = func(state, *args, **kwargs)
                latency = time.time() - start_time
                METRICS.observe_latency(agent_name, latency)
                return result
            except Exception as e:
                METRICS.increment_error(agent_name)
                raise e
        return wrapper
    return decorator
