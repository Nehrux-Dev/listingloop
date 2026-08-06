"""Seed the content calendar.

DATES ARE DATA, NOT A FORMULA
-----------------------------
Christmas and Canada Day are fixed. Diwali, Eid al-Fitr, Eid al-Adha, Lunar New
Year, Easter and Hanukkah are not: they follow lunar or lunisolar calendars, and
Eid depends on local moon sighting, so two countries can legitimately observe it
on different days.

Computing them from a rule would mean shipping an approximation and being
quietly wrong about somebody's religious holiday. Every occurrence below is an
explicit, checked date, and the moving ones are flagged ``needs_date_review`` so
it is visible when the seeded years run out — rather than the calendar simply
going quiet and nobody noticing.

*** THE MOVING DATES BELOW ARE BEST-EFFORT AND SHOULD BE CONFIRMED AGAINST AN
    AUTHORITATIVE SOURCE FOR YOUR MARKET BEFORE LAUNCH. ***

Re-runnable: matched on (slug, date), so adding a year does not disturb what is
already there.
"""

from __future__ import annotations

from datetime import date

from django.core.management.base import BaseCommand
from django.db import transaction

from apps.templates.models import CalendarEvent, TemplateCategory

# (slug, name, category, needs_date_review, regions, description)
EVENT_TYPES = [
    (
        "christmas", "Christmas", TemplateCategory.CHRISTMAS, False, [],
        "Fixed date. Widely observed.",
    ),
    (
        "new-year", "New Year's Day", TemplateCategory.NEW_YEAR, False, [],
        "Fixed date.",
    ),
    (
        "lunar-new-year", "Lunar New Year", TemplateCategory.LUNAR_NEW_YEAR, True, [],
        "Lunisolar. Date changes each year — confirm before relying on it.",
    ),
    (
        "diwali", "Diwali", TemplateCategory.DIWALI, True, [],
        "Lunisolar (Hindu calendar). Date changes each year — confirm.",
    ),
    (
        "eid-al-fitr", "Eid al-Fitr", TemplateCategory.EID, True, [],
        "Islamic lunar calendar, subject to local moon sighting. Confirm locally.",
    ),
    (
        "eid-al-adha", "Eid al-Adha", TemplateCategory.EID, True, [],
        "Islamic lunar calendar, subject to local moon sighting. Confirm locally.",
    ),
    (
        "easter-sunday", "Easter Sunday", TemplateCategory.EASTER, True, [],
        "Moves with the ecclesiastical lunar calendar.",
    ),
    (
        "hanukkah", "Hanukkah (first night)", TemplateCategory.HANUKKAH, True, [],
        "Hebrew calendar. Date changes each year — confirm.",
    ),
    (
        "canada-day", "Canada Day", TemplateCategory.CANADA_DAY, False, ["CA"],
        "Fixed date.",
    ),
    (
        "australia-day", "Australia Day", TemplateCategory.AUSTRALIA_DAY, False, ["AU"],
        "Fixed date. Note this day is contested; consider whether to post at all.",
    ),
    (
        "thanksgiving-ca", "Thanksgiving (Canada)", TemplateCategory.THANKSGIVING, True, ["CA"],
        "Second Monday in October.",
    ),
    (
        "thanksgiving-us", "Thanksgiving (US)", TemplateCategory.THANKSGIVING, True, ["US"],
        "Fourth Thursday in November.",
    ),
    (
        "mothers-day", "Mother's Day", TemplateCategory.MOTHERS_DAY, True, [],
        "Date varies by country. These are US/CA/AU dates.",
    ),
    (
        "fathers-day", "Father's Day", TemplateCategory.FATHERS_DAY, True, [],
        "Date varies by country. These are US/CA dates.",
    ),
]

#: slug -> {year: date}. Filled by hand, deliberately.
OCCURRENCES: dict[str, dict[int, date]] = {
    "christmas": {2026: date(2026, 12, 25), 2027: date(2027, 12, 25), 2028: date(2028, 12, 25)},
    "new-year": {2027: date(2027, 1, 1), 2028: date(2028, 1, 1), 2029: date(2029, 1, 1)},
    "lunar-new-year": {2027: date(2027, 2, 6), 2028: date(2028, 1, 26)},
    "diwali": {2026: date(2026, 11, 8), 2027: date(2027, 10, 29)},
    "eid-al-fitr": {2027: date(2027, 2, 8), 2028: date(2028, 1, 28)},
    "eid-al-adha": {2026: date(2026, 5, 27), 2027: date(2027, 5, 16)},
    "easter-sunday": {2027: date(2027, 3, 28), 2028: date(2028, 4, 16)},
    "hanukkah": {2026: date(2026, 12, 4), 2027: date(2027, 12, 24)},
    "canada-day": {2027: date(2027, 7, 1), 2028: date(2028, 7, 1)},
    "australia-day": {2027: date(2027, 1, 26), 2028: date(2028, 1, 26)},
    "thanksgiving-ca": {2026: date(2026, 10, 12), 2027: date(2027, 10, 11)},
    "thanksgiving-us": {2026: date(2026, 11, 26), 2027: date(2027, 11, 25)},
    "mothers-day": {2027: date(2027, 5, 9), 2028: date(2028, 5, 14)},
    "fathers-day": {2027: date(2027, 6, 20), 2028: date(2028, 6, 18)},
}


class Command(BaseCommand):
    help = "Seed content calendar events (festival dates)."

    @transaction.atomic
    def handle(self, *args, **options) -> None:
        created_count = updated_count = 0
        review_needed = 0

        for slug, name, category, needs_review, regions, description in EVENT_TYPES:
            for _year, occurrence in sorted(OCCURRENCES.get(slug, {}).items()):
                _, created = CalendarEvent.objects.update_or_create(
                    slug=slug,
                    date=occurrence,
                    defaults={
                        "name": name,
                        "category": category,
                        "description": description,
                        "regions": regions,
                        "needs_date_review": needs_review,
                        "is_active": True,
                    },
                )
                created_count += int(created)
                updated_count += int(not created)
                review_needed += int(needs_review)

        total = CalendarEvent.objects.count()
        latest = CalendarEvent.objects.order_by("-date").first()

        self.stdout.write(
            self.style.SUCCESS(
                f"{created_count} created, {updated_count} updated. {total} events total."
            )
        )
        if latest:
            self.stdout.write(f"Calendar runs to {latest.date}.")
        self.stdout.write(
            self.style.WARNING(
                f"{review_needed} occurrence(s) are on lunar or lunisolar calendars. "
                f"Those dates are best-effort and must be confirmed against an "
                f"authoritative source for your market — this command does not "
                f"compute them, on purpose."
            )
        )
