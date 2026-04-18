import pytest
from rest_framework.exceptions import ValidationError as DRFValidationError
from django.core.exceptions import ValidationError as DjangoValidationError
from common.error_utils import format_exception

class TestErrorUtils:
    
    def test_format_drf_validation_error_dict(self):
        e = DRFValidationError({"field1": ["error 1", "error 2"], "field2": ["error 3"]})
        result = format_exception(e)
        # Order might vary in dict, check for content
        assert "error 1" in result
        assert "error 2" in result
        assert "error 3" in result

    def test_format_drf_validation_error_list(self):
        e = DRFValidationError(["Generic error 1", "Generic error 2"])
        result = format_exception(e)
        assert result == "Generic error 1 Generic error 2"

    def test_format_django_validation_error_dict(self):
        e = DjangoValidationError({"field": ["Django error"]})
        result = format_exception(e)
        assert result == "Django error"

    def test_format_django_validation_error_list(self):
        e = DjangoValidationError(["Msg 1", "Msg 2"])
        result = format_exception(e)
        assert result == "Msg 1 Msg 2"

    def test_format_generic_exception(self):
        e = ValueError("Something went wrong")
        result = format_exception(e)
        assert result == "Something went wrong"
