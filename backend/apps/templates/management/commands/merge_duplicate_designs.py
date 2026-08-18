"""Fold pre-existing duplicate designs back into one per template.

WHY THIS EXISTS
---------------
Opening a template used to POST a new design every time, so an agent who came
back to the same template on three days ended up with three near-identical rows
in their designs panel and no way to tell which one held their edits. That is
fixed at the source — ``DesignSerializer.create`` now resumes an existing design
instead of adding another — but the fix only stops new duplicates. The ones
already in the database stay exactly where they are, which is what an agent is
looking at when they say the problem is not fixed.

This command cleans those up.

WHAT COUNTS AS A DUPLICATE
--------------------------
The same grouping the create rule uses: ``(agent, template, calendar_event)``.
Two designs an agent made from one template are duplicates; the same template
opened by two agents is not, and one seasonal template used for Diwali in two
different years is not either.

WHICH ONE SURVIVES
------------------
The most recently edited, because that is the one carrying the work — with one
exception. A design that has been exported has left the building: somebody has
a PNG of it, it may be linked from a listing, and deleting it takes its export
rows with it. So exported designs are never deleted, and a group containing more
than one of them is reported and skipped rather than guessed at.

SAFETY
------
Dry run by default. Nothing is deleted until ``--apply`` is passed, and the dry
run prints exactly what ``--apply`` would do.
"""

from __future__ import annotations

from collections import defaultdict

from django.core.management.base import BaseCommand
from django.db import transaction

from apps.templates.models import Design


class Command(BaseCommand):
    help = "Merge duplicate designs so each template keeps one design per agent."

    def add_arguments(self, parser) -> None:
        parser.add_argument(
            "--apply",
            action="store_true",
            help="Actually delete. Without this the command only reports.",
        )
        parser.add_argument(
            "--agent",
            default=None,
            help="Limit to one agent, by their login email.",
        )
        parser.add_argument(
            "--exclude",
            nargs="*",
            type=int,
            default=[],
            metavar="ID",
            help=(
                "Design ids to spare. For deliberate work that happens to sit "
                "in a duplicate group — a variation made on purpose reads "
                "exactly like an accidental copy from here."
            ),
        )

    def handle(self, *args, **options) -> None:
        apply_changes: bool = options["apply"]
        email: str | None = options["agent"]
        excluded: set[int] = set(options["exclude"])

        designs = Design.objects.select_related("template", "agent__user")
        if email:
            designs = designs.filter(agent__user__email__iexact=email)
        if excluded:
            # Excluded outright rather than merely spared from deletion: a
            # design nobody may touch should not be able to win the "keep the
            # newest" contest either, or it would take a real duplicate's
            # place and leave the group unmerged.
            designs = designs.exclude(pk__in=excluded)

        groups: dict[tuple, list[Design]] = defaultdict(list)
        for design in designs.prefetch_related("exports"):
            groups[(design.agent_id, design.template_id, design.calendar_event_id)].append(
                design
            )

        doomed: list[Design] = []
        skipped = 0

        for members in groups.values():
            if len(members) < 2:
                continue

            exported = [d for d in members if d.exports.exists()]
            if len(exported) > 1:
                # Two designs that have both been rendered are two real pieces
                # of work as far as anyone downstream is concerned. Picking one
                # is not this command's call to make.
                skipped += 1
                self.stdout.write(
                    self.style.WARNING(
                        f"  skipped: {members[0].template.name} for "
                        f"{self._who(members[0])} — "
                        f"{len(exported)} of {len(members)} have exports"
                    )
                )
                continue

            keeper = exported[0] if exported else max(
                members, key=lambda d: d.updated_at
            )
            losers = [d for d in members if d.pk != keeper.pk]
            doomed.extend(losers)

            self.stdout.write(
                f"  {members[0].template.name} for {self._who(keeper)}: "
                f"keeping #{keeper.pk} ({keeper.name}, edited "
                f"{keeper.updated_at:%Y-%m-%d %H:%M})"
                + (" [exported]" if exported else "")
            )
            for loser in losers:
                self.stdout.write(
                    f"    - removing #{loser.pk} ({loser.name}, edited "
                    f"{loser.updated_at:%Y-%m-%d %H:%M})"
                )

        if not doomed:
            self.stdout.write(self.style.SUCCESS("Nothing to merge."))
            return

        if not apply_changes:
            self.stdout.write(
                self.style.WARNING(
                    f"\nDry run. {len(doomed)} design(s) would be deleted, "
                    f"{len(groups)} group(s) examined"
                    + (f", {skipped} skipped." if skipped else ".")
                )
            )
            self.stdout.write("Re-run with --apply to make these changes.")
            return

        with transaction.atomic():
            count, _ = Design.objects.filter(
                pk__in=[d.pk for d in doomed]
            ).delete()

        self.stdout.write(
            self.style.SUCCESS(f"\nDeleted {len(doomed)} duplicate design(s).")
        )
        if skipped:
            self.stdout.write(
                self.style.WARNING(f"{skipped} group(s) skipped — see above.")
            )

    @staticmethod
    def _who(design: Design) -> str:
        user = getattr(design.agent, "user", None)
        return getattr(user, "email", None) or f"agent #{design.agent_id}"
