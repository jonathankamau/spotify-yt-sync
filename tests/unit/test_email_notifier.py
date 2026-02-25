"""Unit tests for email_notifier.py."""

import email
import email.header
from unittest.mock import MagicMock, patch  # noqa: E402

import pytest

from email_notifier import EmailNotifier, SyncReport, TrackInfo

NOTIFIER_KWARGS = {
    "smtp_host": "smtp.example.com",
    "smtp_port": 587,
    "smtp_user": "user@example.com",
    "smtp_password": "secret",
    "from_email": "from@example.com",
    "to_email": "to@example.com",
}


@pytest.fixture
def notifier():
    return EmailNotifier(**NOTIFIER_KWARGS)


@pytest.fixture
def full_report():
    return SyncReport(
        added=[TrackInfo("Song Alpha", "Artist A"), TrackInfo("Song Beta", "Artist B")],
        removed=[TrackInfo("Old Track", "Old Artist")],
        not_found=[TrackInfo("Missing Song", "Ghost Artist")],
        failed=[("'Error Song' by Bad Artist", "API quota exceeded")],
    )


class TestSyncReport:
    def test_has_changes_false_when_empty(self):
        assert SyncReport().has_changes is False

    def test_has_changes_true_with_added(self):
        report = SyncReport(added=[TrackInfo("A", "B")])
        assert report.has_changes is True

    def test_has_changes_true_with_removed(self):
        report = SyncReport(removed=[TrackInfo("A", "B")])
        assert report.has_changes is True

    def test_has_changes_true_with_not_found(self):
        report = SyncReport(not_found=[TrackInfo("A", "B")])
        assert report.has_changes is True

    def test_has_changes_true_with_failures(self):
        report = SyncReport(failed=[("label", "error")])
        assert report.has_changes is True


class TestTrackInfo:
    def test_str_format(self):
        track = TrackInfo("Bohemian Rhapsody", "Queen")
        assert str(track) == "'Bohemian Rhapsody' by Queen"


class TestEmailNotifierSend:
    def test_send_success_returns_true(self, notifier, full_report):
        with patch("smtplib.SMTP") as mock_smtp_cls:
            mock_server = MagicMock()
            mock_smtp_cls.return_value.__enter__.return_value = mock_server
            result = notifier.send_sync_report(full_report)

        assert result is True
        mock_server.starttls.assert_called_once()
        mock_server.login.assert_called_once_with("user@example.com", "secret")
        mock_server.sendmail.assert_called_once()

    def test_send_failure_returns_false(self, notifier, full_report):
        with patch("smtplib.SMTP", side_effect=ConnectionRefusedError("refused")):
            result = notifier.send_sync_report(full_report)

        assert result is False

    def test_smtp_called_with_correct_host_port(self, notifier, full_report):
        with patch("smtplib.SMTP") as mock_smtp_cls:
            mock_smtp_cls.return_value.__enter__.return_value = MagicMock()
            notifier.send_sync_report(full_report)

        mock_smtp_cls.assert_called_once_with("smtp.example.com", 587)

    def test_sendmail_uses_correct_addresses(self, notifier, full_report):
        with patch("smtplib.SMTP") as mock_smtp_cls:
            mock_server = MagicMock()
            mock_smtp_cls.return_value.__enter__.return_value = mock_server
            notifier.send_sync_report(full_report)

        args = mock_server.sendmail.call_args[0]
        assert args[0] == "from@example.com"
        assert args[1] == "to@example.com"


class TestEmailSubject:
    def _capture_subject(self, notifier, report):
        """Helper: send a report and return the decoded subject string."""
        with patch("smtplib.SMTP") as mock_smtp_cls:
            mock_server = MagicMock()
            mock_smtp_cls.return_value.__enter__.return_value = mock_server
            notifier.send_sync_report(report)
            raw_msg = mock_server.sendmail.call_args[0][2]
        msg = email.message_from_string(raw_msg)
        decoded_parts = email.header.decode_header(msg["Subject"])
        return "".join(
            part.decode(enc or "utf-8") if isinstance(part, bytes) else part
            for part, enc in decoded_parts
        )

    def test_subject_includes_added_removed_counts(self, notifier):
        report = SyncReport(
            added=[TrackInfo("A", "B"), TrackInfo("C", "D")],
            removed=[TrackInfo("E", "F")],
        )
        subject = self._capture_subject(notifier, report)
        assert "+2 added" in subject
        assert "-1 removed" in subject

    def test_subject_includes_failure_count_when_nonzero(self, notifier):
        report = SyncReport(failed=[("track", "error")])
        subject = self._capture_subject(notifier, report)
        assert "1 failed" in subject

    def test_subject_omits_failure_when_zero(self, notifier):
        report = SyncReport(added=[TrackInfo("A", "B")])
        subject = self._capture_subject(notifier, report)
        assert "failed" not in subject

    def test_subject_has_dry_run_prefix(self, notifier):
        report = SyncReport(dry_run=True)
        subject = self._capture_subject(notifier, report)
        assert subject.startswith("[DRY RUN]")


class TestTextBody:
    def test_added_tracks_appear_in_text(self, notifier, full_report):
        text = notifier._build_text(full_report)
        assert "Song Alpha" in text
        assert "Artist A" in text
        assert "Song Beta" in text

    def test_removed_tracks_appear_in_text(self, notifier, full_report):
        text = notifier._build_text(full_report)
        assert "Old Track" in text
        assert "Old Artist" in text

    def test_not_found_tracks_appear_in_text(self, notifier, full_report):
        text = notifier._build_text(full_report)
        assert "Missing Song" in text
        assert "Ghost Artist" in text

    def test_failures_appear_in_text(self, notifier, full_report):
        text = notifier._build_text(full_report)
        assert "Error Song" in text
        assert "API quota exceeded" in text

    def test_dry_run_notice_in_text(self, notifier):
        report = SyncReport(dry_run=True)
        text = notifier._build_text(report)
        assert "DRY RUN" in text

    def test_no_changes_message_when_empty(self, notifier):
        text = notifier._build_text(SyncReport())
        assert "No changes" in text


class TestHtmlBody:
    def test_added_tracks_appear_in_html(self, notifier, full_report):
        html = notifier._build_html(full_report)
        assert "Song Alpha" in html
        assert "Artist A" in html

    def test_removed_tracks_appear_in_html(self, notifier, full_report):
        html = notifier._build_html(full_report)
        assert "Old Track" in html

    def test_not_found_tracks_appear_in_html(self, notifier, full_report):
        html = notifier._build_html(full_report)
        assert "Missing Song" in html

    def test_failures_appear_in_html(self, notifier, full_report):
        html = notifier._build_html(full_report)
        assert "API quota exceeded" in html

    def test_dry_run_banner_in_html(self, notifier):
        html = notifier._build_html(SyncReport(dry_run=True))
        assert "DRY RUN" in html

    def test_html_is_valid_structure(self, notifier, full_report):
        html = notifier._build_html(full_report)
        assert html.startswith("<html>")
        assert html.endswith("</html>")
