from rest_framework import status
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework.permissions import AllowAny, IsAuthenticated
from .serializers import (
    SignupStep1Serializer,
    SignupStep2Serializer,
    EmailVerificationSerializer,
    LoginSerializer,
    Verify2FASerializer,
    SocialLoginSerializer,
    AccountDeletionRequestSerializer
)
from .services import (
    signup_step_1,
    signup_step_2,
    verify_email,
    login,
    verify_login_2fa,
    social_login,
    delete_account
)

class SignupStep1View(APIView):
    permission_classes = [AllowAny]
    def post(self, request):
        serializer = SignupStep1Serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        user = signup_step_1(**serializer.validated_data)
        return Response({"detail": "Step 1 complete.", "user_id": user.id}, status=status.HTTP_201_CREATED)

class SignupStep2View(APIView):
    permission_classes = [AllowAny]
    def post(self, request):
        serializer = SignupStep2Serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        signup_step_2(**serializer.validated_data)
        return Response({"detail": "Step 2 complete. Verification email sent."}, status=status.HTTP_200_OK)

class VerifyEmailView(APIView):
    permission_classes = [AllowAny]
    def post(self, request):
        serializer = EmailVerificationSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        session = verify_email(**serializer.validated_data)
        return Response({
            "detail": "Email verified.",
            "session_token": session["session_token"],
            "access": session["access"],
            "refresh": session["refresh"]
        }, status=status.HTTP_200_OK)

class LoginView(APIView):
    permission_classes = [AllowAny]
    def post(self, request):
        serializer = LoginSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        ip = request.META.get('REMOTE_ADDR')
        ua = request.META.get('HTTP_USER_AGENT')
        result = login(**serializer.validated_data, ip_address=ip, user_agent=ua)
        return Response(result, status=status.HTTP_200_OK)

class VerifyLogin2FAView(APIView):
    permission_classes = [AllowAny]
    def post(self, request):
        serializer = Verify2FASerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        ip = request.META.get('REMOTE_ADDR')
        ua = request.META.get('HTTP_USER_AGENT')
        result = verify_login_2fa(**serializer.validated_data, ip_address=ip, user_agent=ua)
        return Response(result, status=status.HTTP_200_OK)

class SocialLoginView(APIView):
    permission_classes = [AllowAny]
    def post(self, request):
        serializer = SocialLoginSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        ip = request.META.get('REMOTE_ADDR')
        ua = request.META.get('HTTP_USER_AGENT')
        result = social_login(**serializer.validated_data, ip_address=ip, user_agent=ua)
        return Response(result, status=status.HTTP_200_OK)

class AccountDeletionView(APIView):
    permission_classes = [IsAuthenticated]
    def post(self, request):
        serializer = AccountDeletionRequestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        delete_account(user=request.user, **serializer.validated_data)
        return Response({"detail": "Account scheduled for deletion. Sessions revoked."}, status=status.HTTP_200_OK)

class PasswordResetRequestView(APIView):
    permission_classes = [AllowAny]
    def post(self, request):
        from .serializers import PasswordResetRequestSerializer
        from .services import password_reset_request
        
        serializer = PasswordResetRequestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        password_reset_request(**serializer.validated_data)
        return Response({"detail": "If an account with that email exists, a password reset link has been sent."}, status=status.HTTP_200_OK)

class PasswordResetVerifyView(APIView):
    permission_classes = [AllowAny]
    def post(self, request):
        from .serializers import PasswordResetVerifySerializer
        from .services import password_reset_verify
        
        serializer = PasswordResetVerifySerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        password_reset_verify(**serializer.validated_data)
        return Response({"detail": "Password has been successfully reset. All sessions revoked."}, status=status.HTTP_200_OK)

class Setup2FAView(APIView):
    permission_classes = [IsAuthenticated]
    def get(self, request):
        from .services import setup_2fa
        result = setup_2fa(request.user)
        return Response(result, status=status.HTTP_200_OK)

class Confirm2FAView(APIView):
    permission_classes = [IsAuthenticated]
    def post(self, request):
        from rest_framework import serializers
        from .services import confirm_2fa
        
        class Confirm2FASerializer(serializers.Serializer):
            totp_code = serializers.CharField(max_length=6)
            
        serializer = Confirm2FASerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        result = confirm_2fa(request.user, serializer.validated_data['totp_code'])
        return Response(result, status=status.HTTP_200_OK)
