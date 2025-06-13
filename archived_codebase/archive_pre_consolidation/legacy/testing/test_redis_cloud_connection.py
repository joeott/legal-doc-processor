#!/usr/bin/env python3
"""
Comprehensive Redis Cloud connection testing script
Tests various connection methods and configurations
"""
import os
import sys
import ssl
import redis
from redis.connection import SSLConnection
import logging
from datetime import datetime

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Get Redis Cloud credentials from environment
REDIS_ENDPOINT = os.getenv('REDIS_PUBLIC_ENDPOINT', '')
REDIS_PASSWORD = os.getenv('REDIS_PW')
REDIS_USERNAME = os.getenv('REDIS_USERNAME')

# Parse endpoint
if REDIS_ENDPOINT and ':' in REDIS_ENDPOINT:
    REDIS_HOST, REDIS_PORT = REDIS_ENDPOINT.rsplit(':', 1)
    REDIS_PORT = int(REDIS_PORT)
else:
    logger.error("Invalid REDIS_PUBLIC_ENDPOINT format")
    sys.exit(1)

print(f"""
Redis Cloud Connection Test
===========================
Host: {REDIS_HOST}
Port: {REDIS_PORT}
Username: {REDIS_USERNAME}
Password: {'***' if REDIS_PASSWORD else 'None'}
Endpoint: {REDIS_ENDPOINT}
Redis-py version: {redis.__version__}
""")

def test_connection(test_name, connection_params):
    """Test a specific connection configuration"""
    print(f"\n{test_name}")
    print("-" * len(test_name))
    
    try:
        # Create client
        client = redis.Redis(**connection_params)
        
        # Test connection
        response = client.ping()
        print(f"✓ Connection successful! PING response: {response}")
        
        # Test basic operations
        test_key = f"test_key_{datetime.now().timestamp()}"
        client.set(test_key, "test_value", ex=60)
        value = client.get(test_key)
        print(f"✓ SET/GET test successful! Value: {value.decode() if value else None}")
        
        # Get server info
        info = client.info("server")
        print(f"✓ Redis version: {info.get('redis_version', 'Unknown')}")
        print(f"✓ Redis mode: {info.get('redis_mode', 'Unknown')}")
        
        # Cleanup
        client.delete(test_key)
        client.close()
        return True
        
    except Exception as e:
        print(f"✗ Failed: {type(e).__name__}: {str(e)}")
        return False

# Test 1: Basic connection without SSL
print("\n" + "="*60)
test_connection("Test 1: Basic connection (no SSL)", {
    'host': REDIS_HOST,
    'port': REDIS_PORT,
    'username': REDIS_USERNAME,
    'password': REDIS_PASSWORD,
    'decode_responses': True,
    'socket_connect_timeout': 5,
    'socket_timeout': 5,
})

# Test 2: Connection with SSL (cert verification disabled)
print("\n" + "="*60)
test_connection("Test 2: SSL with ssl_cert_reqs='none'", {
    'host': REDIS_HOST,
    'port': REDIS_PORT,
    'username': REDIS_USERNAME,
    'password': REDIS_PASSWORD,
    'ssl': True,
    'ssl_cert_reqs': 'none',
    'ssl_check_hostname': False,
    'decode_responses': True,
    'socket_connect_timeout': 5,
    'socket_timeout': 5,
})

# Test 3: SSL with custom SSL context
print("\n" + "="*60)
print("Test 3: SSL with custom context")
print("-" * 30)
try:
    # Create custom SSL context
    ssl_context = ssl.create_default_context()
    ssl_context.check_hostname = False
    ssl_context.verify_mode = ssl.CERT_NONE
    
    # Create connection pool with SSL context
    pool = redis.ConnectionPool(
        host=REDIS_HOST,
        port=REDIS_PORT,
        username=REDIS_USERNAME,
        password=REDIS_PASSWORD,
        connection_class=SSLConnection,
        decode_responses=True,
        socket_connect_timeout=5,
        socket_timeout=5,
        # SSL parameters
        ssl_cert_reqs='none',
        ssl_check_hostname=False,
    )
    
    client = redis.Redis(connection_pool=pool)
    response = client.ping()
    print(f"✓ Connection successful! PING response: {response}")
    client.close()
    
except Exception as e:
    print(f"✗ Failed: {type(e).__name__}: {str(e)}")

# Test 4: ConnectionPool with specific parameters
print("\n" + "="*60)
print("Test 4: ConnectionPool configuration")
print("-" * 36)
try:
    pool = redis.ConnectionPool(
        host=REDIS_HOST,
        port=REDIS_PORT,
        db=0,
        username=REDIS_USERNAME,
        password=REDIS_PASSWORD,
        decode_responses=True,
        max_connections=10,
        socket_keepalive=True,
        socket_keepalive_options={},
        socket_connect_timeout=5,
        socket_timeout=5,
    )
    
    client = redis.Redis(connection_pool=pool)
    response = client.ping()
    print(f"✓ Connection successful! PING response: {response}")
    
    # Test pool stats
    print(f"✓ Pool created connections: {pool.created_connections}")
    print(f"✓ Pool available connections: {len(pool._available_connections)}")
    
    client.close()
    
except Exception as e:
    print(f"✗ Failed: {type(e).__name__}: {str(e)}")

# Test 5: URL-based connection
print("\n" + "="*60)
print("Test 5: URL-based connection")
print("-" * 28)
try:
    # Build Redis URL
    redis_url = f"redis://{REDIS_USERNAME}:{REDIS_PASSWORD}@{REDIS_HOST}:{REDIS_PORT}/0"
    
    client = redis.from_url(redis_url, decode_responses=True)
    response = client.ping()
    print(f"✓ Connection successful! PING response: {response}")
    client.close()
    
except Exception as e:
    print(f"✗ Failed: {type(e).__name__}: {str(e)}")

# Test 6: Sentinel-style connection (if applicable)
print("\n" + "="*60)
print("Test 6: Testing AUTH mechanisms")
print("-" * 31)
try:
    # Test with explicit AUTH
    client = redis.Redis(
        host=REDIS_HOST,
        port=REDIS_PORT,
        password=REDIS_PASSWORD,
        username=REDIS_USERNAME,
        decode_responses=True,
    )
    
    # Try to authenticate
    client.ping()
    print(f"✓ AUTH successful with username/password")
    
    # Check ACL info if available
    try:
        acl_info = client.execute_command('ACL', 'WHOAMI')
        print(f"✓ Current user: {acl_info}")
    except:
        print("- ACL commands not available (Redis < 6.0)")
    
    client.close()
    
except Exception as e:
    print(f"✗ Failed: {type(e).__name__}: {str(e)}")

# Summary
print("\n" + "="*60)
print("Connection Test Summary")
print("="*60)
print(f"""
Based on the tests above, use the working configuration in your application.
The most common issue with Redis Cloud is SSL/TLS configuration.

If basic connection (Test 1) works but SSL doesn't:
- Redis Cloud may not require SSL on this port
- Use the non-SSL configuration

If you need to use SSL:
- Set ssl_cert_reqs='none' to disable certificate verification
- Set ssl_check_hostname=False
- Consider using a custom SSL context for more control
""")