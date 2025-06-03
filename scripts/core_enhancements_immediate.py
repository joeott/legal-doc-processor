#!/usr/bin/env python3
"""
Immediate Core Function Enhancements
Purpose: Quick wins to strengthen core functions based on test results
"""

import functools
import time
import logging
from typing import Any, Callable, Optional, Dict
import asyncio
from dataclasses import dataclass
from datetime import datetime, timedelta

# Configure enhanced logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - [%(correlation_id)s] - %(message)s'
)

# Enhancement 1: Circuit Breaker Pattern
class CircuitBreaker:
    """Circuit breaker for external service calls"""
    
    def __init__(self, failure_threshold: int = 5, recovery_timeout: int = 60):
        self.failure_threshold = failure_threshold
        self.recovery_timeout = recovery_timeout
        self.failure_count = 0
        self.last_failure_time = None
        self.state = "CLOSED"  # CLOSED, OPEN, HALF_OPEN
    
    def __call__(self, func: Callable) -> Callable:
        @functools.wraps(func)
        def wrapper(*args, **kwargs):
            if self.state == "OPEN":
                if self._should_attempt_reset():
                    self.state = "HALF_OPEN"
                else:
                    raise Exception(f"Circuit breaker is OPEN for {func.__name__}")
            
            try:
                result = func(*args, **kwargs)
                self._on_success()
                return result
            except Exception as e:
                self._on_failure()
                raise e
        
        return wrapper
    
    def _should_attempt_reset(self) -> bool:
        return (
            self.last_failure_time and
            datetime.now() - self.last_failure_time > timedelta(seconds=self.recovery_timeout)
        )
    
    def _on_success(self):
        self.failure_count = 0
        self.state = "CLOSED"
    
    def _on_failure(self):
        self.failure_count += 1
        self.last_failure_time = datetime.now()
        if self.failure_count >= self.failure_threshold:
            self.state = "OPEN"

# Enhancement 2: Exponential Backoff with Jitter
def exponential_backoff_retry(
    max_retries: int = 3,
    base_delay: float = 1.0,
    max_delay: float = 60.0,
    exponential_base: float = 2.0,
    jitter: bool = True
):
    """Decorator for exponential backoff retry with jitter"""
    def decorator(func: Callable) -> Callable:
        @functools.wraps(func)
        def wrapper(*args, **kwargs):
            last_exception = None
            
            for attempt in range(max_retries):
                try:
                    return func(*args, **kwargs)
                except Exception as e:
                    last_exception = e
                    
                    if attempt == max_retries - 1:
                        raise
                    
                    # Calculate delay with exponential backoff
                    delay = min(base_delay * (exponential_base ** attempt), max_delay)
                    
                    # Add jitter if enabled
                    if jitter:
                        import random
                        delay = delay * (0.5 + random.random())
                    
                    logging.warning(
                        f"Attempt {attempt + 1} failed for {func.__name__}, "
                        f"retrying in {delay:.2f}s: {str(e)}"
                    )
                    time.sleep(delay)
            
            raise last_exception
        
        return wrapper
    return decorator

# Enhancement 3: Performance Monitoring
@dataclass
class PerformanceMetrics:
    """Track performance metrics for functions"""
    function_name: str
    start_time: float
    end_time: Optional[float] = None
    success: bool = False
    error: Optional[str] = None
    
    @property
    def duration(self) -> Optional[float]:
        if self.end_time:
            return self.end_time - self.start_time
        return None

def monitor_performance(func: Callable) -> Callable:
    """Decorator to monitor function performance"""
    @functools.wraps(func)
    def wrapper(*args, **kwargs):
        metrics = PerformanceMetrics(
            function_name=func.__name__,
            start_time=time.time()
        )
        
        try:
            result = func(*args, **kwargs)
            metrics.success = True
            return result
        except Exception as e:
            metrics.error = str(e)
            raise
        finally:
            metrics.end_time = time.time()
            
            # Log performance metrics
            if metrics.success:
                logging.info(
                    f"Performance: {metrics.function_name} completed in "
                    f"{metrics.duration:.3f}s"
                )
            else:
                logging.error(
                    f"Performance: {metrics.function_name} failed after "
                    f"{metrics.duration:.3f}s: {metrics.error}"
                )
    
    return wrapper

# Enhancement 4: Enhanced Validation
class ValidationError(Exception):
    """Custom validation error with detailed information"""
    def __init__(self, field: str, value: Any, message: str):
        self.field = field
        self.value = value
        self.message = message
        super().__init__(f"Validation error for {field}: {message}")

def validate_input(**validators: Dict[str, Callable]):
    """Decorator for input validation"""
    def decorator(func: Callable) -> Callable:
        @functools.wraps(func)
        def wrapper(*args, **kwargs):
            # Validate each specified argument
            for arg_name, validator in validators.items():
                if arg_name in kwargs:
                    value = kwargs[arg_name]
                    if not validator(value):
                        raise ValidationError(
                            arg_name, 
                            value, 
                            f"Failed validation: {validator.__name__}"
                        )
            
            return func(*args, **kwargs)
        
        return wrapper
    return decorator

# Enhancement 5: Connection Pool Manager
class ConnectionPoolManager:
    """Manage database connection pools efficiently"""
    
    def __init__(self, min_size: int = 5, max_size: int = 20):
        self.min_size = min_size
        self.max_size = max_size
        self._pool = []
        self._in_use = set()
        
    def get_connection(self):
        """Get a connection from the pool"""
        if self._pool:
            conn = self._pool.pop()
            self._in_use.add(conn)
            return conn
        elif len(self._in_use) < self.max_size:
            # Create new connection
            conn = self._create_connection()
            self._in_use.add(conn)
            return conn
        else:
            raise Exception("Connection pool exhausted")
    
    def release_connection(self, conn):
        """Release a connection back to the pool"""
        self._in_use.discard(conn)
        if len(self._pool) < self.min_size:
            self._pool.append(conn)
        else:
            # Close excess connections
            self._close_connection(conn)
    
    def _create_connection(self):
        """Create a new database connection"""
        # Placeholder - implement actual connection logic
        return f"connection_{time.time()}"
    
    def _close_connection(self, conn):
        """Close a database connection"""
        # Placeholder - implement actual close logic
        pass

# Enhancement 6: Async Task Manager
class AsyncTaskManager:
    """Manage async tasks with proper error handling"""
    
    def __init__(self, max_concurrent_tasks: int = 10):
        self.max_concurrent_tasks = max_concurrent_tasks
        self.semaphore = asyncio.Semaphore(max_concurrent_tasks)
        
    async def run_task_with_limit(self, coro):
        """Run a task with concurrency limit"""
        async with self.semaphore:
            try:
                return await coro
            except Exception as e:
                logging.error(f"Async task failed: {e}")
                raise
    
    async def run_tasks_batch(self, tasks: list):
        """Run multiple tasks with error handling"""
        results = []
        
        for task in tasks:
            try:
                result = await self.run_task_with_limit(task)
                results.append({"success": True, "result": result})
            except Exception as e:
                results.append({"success": False, "error": str(e)})
        
        return results

# Example enhanced functions using the decorators

@circuit_breaker(failure_threshold=3, recovery_timeout=30)
@exponential_backoff_retry(max_retries=3)
@monitor_performance
def enhanced_database_query(query: str) -> Any:
    """Example of enhanced database query with all protections"""
    # Simulate database query
    import random
    if random.random() < 0.1:  # 10% failure rate for testing
        raise Exception("Database connection failed")
    
    time.sleep(0.1)  # Simulate query time
    return {"result": "success"}

@validate_input(
    document_id=lambda x: isinstance(x, str) and len(x) == 36,
    file_size=lambda x: isinstance(x, int) and 0 < x < 100_000_000  # 100MB limit
)
@monitor_performance
def enhanced_document_processing(document_id: str, file_size: int) -> Dict[str, Any]:
    """Example of enhanced document processing with validation"""
    return {
        "document_id": document_id,
        "file_size": file_size,
        "status": "processed"
    }

# Testing the enhancements
def test_enhancements():
    """Test the enhancement implementations"""
    print("🧪 Testing Core Function Enhancements")
    print("="*60)
    
    # Test 1: Circuit breaker and retry
    print("\n1️⃣ Testing Circuit Breaker + Retry:")
    for i in range(5):
        try:
            result = enhanced_database_query("SELECT * FROM documents")
            print(f"   ✅ Query {i+1} succeeded")
        except Exception as e:
            print(f"   ❌ Query {i+1} failed: {e}")
    
    # Test 2: Validation
    print("\n2️⃣ Testing Enhanced Validation:")
    test_cases = [
        ("123e4567-e89b-12d3-a456-426614174000", 1000000),  # Valid
        ("invalid-id", 1000000),  # Invalid ID
        ("123e4567-e89b-12d3-a456-426614174000", -1),  # Invalid size
    ]
    
    for doc_id, size in test_cases:
        try:
            result = enhanced_document_processing(document_id=doc_id, file_size=size)
            print(f"   ✅ Validation passed for {doc_id[:8]}...")
        except ValidationError as e:
            print(f"   ❌ Validation failed: {e}")
    
    # Test 3: Async task manager
    print("\n3️⃣ Testing Async Task Manager:")
    
    async def test_async():
        manager = AsyncTaskManager(max_concurrent_tasks=3)
        
        async def sample_task(n):
            await asyncio.sleep(0.1)
            if n == 3:
                raise Exception("Task 3 failed")
            return f"Task {n} completed"
        
        tasks = [sample_task(i) for i in range(5)]
        results = await manager.run_tasks_batch(tasks)
        
        for i, result in enumerate(results):
            if result["success"]:
                print(f"   ✅ Task {i}: {result['result']}")
            else:
                print(f"   ❌ Task {i}: {result['error']}")
    
    asyncio.run(test_async())
    
    print("\n✅ Enhancement testing complete!")

if __name__ == "__main__":
    # Create circuit breaker instance
    circuit_breaker = CircuitBreaker()
    
    # Run tests
    test_enhancements()