from django.test import TestCase
from django.urls import reverse

from core.models import Branch
from menu.models import Food, FoodCategory, FoodType


class LandingMenuTests(TestCase):
    def setUp(self):
        self.branch = Branch.objects.create(name="Landing branch")
        self.fastfood_category = FoodCategory.objects.create(
            branch=self.branch,
            name="Burgerlar",
            type=FoodType.FASTFOOD,
        )
        self.drink_category = FoodCategory.objects.create(
            branch=self.branch,
            name="Ichimliklar",
            type=FoodType.DRINK,
        )
        self.wrap_category = FoodCategory.objects.create(
            branch=self.branch,
            name="Wraplar",
            type=FoodType.FASTFOOD,
        )

        self.burger = Food.objects.create(
            branch=self.branch,
            category=self.fastfood_category,
            name="Cheese Burger",
            type=FoodType.FASTFOOD,
            sell_price=25000,
        )
        self.wrap = Food.objects.create(
            branch=self.branch,
            category=self.wrap_category,
            name="Spicy Wrap",
            type=FoodType.FASTFOOD,
            sell_price=22000,
        )
        self.drink = Food.objects.create(
            branch=self.branch,
            category=self.drink_category,
            name="Cola",
            type=FoodType.DRINK,
            sell_price=9000,
        )

    def test_menu_accepts_public_type_slug(self):
        response = self.client.get(reverse("landing:menu"), {"type": "fastfood"})

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, self.burger.name)
        self.assertContains(response, self.wrap.name)
        self.assertNotContains(response, self.drink.name)

    def test_live_menu_combines_type_search_and_category(self):
        response = self.client.get(
            reverse("landing:menu_live"),
            {
                "type": "fastfood",
                "category": "wraplar",
                "q": "spicy",
            },
            HTTP_X_REQUESTED_WITH="XMLHttpRequest",
        )

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertTrue(payload["ok"])
        self.assertEqual(payload["count"], 1)
        self.assertIn(self.wrap.name, payload["html"])
        self.assertNotIn(self.burger.name, payload["html"])
        self.assertNotIn(self.drink.name, payload["html"])

    def test_menu_reset_without_type_returns_all_items(self):
        response = self.client.get(reverse("landing:menu_live"))

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["count"], 3)
        self.assertIn(self.burger.name, payload["html"])
        self.assertIn(self.wrap.name, payload["html"])
        self.assertIn(self.drink.name, payload["html"])

    def test_menu_page_uses_brand_logo_markup(self):
        response = self.client.get(reverse("landing:menu"))

        self.assertContains(response, "img/favicon.svg")
        self.assertContains(response, "logo-mark")

    def test_home_page_preview_uses_public_menu_card_design(self):
        response = self.client.get(reverse("landing:home"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Menudan tavsiya")
        self.assertContains(response, "public-menu-card")
        self.assertContains(response, "public-menu-price")

    def test_menu_page_removes_intro_hero_and_count_card(self):
        response = self.client.get(reverse("landing:menu"))

        self.assertEqual(response.status_code, 200)
        self.assertNotContains(response, "POS uslubidagi kartalar bilan taomlarni tez toping")
        self.assertNotContains(response, "ta mahsulot ko'rsatilmoqda")
        self.assertContains(response, 'id="landingMenuSearch"', html=False)
        self.assertContains(response, "Mahsulotlar")

    def test_menu_excludes_foods_from_inactive_branches(self):
        inactive_branch = Branch.objects.create(name="Arxiv filial")
        inactive_branch.is_active = False
        inactive_branch.save(update_fields=["is_active"])
        inactive_category = FoodCategory.objects.create(
            branch=inactive_branch,
            name="Arxiv",
            type=FoodType.FASTFOOD,
        )
        hidden_food = Food.objects.create(
            branch=inactive_branch,
            category=inactive_category,
            name="Hidden Burger",
            type=FoodType.FASTFOOD,
            sell_price=21000,
        )

        response = self.client.get(reverse("landing:menu_live"), HTTP_X_REQUESTED_WITH="XMLHttpRequest")

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertNotIn(hidden_food.name, payload["html"])
