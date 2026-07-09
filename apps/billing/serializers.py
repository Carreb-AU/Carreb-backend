from rest_framework import serializers
from apps.billing.models import PaymentRecord, PlanType

class PaymentRecordSerializer(serializers.ModelSerializer):
    item_name = serializers.SerializerMethodField()
    
    class Meta:
        model = PaymentRecord
        fields = [
            'id', 
            'paid_at', 
            'item_name', 
            'amount_display', 
            'payment_method_brand', 
            'payment_method_last4', 
            'invoice_pdf_url'
        ]
        
    def get_item_name(self, obj):
        if obj.plan_type == PlanType.CAR_BUYING_SPRINT:
            return "Car Buying Sprint"
        elif obj.plan_type == PlanType.CORE_ADVANTAGE:
            return "CORE Advantage Subscription"
        elif obj.plan_type == PlanType.FULL_INSIGHT_PRO:
            return "Full Insight Pro Subscription"
        return "Subscription"
