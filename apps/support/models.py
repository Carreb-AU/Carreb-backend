from django.db import models
from django.conf import settings

class SupportTicket(models.Model):
    TICKET_TYPE_CHOICES = (
        ('contact_us', 'Contact Us'),
        ('get_in_touch', 'Get in Touch'),
        ('bug_report', 'Bug Report'),
        ('feature_suggestion', 'Feature Suggestion'),
    )
    
    SEVERITY_CHOICES = (
        ('low', 'Low'),
        ('medium', 'Medium'),
        ('high', 'High'),
    )
    
    STATUS_CHOICES = (
        ('received', 'Received'),
        ('in_review', 'In Review'),
        ('resolved', 'Resolved'),
    )

    ticket_type = models.CharField(max_length=50, choices=TICKET_TYPE_CHOICES)
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name='support_tickets')
    
    # Common fields
    first_name = models.CharField(max_length=255, blank=True, null=True)
    last_name = models.CharField(max_length=255, blank=True, null=True)
    email = models.EmailField(blank=True, null=True)
    phone_number = models.CharField(max_length=20, blank=True, null=True)
    message = models.TextField(max_length=2000)
    
    # Contact Us & Get In Touch fields
    topic = models.CharField(max_length=255, blank=True, null=True)
    what_describes_you = models.CharField(max_length=255, blank=True, null=True)
    
    # Bug Report fields
    page_url = models.URLField(max_length=2000, blank=True, null=True)
    severity = models.CharField(max_length=20, choices=SEVERITY_CHOICES, blank=True, null=True)
    user_agent = models.TextField(blank=True, null=True)
    
    # Feature Suggestion fields
    feature_area = models.CharField(max_length=255, blank=True, null=True)
    
    # Internal & Context fields
    subscription_tier = models.CharField(max_length=50, blank=True, null=True)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='received')
    submitted_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-submitted_at']

    def __str__(self):
        return f"{self.get_ticket_type_display()} - {self.email or (self.user.email if self.user else 'Anonymous')} - {self.status}"
