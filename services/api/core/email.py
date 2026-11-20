from django.core.mail.backends.console import EmailBackend as ConsoleEmailBackend


class EmailBackend(ConsoleEmailBackend):
    """Readable local email previews, without MIME transfer encoding of links."""

    def write_message(self, message):
        self.stream.write(f"Subject: {message.subject}\n")
        self.stream.write(f"From: {message.from_email}\n")
        self.stream.write(f"To: {', '.join(message.to)}\n\n")
        self.stream.write(f"{message.body}\n")
        self.stream.write("-" * 79 + "\n")
