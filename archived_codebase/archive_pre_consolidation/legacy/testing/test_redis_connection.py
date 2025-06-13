#!/usr/bin/env python3
"""Test Redis connection with different configurations"""
import os
import redis
import ssl

# Get Redis Cloud credentials
endpoint = os.getenv('REDIS_PUBLIC_ENDPOINT', '')
password = os.getenv('REDIS_PW')
username = os.getenv('REDIS_USERNAME')

if endpoint and ':' in endpoint:
    host, port = endpoint.rsplit(':', 1)
    port = int(port)
else:
    host = 'localhost'
    port = 6379

print(f"Testing connection to Redis:")
print(f"Host: {host}")
print(f"Port: {port}")
print(f"Username: {username}")
print(f"Password: {'***' if password else 'None'}")

# Test 1: Try with SSL and certificate verification disabled
print("\nTest 1: SSL with no cert verification")
try:
    client = redis.Redis(
        host=host,
        port=port,
        username=username,
        password=password,
        ssl=True,
        ssl_cert_reqs='none',
        ssl_check_hostname=False,
        decode_responses=True
    )
    client.ping()
    print("✓ Connected successfully with SSL!")
except Exception as e:
    print(f"✗ Failed: {e}")

# Test 2: Try without SSL
print("\nTest 2: Without SSL")
try:
    client = redis.Redis(
        host=host,
        port=port,
        username=username,
        password=password,
        ssl=False,
        decode_responses=True
    )
    client.ping()
    print("✓ Connected successfully without SSL!")
except Exception as e:
    print(f"✗ Failed: {e}")

# Test 3: Try with SSL using SSLContext
print("\nTest 3: SSL with custom context")
try:
    ssl_context = ssl.create_default_context()
    ssl_context.check_hostname = False
    ssl_context.verify_mode = ssl.CERT_NONE
    
    client = redis.Redis(
        host=host,
        port=port,
        username=username,
        password=password,
        ssl=True,
        ssl_context=ssl_context,
        decode_responses=True
    )
    client.ping()
    print("✓ Connected successfully with custom SSL context!")
except Exception as e:
    print(f"✗ Failed: {e}")