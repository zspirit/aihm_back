import uuid
from unittest.mock import MagicMock, patch

import pytest


def _make_tenant():
    t = MagicMock()
    t.id = uuid.uuid4()
    t.name = "Acme Corp"
    return t


def _make_candidate(tenant_id=None, position_id=None, email="test@example.com", phone="+212600000000"):
    c = MagicMock()
    c.id = uuid.uuid4()
    c.tenant_id = tenant_id or uuid.uuid4()
    c.position_id = position_id or uuid.uuid4()
    c.name = "Jean Dupont"
    c.email = email
    c.phone = phone
    c.pipeline_status = "scored"
    return c


def _make_position(title="Dev Python"):
    p = MagicMock()
    p.id = uuid.uuid4()
    p.title = title
    return p


def _make_consent(candidate_id=None, granted=False):
    c = MagicMock()
    c.id = uuid.uuid4()
    c.candidate_id = candidate_id or uuid.uuid4()
    c.token = "abc123token"
    c.type = "data_processing"
    c.granted = granted
    return c


def _make_interview(candidate_id=None, position_id=None, tenant_id=None, duration=367):
    i = MagicMock()
    i.id = uuid.uuid4()
    i.candidate_id = candidate_id or uuid.uuid4()
    i.position_id = position_id or uuid.uuid4()
    i.tenant_id = tenant_id or uuid.uuid4()
    i.duration_seconds = duration
    return i


def _make_user(tenant_id=None, role="admin"):
    u = MagicMock()
    u.id = uuid.uuid4()
    u.tenant_id = tenant_id or uuid.uuid4()
    u.email = f"{role}@test.com"
    u.full_name = f"{role.capitalize()} User"
    u.role = role
    return u


class TestSendEmail:
    @patch("app.core.config.get_settings")
    def test_skip_no_api_key(self, mock_settings):
        from app.workers.notifications import send_email

        mock_settings.return_value = MagicMock(RESEND_API_KEY="")
        result = send_email("to@test.com", "Subject", "<p>body</p>")
        assert result["status"] == "skipped"
        assert result["reason"] == "no_api_key"

    @patch("app.core.config.get_settings")
    def test_skip_none_api_key(self, mock_settings):
        from app.workers.notifications import send_email

        mock_settings.return_value = MagicMock(RESEND_API_KEY=None)
        result = send_email("to@test.com", "Subject", "<p>body</p>")
        assert result["status"] == "skipped"

    @patch("httpx.post")
    @patch("app.core.config.get_settings")
    def test_happy_path(self, mock_settings, mock_httpx_post):
        from app.workers.notifications import send_email

        mock_settings.return_value = MagicMock(RESEND_API_KEY="re_test", EMAIL_FROM="noreply@aihm.ai")
        mock_response = MagicMock()
        mock_response.raise_for_status = MagicMock()
        mock_httpx_post.return_value = mock_response

        result = send_email("to@test.com", "Hello", "<p>hi</p>")
        assert result["status"] == "sent"
        mock_httpx_post.assert_called_once()
        call_kwargs = mock_httpx_post.call_args
        assert call_kwargs[1]["json"]["to"] == ["to@test.com"]

    @patch("httpx.post")
    @patch("app.core.config.get_settings")
    def test_http_error(self, mock_settings, mock_httpx_post):
        from app.workers.notifications import send_email

        mock_settings.return_value = MagicMock(RESEND_API_KEY="re_test", EMAIL_FROM="noreply@aihm.ai")
        mock_httpx_post.side_effect = Exception("Connection refused")

        result = send_email("to@test.com", "Hello", "<p>hi</p>")
        assert result["status"] == "error"
        assert "Connection refused" in result["error"]


class TestSendSms:
    @patch("app.core.config.get_settings")
    def test_skip_no_credentials(self, mock_settings):
        from app.workers.notifications import send_sms

        mock_settings.return_value = MagicMock(TWILIO_ACCOUNT_SID="", TWILIO_AUTH_TOKEN="")
        result = send_sms("+212600000000", "Hello")
        assert result["status"] == "skipped"
        assert result["reason"] == "no_credentials"

    @patch("app.core.config.get_settings")
    def test_skip_no_sid(self, mock_settings):
        from app.workers.notifications import send_sms

        mock_settings.return_value = MagicMock(TWILIO_ACCOUNT_SID=None, TWILIO_AUTH_TOKEN="token")
        result = send_sms("+212600000000", "Hello")
        assert result["status"] == "skipped"

    @patch("twilio.rest.Client")
    @patch("app.core.config.get_settings")
    def test_happy_path(self, mock_settings, mock_twilio_client):
        from app.workers.notifications import send_sms

        mock_settings.return_value = MagicMock(
            TWILIO_ACCOUNT_SID="AC_test", TWILIO_AUTH_TOKEN="auth_test",
            TWILIO_PHONE_NUMBER="+15551234567",
        )
        mock_message = MagicMock()
        mock_message.sid = "SM_test123"
        mock_twilio_client.return_value.messages.create.return_value = mock_message

        result = send_sms("+212600000000", "Hello")
        assert result["status"] == "sent"
        assert result["sid"] == "SM_test123"

    @patch("twilio.rest.Client")
    @patch("app.core.config.get_settings")
    def test_twilio_error(self, mock_settings, mock_twilio_client):
        from app.workers.notifications import send_sms

        mock_settings.return_value = MagicMock(
            TWILIO_ACCOUNT_SID="AC_test", TWILIO_AUTH_TOKEN="auth_test",
            TWILIO_PHONE_NUMBER="+15551234567",
        )
        mock_twilio_client.return_value.messages.create.side_effect = Exception("Twilio error")

        result = send_sms("+212600000000", "Hello")
        assert result["status"] == "error"
        assert "Twilio error" in result["error"]


class TestSendConsentEmail:
    @patch("app.workers.base.get_sync_session")
    def test_candidate_not_found(self, mock_get_session):
        from app.workers.notifications import send_consent_email

        session = MagicMock()
        mock_get_session.return_value = session
        session.get.return_value = None

        result = send_consent_email(str(uuid.uuid4()))
        assert result is None
        session.close.assert_called_once()

    @patch("app.workers.base.get_sync_session")
    def test_candidate_no_email(self, mock_get_session):
        from app.workers.notifications import send_consent_email

        session = MagicMock()
        mock_get_session.return_value = session
        candidate = _make_candidate(email=None)
        session.get.return_value = candidate

        result = send_consent_email(str(uuid.uuid4()))
        assert result is None

    @patch("app.services.email.render")
    @patch("app.workers.base.get_sync_session")
    def test_happy_path_with_phone(self, mock_get_session, mock_render):
        from app.workers.notifications import send_consent_email

        tenant = _make_tenant()
        position = _make_position()
        candidate = _make_candidate(tenant_id=tenant.id, position_id=position.id)
        consent = _make_consent(candidate_id=candidate.id)

        session = MagicMock()
        mock_get_session.return_value = session

        def get_side_effect(model_cls, uid):
            name = model_cls.__name__
            if name == "Candidate":
                return candidate
            if name == "Position":
                return position
            if name == "Tenant":
                return tenant
            return None

        session.get.side_effect = get_side_effect

        mock_scalar = MagicMock()
        mock_scalar.scalar_one_or_none.return_value = consent
        session.execute.return_value = mock_scalar

        mock_render.return_value = "<html>consent</html>"

        with patch("app.core.config.get_settings") as mock_settings, \
             patch("app.workers.notifications.send_email") as mock_send_email, \
             patch("app.workers.notifications.send_sms") as mock_send_sms:
            mock_settings.return_value = MagicMock(FRONTEND_URL="https://app.aihm.ai")
            mock_send_email.delay = MagicMock()
            mock_send_sms.delay = MagicMock()

            send_consent_email(str(candidate.id))

            mock_send_email.delay.assert_called_once()
            mock_send_sms.delay.assert_called_once()

        assert candidate.pipeline_status == "invited"
        session.commit.assert_called_once()

    @patch("app.services.email.render")
    @patch("app.workers.base.get_sync_session")
    def test_no_phone_skips_sms(self, mock_get_session, mock_render):
        from app.workers.notifications import send_consent_email

        tenant = _make_tenant()
        position = _make_position()
        candidate = _make_candidate(tenant_id=tenant.id, position_id=position.id, phone=None)
        consent = _make_consent(candidate_id=candidate.id)

        session = MagicMock()
        mock_get_session.return_value = session

        def get_side_effect(model_cls, uid):
            name = model_cls.__name__
            if name == "Candidate":
                return candidate
            if name == "Position":
                return position
            if name == "Tenant":
                return tenant
            return None

        session.get.side_effect = get_side_effect

        mock_scalar = MagicMock()
        mock_scalar.scalar_one_or_none.return_value = consent
        session.execute.return_value = mock_scalar

        mock_render.return_value = "<html>consent</html>"

        with patch("app.core.config.get_settings") as mock_settings, \
             patch("app.workers.notifications.send_email") as mock_send_email, \
             patch("app.workers.notifications.send_sms") as mock_send_sms:
            mock_settings.return_value = MagicMock(FRONTEND_URL="https://app.aihm.ai")
            mock_send_email.delay = MagicMock()
            mock_send_sms.delay = MagicMock()

            send_consent_email(str(candidate.id))

            mock_send_email.delay.assert_called_once()
            mock_send_sms.delay.assert_not_called()

    @patch("app.workers.base.get_sync_session")
    def test_no_consent_record(self, mock_get_session):
        from app.workers.notifications import send_consent_email

        candidate = _make_candidate()
        session = MagicMock()
        mock_get_session.return_value = session
        session.get.return_value = candidate

        mock_scalar = MagicMock()
        mock_scalar.scalar_one_or_none.return_value = None
        session.execute.return_value = mock_scalar

        result = send_consent_email(str(candidate.id))
        assert result is None


class TestSendConsentReminder:
    @patch("app.workers.base.get_sync_session")
    def test_candidate_not_found(self, mock_get_session):
        from app.workers.notifications import send_consent_reminder

        session = MagicMock()
        mock_get_session.return_value = session
        session.get.return_value = None

        result = send_consent_reminder(str(uuid.uuid4()))
        assert result is None

    @patch("app.workers.base.get_sync_session")
    def test_already_consented_skips(self, mock_get_session):
        from app.workers.notifications import send_consent_reminder

        candidate = _make_candidate()
        consented = _make_consent(candidate_id=candidate.id, granted=True)

        session = MagicMock()
        mock_get_session.return_value = session
        session.get.return_value = candidate

        mock_scalar = MagicMock()
        mock_scalar.scalar_one_or_none.return_value = consented
        session.execute.return_value = mock_scalar

        result = send_consent_reminder(str(candidate.id))
        assert result is None

    @patch("app.services.email.render")
    @patch("app.workers.base.get_sync_session")
    def test_happy_path(self, mock_get_session, mock_render):
        from app.workers.notifications import send_consent_reminder

        tenant = _make_tenant()
        position = _make_position()
        candidate = _make_candidate(tenant_id=tenant.id, position_id=position.id)
        consent = _make_consent(candidate_id=candidate.id, granted=False)

        session = MagicMock()
        mock_get_session.return_value = session

        def get_side_effect(model_cls, uid):
            name = model_cls.__name__
            if name == "Candidate":
                return candidate
            if name == "Position":
                return position
            if name == "Tenant":
                return tenant
            return None

        session.get.side_effect = get_side_effect

        # First execute: check if already consented -> None
        # Second execute: get consent record -> consent
        mock_scalar_none = MagicMock()
        mock_scalar_none.scalar_one_or_none.return_value = None
        mock_scalar_consent = MagicMock()
        mock_scalar_consent.scalar_one_or_none.return_value = consent
        session.execute.side_effect = [mock_scalar_none, mock_scalar_consent]

        mock_render.return_value = "<html>reminder</html>"

        with patch("app.core.config.get_settings") as mock_settings, \
             patch("app.workers.notifications.send_email") as mock_send_email, \
             patch("app.workers.notifications.send_sms") as mock_send_sms:
            mock_settings.return_value = MagicMock(FRONTEND_URL="https://app.aihm.ai")
            mock_send_email.delay = MagicMock()
            mock_send_sms.delay = MagicMock()

            send_consent_reminder(str(candidate.id))

            mock_send_email.delay.assert_called_once()
            mock_send_sms.delay.assert_called_once()


class TestSendReportReady:
    @patch("app.workers.base.get_sync_session")
    def test_interview_not_found(self, mock_get_session):
        from app.workers.notifications import send_report_ready

        session = MagicMock()
        mock_get_session.return_value = session
        session.get.return_value = None

        result = send_report_ready(str(uuid.uuid4()))
        assert result is None

    @patch("app.services.email.render")
    @patch("app.workers.base.get_sync_session")
    def test_happy_path(self, mock_get_session, mock_render):
        from app.workers.notifications import send_report_ready

        tenant = _make_tenant()
        position = _make_position()
        candidate = _make_candidate(tenant_id=tenant.id, position_id=position.id)
        interview = _make_interview(
            candidate_id=candidate.id, position_id=position.id, tenant_id=tenant.id,
        )
        admin = _make_user(tenant_id=tenant.id, role="admin")
        recruiter = _make_user(tenant_id=tenant.id, role="recruiter")
        recruiter.email = "recruiter@test.com"

        report = MagicMock()
        report.content = {"global_score": 78}

        session = MagicMock()
        mock_get_session.return_value = session

        def get_side_effect(model_cls, uid):
            name = model_cls.__name__
            if name == "Interview":
                return interview
            if name == "Candidate":
                return candidate
            if name == "Position":
                return position
            if name == "Tenant":
                return tenant
            return None

        session.get.side_effect = get_side_effect

        mock_report_result = MagicMock()
        mock_report_result.scalar_one_or_none.return_value = report
        mock_users_result = MagicMock()
        mock_users_result.scalars.return_value.all.return_value = [admin, recruiter]
        session.execute.side_effect = [mock_report_result, mock_users_result]

        mock_render.return_value = "<html>report ready</html>"

        with patch("app.core.config.get_settings") as mock_settings, \
             patch("app.workers.notifications.send_email") as mock_send_email:
            mock_settings.return_value = MagicMock(FRONTEND_URL="https://app.aihm.ai")
            mock_send_email.delay = MagicMock()

            send_report_ready(str(interview.id))

            assert mock_send_email.delay.call_count == 2

        assert session.add.call_count == 2
        session.commit.assert_called_once()

    @patch("app.services.email.render")
    @patch("app.workers.base.get_sync_session")
    def test_no_report_content(self, mock_get_session, mock_render):
        from app.workers.notifications import send_report_ready

        tenant = _make_tenant()
        position = _make_position()
        candidate = _make_candidate(tenant_id=tenant.id, position_id=position.id)
        interview = _make_interview(
            candidate_id=candidate.id, position_id=position.id, tenant_id=tenant.id,
        )
        admin = _make_user(tenant_id=tenant.id)

        session = MagicMock()
        mock_get_session.return_value = session

        def get_side_effect(model_cls, uid):
            name = model_cls.__name__
            if name == "Interview":
                return interview
            if name == "Candidate":
                return candidate
            if name == "Position":
                return position
            if name == "Tenant":
                return tenant
            return None

        session.get.side_effect = get_side_effect

        mock_report_result = MagicMock()
        mock_report_result.scalar_one_or_none.return_value = None
        mock_users_result = MagicMock()
        mock_users_result.scalars.return_value.all.return_value = [admin]
        session.execute.side_effect = [mock_report_result, mock_users_result]

        mock_render.return_value = "<html>report</html>"

        with patch("app.core.config.get_settings") as mock_settings, \
             patch("app.workers.notifications.send_email") as mock_send_email:
            mock_settings.return_value = MagicMock(FRONTEND_URL="https://app.aihm.ai")
            mock_send_email.delay = MagicMock()

            send_report_ready(str(interview.id))

            mock_send_email.delay.assert_called_once()


class TestSendInterviewComplete:
    @patch("app.workers.base.get_sync_session")
    def test_interview_not_found(self, mock_get_session):
        from app.workers.notifications import send_interview_complete

        session = MagicMock()
        mock_get_session.return_value = session
        session.get.return_value = None

        result = send_interview_complete(str(uuid.uuid4()))
        assert result is None

    @patch("app.workers.base.get_sync_session")
    def test_candidate_no_email(self, mock_get_session):
        from app.workers.notifications import send_interview_complete

        interview = _make_interview()
        candidate = _make_candidate(email=None)

        session = MagicMock()
        mock_get_session.return_value = session

        def get_side_effect(model_cls, uid):
            name = model_cls.__name__
            if name == "Interview":
                return interview
            if name == "Candidate":
                return candidate
            return None

        session.get.side_effect = get_side_effect

        result = send_interview_complete(str(interview.id))
        assert result is None

    @patch("app.services.email.render")
    @patch("app.workers.base.get_sync_session")
    def test_happy_path(self, mock_get_session, mock_render):
        from app.workers.notifications import send_interview_complete

        tenant = _make_tenant()
        position = _make_position()
        candidate = _make_candidate(tenant_id=tenant.id, position_id=position.id)
        interview = _make_interview(
            candidate_id=candidate.id, position_id=position.id,
            tenant_id=tenant.id, duration=367,
        )

        session = MagicMock()
        mock_get_session.return_value = session

        def get_side_effect(model_cls, uid):
            name = model_cls.__name__
            if name == "Interview":
                return interview
            if name == "Candidate":
                return candidate
            if name == "Position":
                return position
            if name == "Tenant":
                return tenant
            return None

        session.get.side_effect = get_side_effect

        mock_render.return_value = "<html>complete</html>"

        with patch("app.workers.notifications.send_email") as mock_send_email:
            mock_send_email.delay = MagicMock()

            send_interview_complete(str(interview.id))

            mock_send_email.delay.assert_called_once()
            call_args = mock_send_email.delay.call_args
            assert candidate.email == call_args[0][0]
            assert "Dev Python" in call_args[0][1]

    @patch("app.services.email.render")
    @patch("app.workers.base.get_sync_session")
    def test_duration_formatting(self, mock_get_session, mock_render):
        from app.workers.notifications import send_interview_complete

        tenant = _make_tenant()
        position = _make_position()
        candidate = _make_candidate(tenant_id=tenant.id, position_id=position.id)
        interview = _make_interview(
            candidate_id=candidate.id, position_id=position.id,
            tenant_id=tenant.id, duration=0,
        )

        session = MagicMock()
        mock_get_session.return_value = session

        def get_side_effect(model_cls, uid):
            name = model_cls.__name__
            if name == "Interview":
                return interview
            if name == "Candidate":
                return candidate
            if name == "Position":
                return position
            if name == "Tenant":
                return tenant
            return None

        session.get.side_effect = get_side_effect

        mock_render.return_value = "<html>done</html>"

        with patch("app.workers.notifications.send_email") as mock_send_email:
            mock_send_email.delay = MagicMock()

            send_interview_complete(str(interview.id))

            render_kwargs = mock_render.call_args[1]
            assert render_kwargs["duration"] == "0 min 00 s"
