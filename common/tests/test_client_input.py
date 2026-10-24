from datetime import date
from decimal import Decimal

import pytest
from rest_framework.exceptions import ValidationError

from common.client_input import (
    date_value,
    decimal_value,
    error_message,
    id_value,
    list_of_objects,
    money_value,
    quantity_value,
)


def _message(call, *args, **kwargs):
    with pytest.raises(ValidationError) as exc:
        call(*args, **kwargs)
    return error_message(exc.value)


class TestIdValue:
    @pytest.mark.parametrize("raw,expected", [(7, 7), ("12", 12), (" 9 ", 9), (2 ** 63 - 1, 2 ** 63 - 1)])
    def test_whole_numbers(self, raw, expected):
        assert id_value(raw, "product_id") == expected

    @pytest.mark.parametrize("raw", ["abc", "1.5", "", None, [1], True])
    def test_not_a_whole_number(self, raw):
        assert _message(id_value, raw, "product_id") == "product_id: Must be a whole number."

    @pytest.mark.parametrize("raw", [0, "-3", 2 ** 63])
    def test_out_of_range(self, raw):
        assert _message(id_value, raw, "order_id") == "order_id: Must be a positive id."


class TestNumbers:
    @pytest.mark.parametrize("raw,expected", [
        ("2.5", Decimal("2.5")), (3, Decimal("3")), (-4, Decimal("-4")), (0.25, Decimal("0.25")),
    ])
    def test_decimal_value(self, raw, expected):
        assert decimal_value(raw, "credit") == expected

    @pytest.mark.parametrize("raw", ["x", "nan", "inf", "-Infinity", None, True, {"a": 1}])
    def test_decimal_value_rejects(self, raw):
        assert _message(decimal_value, raw, "credit") == "credit: Must be a number."

    def test_quantity(self):
        assert quantity_value("0.125", "quantity") == Decimal("0.125")
        assert quantity_value(0, "quantity", allow_zero=True) == Decimal("0")
        assert _message(quantity_value, 0, "quantity") == "quantity: Must be more than zero."
        assert _message(quantity_value, "-1", "quantity") == "quantity: Must be more than zero."
        assert _message(quantity_value, -1, "quantity", allow_zero=True) == "quantity: Cannot be negative."
        assert _message(quantity_value, "1e9", "quantity") == "quantity: Is too large."

    def test_money(self):
        assert money_value("0", "price") == Decimal("0")
        assert money_value("99999999.99", "price") == Decimal("99999999.99")
        assert _message(money_value, "-0.01", "price") == "price: Cannot be negative."
        assert _message(money_value, "1e8", "price") == "price: Is too large."


class TestDateValue:
    def test_iso_date(self):
        assert date_value("2026-10-22", "start_date") == date(2026, 10, 22)

    @pytest.mark.parametrize("raw", ["x", "2026-02-30", "22/10/2026", ""])
    def test_rejects(self, raw):
        assert _message(date_value, raw, "start_date") == "start_date: Use a date in YYYY-MM-DD format."


class TestListOfObjects:
    def test_objects(self):
        rows = [{"product_id": 1}]
        assert list_of_objects(rows, "items") is rows

    @pytest.mark.parametrize("raw", ["x", [1, 2], [{"a": 1}, "b"], {"a": 1}, None])
    def test_rejects(self, raw):
        assert _message(list_of_objects, raw, "items") == "items: Must be a list of objects."


class TestErrorMessage:
    def test_dict_list_and_text_details(self):
        assert error_message(ValidationError({"a": ["x", "y"], "b": "z"})) == "a: x y b: z"
        assert error_message(ValidationError(["one", "two"])) == "one two"
