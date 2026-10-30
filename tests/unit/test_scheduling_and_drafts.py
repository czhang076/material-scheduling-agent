from dataclasses import replace
import unittest

from material_scheduler.domain.drafts import (
    ConfirmationCommand, Draft, DraftProposal, DraftState, confirm_draft,
    create_draft, invalidate_draft, propose_draft, replan_draft,
)
from material_scheduler.domain.review import ReviewStatus, RuleSet, evaluate_review
from material_scheduler.domain.scheduling import (
    Booking, Candidate, QueryMode, SlotOffer, conflicts_for, query_slots,
)
from material_scheduler.domain.time import TimeInterval, parse_time
from material_scheduler.domain.validation import DomainError
from .helpers import candidate, fixture_data, item


def booking(hour=18, channel="douyin"):
    return Booking(
        "B01", 1, channel,
        TimeInterval(parse_time(f"2030-06-01T{hour:02}:00+08:00"), parse_time(f"2030-06-01T{hour:02}:30+08:00")),
    )


class SchedulingTests(unittest.TestCase):
    def setUp(self):
        self.data = fixture_data()
        self.item = item()

    def test_requested_slot_and_conflict_alternative(self):
        normal = query_slots(self.item, self.data.slot_offers, (), QueryMode.REQUESTED)
        self.assertTrue(normal.requested_available)
        self.assertEqual(normal.candidates[0].offer_id, "O18")
        conflict = query_slots(self.item, self.data.slot_offers, (booking(),), QueryMode.REQUESTED)
        self.assertFalse(conflict.requested_available)
        self.assertEqual(conflict.candidates, ())
        self.assertEqual(conflict.requested_conflicts[0].booking_id, "B01")
        alternatives = query_slots(self.item, self.data.slot_offers, (booking(),), QueryMode.ALTERNATIVES)
        self.assertEqual([entry.offer_id for entry in alternatives.candidates], ["O19", "O20"])

    def test_changed_occupancy_changes_current_availability(self):
        result = query_slots(self.item, self.data.slot_offers, (booking(19),), QueryMode.REQUESTED)
        self.assertTrue(result.requested_available)
        alternatives = query_slots(self.item, self.data.slot_offers, (booking(19),), QueryMode.ALTERNATIVES)
        self.assertEqual([entry.offer_id for entry in alternatives.candidates], ["O20"])

    def test_all_slots_occupied_returns_no_invented_candidate(self):
        occupied = tuple(replace(booking(hour), booking_id=f"B{hour}") for hour in (18, 19, 20))
        result = query_slots(self.item, self.data.slot_offers, occupied, QueryMode.ALTERNATIVES)
        self.assertEqual(result.candidates, ())

    def test_other_channel_and_adjacent_slots_do_not_conflict(self):
        interval = self.item.time_requirement.requested_interval
        self.assertEqual(conflicts_for("douyin", interval, (booking(channel="bilibili"),)), ())
        adjacent = Booking("B02", 1, "douyin", TimeInterval(interval.end, parse_time("2030-06-01T19:00+08:00")))
        self.assertEqual(conflicts_for("douyin", interval, (adjacent,)), ())

    def test_self_exclusion_is_explicit(self):
        interval = self.item.time_requirement.requested_interval
        self.assertEqual(len(conflicts_for("douyin", interval, (booking(),))), 1)
        self.assertEqual(conflicts_for("douyin", interval, (booking(),), exclude_booking_id="B01"), ())

    def test_offer_must_cover_full_duration_and_request_window(self):
        longer = replace(self.item, time_requirement=replace(self.item.time_requirement, duration_minutes=60))
        result = query_slots(longer, self.data.slot_offers, (), QueryMode.REQUESTED)
        self.assertFalse(result.requested_available)
        outside = SlotOffer(
            "OUTSIDE", 1, "douyin",
            TimeInterval(parse_time("2030-06-01T21:00+08:00"), parse_time("2030-06-01T21:30+08:00")),
        )
        result = query_slots(self.item, (outside,), (), QueryMode.ALTERNATIVES)
        self.assertEqual(result.candidates, ())

    def test_offer_duplicates_and_order_do_not_duplicate_suggestions(self):
        duplicate = replace(self.data.slot_offers[1], offer_id="O19-DUP")
        offers = (duplicate, *reversed(self.data.slot_offers))
        result = query_slots(self.item, offers, (), QueryMode.ALTERNATIVES, limit=1)
        self.assertEqual(len(result.candidates), 1)
        self.assertEqual(result.candidates[0].offer_id, "O19")

    def test_query_rejects_boolean_limit_and_unknown_mode(self):
        for value in (0, 11, True, "1"):
            with self.assertRaises(DomainError):
                query_slots(self.item, self.data.slot_offers, (), QueryMode.REQUESTED, limit=value)
        with self.assertRaises(DomainError):
            query_slots(self.item, self.data.slot_offers, (), "requested")


class DraftLifecycleTests(unittest.TestCase):
    def setUp(self):
        self.data = fixture_data()
        self.item = item()
        self.review = evaluate_review(self.data.material("M01"), self.data.rule_set, "douyin")
        self.alternative, self.offer = candidate(self.item, 19)
        self.proposal = propose_draft(self.item, self.review, self.alternative)
        self.draft = create_draft("D01", "REQ01", self.proposal)

    def command(self, draft=None, accepted=None):
        draft = draft or self.draft
        return ConfirmationCommand(
            "C01", draft.draft_id, draft.version,
            draft.pending_confirmations if accepted is None else accepted, "本地运营",
        )

    def test_normal_draft_is_ready_and_never_published(self):
        original, _ = candidate(self.item, 18)
        draft = create_draft("D02", "REQ02", propose_draft(self.item, self.review, original))
        self.assertEqual(draft.state, DraftState.READY)
        self.assertFalse(draft.published)

    def test_hard_time_change_retains_original_requirement_and_needs_consent(self):
        self.assertEqual(self.draft.state, DraftState.PENDING_CONFIRMATION)
        self.assertEqual(self.draft.pending_confirmations, ("TIME_CHANGE",))
        self.assertEqual(self.draft.proposal.item.time_requirement.requested_start.hour, 18)
        self.assertEqual(self.draft.proposal.candidate.interval.start.hour, 19)
        self.assertFalse(self.draft.published)

    def test_preferred_change_requires_explicit_authorized_range(self):
        preferred = item(mode="preferred")
        alternate, _ = candidate(preferred, 19)
        self.assertEqual(propose_draft(preferred, self.review, alternate).initial_state, DraftState.READY)
        unspecified = item(mode="preferred", explicit_window=False)
        alternate, _ = candidate(unspecified, 19)
        proposal = propose_draft(unspecified, self.review, alternate)
        self.assertEqual(proposal.required_confirmations, ("TIME_CHANGE", "TIME_RANGE_UNSPECIFIED"))

    def test_missing_and_blocked_review_prevent_proposals(self):
        for material_id, expected_code in (("M02", "METADATA_MISSING"), ("M03", "REVIEW_BLOCKED")):
            request_item = item(material_id)
            review = evaluate_review(self.data.material(material_id), self.data.rule_set, "douyin")
            selected, _ = candidate(request_item)
            with self.assertRaises(DomainError) as caught:
                propose_draft(request_item, review, selected)
            self.assertEqual(caught.exception.code, expected_code)

    def test_review_for_another_material_cannot_authorize_proposal(self):
        with self.assertRaises(DomainError):
            propose_draft(item("M02"), self.review, self.alternative)

    def test_outside_window_and_wrong_channel_rejected(self):
        outside = Candidate("O21", 1, "douyin", TimeInterval(parse_time("2030-06-01T21:00+08:00"), parse_time("2030-06-01T21:30+08:00")))
        with self.assertRaises(DomainError) as caught:
            propose_draft(self.item, self.review, outside)
        self.assertEqual(caught.exception.code, "OUTSIDE_WINDOW")
        with self.assertRaises(DomainError):
            propose_draft(self.item, self.review, replace(self.alternative, channel="bilibili"))

    def test_confirmation_requirements_cannot_be_forged_in_constructors(self):
        with self.assertRaises(DomainError):
            DraftProposal(self.item, self.review, self.alternative, ())
        with self.assertRaises(DomainError):
            Draft("D01", "REQ01", 1, self.proposal, DraftState.READY)

    def test_confirm_current_version_rechecks_facts_and_keeps_draft_only(self):
        confirmed = confirm_draft(self.draft, self.command(), self.review, self.offer, ())
        self.assertEqual(confirmed.draft_id, self.draft.draft_id)
        self.assertEqual(confirmed.version, 2)
        self.assertEqual(confirmed.state, DraftState.READY)
        self.assertEqual(confirmed.pending_confirmations, ())
        self.assertFalse(confirmed.published)
        self.assertEqual(self.draft.state, DraftState.PENDING_CONFIRMATION)

    def test_old_version_and_incomplete_or_extra_acceptance_rejected(self):
        with self.assertRaises(DomainError) as caught:
            confirm_draft(self.draft, replace(self.command(), expected_version=2), self.review, self.offer, ())
        self.assertEqual(caught.exception.code, "DRAFT_VERSION_CONFLICT")
        for accepted in ((), ("TIME_CHANGE", "NOT_A_CURRENT_RISK")):
            with self.assertRaises(DomainError) as caught:
                confirm_draft(self.draft, self.command(accepted=accepted), self.review, self.offer, ())
            self.assertEqual(caught.exception.code, "CONFIRMATION_INCOMPLETE")

    def test_changed_copy_rules_or_offer_revision_invalidate_old_confirmation(self):
        changed_copy = evaluate_review(replace(self.data.material("M01"), copy_text="文案已经更新"), self.data.rule_set, "douyin")
        raw_rules = self.data.rule_set.to_dict()
        raw_rules["version"] = "1.1"
        changed_rules = evaluate_review(self.data.material("M01"), RuleSet.from_dict(raw_rules), "douyin")
        for review, offer in ((changed_copy, self.offer), (changed_rules, self.offer), (self.review, replace(self.offer, revision=2))):
            with self.assertRaises(DomainError) as caught:
                confirm_draft(self.draft, self.command(), review, offer, ())
            self.assertEqual(caught.exception.code, "STALE_DRAFT")

    def test_new_occupancy_prevents_confirmation(self):
        with self.assertRaises(DomainError) as caught:
            confirm_draft(self.draft, self.command(), self.review, self.offer, (booking(19),))
        self.assertEqual(caught.exception.code, "SLOT_CONFLICT")
        self.assertEqual(self.draft.version, 1)

    def test_risk_acceptance_is_recorded_without_erasing_review_risk(self):
        request_item = item("M04")
        review = evaluate_review(self.data.material("M04"), self.data.rule_set, "douyin")
        selected, offer = candidate(request_item)
        draft = create_draft("D04", "REQ04", propose_draft(request_item, review, selected))
        self.assertEqual(draft.pending_confirmations, ("RISK:R-MEDICAL-001",))
        confirmed = confirm_draft(draft, self.command(draft), review, offer, ())
        self.assertEqual(confirmed.state, DraftState.READY)
        self.assertEqual(confirmed.proposal.review.status, ReviewStatus.NEEDS_REVIEW)
        self.assertTrue(confirmed.proposal.review.findings)

    def test_same_proposal_reuse_does_not_revoke_valid_confirmation(self):
        confirmed = confirm_draft(self.draft, self.command(), self.review, self.offer, ())
        same_proposal = propose_draft(self.item, self.review, self.alternative)
        self.assertIs(replan_draft(confirmed, same_proposal), confirmed)
        self.assertEqual(confirmed.version, 2)

    def test_stale_replan_keeps_identity_and_drops_old_approval(self):
        confirmed = confirm_draft(self.draft, self.command(), self.review, self.offer, ())
        stale = invalidate_draft(confirmed)
        self.assertEqual(stale.state, DraftState.STALE)
        self.assertIs(invalidate_draft(stale), stale)
        replanned = replan_draft(stale, self.proposal)
        self.assertEqual(replanned.draft_id, confirmed.draft_id)
        self.assertEqual(replanned.version, 4)
        self.assertIsNone(replanned.confirmation)
        self.assertEqual(replanned.state, DraftState.PENDING_CONFIRMATION)

    def test_replan_cannot_replace_original_request(self):
        changed = replace(self.item, item_id="DIFFERENT")
        proposed = propose_draft(changed, self.review, self.alternative)
        with self.assertRaises(DomainError):
            replan_draft(self.draft, proposed)

    def test_replan_cannot_change_default_day_through_equivalent_utc_time(self):
        original = item(explicit_window=False)
        selected, _ = candidate(original, 19)
        draft = create_draft("D03", "REQ03", propose_draft(original, self.review, selected))
        changed = replace(
            original, time_requirement=replace(
                original.time_requirement, requested_start=parse_time("2030-06-01T10:00Z")
            ),
        )
        changed_proposal = propose_draft(changed, self.review, selected)
        with self.assertRaises(DomainError):
            replan_draft(draft, changed_proposal)

    def test_confirmation_input_is_strict_and_not_a_model_permission_field(self):
        raw = {
            "confirmation_id": "C01", "draft_id": "D01", "expected_version": 1,
            "accepted_item_ids": ["TIME_CHANGE"], "actor": "本地运营",
        }
        self.assertEqual(ConfirmationCommand.from_dict(raw).actor, "本地运营")
        raw["approved"] = True
        with self.assertRaises(DomainError):
            ConfirmationCommand.from_dict(raw)
