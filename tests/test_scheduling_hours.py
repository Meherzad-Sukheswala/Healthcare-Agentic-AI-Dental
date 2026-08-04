"""
Clinic hours are a hard constraint: an appointment must start no earlier than 9:00am and
FINISH no later than 5:00pm.

The second half is the one that bites. A 5:00pm start looks like it satisfies "9 to 5"
until you notice a 30-minute visit runs to 5:30pm — half an hour after the practice
closes, with a patient in the chair and staff unpaid. That is exactly the bug this file
exists to prevent regressing.
"""
from datetime import datetime, timedelta, timezone

from src.agents.scheduling import SchedulerOrchestrator
from src.config import Settings
from src.core.llm import LLMClient
from src.core.orchestrator import PipelineContext
from src.integrations import build_registry
from src.integrations.sandbox import SandboxSchedule
from src.integrations.seed_data import PROVIDERS

OPEN_MIN = 9 * 60          # 09:00
CLOSE_MIN = 17 * 60        # 17:00


def _minutes(iso: str) -> int:
    dt = datetime.fromisoformat(iso)
    return dt.hour * 60 + dt.minute


def _orch():
    s = Settings(_env_file=None)
    return SchedulerOrchestrator(registry=build_registry(s), llm_client=LLMClient(s))


# ------------------------------------------------------------------ the grid itself
def test_last_start_leaves_room_to_finish_before_close():
    """4:30pm is the last valid start for a 30-minute visit; 5:00pm is not a slot."""
    starts = SandboxSchedule.slot_starts()
    assert (16, 30) in starts
    assert (17, 0) not in starts
    assert max(h * 60 + m for h, m in starts) == CLOSE_MIN - SandboxSchedule._SLOT_MIN


def test_no_slot_starts_before_opening():
    starts = SandboxSchedule.slot_starts()
    assert (9, 0) in starts
    assert min(h * 60 + m for h, m in starts) == OPEN_MIN
    assert not [s for s in starts if s[0] < 9]


def test_every_slot_finishes_within_clinic_hours():
    for hour, mins in SandboxSchedule.slot_starts():
        start = hour * 60 + mins
        end = start + SandboxSchedule._SLOT_MIN
        assert start >= OPEN_MIN, f"{hour}:{mins:02d} starts before opening"
        assert end <= CLOSE_MIN, f"{hour}:{mins:02d} would run to {end // 60}:{end % 60:02d}"


def test_practice_is_closed_over_lunch():
    assert not [(h, m) for h, m in SandboxSchedule.slot_starts() if h == 12]


# ------------------------------------------------- what a provider is actually offered
async def test_provider_availability_never_falls_outside_hours():
    sched = SandboxSchedule()
    for provider in PROVIDERS[:3]:
        slots = await sched.availability(provider.npi, limit=50)
        assert slots, f"no availability for {provider.npi}"
        for slot in slots:
            start = _minutes(slot["start"])
            end = start + slot["duration_min"]
            assert start >= OPEN_MIN
            assert end <= CLOSE_MIN


async def test_availability_skips_weekends():
    sched = SandboxSchedule()
    slots = await sched.availability(PROVIDERS[0].npi, limit=50)
    for slot in slots:
        assert datetime.fromisoformat(slot["start"]).weekday() < 5


async def test_availability_is_in_the_future():
    sched = SandboxSchedule()
    slots = await sched.availability(PROVIDERS[0].npi, limit=50)
    now = datetime.now().astimezone()
    for slot in slots:
        assert datetime.fromisoformat(slot["start"]) > now


# ----------------------------------------------- what the patient is actually shown
async def test_slots_offered_to_the_patient_respect_the_window():
    """The end-to-end check: whatever reaches the slot-selection gate must be bookable."""
    ctx = PipelineContext(encounter_id="H1", input_data={
        "patient_id": "PAT-001", "request_text": "tooth pain and swelling",
        "requires_referral": False, "preferred_provider_npi": ""})
    paused = await _orch().run(ctx)
    options = paused.gate.data["options"]
    assert options, "patient was offered no appointments"
    for opt in options:
        start = _minutes(opt["start"])
        end = start + opt["duration_min"]
        assert start >= OPEN_MIN, f"option {opt['id']} starts before 9am"
        assert end <= CLOSE_MIN, f"option {opt['id']} runs past 5pm"


async def test_patient_sees_options_across_more_than_one_day():
    """Three consecutive half-hours on the same morning is not a choice. Spreading the
    offers is what makes the picker useful rather than decorative."""
    ctx = PipelineContext(encounter_id="H2", input_data={
        "patient_id": "PAT-001", "request_text": "tooth pain and swelling",
        "requires_referral": False, "preferred_provider_npi": ""})
    paused = await _orch().run(ctx)
    days = {datetime.fromisoformat(o["start"]).date() for o in paused.gate.data["options"]}
    assert len(days) > 1, f"all options fell on one day: {days}"


def test_booking_a_slot_removes_it_from_availability():
    """Guards the constraint against a second route in: a booked slot must not reappear."""
    import asyncio

    async def run():
        sched = SandboxSchedule()
        npi = PROVIDERS[0].npi
        first = (await sched.availability(npi, limit=1))[0]["start"]
        assert await sched.book(npi, first) is True
        assert await sched.book(npi, first) is False          # no double-booking
        remaining = [s["start"] for s in await sched.availability(npi, limit=50)]
        assert first not in remaining

    asyncio.run(run())


# ------------------------------------------------------- timezone (the 5am regression)
async def test_slots_are_stamped_in_the_clinic_timezone_not_the_servers():
    """The bug: slots were generated with `datetime.now().astimezone()`, i.e. the SERVER's
    zone. That is fine on a laptop in the clinic's timezone and wrong the moment it
    deploys — Render runs containers in UTC, so a 9:30am slot went out as 09:30+00:00 and
    a patient in US Eastern saw 5:30am. The offset must be the CLINIC's, for that date."""
    clinic_tz = Settings(_env_file=None).clinic_tz()
    sched = SandboxSchedule()
    slots = await sched.availability(PROVIDERS[0].npi, limit=10)
    assert slots
    for slot in slots:
        dt = datetime.fromisoformat(slot["start"])
        assert dt.tzinfo is not None, "slot is timezone-naive — ambiguous"
        assert dt.utcoffset() == clinic_tz.utcoffset(dt.replace(tzinfo=None)), (
            f"{slot['start']} does not carry the clinic's offset")
        assert slot["timezone"] == str(clinic_tz)


async def test_clinic_local_time_is_9_to_5_even_though_utc_is_not():
    """The distinguishing check. If we were still stamping UTC, clinic-local and UTC would
    be identical. They must differ, while CLINIC-local stays inside 9-5."""
    sched = SandboxSchedule()
    slots = await sched.availability(PROVIDERS[0].npi, limit=6)
    differed = False
    for slot in slots:
        dt = datetime.fromisoformat(slot["start"])
        local_min = dt.hour * 60 + dt.minute
        assert OPEN_MIN <= local_min <= CLOSE_MIN - SandboxSchedule._SLOT_MIN
        utc = dt.astimezone(timezone.utc)
        if (utc.hour * 60 + utc.minute) != local_min:
            differed = True
    assert differed, "clinic time equals UTC — slots are still being stamped in UTC"


async def test_every_slot_carries_a_prebuilt_clinic_local_display_string():
    """The UI renders `display` verbatim. If it were missing it would fall back to parsing
    the ISO string, which a browser converts to the VIEWER's timezone — the original bug."""
    sched = SandboxSchedule()
    for slot in await sched.availability(PROVIDERS[0].npi, limit=10):
        dt = datetime.fromisoformat(slot["start"])
        hour12 = dt.strftime("%I").lstrip("0") or "12"
        assert slot["display"], "no display string — the UI would reconvert and drift"
        assert f"{hour12}:{dt:%M %p}" in slot["display"], (
            f"{slot['display']!r} disagrees with {slot['start']}")
        assert slot["window"]


async def test_no_slot_ever_displays_a_time_outside_9am_to_5pm():
    """Reads the rendered strings the way a patient would, not the underlying data."""
    sched = SandboxSchedule()
    for slot in await sched.availability(PROVIDERS[0].npi, limit=20):
        shown = slot["display"].rsplit(", ", 1)[-1]              # "9:30 AM"
        hh, rest = shown.split(":")
        mm, meridiem = rest.split(" ")
        hour24 = int(hh) % 12 + (12 if meridiem == "PM" else 0)
        minutes = hour24 * 60 + int(mm)
        assert OPEN_MIN <= minutes <= CLOSE_MIN - SandboxSchedule._SLOT_MIN, (
            f"patient is shown {shown}, outside 9am-5pm")
        assert "AM" in slot["display"] or "PM" in slot["display"]


async def test_options_reaching_the_patient_carry_the_timezone():
    ctx = PipelineContext(encounter_id="H3", input_data={
        "patient_id": "PAT-001", "request_text": "tooth pain and swelling",
        "requires_referral": False, "preferred_provider_npi": ""})
    paused = await _orch().run(ctx)
    clinic = str(Settings(_env_file=None).clinic_tz())
    for opt in paused.gate.data["options"]:
        assert opt["display"], f"option {opt['id']} has no clinic-local label"
        assert opt["timezone"] == clinic


def test_a_bad_clinic_timezone_fails_at_startup_not_at_booking():
    """A typo should surface immediately with a clear message, not as a
    ZoneInfoNotFoundError deep inside slot generation on a patient's first booking."""
    import pytest
    with pytest.raises(Exception) as exc:
        Settings(_env_file=None, clinic_timezone="America/Nowhere")
    assert "CLINIC_TIMEZONE" in str(exc.value)


def test_window_constants_are_the_documented_ones():
    """If someone widens the window, this test should make them say so out loud."""
    assert SandboxSchedule._OPEN_HOUR == 9
    assert SandboxSchedule._CLOSE_HOUR == 17
    assert SandboxSchedule._SLOT_MIN == 30
    assert timedelta(minutes=SandboxSchedule._SLOT_MIN) == timedelta(minutes=30)
