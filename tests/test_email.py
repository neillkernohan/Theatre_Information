"""Tests for email functions — mail.send is mocked so nothing actually goes out."""
import pytest
from unittest.mock import patch, MagicMock
from datetime import date, time


@pytest.fixture
def registration(db, actor, slot_show, slot):
    from auditions.models import Registration
    reg = Registration(
        user_id=actor.id,
        show_id=slot_show.id,
        slot_id=slot.id,
        status='confirmed',
    )
    db.session.add(reg)
    slot.current_count = 1
    db.session.commit()
    return reg


@pytest.fixture
def waitlisted_reg(db, actor, slot_show):
    from auditions.models import Registration
    reg = Registration(
        user_id=actor.id,
        show_id=slot_show.id,
        status='waitlisted',
    )
    db.session.add(reg)
    db.session.commit()
    return reg


class TestConfirmationEmail:

    def test_sends_to_correct_address(self, app, registration):
        with app.app_context():
            with patch('auditions.email._get_mail') as mock_mail_fn:
                mock_mail = MagicMock()
                mock_mail_fn.return_value = mock_mail
                from auditions.email import send_confirmation_email
                send_confirmation_email(registration)
                mock_mail.send.assert_called_once()
                msg = mock_mail.send.call_args[0][0]
                assert registration.user.email in msg.recipients

    def test_subject_contains_show_title(self, app, registration):
        with app.app_context():
            with patch('auditions.email._get_mail') as mock_mail_fn:
                mock_mail = MagicMock()
                mock_mail_fn.return_value = mock_mail
                from auditions.email import send_confirmation_email
                send_confirmation_email(registration)
                msg = mock_mail.send.call_args[0][0]
                assert registration.show.title in msg.subject

    def test_logs_sent_status_on_success(self, app, registration, db):
        with app.app_context():
            with patch('auditions.email._get_mail') as mock_mail_fn:
                mock_mail = MagicMock()
                mock_mail_fn.return_value = mock_mail
                from auditions.email import send_confirmation_email
                from auditions.models import EmailLog
                send_confirmation_email(registration)
                log = EmailLog.query.filter_by(
                    registration_id=registration.id,
                    email_type='confirmation'
                ).first()
                assert log is not None
                assert log.status == 'sent'

    def test_logs_failed_status_on_error(self, app, registration, db):
        with app.app_context():
            with patch('auditions.email._get_mail') as mock_mail_fn:
                mock_mail = MagicMock()
                mock_mail.send.side_effect = Exception('SMTP error')
                mock_mail_fn.return_value = mock_mail
                from auditions.email import send_confirmation_email
                from auditions.models import EmailLog
                result = send_confirmation_email(registration)
                assert result is False
                log = EmailLog.query.filter_by(
                    registration_id=registration.id,
                    email_type='confirmation'
                ).first()
                assert log.status == 'failed'
                assert 'SMTP error' in log.error_message


class TestWaitlistEmail:

    def test_waitlist_email_sent(self, app, waitlisted_reg):
        with app.app_context():
            with patch('auditions.email._get_mail') as mock_mail_fn:
                mock_mail = MagicMock()
                mock_mail_fn.return_value = mock_mail
                from auditions.email import send_waitlist_email
                send_waitlist_email(waitlisted_reg)
                mock_mail.send.assert_called_once()

    def test_waitlist_subject(self, app, waitlisted_reg):
        with app.app_context():
            with patch('auditions.email._get_mail') as mock_mail_fn:
                mock_mail = MagicMock()
                mock_mail_fn.return_value = mock_mail
                from auditions.email import send_waitlist_email
                send_waitlist_email(waitlisted_reg)
                msg = mock_mail.send.call_args[0][0]
                assert 'Waitlisted' in msg.subject


class TestCallbackEmail:

    def test_callback_email_sent_with_details(self, app, registration):
        with app.app_context():
            with patch('auditions.email._get_mail') as mock_mail_fn:
                mock_mail = MagicMock()
                mock_mail_fn.return_value = mock_mail
                from auditions.email import send_callback_email
                send_callback_email(registration, callback_details='Thursday at 7pm')
                mock_mail.send.assert_called_once()
                msg = mock_mail.send.call_args[0][0]
                assert 'Callback' in msg.subject


class TestReminderEmail:

    def test_reminder_email_sent(self, app, registration):
        with app.app_context():
            with patch('auditions.email._get_mail') as mock_mail_fn:
                mock_mail = MagicMock()
                mock_mail_fn.return_value = mock_mail
                from auditions.email import send_reminder_email
                send_reminder_email(registration)
                mock_mail.send.assert_called_once()

    def test_reminder_subject_says_tomorrow(self, app, registration):
        with app.app_context():
            with patch('auditions.email._get_mail') as mock_mail_fn:
                mock_mail = MagicMock()
                mock_mail_fn.return_value = mock_mail
                from auditions.email import send_reminder_email
                send_reminder_email(registration)
                msg = mock_mail.send.call_args[0][0]
                assert 'Tomorrow' in msg.subject


class TestCancellationEmail:

    def test_cancellation_email_sent(self, app, registration):
        with app.app_context():
            with patch('auditions.email._get_mail') as mock_mail_fn:
                mock_mail = MagicMock()
                mock_mail_fn.return_value = mock_mail
                from auditions.email import send_cancellation_email
                send_cancellation_email(registration)
                mock_mail.send.assert_called_once()


class TestInfoRequestEmail:

    def test_info_request_with_items(self, app, registration):
        with app.app_context():
            with patch('auditions.email._get_mail') as mock_mail_fn:
                mock_mail = MagicMock()
                mock_mail_fn.return_value = mock_mail
                from auditions.email import send_info_request_email
                send_info_request_email(registration, requested_items=['Headshot', 'Résumé'])
                mock_mail.send.assert_called_once()
