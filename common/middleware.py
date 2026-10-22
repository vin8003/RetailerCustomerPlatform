import re
import time
import logging
from django.http import JsonResponse
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


# An unescaped \u0000 in a JSON body (an even run of backslashes before it is just text).
_JSON_NUL = re.compile(rb'(?<!\\)(?:\\\\)*\\u0000')


class RejectNulCharactersMiddleware(MiddlewareMixin):
    """
    PostgreSQL text cannot hold NUL, so a query value or JSON string with one reached
    the database driver and the view answered 500. Refuse it here with a 400 instead.
    JSON bodies above DATA_UPLOAD_MAX_MEMORY_SIZE are left alone, as before.
    """

    def process_request(self, request):
        if self._query_has_nul(request) or self._json_body_has_nul(request):
            return JsonResponse(
                {'error': 'Text cannot contain the NUL character (\\u0000).'},
                status=400,
            )
        return None

    @staticmethod
    def _query_has_nul(request):
        return any(
            '\x00' in key or any('\x00' in value for value in values)
            for key, values in request.GET.lists()
        )

    @staticmethod
    def _json_body_has_nul(request):
        if 'json' not in request.META.get('CONTENT_TYPE', ''):
            return False
        try:
            length = int(request.META.get('CONTENT_LENGTH') or 0)
        except ValueError:
            return False
        limit = settings.DATA_UPLOAD_MAX_MEMORY_SIZE
        if length <= 0 or (limit is not None and length > limit):
            return False
        return _JSON_NUL.search(request.body) is not None
