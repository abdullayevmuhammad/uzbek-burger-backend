from django.contrib.auth import get_user_model
from django.test import SimpleTestCase, TestCase

from core.models import Branch
from finance.models import CashTransaction, Direction, MoneyAccount, TxnType
from finance.services import create_cash_adjustment, get_branch_cash_history
from finance.utils import parse_uzs_amount
from sales.services import create_order_with_items, pay_order
from menu.models import Food, FoodCategory, FoodType
from users.models import StaffProfile, StaffRole


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


User = get_user_model()


class CashAdjustmentFlowTests(TestCase):
    def setUp(self):
        self.branch = Branch.objects.create(name="Finance Branch")
        self.superuser = User.objects.create_superuser("super_fin", "super_fin@example.com", "x")
        self.admin_user = User.objects.create_user("manager_fin", password="x", is_staff=True)
        StaffProfile.objects.create(user=self.admin_user, role=StaffRole.ADMIN, is_active=True)
        self.cashier = User.objects.create_user("cashier_fin", password="x")
        StaffProfile.objects.create(user=self.cashier, role=StaffRole.CASHIER, branch=self.branch, is_active=True)
        self.account = MoneyAccount.objects.create(branch=self.branch, name="Cashbox")

        category = FoodCategory.objects.create(branch=self.branch, name="Burger", type=FoodType.FASTFOOD)
        self.food = Food.objects.create(branch=self.branch, category=category, name="Burger", sell_price=15000)

    def test_opening_balance_transaction_works(self):
        tx = create_cash_adjustment(
            account=self.account,
            txn_type=TxnType.OPENING_BALANCE,
            amount=100000,
            reason="Start of day",
            note="Initial drawer amount",
            actor=self.superuser,
        )
        self.account.refresh_from_db()
        self.assertEqual(tx.direction, Direction.IN_)
        self.assertEqual(self.account.balance_cache, 100000)

    def test_cash_adjustment_works(self):
        tx = create_cash_adjustment(
            account=self.account,
            txn_type=TxnType.CASH_ADJUSTMENT,
            amount=5000,
            direction=Direction.OUT,
            reason="Count mismatch",
            note="Removed over-count after audit",
            actor=self.superuser,
        )
        self.account.refresh_from_db()
        self.assertEqual(tx.direction, Direction.OUT)
        self.assertEqual(self.account.balance_cache, -5000)

    def test_cash_in_works(self):
        tx = create_cash_adjustment(
            account=self.account,
            txn_type=TxnType.CASH_IN,
            amount=7000,
            reason="Petty cash returned",
            note="Shift manager returned petty cash",
            actor=self.superuser,
        )
        self.account.refresh_from_db()
        self.assertEqual(tx.direction, Direction.IN_)
        self.assertEqual(self.account.balance_cache, 7000)

    def test_cash_out_works(self):
        create_cash_adjustment(
            account=self.account,
            txn_type=TxnType.OPENING_BALANCE,
            amount=20000,
            reason="Start",
            note="Start balance",
            actor=self.superuser,
        )
        tx = create_cash_adjustment(
            account=self.account,
            txn_type=TxnType.CASH_OUT,
            amount=4000,
            reason="Petty cash",
            note="Cash taken out for supplies",
            actor=self.superuser,
        )
        self.account.refresh_from_db()
        self.assertEqual(tx.direction, Direction.OUT)
        self.assertEqual(self.account.balance_cache, 16000)

    def test_non_superuser_cannot_create_manual_cash_adjustment(self):
        with self.assertRaises(PermissionError):
            create_cash_adjustment(
                account=self.account,
                txn_type=TxnType.CASH_IN,
                amount=1000,
                reason="No permission",
                note="Should fail",
                actor=self.admin_user,
            )

    def test_fake_order_payment_workaround_is_not_allowed(self):
        with self.assertRaisesMessage(Exception, "Sale transaction faqat real order payment bilan bog'lanadi."):
            CashTransaction.objects.create(
                branch=self.branch,
                account=self.account,
                actor=self.superuser,
                direction=Direction.IN_,
                txn_type=TxnType.SALE,
                amount=12000,
                reason="Fake sale",
                note="Should be blocked",
            )

    def test_reports_history_distinguish_sales_vs_adjustments(self):
        create_cash_adjustment(
            account=self.account,
            txn_type=TxnType.OPENING_BALANCE,
            amount=20000,
            reason="Start",
            note="Shift opening balance",
            actor=self.superuser,
        )
        order = create_order_with_items(
            branch=self.branch,
            created_by=self.cashier,
            order_type="dine_in",
            note=None,
            items=[{"food": str(self.food.id), "qty": 1}],
        )
        payment = pay_order(order, account=self.account, amount=15000, by_user=self.cashier)

        history = get_branch_cash_history(self.branch)

        self.assertEqual(history["sales"].count(), 1)
        self.assertEqual(history["sales"].first().id, payment.cash_txn_id)
        self.assertEqual(history["non_sales"].count(), 1)
        self.assertEqual(history["adjustments"].count(), 1)
