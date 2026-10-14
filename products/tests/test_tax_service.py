# products/tests/test_tax_service.py
from decimal import Decimal
from django.test import SimpleTestCase
from products.tax_service import (
    split_inclusive_line,
    resolve_tax_type,
    gstin_state_code,
    allocate_order_discount,
    round_rupee,
)


class TaxServiceTests(SimpleTestCase):
    def test_zero_rate_passthrough(self):
        r = split_inclusive_line(Decimal('100.00'), Decimal('0'))
        self.assertEqual(r['taxable_value'], Decimal('100.00'))
        self.assertEqual(r['tax_amount'], Decimal('0.00'))

    def test_inclusive_18(self):
        # 118 inclusive @ 18% → taxable 100, tax 18
        r = split_inclusive_line(Decimal('118.00'), Decimal('18'))
        self.assertEqual(r['taxable_value'], Decimal('100.00'))
        self.assertEqual(r['tax_amount'], Decimal('18.00'))

    def test_inclusive_5_paise(self):
        r = split_inclusive_line(Decimal('105.00'), Decimal('5'))
        self.assertEqual(r['taxable_value'], Decimal('100.00'))
        self.assertEqual(r['tax_amount'], Decimal('5.00'))

    def test_gstin_state(self):
        self.assertEqual(gstin_state_code('27AAAAA0000A1Z5'), '27')
        self.assertIsNone(gstin_state_code(''))
        self.assertIsNone(gstin_state_code('BAD'))

    def test_tax_type_default_gst(self):
        self.assertEqual(resolve_tax_type('27AAAAA0000A1Z5', ''), 'GST')
        self.assertEqual(resolve_tax_type('27AAAAA0000A1Z5', '27BBBBB0000B1Z5'), 'GST')
        self.assertEqual(resolve_tax_type('27AAAAA0000A1Z5', '09CCCCC0000C1Z5'), 'IGST')

    def test_allocate_discount(self):
        # lines 100+300=400, discount 40 → 10 and 30 off
        out = allocate_order_discount(
            [Decimal('100.00'), Decimal('300.00')],
            Decimal('40.00'),
        )
        self.assertEqual(out, [Decimal('90.00'), Decimal('270.00')])

    def test_round_rupee(self):
        self.assertEqual(round_rupee(Decimal('10.50')), Decimal('11'))
        self.assertEqual(round_rupee(Decimal('10.49')), Decimal('10'))
