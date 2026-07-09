from django.contrib import admin
from .models import SupportTicket

@admin.register(SupportTicket)
class SupportTicketAdmin(admin.ModelAdmin):
    list_display = ('id', 'ticket_type', 'status', 'email', 'user', 'submitted_at')
    list_filter = ('ticket_type', 'status', 'severity', 'submitted_at')
    search_fields = ('email', 'first_name', 'last_name', 'message', 'topic', 'phone_number')
    readonly_fields = ('submitted_at',)
    
    fieldsets = (
        ('Core Information', {
            'fields': ('ticket_type', 'status', 'user', 'submitted_at')
        }),
        ('User Details', {
            'fields': ('first_name', 'last_name', 'email', 'phone_number', 'subscription_tier')
        }),
        ('Ticket Details', {
            'fields': ('topic', 'what_describes_you', 'message')
        }),
        ('Bug / Feature Context', {
            'fields': ('page_url', 'severity', 'feature_area', 'user_agent')
        }),
    )
