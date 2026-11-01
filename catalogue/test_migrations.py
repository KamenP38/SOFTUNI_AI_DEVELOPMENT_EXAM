"""Exercise the demo refresh against historical models in an isolated test DB."""

from decimal import Decimal

from django.db import connection
from django.db.migrations.executor import MigrationExecutor
from django.test import TransactionTestCase


# Frozen pre-refresh fixtures: deliberately independent of the migration's mapping.
ORIGINAL_SERVICES = [
    (
        "Signature haircut", "Класическо подстригване",
        "A considered cut, shaped to suit you. Finished with a wash and style.",
        "Прецизно подстригване, съобразено с вас, с измиване и оформяне.", 40, "25.00",
    ),
    (
        "Skin fade", "Скин фейд",
        "A seamless fade with clean edges and a carefully styled finish.",
        "Плавен преход, изчистени контури и внимателно оформен завършек.", 45, "28.00",
    ),
    (
        "Beard sculpting", "Оформяне на брада",
        "Shape, definition and a tidy finish, tailored to your beard.",
        "Форма, ясни контури и спретнат завършек, съобразени с вашата брада.", 25, "18.00",
    ),
    (
        "Haircut & beard", "Подстригване и брада",
        "The full refresh. A signature haircut paired with beard shaping.",
        "Цялостно освежаване: класическо подстригване и оформяне на брадата.", 60, "38.00",
    ),
    (
        "Traditional shave", "Класическо бръснене",
        "A close shave with a warm towel and a soothing finish.",
        "Гладко бръснене с топла кърпа и успокояваща финална грижа.", 30, "22.00",
    ),
    (
        "Scalp & hair treatment", "Грижа за косата и скалпа",
        "A little extra care: a cleansing wash, scalp massage and conditioning.",
        "Допълнителна грижа с измиване, масаж на скалпа и подхранване.", 20, "15.00",
    ),
]

EDITED_FIELDS = {
    "name": "Custom name",
    "name_bg": "Редактирано име",
    "description": "Shop-confirmed description",
    "description_bg": "Редактирано описание",
    "duration_minutes": 55,
    "price": Decimal("42.25"),
    "is_active": False,
    "display_order": 99,
}


class DemoRefreshMigrationTests(TransactionTestCase):
    before = [("catalogue", "0002_service_description_bg_service_name_bg")]
    after = [("catalogue", "0003_refresh_unchanged_demo_services")]

    def migrate(self, targets):
        executor = MigrationExecutor(connection)
        executor.migrate(targets)
        return executor.loader.project_state(targets).apps.get_model("catalogue", "Service")

    def setUp(self):
        super().setUp()
        self.Service = self.migrate(self.before)

    def tearDown(self):
        # Restore schema/state even after an assertion failure for subsequent tests.
        try:
            executor = MigrationExecutor(connection)
            executor.migrate(executor.loader.graph.leaf_nodes())
        finally:
            super().tearDown()

    def seed_originals(self):
        fields = ("name", "name_bg", "description", "description_bg", "duration_minutes", "price")
        return [
            self.Service.objects.create(**dict(zip(fields, row)), display_order=index, is_active=True)
            for index, row in enumerate(ORIGINAL_SERVICES, 1)
        ]

    def snapshot(self):
        return list(self.Service.objects.order_by("pk").values())

    def test_forward_refresh_updates_all_six_rows_in_place_and_reverse_restores_them(self):
        originals = self.seed_originals()
        before = self.snapshot()
        self.migrate(self.after)
        expected = [
            (originals[0].pk, "Classic Haircut", "Класическо подстригване", 30, Decimal("20.00")),
            (originals[2].pk, "Beard Trim & Shape", "Оформяне на брада", 30, Decimal("15.00")),
            (originals[1].pk, "Fade & Taper", "Фейд & Тейпър", 45, Decimal("25.00")),
            (originals[4].pk, "Hot Towel Shave", "Бръснене с гореща кърпа", 30, Decimal("25.00")),
            (originals[3].pk, "Cut & Beard Combo", "Подстригване + Брада", 60, Decimal("35.00")),
            (originals[5].pk, "Kids Cut", "Детско подстригване", 30, Decimal("15.00")),
        ]
        self.assertEqual(
            list(self.Service.objects.values_list("pk", "name", "name_bg", "duration_minutes", "price")),
            expected,
        )
        self.assertEqual(list(self.Service.objects.values_list("display_order", flat=True)), list(range(1, 7)))
        for old in before:
            updated = self.Service.objects.get(pk=old["id"])
            self.assertNotEqual(updated.description, old["description"])
            self.assertNotEqual(updated.description_bg, old["description_bg"])
            self.assertTrue(updated.is_active)
        self.migrate(self.before)
        self.assertEqual(self.snapshot(), before)

    def test_migration_does_not_seed_an_empty_database(self):
        self.migrate(self.after)
        self.assertFalse(self.Service.objects.exists())
        self.migrate(self.before)
        self.assertFalse(self.Service.objects.exists())

    def test_forward_preserves_every_kind_of_admin_edit(self):
        for field, value in EDITED_FIELDS.items():
            with self.subTest(field=field):
                self.migrate(self.before)
                self.Service.objects.all().delete()
                originals = self.seed_originals()
                self.Service.objects.filter(pk=originals[0].pk).update(**{field: value})
                edited = self.Service.objects.values().get(pk=originals[0].pk)
                self.migrate(self.after)
                self.assertEqual(self.Service.objects.values().get(pk=originals[0].pk), edited)
                self.assertEqual(self.Service.objects.count(), 6)
                self.assertTrue(self.Service.objects.filter(pk=originals[1].pk, name="Fade & Taper").exists())

    def test_reverse_preserves_every_kind_of_admin_edit(self):
        for field, value in EDITED_FIELDS.items():
            with self.subTest(field=field):
                self.migrate(self.before)
                self.Service.objects.all().delete()
                originals = self.seed_originals()
                self.migrate(self.after)
                self.Service.objects.filter(pk=originals[0].pk).update(**{field: value})
                edited = self.Service.objects.values().get(pk=originals[0].pk)
                self.migrate(self.before)
                self.assertEqual(self.Service.objects.values().get(pk=originals[0].pk), edited)
                self.assertEqual(self.Service.objects.count(), 6)
                self.assertTrue(self.Service.objects.filter(pk=originals[1].pk, name="Skin fade").exists())

    def test_forward_preserves_target_name_collision_and_unrelated_services(self):
        self.seed_originals()
        custom = self.Service.objects.create(name="Classic Haircut", duration_minutes=20, price="8.00")
        original = self.Service.objects.values().get(name="Signature haircut")
        custom_before = self.Service.objects.values().get(pk=custom.pk)
        self.migrate(self.after)
        self.assertEqual(self.Service.objects.values().get(pk=original["id"]), original)
        self.assertEqual(self.Service.objects.values().get(pk=custom.pk), custom_before)
        self.assertEqual(self.Service.objects.count(), 7)
        self.assertTrue(self.Service.objects.filter(name="Kids Cut").exists())

    def test_reverse_preserves_target_name_collision(self):
        originals = self.seed_originals()
        self.migrate(self.after)
        custom = self.Service.objects.create(name="Signature haircut", duration_minutes=20, price="8.00")
        refreshed = self.Service.objects.values().get(pk=originals[0].pk)
        custom_before = self.Service.objects.values().get(pk=custom.pk)
        self.migrate(self.before)
        self.assertEqual(self.Service.objects.values().get(pk=originals[0].pk), refreshed)
        self.assertEqual(self.Service.objects.values().get(pk=custom.pk), custom_before)
        self.assertEqual(self.Service.objects.count(), 7)
        self.assertTrue(self.Service.objects.filter(name="Scalp & hair treatment").exists())
