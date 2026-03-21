from decimal import Decimal

from django.contrib.auth import get_user_model
from django.http import HttpResponse
from django.test import RequestFactory, SimpleTestCase, TestCase, override_settings
from django.urls import reverse

from config import urls_landing, urls_pos
from core.middleware import ActiveBranchMiddleware, AdminGuardMiddleware
from core.models import Branch
from core.services import archive_branch, purge_branch
from finance.models import MoneyAccount, TxnType
from finance.services import create_cash_adjustment
from inventory.models import BranchProduct, StockImport, StockImportItem
from inventory.services import post_stock_import
from menu.models import Food, FoodCategory, FoodType
from sales.models import Order
from sales.services import create_order_with_items
from users.models import StaffProfile, StaffRole


class DummyUser:
    def __init__(self, *, is_authenticated=True, is_superuser=False, profile=None):
        self.is_authenticated = is_authenticated
        self.is_superuser = is_superuser
        self.profile = profile


class RootUrlConfSplitTests(SimpleTestCase):
    def test_pos_urlconf_contains_internal_routes(self):
        routes = [str(pattern.pattern) for pattern in urls_pos.urlpatterns]
        self.assertIn("admin/", routes)
        self.assertIn("accounts/", routes)
        self.assertIn("pos/", routes)

    def test_landing_urlconf_is_landing_only(self):
        routes = [str(pattern.pattern) for pattern in urls_landing.urlpatterns]
        self.assertEqual(routes, [""])


class ActiveBranchMiddlewareTests(SimpleTestCase):
    def setUp(self):
        self.factory = RequestFactory()

    @override_settings(POS_MODE=False, ROOT_URLCONF="config.urls_landing")
    def test_landing_mode_skips_active_branch_enforcement(self):
        middleware = ActiveBranchMiddleware(lambda request: HttpResponse("ok"))
        request = self.factory.get("/")
        request.user = DummyUser(is_authenticated=True, is_superuser=True)
        request.session = {}

        response = middleware(request)

        self.assertEqual(response.status_code, 200)

    @override_settings(POS_MODE=True, ROOT_URLCONF="config.urls_landing")
    def test_missing_select_branch_route_does_not_crash(self):
        middleware = ActiveBranchMiddleware(lambda request: HttpResponse("ok"))
        request = self.factory.get("/")
        request.user = DummyUser(is_authenticated=True, is_superuser=True)
        request.session = {}

        response = middleware(request)

        self.assertEqual(response.status_code, 200)
        self.assertTrue(hasattr(request, "active_branch"))
        self.assertIsNone(request.active_branch)


User = get_user_model()


class AdminAccessTests(TestCase):
    def setUp(self):
        self.cashier = User.objects.create_user("cashier_admin", password="x")
        self.admin_user = User.objects.create_user("admin_admin", password="x", is_staff=True)
        self.superuser = User.objects.create_superuser("super_admin", "super_admin@example.com", "x")
        self.branch = Branch.objects.create(name="Admin Branch")
        StaffProfile.objects.create(user=self.cashier, role=StaffRole.CASHIER, branch=self.branch, is_active=True)
        StaffProfile.objects.create(user=self.admin_user, role=StaffRole.ADMIN, is_active=True)

    def test_cashier_cannot_access_admin(self):
        self.client.force_login(self.cashier)
        response = self.client.get("/admin/")
        self.assertEqual(response.status_code, 403)

    def test_admin_can_access_admin(self):
        self.client.force_login(self.admin_user)
        response = self.client.get("/admin/")
        self.assertEqual(response.status_code, 200)

    def test_superuser_has_full_access(self):
        self.client.force_login(self.superuser)
        response = self.client.get("/admin/")
        self.assertEqual(response.status_code, 200)


class BranchArchiveAndPurgeTests(TestCase):
    def setUp(self):
        self.branch = Branch.objects.create(name="Branch Ops")
        self.superuser = User.objects.create_superuser("super_ops", "super_ops@example.com", "x")
        self.admin_user = User.objects.create_user("admin_ops", password="x", is_staff=True)
        StaffProfile.objects.create(user=self.admin_user, role=StaffRole.ADMIN, is_active=True)
        self.cashier = User.objects.create_user("cashier_ops", password="x")
        self.cashier_profile = StaffProfile.objects.create(
            user=self.cashier,
            role=StaffRole.CASHIER,
            branch=self.branch,
            is_active=True,
        )
        self.account = MoneyAccount.objects.create(branch=self.branch, name="Main cash")
        self.category = FoodCategory.objects.create(branch=self.branch, name="Burger", type=FoodType.FASTFOOD)
        self.food = Food.objects.create(branch=self.branch, category=self.category, name="Burger", sell_price=20000)

    def _activate_branch(self, user):
        self.client.force_login(user)
        session = self.client.session
        session["active_branch_id"] = str(self.branch.id)
        session.save()

    def test_archived_branch_cannot_be_used_in_pos(self):
        archive_branch(branch=self.branch, actor=self.admin_user)
        self._activate_branch(self.cashier)

        response = self.client.get(reverse("sales:pos_orders"))

        self.assertEqual(response.status_code, 403)

    def test_archived_branch_cannot_receive_new_operations(self):
        archive_branch(branch=self.branch, actor=self.admin_user)

        with self.assertRaisesMessage(ValueError, "Filial arxivlangan yoki noaktiv"):
            create_order_with_items(
                branch=self.branch,
                created_by=self.cashier,
                order_type="dine_in",
                note=None,
                items=[{"food": str(self.food.id), "qty": 1}],
            )

        with self.assertRaises(ValueError):
            create_cash_adjustment(
                account=self.account,
                txn_type=TxnType.CASH_IN,
                amount=1000,
                reason="Archive test",
                note="Should fail on archived branch",
                actor=self.superuser,
            )

    def test_purge_is_superuser_only(self):
        with self.assertRaises(PermissionError):
            purge_branch(branch=self.branch, actor=self.admin_user)

    def test_purge_removes_branch_related_records_cleanly(self):
        from catalog.models import CountType, Product

        product = Product.objects.create(name="Meat cleanup", count_type=CountType.KG)
        BranchProduct.objects.create(branch=self.branch, product=product, stock_qty=Decimal("2.000"))

        order = create_order_with_items(
            branch=self.branch,
            created_by=self.cashier,
            order_type="dine_in",
            note="purge me",
            items=[{"food": str(self.food.id), "qty": 1}],
        )

        stock_import = StockImport.objects.create(branch=self.branch, created_by=self.admin_user)
        StockImportItem.objects.create(
            stock_import=stock_import,
            product=product,
            qty=Decimal("1.000"),
            line_total_cost=5000,
        )
        post_stock_import(stock_import, by_user=self.admin_user)

        purge_branch(branch=self.branch, actor=self.superuser)

        self.assertFalse(Branch.objects.filter(pk=self.branch.pk).exists())
        self.assertFalse(Order.objects.filter(pk=order.pk).exists())
        self.assertFalse(MoneyAccount.objects.filter(branch_id=self.branch.pk).exists())
        self.assertFalse(Food.objects.filter(branch_id=self.branch.pk).exists())
        self.assertFalse(FoodCategory.objects.filter(branch_id=self.branch.pk).exists())
        self.assertFalse(BranchProduct.objects.filter(branch_id=self.branch.pk).exists())
        self.assertFalse(StockImport.objects.filter(branch_id=self.branch.pk).exists())
        self.cashier_profile.refresh_from_db()
        self.assertIsNone(self.cashier_profile.branch_id)
        self.assertFalse(self.cashier_profile.is_active)


class AdminGuardMiddlewareTests(SimpleTestCase):
    def test_cashier_is_blocked_from_admin(self):
        middleware = AdminGuardMiddleware(lambda request: HttpResponse("ok"))
        request = RequestFactory().get("/admin/")
        request.user = DummyUser(is_authenticated=True, is_superuser=False, profile=type("P", (), {"role": "cashier", "is_active": True})())

        response = middleware(request)

        self.assertEqual(response.status_code, 403)
