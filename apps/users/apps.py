from django.apps import AppConfig


class UsersConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.users"

    def ready(self):
        import os
        import firebase_admin
        from firebase_admin import credentials
        from django.conf import settings
        
        try:
            # Check if default app is already initialized
            firebase_admin.get_app()
        except ValueError:
            # Initialize the default app
            firebase_creds_path = getattr(settings, 'FIREBASE_CREDENTIALS_PATH', None)
            if firebase_creds_path and os.path.exists(firebase_creds_path):
                cred = credentials.Certificate(firebase_creds_path)
                firebase_admin.initialize_app(cred)
