from django.db import migrations


def add_exclusion(apps, schema_editor):
    if schema_editor.connection.vendor == "postgresql":
        schema_editor.execute("CREATE EXTENSION IF NOT EXISTS btree_gist")
        # Half-open ranges allow adjacent appointments. Cancelled rows release time.
        schema_editor.execute("""
            ALTER TABLE booking_appointment
            ADD CONSTRAINT booking_no_overlap
            EXCLUDE USING gist (
                barber_id WITH =,
                tstzrange(starts_at, ends_at, '[)') WITH &&
            ) WHERE (cancelled_at IS NULL)
        """)


def remove_exclusion(apps, schema_editor):
    if schema_editor.connection.vendor == "postgresql":
        schema_editor.execute("ALTER TABLE booking_appointment DROP CONSTRAINT IF EXISTS booking_no_overlap")


class Migration(migrations.Migration):
    dependencies = [("booking", "0001_initial")]
    operations = [migrations.RunPython(add_exclusion, remove_exclusion)]
