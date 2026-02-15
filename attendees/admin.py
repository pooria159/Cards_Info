from django.contrib import admin
from .models import DataUpload, Attendee


@admin.register(DataUpload)
class DataUploadAdmin(admin.ModelAdmin):
    list_display = ("id", "created_at", "excel_file", "photos_zip")
    readonly_fields = ("created_at",)
    search_fields = ("id", "excel_file", "photos_zip")


@admin.register(Attendee)
class AttendeeAdmin(admin.ModelAdmin):
    list_display = ("name", "email", "tag", "selected", "upload", "updated_at")
    list_filter = ("selected", "tag", "upload")
    search_fields = ("name", "email")
    list_editable = ("selected",)
    autocomplete_fields = ("upload",)

    actions = ("mark_selected", "mark_unselected")

    @admin.action(description="علامت‌گذاری به عنوان انتخاب‌شده")
    def mark_selected(self, request, queryset):
        queryset.update(selected=True)

    @admin.action(description="علامت‌گذاری به عنوان انتخاب‌نشده")
    def mark_unselected(self, request, queryset):
        queryset.update(selected=False)
