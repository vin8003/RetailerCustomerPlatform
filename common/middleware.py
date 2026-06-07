import time
import logging
from django.utils.deprecation import MiddlewareMixin
from django.conf import settings

logger = logging.getLogger('django.request')

class RequestLoggingMiddleware(MiddlewareMixin):
    """
    Middleware to log all incoming requests and outgoing responses.
    Captures method, path, status code, user, and execution time.
    """
    
    def process_request(self, request):
        request.start_time = time.time()

    def process_response(self, request, response):
        if hasattr(request, 'start_time'):
            duration = time.time() - request.start_time
        else:
            duration = 0.0

        user = getattr(request, 'user', None)
        user_info = f"User:{user.id}" if user and user.is_authenticated else "Anonymous"

        # Do not log sensitive endpoints excessively or with payloads, 
        # but basic request info is fine.
        log_message = (
            f"Method={request.method} "
            f"Path={request.path} "
            f"Status={response.status_code} "
            f"Duration={duration:.3f}s "
            f"{user_info}"
        )

        # Log as WARNING if status is 4xx, ERROR if 5xx, else INFO
        if response.status_code >= 500:
            logger.error(log_message)
        elif response.status_code >= 400:
            logger.warning(log_message)
        else:
            logger.info(log_message)

        return response
