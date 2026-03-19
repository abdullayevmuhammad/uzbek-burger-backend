from decimal import Decimal

from django.contrib import admin
from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.test import RequestFactory, TestCase
from django.urls import reverse

from catalog.models import CountType, Product
from core.models import Branch
from finance.admin import CashTransactionAdmin
from finance.models import CashTransaction, MoneyAccount
from inventory.models import BranchProduct
from menu.models import Food, FoodCategory, FoodItem, FoodType
from sales.admin import OrderAdmin
from sales.models import Order, OrderItem
from sales.services import (
    OrderValidationError,
    add_item,
    cancel_order,
    create_order_with_items,
    mark_delivered,
    pay_order,
)
from users.models import StaffProfile, StaffRole


User = get_user_model()


class SalesFlowTests(TestCase):
    def setUp(self):
        self.factory = RequestFactory()
        self.branch_a = Branch.objects.create(name="Branch A")
        self.branch_b = Branch.objects.create(name="Branch B")

        self.superuser = User.objects.create_superuser("admin", "admin@example.com", "x")
        self.owner = User.objects.create_user("owner", password="x")
        StaffProfile.objects.create(user=self.owner, role=StaffRole.OWNER, is_active=True)

        self.staff_a = User.objects.create_user("staff_a", password="x")
        StaffProfile.objects.create(user=self.staff_a, role=StaffRole.STAFF, branch=self.branch_a, is_active=True)

        self.staff_b = User.objects.create_user("staff_b", password="x")
        StaffProfile.objects.create(user=self.staff_b, role=StaffRole.STAFF, branch=self.branch_b, is_active=True)

        self.account_a = MoneyAccount.objects.create(branch=self.branch_a, name="Cash A")
        self.account_b = MoneyAccount.objects.create(branch=self.branch_b, name="Cash B")

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

    def test_admin_owner_sees_all_orders(self):
        Order.objects.create(branch=self.branch_a)
        Order.objects.create(branch=self.branch_b)

        request = self.factory.get("/")
        request.user = self.owner

        self.assertEqual(self.order_admin.get_queryset(request).count(), 2)

    def test_admin_staff_sees_only_own_branch_orders(self):
        order_a = Order.objects.create(branch=self.branch_a)
        Order.objects.create(branch=self.branch_b)

        request = self.factory.get("/")
        request.user = self.staff_a

        self.assertEqual(list(self.order_admin.get_queryset(request)), [order_a])

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
        self.assertContains(response, "Buyurtmada xato itemlar bor")
        self.assertEqual(Order.objects.count(), 0)


class AdminReadOnlyTests(TestCase):
    def test_cash_transaction_admin_is_read_only(self):
        admin_view = CashTransactionAdmin(CashTransaction, admin.site)
        request = RequestFactory().get("/")
        request.user = User.objects.create_superuser("su", "su@example.com", "x")

        self.assertFalse(admin_view.has_add_permission(request))
        self.assertFalse(admin_view.has_change_permission(request))
        self.assertFalse(admin_view.has_delete_permission(request))


class MenuIntegrityTests(TestCase):
    def test_food_category_branch_mismatch_rejected_on_save_path(self):
        branch_a = Branch.objects.create(name="A")
        branch_b = Branch.objects.create(name="B")
        category = FoodCategory.objects.create(branch=branch_a, name="Cat", type=FoodType.FASTFOOD)

        with self.assertRaises(ValidationError):
            Food.objects.create(branch=branch_b, category=category, name="Mismatch", sell_price=1000)
