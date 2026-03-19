from django.test import SimpleTestCase

from finance.utils import parse_uzs_amount


class ParseUZSAmountTests(SimpleTestCase):
    def test_plain_integer_string(self):
        self.assertEqual(parse_uzs_amount("50000"), 50000)

    def test_space_grouped_integer_string(self):
        self.assertEqual(parse_uzs_amount("50 000"), 50000)

    def test_comma_grouped_integer_string(self):
        self.assertEqual(parse_uzs_amount("50,000"), 50000)

    def test_invalid_mixed_string_rejected(self):
        with self.assertRaises(ValueError):
            parse_uzs_amount("50, 000")

    def test_float_rejected(self):
        with self.assertRaises(ValueError):
            parse_uzs_amount(100.5)
