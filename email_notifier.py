import logging
import smtplib
from dataclasses import dataclass, field
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

logger = logging.getLogger(__name__)


@dataclass
class TrackInfo:
    name: str
    artist: str

    def __str__(self) -> str:
        return f"'{self.name}' by {self.artist}"


@dataclass
class SyncReport:
    added: list[TrackInfo] = field(default_factory=list)
    removed: list[TrackInfo] = field(default_factory=list)
    not_found: list[TrackInfo] = field(default_factory=list)
    failed: list[tuple[str, str]] = field(default_factory=list)  # (label, error)
    dry_run: bool = False

    @property
    def has_changes(self) -> bool:
        return bool(self.added or self.removed or self.not_found or self.failed)


class EmailNotifier:
    def __init__(
        self,
        smtp_host: str,
        smtp_port: int,
        smtp_user: str,
        smtp_password: str,
        from_email: str,
        to_email: str,
    ) -> None:
        self._smtp_host = smtp_host
        self._smtp_port = smtp_port
        self._smtp_user = smtp_user
        self._smtp_password = smtp_password
        self._from_email = from_email
        self._to_email = to_email

    def send_sync_report(self, report: SyncReport) -> bool:
        """Send a sync summary email. Returns True on success, False on failure."""
        prefix = "[DRY RUN] " if report.dry_run else ""
        subject = (
            f"{prefix}Spotify → YouTube Sync: "
            f"+{len(report.added)} added, -{len(report.removed)} removed"
            + (f", {len(report.failed)} failed" if report.failed else "")
        )

        msg = MIMEMultipart("alternative")
        msg["Subject"] = subject
        msg["From"] = self._from_email
        msg["To"] = self._to_email

        msg.attach(MIMEText(self._build_text(report), "plain"))
        msg.attach(MIMEText(self._build_html(report), "html"))

        try:
            with smtplib.SMTP(self._smtp_host, self._smtp_port) as server:
                server.ehlo()
                server.starttls()
                server.login(self._smtp_user, self._smtp_password)
                server.sendmail(self._from_email, self._to_email, msg.as_string())
            logger.info("Sync report email sent to %s", self._to_email)
            return True
        except Exception:
            logger.exception("Failed to send sync report email")
            return False

    def _build_text(self, report: SyncReport) -> str:
        lines: list[str] = []

        if report.dry_run:
            lines.append("*** DRY RUN — no actual changes were made ***\n")

        lines.append("SPOTIFY → YOUTUBE SYNC REPORT")
        lines.append("=" * 40)
        lines.append(
            f"Added: {len(report.added)}  |  "
            f"Removed: {len(report.removed)}  |  "
            f"Not found: {len(report.not_found)}  |  "
            f"Failed: {len(report.failed)}"
        )
        lines.append("")

        if report.added:
            lines.append(f"ADDED ({len(report.added)}):")
            for track in report.added:
                lines.append(f"  + {track}")
            lines.append("")

        if report.removed:
            lines.append(f"REMOVED ({len(report.removed)}):")
            for track in report.removed:
                lines.append(f"  - {track}")
            lines.append("")

        if report.not_found:
            lines.append(f"NOT FOUND ON YOUTUBE ({len(report.not_found)}):")
            for track in report.not_found:
                lines.append(f"  ? {track}")
            lines.append("")

        if report.failed:
            lines.append(f"FAILURES ({len(report.failed)}):")
            for label, error in report.failed:
                lines.append(f"  ! {label}")
                lines.append(f"    Error: {error}")
            lines.append("")

        if not report.has_changes:
            lines.append("No changes detected during this sync run.")

        return "\n".join(lines)

    def _build_html(self, report: SyncReport) -> str:
        parts: list[str] = ["<html><body>"]
        parts.append('<div style="font-family:sans-serif;max-width:600px;margin:0 auto">>')

        if report.dry_run:
            parts.append(
                '<p style="background:#fff3cd;border:1px solid #ffc107;padding:8px;'
                'border-radius:4px"><strong>DRY RUN</strong> — no actual changes were made</p>'
            )

        parts.append("<h2>Spotify → YouTube Sync Report</h2>")

        # Summary bar
        parts.append('<table style="border-collapse:collapse;margin-bottom:16px">')
        parts.append("<tr>")
        for label, count, color in [
            ("Added", len(report.added), "#28a745"),
            ("Removed", len(report.removed), "#dc3545"),
            ("Not Found", len(report.not_found), "#fd7e14"),
            ("Failed", len(report.failed), "#6c757d"),
        ]:
            parts.append(
                f'<td style="padding:8px 16px;background:{color};color:white;'
                f'border-radius:4px;margin:4px;text-align:center">'
                f"<strong>{count}</strong><br>{label}</td>"
            )
        parts.append("</tr></table>")

        def _track_list(header: str, tracks: list[TrackInfo], bullet: str, color: str) -> None:
            if not tracks:
                return
            parts.append(f'<h3 style="color:{color}">{header}</h3><ul>')
            for track in tracks:
                parts.append(f"<li><strong>{track.name}</strong> — {track.artist}</li>")
            parts.append("</ul>")

        _track_list(f"Added ({len(report.added)})", report.added, "+", "#28a745")
        _track_list(f"Removed ({len(report.removed)})", report.removed, "−", "#dc3545")
        _track_list(
            f"Not Found on YouTube ({len(report.not_found)})", report.not_found, "?", "#fd7e14"
        )

        if report.failed:
            parts.append(f'<h3 style="color:#6c757d">Failures ({len(report.failed)})</h3><ul>')
            for label, error in report.failed:
                parts.append(
                    f"<li><strong>{label}</strong><br>"
                    f'<code style="color:#dc3545">{error}</code></li>'
                )
            parts.append("</ul>")

        if not report.has_changes:
            parts.append("<p><em>No changes detected during this sync run.</em></p>")

        parts.append("</div></body></html>")
        return "".join(parts)
