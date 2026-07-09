import time
from datetime import datetime, timedelta
import zoneinfo
from django.core.cache import cache
from rest_framework.exceptions import APIException

class RateLimitExceeded(APIException):
    status_code = 429
    default_code = 'rate_limit_exceeded'
    
    def __init__(self, error_code, message, retry_after):
        self.detail = {
            "error": error_code,
            "message": message,
            "retry_after": retry_after
        }

def get_seconds_until_aest_midnight():
    aest = zoneinfo.ZoneInfo('Australia/Sydney')
    now_utc = datetime.now(zoneinfo.ZoneInfo('UTC'))
    now_aest = now_utc.astimezone(aest)
    
    tomorrow_aest = (now_aest + timedelta(days=1)).replace(hour=0, minute=0, second=0, microsecond=0)
    return int((tomorrow_aest - now_aest).total_seconds())

def check_unauthenticated_rate_limit(ip_address):
    key = f"support_rl:ip:{ip_address}"
    limit = 3
    ttl_seconds = 3600
    
    now = int(time.time())
    data = cache.get(key)
    
    if data:
        count = data.get('count', 0)
        reset_time = data.get('reset_time', now + ttl_seconds)
    else:
        count = 0
        reset_time = now + ttl_seconds
        
    if count >= limit:
        retry_after = max(0, reset_time - now)
        raise RateLimitExceeded(
            error_code="rate_limit_exceeded",
            message="Too many requests. Please try again later.",
            retry_after=retry_after
        )
        
    # Increment and save
    cache.set(key, {'count': count + 1, 'reset_time': reset_time}, timeout=max(0, reset_time - now))

def check_authenticated_rate_limit(user_id):
    key = f"support_rl:user:{user_id}"
    limit = 10
    now = int(time.time())
    
    data = cache.get(key)
    if data:
        count = data.get('count', 0)
        reset_time = data.get('reset_time', now + get_seconds_until_aest_midnight())
    else:
        count = 0
        reset_time = now + get_seconds_until_aest_midnight()
        
    if count >= limit:
        retry_after = max(0, reset_time - now)
        raise RateLimitExceeded(
            error_code="daily_limit_exceeded",
            message="You have reached the daily support submission limit. Please try again tomorrow.",
            retry_after=retry_after
        )
        
    cache.set(key, {'count': count + 1, 'reset_time': reset_time}, timeout=max(0, reset_time - now))

def get_authenticated_rate_limit_status(user_id):
    key = f"support_rl:user:{user_id}"
    limit = 10
    data = cache.get(key)
    count = data.get('count', 0) if data else 0
    return {
        "submissions_today": count,
        "daily_limit": limit,
        "remaining": max(0, limit - count)
    }

