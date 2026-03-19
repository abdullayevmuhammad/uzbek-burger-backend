from decimal import Decimal

from django.contrib import admin
from django.test import TestCase

from catalog.admin import ProductAdmin
from catalog.models import Product, CountType
from core.models import Branch
from inventory.models import BranchProduct


class ProductValuationTests(TestCase):
    def test_weighted_avg_unit_cost_uses_base_units(self):
        branch_a = Branch.objects.create(name="A")
        branch_b = Branch.objects.create(name="B")
        product = Product.objects.create(name="Sut", count_type=CountType.L)

        BranchProduct.objects.create(
            branch=branch_a,
            product=product,
            stock_qty=Decimal("2.000"),
            avg_unit_cost=4,
        )
        BranchProduct.objects.create(
            branch=branch_b,
            product=product,
            stock_qty=Decimal("1.000"),
            avg_unit_cost=10,
        )

        self.assertEqual(product.weighted_avg_unit_cost, 6.0)

    def test_product_admin_avg_cost_uses_product_property(self):
        branch = Branch.objects.create(name="Main")
        product = Product.objects.create(name="Yog'", count_type=CountType.KG)
        BranchProduct.objects.create(
            branch=branch,
            product=product,
            stock_qty=Decimal("1.500"),
            avg_unit_cost=8,
        )

        admin_view = ProductAdmin(Product, admin.site)
        self.assertEqual(admin_view.avg_cost(product), 8.0)
