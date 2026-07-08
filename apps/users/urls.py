from django.urls import path
from rest_framework_simplejwt.views import TokenRefreshView
from .views import (
    SignupStep1View,
    SignupStep2View,
    VerifyEmailView,
    LoginView,
    VerifyLogin2FAView,
    SocialLoginView,
    AccountDeletionView,
    PasswordResetRequestView,
    PasswordResetVerifyView,
    Setup2FAView,
    Confirm2FAView,
    UserProfileView
)

urlpatterns = [
    path('signup/step1/', SignupStep1View.as_view(), name='signup-step1'),
    path('signup/step2/', SignupStep2View.as_view(), name='signup-step2'),
    path('verify-email/', VerifyEmailView.as_view(), name='verify-email'),
    path('login/', LoginView.as_view(), name='login'),
    path('login/2fa/', VerifyLogin2FAView.as_view(), name='login-2fa'),
    path('login/social/', SocialLoginView.as_view(), name='login-social'),
    path('account/delete/', AccountDeletionView.as_view(), name='account-delete'),
    path('profile/', UserProfileView.as_view(), name='user-profile'),
    path('password-reset/', PasswordResetRequestView.as_view(), name='password-reset'),
    path('password-reset/verify/', PasswordResetVerifyView.as_view(), name='password-reset-verify'),
    
    # 2FA Setup
    path('2fa/setup/', Setup2FAView.as_view(), name='2fa-setup'),
    path('2fa/enable/', Confirm2FAView.as_view(), name='2fa-enable'),
    
    # JWT Refresh Token Endpoint
    path('token/refresh/', TokenRefreshView.as_view(), name='token_refresh'),
]
