"""
Scheduling domain — 9 single-task agents in SchedulerOrchestrator, plus one more
(recall_scheduler) invoked directly by MasterOrchestrator after the visit completes.

  request_parser        (LLM)         parse the illness description -> specialty
  triage_classifier     (rules)       assign urgency
  referral_approval     (HUMAN GATE)  PCP referral sign-off (conditional)
  provider_matcher      (directory)   match doctors by specialty (NPPES)
  availability_finder   (calendar)    gather open slots across matched doctors
  slot_selection        (HUMAN GATE)  patient picks doctor + time (always)
  appointment_creator   (det.)        book the chosen slot
  reminder_dispatcher   (det.)        schedule reminders
  audit_logger          (det.)        HIPAA audit trail

  recall_scheduler       (det.)       post-visit recare interval — see its docstring
                                       for why it isn't a step in build_steps() above
"""
from .orchestrator import SchedulerOrchestrator

__all__ = ["SchedulerOrchestrator"]
