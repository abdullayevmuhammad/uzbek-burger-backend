from django import forms
from decimal import Decimal
from catalog.models import Product
from finance.models import MoneyAccount
from .models import StockImport, StockImportItem, BranchProduct


def _style_form(form: forms.Form):
    for f in form.fields.values():
        cls = f.widget.attrs.get("class", "")
        f.widget.attrs["class"] = (cls + " control").strip()


class StockImportCreateForm(forms.ModelForm):
    paid_from_account = forms.ModelChoiceField(
        queryset=MoneyAccount.objects.none(),
        required=False,
        label="Qaysi hisobdan to‘landi?",
    )

    class Meta:
        model = StockImport
        fields = ["note", "paid_from_account"]
        labels = {"note": "Izoh"}

    def __init__(self, *args, branch=None, **kwargs):
        super().__init__(*args, **kwargs)
        if branch:
            self.fields["paid_from_account"].queryset = MoneyAccount.objects.filter(
                branch=branch, is_active=True
            ).order_by("name")
        _style_form(self)
        self.fields["note"].widget.attrs.setdefault("placeholder", "Masalan: 1-ombor kirimi")


class StockImportItemForm(forms.ModelForm):
    class Meta:
        model = StockImportItem
        fields = ["product", "qty", "line_total_cost"]
        labels = {
            "product": "Mahsulot",
            "qty": "Miqdor",
            "line_total_cost": "Jami qiymat (so‘m)",
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["product"].queryset = Product.objects.filter(is_active=True).order_by("name")
        self.fields["product"].widget.attrs["data-placeholder"] = "Mahsulot tanlang..."

        _style_form(self)
        self.fields["qty"].widget.attrs.setdefault("placeholder", "Masalan: 10")
        self.fields["line_total_cost"].widget.attrs.setdefault("placeholder", "Masalan: 250000")
        self.fields["product"].widget.attrs["data-choices"] = "1"


    def clean_qty(self):
        qty = self.cleaned_data["qty"]
        if qty is None or qty <= Decimal("0"):
            raise forms.ValidationError("Miqdor 0 dan katta bo‘lishi kerak.")
        return qty

    def clean_line_total_cost(self):
        v = self.cleaned_data["line_total_cost"]
        if v is None or int(v) <= 0:
            raise forms.ValidationError("Jami qiymat 0 dan katta bo‘lishi kerak.")
        return int(v)


class ProductCreateForm(forms.ModelForm):
    class Meta:
        model = Product
        fields = ["name", "count_type", "sku", "barcode", "is_active"]
        labels = {
            "name": "Mahsulot nomi",
            "count_type": "O‘lchov birligi",
            "sku": "SKU",
            "barcode": "Shtrix-kod",
            "is_active": "Faol",
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["count_type"].widget.attrs["data-choices"] = "1"
        self.fields["count_type"].widget.attrs["data-choices-nosearch"] = "1"
        self.fields["count_type"].widget.attrs["data-placeholder"] = "O‘lchov birligini tanlang..."
        _style_form(self)
        self.fields["name"].widget.attrs.setdefault("placeholder", "Masalan: Un 1-nav")
        self.fields["sku"].widget.attrs.setdefault("placeholder", "ixtiyoriy")
        self.fields["barcode"].widget.attrs.setdefault("placeholder", "ixtiyoriy")
        self.fields["count_type"].empty_label = "O‘lchov birligini tanlang..."
