# products/tax_service.py
from __future__ import annotations
from decimal import Decimal, ROUND_HALF_UP
from typing import Literal

GST_RATES = (
    Decimal('0'),
    Decimal('3'),
    Decimal('5'),
    Decimal('18'),
    Decimal('40'),
)
TWO = Decimal('0.01')
HSN_MAX_LENGTH = 8
TaxType = Literal['GST', 'IGST']


def clean_hsn_code(value) -> str:
    """Normalize an HSN code for storage.

    Raises ValueError for anything the varchar(8) column cannot hold, so callers
    that bypass serializer validation fail with a 400 instead of a DataError.
    """
    hsn = str(value).strip()
    if not hsn:
        return ''
    if not hsn.isdigit() or len(hsn) > HSN_MAX_LENGTH:
        raise ValueError(
            f'Invalid HSN code: {value}. Use up to {HSN_MAX_LENGTH} digits.'
        )
    return hsn


def quantize_2(value: Decimal) -> Decimal:
    return value.quantize(TWO, rounding=ROUND_HALF_UP)


def round_rupee(amount: Decimal) -> Decimal:
    return amount.quantize(Decimal('1'), rounding=ROUND_HALF_UP)


def gstin_state_code(gstin: str | None) -> str | None:
    if not gstin:
        return None
    g = ''.join(c for c in str(gstin).upper() if c.isalnum())
    if len(g) < 2 or not g[:2].isdigit():
        return None
    return g[:2]


def resolve_tax_type(seller_gstin: str | None, counterparty_gstin: str | None) -> TaxType:
    a = gstin_state_code(seller_gstin)
    b = gstin_state_code(counterparty_gstin)
    if a and b and a != b:
        return 'IGST'
    return 'GST'


def split_inclusive_line(line_total: Decimal, gst_rate: Decimal) -> dict:
    line_total = quantize_2(Decimal(line_total))
    rate = Decimal(gst_rate)
    if rate not in GST_RATES:
        raise ValueError(f'Unsupported GST rate: {rate}')
    if rate == 0:
        return {
            'line_total': line_total,
            'taxable_value': line_total,
            'tax_amount': Decimal('0.00'),
        }
    taxable = quantize_2(line_total / (Decimal('1') + rate / Decimal('100')))
    tax = quantize_2(line_total - taxable)
    return {
        'line_total': line_total,
        'taxable_value': taxable,
        'tax_amount': tax,
    }


def allocate_order_discount(line_totals: list[Decimal], discount: Decimal) -> list[Decimal]:
    """Return inclusive line totals after proportional discount. Last line absorbs remainder."""
    discount = quantize_2(Decimal(discount))
    if discount <= 0:
        return [quantize_2(t) for t in line_totals]
    totals = [quantize_2(t) for t in line_totals]
    grand = sum(totals, Decimal('0.00'))
    if grand <= 0:
        return totals
    discount = min(discount, grand)
    remaining_discount = discount
    result: list[Decimal] = []
    for i, t in enumerate(totals):
        if i == len(totals) - 1:
            share = remaining_discount
        else:
            share = quantize_2(discount * t / grand)
            remaining_discount -= share
        result.append(quantize_2(t - share))
    return result
