from fastapi import APIRouter, Form, Request

router = APIRouter(prefix="/webhooks", tags=["webhooks"])


@router.post("/twilio/status")
async def twilio_status_callback(
    request: Request,
    CallSid: str = Form(""),
    CallStatus: str = Form(""),
    CallDuration: str = Form("0"),
):
    from app.workers.telephony import handle_call_status

    handle_call_status.delay(CallSid, CallStatus, int(CallDuration or 0))
    return {"status": "ok"}


@router.post("/twilio/recording")
async def twilio_recording_callback(
    request: Request,
    CallSid: str = Form(""),
    RecordingUrl: str = Form(""),
    RecordingSid: str = Form(""),
    RecordingDuration: str = Form("0"),
):
    from app.workers.telephony import handle_recording_ready

    handle_recording_ready.delay(CallSid, RecordingUrl, RecordingSid, int(RecordingDuration or 0))
    return {"status": "ok"}
