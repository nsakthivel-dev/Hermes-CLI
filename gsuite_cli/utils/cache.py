"""
Advanced caching system for GSuite CLI
"""

import hashlib
import json
import time
import logging
from pathlib import Path
from typing import Any, Optional, Dict, Union
from functools import wraps
from datetime import datetime, timedelta

import diskcache as dc

logger = logging.getLogger(__name__)


class CacheManager:
    """Advanced caching manager with TTL and intelligent invalidation"""
    
    def __init__(self, cache_dir: Optional[str] = None, default_ttl: int = 300):
        """
        Initialize cache manager
        
        Args:
            cache_dir: Custom cache directory
            default_ttl: Default time-to-live in seconds (default: 5 minutes)
        """
        if cache_dir:
            self.cache_dir = Path(cache_dir)
        else:
            self.cache_dir = Path.home() / '.cache' / 'gsuite-cli'
        
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self.cache = dc.Cache(str(self.cache_dir))
        self.default_ttl = default_ttl
        
        # Cache statistics
        self.stats = {
            'hits': 0,
            'misses': 0,
            'sets': 0,
            'evictions': 0
        }
    
    def _generate_key(self, prefix: str, *args, **kwargs) -> str:
        """Generate cache key from arguments"""
        key_data = {
            'prefix': prefix,
            'args': args,
            'kwargs': sorted(kwargs.items())
        }
        key_string = json.dumps(key_data, sort_keys=True, default=str)
        hashed = hashlib.md5(key_string.encode()).hexdigest()
        return f"{prefix}:{hashed}"
    
    def get(self, key: str) -> Optional[Any]:
        """Get value from cache"""
        try:
            value = self.cache.get(key)
            if value is not None:
                self.stats['hits'] += 1
                logger.debug(f"Cache hit: {key}")
                return value
            else:
                self.stats['misses'] += 1
                logger.debug(f"Cache miss: {key}")
                return None
        except Exception as e:
            logger.warning(f"Cache get error: {e}")
            return None
    
    def set(self, key: str, value: Any, ttl: Optional[int] = None, expire: Optional[int] = None) -> bool:
        """Set value in cache with TTL (supports both ttl and expire keyword arguments)"""
        try:
            effective_ttl = expire if expire is not None else (ttl or self.default_ttl)
            self.cache.set(key, value, expire=effective_ttl)
            self.stats['sets'] += 1
            logger.debug(f"Cache set: {key} (TTL: {effective_ttl}s)")
            return True
        except Exception as e:
            logger.warning(f"Cache set error: {e}")
            return False
    
    def delete(self, key: str) -> bool:
        """Delete specific key from cache"""
        try:
            deleted = self.cache.delete(key)
            if deleted:
                logger.debug(f"Cache delete: {key}")
            return deleted
        except Exception as e:
            logger.warning(f"Cache delete error: {e}")
            return False
    
    def clear(self) -> bool:
        """Clear all cache"""
        try:
            self.cache.clear()
            logger.info("Cache cleared")
            return True
        except Exception as e:
            logger.error(f"Cache clear error: {e}")
            return False
    
    def get_stats(self) -> Dict[str, Any]:
        """Get cache statistics"""
        total_requests = self.stats['hits'] + self.stats['misses']
        hit_rate = (self.stats['hits'] / total_requests * 100) if total_requests > 0 else 0
        
        return {
            'hits': self.stats['hits'],
            'misses': self.stats['misses'],
            'sets': self.stats['sets'],
            'hit_rate_percent': round(hit_rate, 2),
            'total_items': len(self.cache),
            'cache_size_mb': round(self.cache.volume() / (1024 * 1024), 2),
            'cache_dir': str(self.cache_dir)
        }
    
    def expire(self, pattern: str = None) -> int:
        """Expire cache entries"""
        try:
            if pattern:
                # Delete keys matching pattern
                count = 0
                keys_to_delete = []
                for key in self.cache.iterkeys():
                    key_str = str(key) if not isinstance(key, bytes) else key.decode('utf-8', errors='ignore')
                    if pattern in key_str:
                        keys_to_delete.append(key)
                
                for key in keys_to_delete:
                    if self.cache.delete(key):
                        count += 1
                logger.info(f"Expired {count} cache entries matching '{pattern}'")
                return count
            else:
                # Let diskcache handle expired entries
                self.cache.expire()
                return 0
        except Exception as e:
            logger.error(f"Cache expire error: {e}")
            return 0
    
    def vacuum(self) -> bool:
        """Vacuum cache to reclaim space"""
        try:
            self.cache.vacuum()
            logger.info("Cache vacuumed")
            return True
        except Exception as e:
            logger.error(f"Cache vacuum error: {e}")
            return False


def cached(prefix: str, ttl: Optional[int] = None, cache_manager: Optional[CacheManager] = None):
    """
    Decorator for caching function results
    
    Args:
        prefix: Cache key prefix
        ttl: Time-to-live in seconds
        cache_manager: Custom cache manager instance
    """
    def decorator(func):
        @wraps(func)
        def wrapper(*args, **kwargs):
            # Use provided cache manager or create default one
            cache = cache_manager or CacheManager()
            
            # Generate cache key
            cache_key = cache._generate_key(prefix, *args, **kwargs)
            
            # Try to get from cache
            cached_result = cache.get(cache_key)
            if cached_result is not None:
                return cached_result
            
            # Execute function and cache result
            result = func(*args, **kwargs)
            if result is not None:
                cache.set(cache_key, result, ttl)
            
            return result
        
        # Add cache management methods to wrapped function
        wrapper.cache_clear = lambda: cache.clear()
        wrapper.cache_stats = lambda: cache.get_stats()
        wrapper.cache_expire = lambda pattern=None: cache.expire(pattern)
        
        return wrapper
    return decorator


class ServiceCache:
    """Service-specific cache wrapper"""
    
    def __init__(self, service_name: str, cache_manager: Optional[CacheManager] = None):
        self.service_name = service_name
        self.cache = cache_manager or CacheManager()
        self.prefix = f"{service_name}"
    
    def get(self, operation: str, *args, **kwargs) -> Optional[Any]:
        """Get cached result for service operation"""
        key = self.cache._generate_key(f"{self.prefix}.{operation}", *args, **kwargs)
        return self.cache.get(key)
    
    def set(self, operation: str, result: Any, ttl: Optional[int] = None, *args, **kwargs) -> bool:
        """Cache result for service operation"""
        key = self.cache._generate_key(f"{self.prefix}.{operation}", *args, **kwargs)
        return self.cache.set(key, result, ttl)
    
    def invalidate(self, *args, **kwargs) -> int:
        """Invalidate cached operations for this service"""
        # For maximum reliability, we clear everything for this service when ANY change occurs
        return self.cache.expire(self.prefix)
    
    def get_stats(self) -> Dict[str, Any]:
        """Get cache stats for this service"""
        stats = self.cache.get_stats()
        stats['service'] = self.service_name
        return stats


# Global cache instance
_global_cache = None


def get_global_cache() -> CacheManager:
    """Get global cache instance"""
    global _global_cache
    if _global_cache is None:
        _global_cache = CacheManager()
    return _global_cache


def cache_result(prefix: str, ttl: Optional[int] = None):
    """Simple cache decorator using global cache"""
    return cached(prefix, ttl, get_global_cache())


# Cache configuration utilities
def configure_cache(ttl: int = 300, cache_dir: Optional[str] = None, enabled: bool = True):
    """Configure global cache settings"""
    global _global_cache
    
    if not enabled:
        _global_cache = None
        return
    
    _global_cache = CacheManager(cache_dir, ttl)


def is_cache_enabled() -> bool:
    """Check if caching is enabled"""
    return _global_cache is not None
