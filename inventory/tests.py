import importlib
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.test import TestCase

from catalog.models import Product, CountType
from core.models import Branch
from finance.models import MoneyAccount
from inventory.models import BranchProduct, StockImport, StockImportItem
from inventory.services import post_stock_import


User = get_user_model()


class InventoryNormalizationTests(TestCase):
    def setUp(self):
        self.branch = Branch.objects.create(name="Main")
        self.user = User.objects.create_user(username="worker", password="x")
        self.account = MoneyAccount.objects.create(branch=self.branch, name="Cashbox")

    def test_kg_import_keeps_product_unit_stock_and_base_unit_cost(self):
        product = Product.objects.create(name="Un", count_type=CountType.KG)
        stock_import = StockImport.objects.create(branch=self.branch, created_by=self.user)
        StockImportItem.objects.create(
            stock_import=stock_import,
            product=product,
            qty=Decimal("2.000"),
            line_total_cost=10000,
        )

        post_stock_import(stock_import, by_user=self.user)

        bp = BranchProduct.objects.get(branch=self.branch, product=product)
        self.assertEqual(bp.stock_qty, Decimal("2.000"))
        self.assertEqual(bp.avg_unit_cost, 5)

    def test_liter_import_keeps_product_unit_stock_and_base_unit_cost(self):
        product = Product.objects.create(name="Cola Syrup", count_type=CountType.L)
        stock_import = StockImport.objects.create(branch=self.branch, created_by=self.user)
        StockImportItem.objects.create(
            stock_import=stock_import,
            product=product,
            qty=Decimal("3.000"),
            line_total_cost=9000,
        )

        post_stock_import(stock_import, by_user=self.user)

        bp = BranchProduct.objects.get(branch=self.branch, product=product)
        self.assertEqual(bp.stock_qty, Decimal("3.000"))
        self.assertEqual(bp.avg_unit_cost, 3)

    def test_post_stock_import_is_idempotent(self):
        product = Product.objects.create(name="Kartoshka", count_type=CountType.KG)
        stock_import = StockImport.objects.create(branch=self.branch, created_by=self.user)
        StockImportItem.objects.create(
            stock_import=stock_import,
            product=product,
            qty=Decimal("1.000"),
            line_total_cost=7000,
        )

        post_stock_import(stock_import, by_user=self.user)
        post_stock_import(stock_import, by_user=self.user)

        bp = BranchProduct.objects.get(branch=self.branch, product=product)
        self.assertEqual(bp.stock_qty, Decimal("1.000"))
        self.assertEqual(bp.avg_unit_cost, 7)

    def test_normalize_units_migration_depends_on_existing_menu_migration(self):
        module = importlib.import_module("inventory.migrations.0002_normalize_units")
        self.assertIn(("menu", "0002_setitem"), module.Migration.dependencies)
