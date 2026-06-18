from django.db import models

class PrelaunchConfig(models.Model):
    launch_date = models.DateField(help_text="The date when the pre-launch phase ends.")

    class Meta:
        verbose_name = "Prelaunch Configuration"
        verbose_name_plural = "Prelaunch Configuration"

    def save(self, *args, **kwargs):
        self.pk = 1
        super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        pass

    @classmethod
    def get_solo(cls):
        from datetime import date
        obj, created = cls.objects.get_or_create(pk=1, defaults={'launch_date': date(2026, 7, 10)})
        return obj

class WaitlistEntry(models.Model):
    email = models.EmailField(unique=True, db_index=True)
    submitted_at = models.DateTimeField(auto_now_add=True)
    notified_at = models.DateTimeField(null=True, blank=True)
    source = models.CharField(max_length=100, null=True, blank=True)

    def __str__(self):
        return self.email
