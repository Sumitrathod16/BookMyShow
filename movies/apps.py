# pyrefly: ignore [missing-import]
from django.apps import AppConfig


class MoviesConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'movies'

    def ready(self):
        import os
        import sys
        
        # Only start background scheduler thread when running as a server (avoid tests, migrations, etc.)
        is_server = False
        if any(cmd in sys.argv for cmd in ['runserver', 'gunicorn', 'runserver_plus']):
            is_server = True
        elif 'wsgi' in sys.modules or 'asgi' in sys.modules:
            is_server = True
            
        if is_server:
            # Avoid starting the thread in the runserver reloader parent process
            if 'runserver' in sys.argv and os.environ.get('RUN_MAIN') != 'true':
                return
                
            try:
                from .scheduler import start_background_scheduler
                start_background_scheduler()
            except Exception as e:
                sys.stderr.write(f"Warning: Failed to start background seat reservation scheduler: {e}\n")
