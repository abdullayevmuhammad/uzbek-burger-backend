from django.contrib import admin, messages
from django.core.exceptions import ValidationError
from django.utils.html import format_html

from .forms import FoodItemInlineFormSet, SetItemInlineFormSet, FoodForm
from .models import Food, FoodItem, FoodCategory, SetItem, FoodType
from django.utils.safestring import mark_safe




class FoodItemInline(admin.TabularInline):
    model = FoodItem
    formset = FoodItemInlineFormSet
    extra = 1
    autocomplete_fields = ("product",)
    fields = ("product", "qty")



class SetItemInline(admin.TabularInline):
    model = SetItem
    fk_name = "set_food"   # ✅ MUHIM: qaysi FK parent Food ekanini aytamiz
    formset = SetItemInlineFormSet
    extra = 1
    autocomplete_fields = ("food",)
    fields = ("food", "qty")


@admin.register(FoodCategory)
class FoodCategoryAdmin(admin.ModelAdmin):
    list_display = ("name", "type", "branch", "sort_order", "is_active")
    list_filter = ("type", "is_active", "branch")
    search_fields = ("name",)
    list_editable = ("sort_order", "is_active")
    ordering = ("type", "sort_order", "name")


@admin.register(Food)
class FoodAdmin(admin.ModelAdmin):
    inlines = (FoodItemInline, SetItemInline)
    list_display = ("name", "type", "category", "branch", "sell_price", "is_active")
    list_filter = ("type", "is_active", "branch", "category")
    search_fields = ("name",)
    list_editable = ("is_active",)
    ordering = ("type", "category__sort_order", "sort_order", "name")
    list_per_page = 50
    readonly_fields = ("image_preview",)  # preview read-only bo'ladi
    form= FoodForm

    fieldsets = (
        (None, {
            "fields": (
                "branch",
                "type",
                "category",
                "name",
                "image",
                "image_preview",  # image tagidan keyin qo'ying
                "sell_price",
                "sort_order",
                "is_active",
            )
        }),
        # sizda inline/items bo'lsa qolaversin
    )
    def changeform_view(self, request, object_id=None, form_url="", extra_context=None):
        """
        Inline formset xatolari temada ko‘rinmay qolsa ham,
        messages.error orqali har doim ko‘rinadigan qilib chiqaramiz.
        """
        response = super().changeform_view(request, object_id, form_url, extra_context)

        # Faqat POST paytida, form invalid bo'lgan holatda ishlasin
        if request.method == "POST":
            ctx = getattr(response, "context_data", None) or {}
            adminform = ctx.get("adminform")
            inline_admin_formsets = ctx.get("inline_admin_formsets", [])

            # Parent form xatolari
            if adminform and adminform.form.errors:
                # bu odatda ko'rinadi, lekin baribir message qilib ham chiqaramiz
                messages.error(request, "Formada xatolik bor. Iltimos, to‘g‘rilang.")

            # Inline formset non_form_errors (bizning ValidationError shu yerga tushadi)
            for iafs in inline_admin_formsets:
                formset = iafs.formset
                errs = formset.non_form_errors()
                for e in errs:
                    messages.error(request, str(e))

        return response



    def image_preview(self, obj):
        if obj and getattr(obj, "image", None):
            try:
                return format_html(
                    '<img id="image-preview" src="{}" style="max-height:160px; border-radius:12px; border:1px solid #334; padding:4px;" />',
                    obj.image.url
                )
            except Exception:
                pass

        return mark_safe(
            '<img id="image-preview" style="display:none; max-height:160px; border-radius:12px; border:1px solid #334; padding:4px;" />'
        )

    image_preview.short_description = "Preview"

    class Media:
        js = ("admin/js/image_preview.js",)


@admin.register(FoodItem)
class FoodItemAdmin(admin.ModelAdmin):
    list_display = ("food", "product", "qty")
    search_fields = ("food__name", "product__name", "product__sku", "product__barcode")
    autocomplete_fields = ("food", "product")
    list_select_related = ("food", "product")

@admin.register(SetItem)
class SetItemAdmin(admin.ModelAdmin):
    list_display = ("set_food", "food", "qty")
    search_fields = ("set_food__name", "food__name")
    autocomplete_fields = ("set_food", "food")
    list_select_related = ("set_food", "food")