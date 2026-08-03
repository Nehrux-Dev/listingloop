"""Django admin registration for the custom user model."""

from django.contrib import admin
from django.contrib.auth.admin import UserAdmin as BaseUserAdmin
from django.contrib.auth.forms import UserChangeForm, UserCreationForm
from django.utils.translation import gettext_lazy as _

from apps.accounts.models import AgentProfile, BrandKit, Brokerage, User


class UserCreateForm(UserCreationForm):
    class Meta(UserCreationForm.Meta):
        model = User
        fields = ("email", "full_name", "role")


class UserEditForm(UserChangeForm):
    class Meta(UserChangeForm.Meta):
        model = User
        fields = "__all__"


@admin.register(User)
class UserAdmin(BaseUserAdmin):
    add_form = UserCreateForm
    form = UserEditForm
    model = User

    list_display = ("email", "full_name", "role", "is_active", "is_staff", "date_joined")
    list_filter = ("role", "is_active", "is_staff", "is_superuser")
    search_fields = ("email", "full_name")
    ordering = ("email",)

    fieldsets = (
        (None, {"fields": ("email", "password")}),
        (_("Personal info"), {"fields": ("full_name",)}),
        (_("Role"), {"fields": ("role",)}),
        (
            _("Permissions"),
            {
                "fields": (
                    "is_active",
                    "is_staff",
                    "is_superuser",
                    "groups",
                    "user_permissions",
                )
            },
        ),
        (_("Important dates"), {"fields": ("last_login", "date_joined")}),
    )

    add_fieldsets = (
        (
            None,
            {
                "classes": ("wide",),
                "fields": ("email", "full_name", "role", "password1", "password2"),
            },
        ),
    )


@admin.register(Brokerage)
class BrokerageAdmin(admin.ModelAdmin):
    list_display = ("name", "agent_count", "has_logo", "updated_at")
    search_fields = ("name",)
    filter_horizontal = ("admins",)
    readonly_fields = ("created_at", "updated_at")

    @admin.display(description="Agents")
    def agent_count(self, obj: Brokerage) -> int:
        return obj.agents.count()

    @admin.display(boolean=True, description="Logo")
    def has_logo(self, obj: Brokerage) -> bool:
        return bool(obj.logo)


@admin.register(AgentProfile)
class AgentProfileAdmin(admin.ModelAdmin):
    list_display = ("name", "user", "brokerage", "job_title", "updated_at")
    list_filter = ("brokerage",)
    search_fields = ("name", "user__email", "email", "job_title")
    autocomplete_fields = ("brokerage",)
    readonly_fields = ("created_at", "updated_at")


@admin.register(BrandKit)
class BrandKitAdmin(admin.ModelAdmin):
    list_display = ("__str__", "owner_type", "design_style", "updated_at")
    list_filter = ("design_style",)
    search_fields = ("name", "agent__name", "brokerage__name")
    autocomplete_fields = ("agent", "brokerage")
    readonly_fields = ("created_at", "updated_at")
