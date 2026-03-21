from decimal import Decimal
from pathlib import Path

from django.contrib import admin
from django.contrib.messages.storage.fallback import FallbackStorage
from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.test import RequestFactory, TestCase, SimpleTestCase
from django.urls import reverse

from catalog.models import CountType, Product
from core.models import Branch
from finance.admin import CashTransactionAdmin
from finance.models import CashTransaction, MoneyAccount
from inventory.models import BranchProduct
from menu.models import Food, FoodCategory, FoodItem, FoodType
from sales.admin import OrderAdmin
from sales.models import Order, OrderItem, OrderPayment, KitchenTask
from sales.services import (
    OrderValidationError,
    add_item,
    cancel_order,
    create_order_with_items,
    delete_order_for_recovery,
    delete_orders_for_recovery,
    mark_delivered,
    pay_order,
)
from users.models import StaffProfile, StaffRole


User = get_user_model()


class LayoutCssTests(SimpleTestCase):
    def test_pos_layout_ratio_and_breakpoint(self):
        css = Path("static/css/app.css").read_text(encoding="utf-8")
        self.assertIn("grid-template-columns: 7fr 3fr", css)
        self.assertIn("@media (max-width: 880px)", css)


class SalesFlowTests(TestCase):
    def setUp(self):
        self.factory = RequestFactory()
        self.branch_a = Branch.objects.create(name="Branch A")
        self.branch_b = Branch.objects.create(name="Branch B")

        self.superuser = User.objects.create_superuser("admin", "admin@example.com", "x")
        self.admin_user = User.objects.create_user("owner", password="x", is_staff=True)
        StaffProfile.objects.create(user=self.admin_user, role=StaffRole.ADMIN, is_active=True)

        self.staff_a = User.objects.create_user("staff_a", password="x")
        StaffProfile.objects.create(user=self.staff_a, role=StaffRole.CASHIER, branch=self.branch_a, is_active=True)

        self.staff_b = User.objects.create_user("staff_b", password="x")
        StaffProfile.objects.create(user=self.staff_b, role=StaffRole.CASHIER, branch=self.branch_b, is_active=True)

        self.account_a = MoneyAccount.objects.get(branch=self.branch_a, name="Kassa")
        self.account_a.name = "Cash A"
        self.account_a.save(update_fields=["name"])
        self.account_b = MoneyAccount.objects.get(branch=self.branch_b, name="Kassa")
        self.account_b.name = "Cash B"
        self.account_b.save(update_fields=["name"])

        self.category_a = FoodCategory.objects.create(branch=self.branch_a, name="Burger", type=FoodType.FASTFOOD)
        self.category_b = FoodCategory.objects.create(branch=self.branch_b, name="Drink", type=FoodType.DRINK)
        self.food_a = Food.objects.create(
            branch=self.branch_a,
            category=self.category_a,
            name="Cheese Burger",
            sell_price=10000,
        )
        self.food_b = Food.objects.create(
            branch=self.branch_b,
            category=self.category_b,
            name="Cola",
            sell_price=12000,
            type=FoodType.DRINK,
        )

        self.product_kg = Product.objects.create(name="Go'sht", count_type=CountType.KG)
        FoodItem.objects.create(food=self.food_a, product=self.product_kg, qty=Decimal("0.200"))
        BranchProduct.objects.create(
            branch=self.branch_a,
            product=self.product_kg,
            stock_qty=Decimal("5.000"),
            avg_unit_cost=20,
        )

        self.order_admin = OrderAdmin(Order, admin.site)

    def _activate_branch(self, user, branch):
        self.client.force_login(user)
        session = self.client.session
        session["active_branch_id"] = str(branch.id)
        session.save()

    def test_admin_superuser_sees_all_orders(self):
        order_a = Order.objects.create(branch=self.branch_a)
        order_b = Order.objects.create(branch=self.branch_b)

        request = self.factory.get("/")
        request.user = self.superuser

        qs = self.order_admin.get_queryset(request)
        self.assertSetEqual(set(qs.values_list("id", flat=True)), {order_a.id, order_b.id})

    def test_admin_operational_user_sees_all_orders(self):
        Order.objects.create(branch=self.branch_a)
        Order.objects.create(branch=self.branch_b)

        request = self.factory.get("/")
        request.user = self.admin_user

        self.assertEqual(self.order_admin.get_queryset(request).count(), 2)

    def test_cashier_does_not_get_admin_delete_permission(self):
        order_a = Order.objects.create(branch=self.branch_a)

        request = self.factory.get("/")
        request.user = self.staff_a

        self.assertFalse(self.order_admin.has_delete_permission(request, order_a))

    def test_invalid_items_fail_order_creation_instead_of_dropping(self):
        with self.assertRaises(OrderValidationError):
            create_order_with_items(
                branch=self.branch_a,
                created_by=self.staff_a,
                order_type=Order.OrderType.DINE_IN,
                note=None,
                items=[
                    {"food": str(self.food_a.id), "qty": 1},
                    {"food": "missing", "qty": 1},
                ],
            )
        self.assertEqual(Order.objects.count(), 0)

    def test_all_invalid_items_do_not_create_order(self):
        with self.assertRaises(OrderValidationError):
            create_order_with_items(
                branch=self.branch_a,
                created_by=self.staff_a,
                order_type=Order.OrderType.DINE_IN,
                note=None,
                items=[{"food": "missing", "qty": 0}],
            )
        self.assertEqual(Order.objects.count(), 0)

    def test_duplicate_valid_items_are_coalesced(self):
        order = create_order_with_items(
            branch=self.branch_a,
            created_by=self.staff_a,
            order_type=Order.OrderType.DINE_IN,
            note=None,
            items=[
                {"food": str(self.food_a.id), "qty": 1},
                {"food": str(self.food_a.id), "qty": 2},
            ],
        )

        item = order.items.get()
        self.assertEqual(item.qty, 3)
        self.assertEqual(order.total_amount, 30000)

    def test_payment_full_amount_sets_status_paid(self):
        order = create_order_with_items(
            branch=self.branch_a,
            created_by=self.staff_a,
            order_type=Order.OrderType.DINE_IN,
            note=None,
            items=[{"food": str(self.food_a.id), "qty": 1}],
        )

        pay_order(order, account=self.account_a, amount=10000, by_user=self.staff_a)

        order.refresh_from_db()
        self.assertEqual(order.status, Order.Status.PAID)
        self.assertEqual(order.paid_amount, 10000)

    def test_delivered_and_fully_paid_locks_exactly_once(self):
        order = create_order_with_items(
            branch=self.branch_a,
            created_by=self.staff_a,
            order_type=Order.OrderType.DINE_IN,
            note=None,
            items=[{"food": str(self.food_a.id), "qty": 1}],
        )

        mark_delivered(order, by_user=self.staff_a)
        pay_order(order, account=self.account_a, amount=10000, by_user=self.staff_a)
        order.refresh_from_db()
        locked_at = order.locked_at

        mark_delivered(order, by_user=self.staff_a)
        order.refresh_from_db()

        self.assertTrue(order.is_locked)
        self.assertEqual(order.locked_at, locked_at)

    def test_overpayment_is_blocked(self):
        order = create_order_with_items(
            branch=self.branch_a,
            created_by=self.staff_a,
            order_type=Order.OrderType.DINE_IN,
            note=None,
            items=[{"food": str(self.food_a.id), "qty": 1}],
        )

        with self.assertRaises(ValueError):
            pay_order(order, account=self.account_a, amount=20000, by_user=self.staff_a)

    def test_delivery_is_idempotent_for_stock(self):
        order = create_order_with_items(
            branch=self.branch_a,
            created_by=self.staff_a,
            order_type=Order.OrderType.DINE_IN,
            note=None,
            items=[{"food": str(self.food_a.id), "qty": 2}],
        )

        mark_delivered(order, by_user=self.staff_a)
        mark_delivered(order, by_user=self.staff_a)

        branch_product = BranchProduct.objects.get(branch=self.branch_a, product=self.product_kg)
        self.assertEqual(branch_product.stock_qty, Decimal("4.600"))

    def test_locked_order_cannot_be_edited(self):
        order = create_order_with_items(
            branch=self.branch_a,
            created_by=self.staff_a,
            order_type=Order.OrderType.DINE_IN,
            note=None,
            items=[{"food": str(self.food_a.id), "qty": 1}],
        )
        order.is_locked = True
        order.save(update_fields=["is_locked"])

        with self.assertRaises(ValueError):
            add_item(order, food=self.food_a, qty=1)

    def test_branch_mismatch_payment_rejected(self):
        order = create_order_with_items(
            branch=self.branch_a,
            created_by=self.staff_a,
            order_type=Order.OrderType.DINE_IN,
            note=None,
            items=[{"food": str(self.food_a.id), "qty": 1}],
        )

        with self.assertRaises(ValueError):
            pay_order(order, account=self.account_b, amount=1000, by_user=self.staff_a)

    def test_order_item_cross_branch_save_is_rejected(self):
        order = Order.objects.create(branch=self.branch_a, created_by=self.staff_a)
        with self.assertRaises(ValidationError):
            OrderItem.objects.create(order=order, food=self.food_b, qty=1, unit_price=1, line_total=1)

    def test_cancel_order_before_payment_and_delivery(self):
        order = create_order_with_items(
            branch=self.branch_a,
            created_by=self.staff_a,
            order_type=Order.OrderType.DINE_IN,
            note=None,
            items=[{"food": str(self.food_a.id), "qty": 1}],
        )

        cancel_order(order, by_user=self.staff_a)
        order.refresh_from_db()
        self.assertEqual(order.status, Order.Status.CANCELED)

    def test_cancel_order_after_payment_is_blocked(self):
        order = create_order_with_items(
            branch=self.branch_a,
            created_by=self.staff_a,
            order_type=Order.OrderType.DINE_IN,
            note=None,
            items=[{"food": str(self.food_a.id), "qty": 1}],
        )
        pay_order(order, account=self.account_a, amount=10000, by_user=self.staff_a)

        with self.assertRaises(ValueError):
            cancel_order(order, by_user=self.staff_a)

    def test_receipt_route_supports_58mm_and_80mm(self):
        order = create_order_with_items(
            branch=self.branch_a,
            created_by=self.staff_a,
            order_type=Order.OrderType.DINE_IN,
            note=None,
            items=[{"food": str(self.food_a.id), "qty": 1}],
        )
        self._activate_branch(self.staff_a, self.branch_a)

        response_58 = self.client.get(reverse("sales:pos_order_receipt", args=[order.pk]) + "?paper=58")
        response_80 = self.client.get(reverse("sales:pos_order_receipt", args=[order.pk]) + "?paper=80")

        self.assertContains(response_58, "58mm")
        self.assertContains(response_80, "80mm")

    def test_cancel_action_view_cancels_safe_order(self):
        order = create_order_with_items(
            branch=self.branch_a,
            created_by=self.staff_a,
            order_type=Order.OrderType.DINE_IN,
            note=None,
            items=[{"food": str(self.food_a.id), "qty": 1}],
        )
        self._activate_branch(self.staff_a, self.branch_a)

        response = self.client.post(reverse("sales:pos_order_cancel", args=[order.pk]))

        self.assertEqual(response.status_code, 302)
        order.refresh_from_db()
        self.assertEqual(order.status, Order.Status.CANCELED)

    def test_create_order_view_surfaces_invalid_item_error(self):
        self._activate_branch(self.staff_a, self.branch_a)

        response = self.client.post(
            reverse("sales:pos_order_create"),
            {
                "items_json": '[{"food": "%s", "qty": 1}, {"food": "missing", "qty": 1}]' % self.food_a.id,
                "order_type": Order.OrderType.DINE_IN,
            },
            follow=True,
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "xato itemlar")
        self.assertEqual(Order.objects.count(), 0)

    def test_create_order_view_hides_dropdown_for_single_account(self):
        self._activate_branch(self.staff_a, self.branch_a)

        response = self.client.get(reverse("sales:pos_order_create"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "To'lov hisobi")
        self.assertContains(response, f'value="{self.account_a.id}"', html=False)
        self.assertNotContains(response, '<select class="control" name="account_id"', html=False)
        self.assertNotContains(response, "Tanlang...")

    def test_create_order_view_uses_single_account_without_dropdown_selection(self):
        self._activate_branch(self.staff_a, self.branch_a)

        response = self.client.post(
            reverse("sales:pos_order_create"),
            {
                "items_json": '[{"food": "%s", "qty": 1}]' % self.food_a.id,
                "order_type": Order.OrderType.DINE_IN,
                "is_paid": "1",
                "paid_amount": "10000",
            },
            follow=True,
        )

        self.assertEqual(response.status_code, 200)
        order = Order.objects.get(branch=self.branch_a)
        self.assertEqual(order.paid_amount, 10000)
        self.assertEqual(order.status, Order.Status.PAID)

    def test_pos_create_page_hides_sidebar(self):
        self._activate_branch(self.staff_a, self.branch_a)
        response = self.client.get(reverse("sales:pos_order_create"))
        self.assertEqual(response.status_code, 200)
        self.assertNotContains(response, "class=\"sidebar\"", html=False)
        self.assertContains(response, "no-sidebar", html=False)
        self.assertNotContains(response, "Mavzu", html=False)
        self.assertNotContains(response, "Chiqish", html=False)

    def test_create_order_view_shows_dropdown_when_multiple_accounts_exist(self):
        MoneyAccount.objects.create(branch=self.branch_a, name="Card A")
        self._activate_branch(self.staff_a, self.branch_a)

        response = self.client.get(reverse("sales:pos_order_create"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'select class="control" name="account_id"', html=False)
        self.assertContains(response, "Tanlang...")

    def test_create_order_view_warns_and_blocks_payment_when_no_accounts_exist(self):
        self.account_a.delete()
        self._activate_branch(self.staff_a, self.branch_a)

        response = self.client.get(reverse("sales:pos_order_create"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Faol to'lov hisobi topilmadi")
        self.assertContains(response, 'id="is_paid" name="is_paid" value="1" disabled', html=False)

        post_response = self.client.post(
            reverse("sales:pos_order_create"),
            {
                "items_json": '[{"food": "%s", "qty": 1}]' % self.food_a.id,
                "order_type": Order.OrderType.DINE_IN,
                "is_paid": "1",
                "paid_amount": "10000",
            },
            follow=True,
        )

        self.assertEqual(post_response.status_code, 200)
        self.assertContains(post_response, "Faol to'lov hisobi topilmadi")
        self.assertEqual(Order.objects.count(), 0)

    def test_pay_order_view_hides_dropdown_for_single_account(self):
        order = create_order_with_items(
            branch=self.branch_a,
            created_by=self.staff_a,
            order_type=Order.OrderType.DINE_IN,
            note=None,
            items=[{"food": str(self.food_a.id), "qty": 1}],
        )
        self._activate_branch(self.staff_a, self.branch_a)

        response = self.client.get(reverse("sales:pos_order_detail", args=[order.pk]))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "To'lov hisobi")
        self.assertContains(response, f'value="{self.account_a.id}"', html=False)
        self.assertNotContains(response, "Tanlang...")

    def test_pay_order_view_uses_single_account_without_dropdown_selection(self):
        order = create_order_with_items(
            branch=self.branch_a,
            created_by=self.staff_a,
            order_type=Order.OrderType.DINE_IN,
            note=None,
            items=[{"food": str(self.food_a.id), "qty": 1}],
        )
        self._activate_branch(self.staff_a, self.branch_a)

        response = self.client.post(
            reverse("sales:pos_order_pay", args=[order.pk]),
            {"amount": "10000"},
            follow=True,
        )

        self.assertEqual(response.status_code, 200)
        order.refresh_from_db()
        self.assertEqual(order.paid_amount, 10000)
        self.assertEqual(order.status, Order.Status.PAID)

    def test_pay_order_view_shows_warning_and_rejects_when_no_accounts_exist(self):
        order = create_order_with_items(
            branch=self.branch_a,
            created_by=self.staff_a,
            order_type=Order.OrderType.DINE_IN,
            note=None,
            items=[{"food": str(self.food_a.id), "qty": 1}],
        )
        self.account_a.delete()
        self._activate_branch(self.staff_a, self.branch_a)

        response = self.client.get(reverse("sales:pos_order_detail", args=[order.pk]))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Faol to'lov hisobi topilmadi")
        self.assertContains(response, 'type="submit" disabled', html=False)

        post_response = self.client.post(
            reverse("sales:pos_order_pay", args=[order.pk]),
            {"amount": "10000"},
            follow=True,
        )

        self.assertEqual(post_response.status_code, 200)
        self.assertContains(post_response, "Faol to'lov hisobi topilmadi")
        order.refresh_from_db()
        self.assertEqual(order.paid_amount, 0)


class CashTransactionAdminPermissionTests(TestCase):
    def test_cash_transaction_admin_is_restricted_for_non_superuser(self):
        admin_view = CashTransactionAdmin(CashTransaction, admin.site)
        request = RequestFactory().get("/")
        request.user = User.objects.create_user("manager", password="x", is_staff=True)
        StaffProfile.objects.create(user=request.user, role=StaffRole.ADMIN, is_active=True)

        self.assertFalse(admin_view.has_add_permission(request))
        self.assertFalse(admin_view.has_delete_permission(request))

    def test_cash_transaction_admin_is_writable_for_superuser(self):
        admin_view = CashTransactionAdmin(CashTransaction, admin.site)
        request = RequestFactory().get("/")
        request.user = User.objects.create_superuser("su", "su@example.com", "x")

        self.assertTrue(admin_view.has_add_permission(request))
        self.assertTrue(admin_view.has_change_permission(request))
        self.assertTrue(admin_view.has_delete_permission(request))


class OrderRecoveryDeleteTests(TestCase):
    def setUp(self):
        self.factory = RequestFactory()
        self.branch = Branch.objects.create(name="Recovery Branch")
        self.superuser = User.objects.create_superuser("super", "super@example.com", "x")
        self.admin_user = User.objects.create_user("admin_user", password="x", is_staff=True)
        StaffProfile.objects.create(user=self.admin_user, role=StaffRole.ADMIN, is_active=True)
        self.cashier = User.objects.create_user("cashier", password="x")
        StaffProfile.objects.create(user=self.cashier, role=StaffRole.CASHIER, branch=self.branch, is_active=True)
        self.account = MoneyAccount.objects.get(branch=self.branch, name="Kassa")
        self.account.name = "Main cash"
        self.account.save(update_fields=["name"])
        category = FoodCategory.objects.create(branch=self.branch, name="Burger", type=FoodType.FASTFOOD)
        self.food = Food.objects.create(branch=self.branch, category=category, name="Test food", sell_price=12000)
        self.product = Product.objects.create(name="Meat", count_type=CountType.KG)
        FoodItem.objects.create(food=self.food, product=self.product, qty=Decimal("0.200"))
        BranchProduct.objects.create(branch=self.branch, product=self.product, stock_qty=Decimal("3.000"), avg_unit_cost=10)
        self.order_admin = OrderAdmin(Order, admin.site)

    def _create_paid_order(self):
        order = create_order_with_items(
            branch=self.branch,
            created_by=self.cashier,
            order_type=Order.OrderType.DINE_IN,
            note="cleanup me",
            items=[{"food": str(self.food.id), "qty": 1}],
        )
        payment = pay_order(order, account=self.account, amount=12000, by_user=self.cashier)
        order.refresh_from_db()
        return order, payment

    def test_superuser_can_delete_order_with_related_records_cleanly(self):
        order, payment = self._create_paid_order()

        delete_order_for_recovery(order, actor=self.superuser)

        self.assertFalse(Order.objects.filter(pk=order.pk).exists())
        self.assertFalse(OrderItem.objects.filter(order_id=order.pk).exists())
        self.assertFalse(OrderPayment.objects.filter(pk=payment.pk).exists())
        self.assertFalse(CashTransaction.objects.filter(pk=payment.cash_txn_id).exists())
        self.account.refresh_from_db()
        self.assertEqual(self.account.balance_cache, 0)

    def test_non_superuser_cannot_use_recovery_delete(self):
        order, _ = self._create_paid_order()
        request = self.factory.get("/admin/sales/order/")
        request.user = self.admin_user
        self.assertFalse(self.order_admin.has_delete_permission(request, order))
        with self.assertRaises(PermissionError):
            delete_order_for_recovery(order, actor=self.admin_user)

    def test_bulk_delete_orders_for_superuser_removes_orphans(self):
        order_1, payment_1 = self._create_paid_order()
        order_2, payment_2 = self._create_paid_order()

        deleted_count = delete_orders_for_recovery(
            queryset=Order.objects.filter(pk__in=[order_1.pk, order_2.pk]),
            actor=self.superuser,
        )

        self.assertGreaterEqual(deleted_count, 2)
        self.assertFalse(Order.objects.filter(pk__in=[order_1.pk, order_2.pk]).exists())
        self.assertFalse(OrderPayment.objects.filter(pk__in=[payment_1.pk, payment_2.pk]).exists())
        self.assertFalse(CashTransaction.objects.filter(pk__in=[payment_1.cash_txn_id, payment_2.cash_txn_id]).exists())
        self.account.refresh_from_db()
        self.assertEqual(self.account.balance_cache, 0)

    def test_superuser_delete_restores_stock(self):
        order, _ = self._create_paid_order()
        mark_delivered(order, by_user=self.cashier)
        bp_before = BranchProduct.objects.get(branch=self.branch, product=self.product)
        stock_after_delivery = bp_before.stock_qty
        delete_order_for_recovery(order, actor=self.superuser)
        bp_after = BranchProduct.objects.get(branch=self.branch, product=self.product)
        self.assertEqual(bp_after.stock_qty, Decimal("3.000"))


class KitchenTaskTests(TestCase):
    def setUp(self):
        self.branch = Branch.objects.create(name="Kitchen")
        self.cashier = User.objects.create_user("cashier_k", password="x")
        StaffProfile.objects.create(user=self.cashier, role=StaffRole.CASHIER, branch=self.branch, is_active=True)
        self.account = MoneyAccount.objects.get(branch=self.branch, name="Kassa")
        category = FoodCategory.objects.create(branch=self.branch, name="Burger", type=FoodType.FASTFOOD)
        self.food = Food.objects.create(branch=self.branch, category=category, name="Test food", sell_price=8000)
        self._activate_branch()

    def _activate_branch(self):
        self.client.force_login(self.cashier)
        session = self.client.session
        session["active_branch_id"] = str(self.branch.id)
        session.save()

    def test_kitchen_task_created_and_shows_items(self):
        order = create_order_with_items(
            branch=self.branch,
            created_by=self.cashier,
            order_type=Order.OrderType.DINE_IN,
            note="tez",
            items=[{"food": str(self.food.id), "qty": 2}],
        )
        response = self.client.get(reverse("sales:pos_order_kitchen", args=[order.pk]))
        self.assertEqual(response.status_code, 200)
        self.assertTrue(KitchenTask.objects.filter(order=order).exists())
        self.assertContains(response, "Oshxona vazifasi")
        self.assertContains(response, "Test food")


class MenuIntegrityTests(TestCase):
    def test_food_category_branch_mismatch_rejected_on_save_path(self):
        branch_a = Branch.objects.create(name="A")
        branch_b = Branch.objects.create(name="B")
        category = FoodCategory.objects.create(branch=branch_a, name="Cat", type=FoodType.FASTFOOD)

        with self.assertRaises(ValidationError):
            Food.objects.create(branch=branch_b, category=category, name="Mismatch", sell_price=1000)
