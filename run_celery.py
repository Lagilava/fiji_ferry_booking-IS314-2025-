import os
from celery import Celery

# Load environment variables from .env
from dotenv import load_dotenv
load_dotenv()

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "ferry_system.settings")

app = Celery("ferry_system")
app.config_from_object("django.conf:settings", namespace="CELERY")
app.autodiscover_tasks()

if __name__ == "__main__":
    import subprocess
    import sys

    # Start worker
    worker_cmd = [sys.executable, "-m", "celery", "-A", "ferry_system", "worker", "-l", "info", "--pool=solo"]
    # Start beat
    beat_cmd = [sys.executable, "-m", "celery", "-A", "ferry_system", "beat", "-l", "info", "--scheduler", "django_celery_beat.schedulers:DatabaseScheduler"]

    print("Starting Celery worker...")
    worker_proc = subprocess.Popen(worker_cmd)
    print("Starting Celery beat...")
    beat_proc = subprocess.Popen(beat_cmd)

    try:
        worker_proc.wait()
        beat_proc.wait()
    except KeyboardInterrupt:
        print("Stopping Celery...")
        worker_proc.terminate()
        beat_proc.terminate()
