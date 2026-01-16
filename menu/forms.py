from django import forms

from .models import Food


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
