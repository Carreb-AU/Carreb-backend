from django.contrib import admin
from .models import WaitlistEntry, PrelaunchConfig

@admin.register(WaitlistEntry)
class WaitlistEntryAdmin(admin.ModelAdmin):
    list_display = ('email', 'submitted_at', 'notified_at', 'source')
    search_fields = ('email',)
    list_filter = ('notified_at', 'source')

@admin.register(PrelaunchConfig)
class PrelaunchConfigAdmin(admin.ModelAdmin):
    list_display = ('launch_date',)

    def has_add_permission(self, request):
        if self.model.objects.exists():
            return False
        return super().has_add_permission(request)

    def has_delete_permission(self, request, obj=None):
        return False
