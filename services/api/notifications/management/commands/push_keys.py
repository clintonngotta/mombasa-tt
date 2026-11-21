from django.core.management.base import BaseCommand

from notifications import webpush


class Command(BaseCommand):
    help = "Print a new VAPID key pair for browser push (TASK-034). Set WEB_PUSH_PRIVATE_KEY to the first."

    def handle(self, *args, **options):
        private, public = webpush.new_keys()
        self.stdout.write(f"WEB_PUSH_PRIVATE_KEY={private}\n")
        self.stdout.write(f"# public key (served to browsers by GET /api/v1/me/push/): {public}\n")
