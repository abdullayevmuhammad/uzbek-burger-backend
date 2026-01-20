from django import forms

from .models import Food
from django.core.exceptions import ValidationError
from django.forms.models import BaseInlineFormSet
from .models import FoodType

def _style_form(form: forms.Form):
    for f in form.fields.values():
        cls = f.widget.attrs.get("class", "")
        f.widget.attrs["class"] = (cls + " control").strip()


class FoodForm(forms.ModelForm):
    class Meta:
        model = Food
        fields = ["type", "category", "name", "sell_price", "sort_order", "image", "is_active"]
        labels = {
            "type": "Type",
            "category": "Kategoriya",
            "name": "Nomi",
            "sell_price": "Narx (so‘m)",
            "sort_order": "Tartib (sort)",
            "image": "Rasm",
            "is_active": "Aktiv",
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        _style_form(self)

        # selects
        if "type" in self.fields:
            self.fields["type"].widget.attrs.update({
                "data-choices": "1",
                "data-choices-nosearch": "1",
            })
        if "category" in self.fields:
            self.fields["category"].required = False
            self.fields["category"].widget.attrs.update({
                "data-choices": "1",
                "data-choices-nosearch": "1",
                "data-placeholder": "Kategoriya tanlang (ixtiyoriy)...",
            })

        # placeholders
        self.fields["name"].widget.attrs.setdefault("placeholder", "Masalan: Lavash, Burger, Cola 0.5...")
        self.fields["sell_price"].widget.attrs.setdefault("placeholder", "Masalan: 35000")
        if "sort_order" in self.fields:
            self.fields["sort_order"].widget.attrs.setdefault("placeholder", "0")

        # checkbox
        if "is_active" in self.fields:
            self.fields["is_active"].widget.attrs.pop("class", None)
class FoodItemInlineFormSet(BaseInlineFormSet):
    def clean(self):
        super().clean()
        food = self.instance
        if not food or not getattr(food, "type", None):
            return

        if food.type == FoodType.SET:
            bad = []
            for form in self.forms:
                if not hasattr(form, "cleaned_data"):
                    continue
                cd = form.cleaned_data
                if cd.get("DELETE"):
                    continue
                if cd.get("product") and cd.get("qty"):
                    bad.append(str(cd.get("product")))

            if bad:
                raise ValidationError(
                    "XATO: Type=SET bo'lsa, Product ingredient kiritilmaydi. "
                    "Noto'g'ri qo'shilgan product(lar): " + ", ".join(bad) + ". "
                    "Bularni o'chiring va 'Set elementlari' bo'limidan taom qo'shing."
                )


class SetItemInlineFormSet(BaseInlineFormSet):
    def clean(self):
        super().clean()
        food = self.instance
        if not food or not getattr(food, "type", None):
            return

        if food.type in (FoodType.FASTFOOD, FoodType.DRINK):
            bad = []
            for form in self.forms:
                if not hasattr(form, "cleaned_data"):
                    continue
                cd = form.cleaned_data
                if cd.get("DELETE"):
                    continue
                if cd.get("food") and cd.get("qty"):
                    bad.append(str(cd.get("food")))

            if bad:
                raise ValidationError(
                    "XATO: Fastfood/Drink uchun SET element qo'shib bo'lmaydi. "
                    "Noto'g'ri qo'shilgan element(lar): " + ", ".join(bad) + ". "
                    "Bularni o'chiring yoki Type ni SET qiling."
                )

        if food.type == FoodType.SET:
            count = 0
            for form in self.forms:
                if not hasattr(form, "cleaned_data"):
                    continue
                cd = form.cleaned_data
                if cd.get("DELETE"):
                    continue
                if cd.get("food") and cd.get("qty"):
                    count += 1
            if count == 0:
                raise ValidationError(
                    "XATO: Type=SET bo'lsa, kamida bitta 'Set elementi' qo'shish shart."
                )
