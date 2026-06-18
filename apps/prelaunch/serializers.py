from rest_framework import serializers

class WaitlistSubmitSerializer(serializers.Serializer):
    email = serializers.EmailField()
    source = serializers.CharField(max_length=100, required=False, allow_blank=True, allow_null=True)

class PrelaunchStatusSerializer(serializers.Serializer):
    is_prelaunch = serializers.BooleanField()
    launch_date = serializers.DateField(format="%Y-%m-%d")

class WaitlistNotifySummarySerializer(serializers.Serializer):
    total_in_waitlist = serializers.IntegerField()
    total_notified_successfully = serializers.IntegerField()
    total_failed = serializers.IntegerField()
