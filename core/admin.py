from django import forms
from django.contrib import admin, messages
from django.core.exceptions import PermissionDenied
from django.http import HttpResponseRedirect
from django.template.response import TemplateResponse
from django.urls import path, reverse
from django.utils.html import format_html

from core.services import archive_branch, purge_branch
from users.utils import is_admin_user, is_super_recovery_user

from .models import Branch


class BranchPurgeForm(forms.Form):
    branch_name = forms.CharField(label="Branch name")
    confirmation_token = forms.CharField(label="Type PURGE")


@admin.action(description="Tanlangan branchlarni arxivlash")
def archive_selected_branches(modeladmin, request, queryset):
    archived = 0
    for branch in queryset:
        if branch.is_active:
            archive_branch(branch=branch, actor=request.user)
            archived += 1
    if archived:
        modeladmin.message_user(request, f"{archived} ta filial arxivlandi.", level=messages.SUCCESS)


@admin.action(description="Tanlangan branchlarni aktiv qilish")
def activate_selected_branches(modeladmin, request, queryset):
    updated = queryset.update(is_active=True)
    if updated:
        modeladmin.message_user(request, f"{updated} ta filial aktiv qilindi.", level=messages.SUCCESS)


@admin.register(Branch)
class BranchAdmin(admin.ModelAdmin):
    list_display = ("name", "is_active", "address", "id")
    list_filter = ("is_active",)
    search_fields = ("name", "address")
    list_editable = ("is_active",)
    ordering = ("name",)
    actions = (archive_selected_branches, activate_selected_branches)

    def has_module_permission(self, request):
        return is_admin_user(request.user)

    def has_view_permission(self, request, obj=None):
        return is_admin_user(request.user)

    def has_delete_permission(self, request, obj=None):
        return False

    def get_readonly_fields(self, request, obj=None):
        ro = list(super().get_readonly_fields(request, obj))
        if obj and is_super_recovery_user(request.user):
            ro.append("purge_link")
        return tuple(ro)

    def get_fields(self, request, obj=None):
        fields = ["name", "address", "is_active", "public_phone", "public_address", "working_hours", "map_iframe", "latitude", "longitude", "show_on_landing"]
        if obj and is_super_recovery_user(request.user):
            fields.append("purge_link")
        return fields

    @admin.display(description="Danger zone")
    def purge_link(self, obj):
        if not obj:
            return "-"
        url = reverse("admin:core_branch_purge", args=[obj.pk])
        return format_html('<a class="button" href="{}">Purge branch</a>', url)

    def get_urls(self):
        urls = super().get_urls()
        custom_urls = [
            path(
                "<path:object_id>/purge/",
                self.admin_site.admin_view(self.purge_view),
                name="core_branch_purge",
            ),
        ]
        return custom_urls + urls

    def purge_view(self, request, object_id):
        if not is_super_recovery_user(request.user):
            raise PermissionDenied("Branch purge faqat superuser uchun.")

        branch = self.get_object(request, object_id)
        if branch is None:
            raise PermissionDenied("Filial topilmadi.")

        form = BranchPurgeForm(request.POST or None)
        if request.method == "POST":
            if form.is_valid():
                if form.cleaned_data["branch_name"] != branch.name:
                    form.add_error("branch_name", "Filial nomi aniq mos bo'lishi kerak.")
                if form.cleaned_data["confirmation_token"] != "PURGE":
                    form.add_error("confirmation_token", "Tasdiqlash uchun PURGE yozing.")

                if not form.errors:
                    purge_branch(branch=branch, actor=request.user)
                    self.message_user(
                        request,
                        f"Filial '{branch.name}' va unga bog'liq barcha branch ma'lumotlari purge qilindi.",
                        level=messages.SUCCESS,
                    )
                    changelist_url = reverse("admin:core_branch_changelist")
                    return HttpResponseRedirect(changelist_url)

        context = {
            **self.admin_site.each_context(request),
            "opts": self.model._meta,
            "title": f"Purge branch: {branch.name}",
            "branch": branch,
            "form": form,
        }
        return TemplateResponse(request, "admin/core/branch/purge_confirmation.html", context)
