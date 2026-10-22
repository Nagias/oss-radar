from django.db import migrations
from django.utils import timezone

BATCH_SIZE = 500


def seed_snapshots(apps, schema_editor):
    """Mỗi repo đang có trong kho được tạo sẵn một ảnh chụp từ số star và ngày thấy gần nhất.

    Nhờ vậy ngay lượt quét hằng ngày đầu tiên đã có mốc để so. Dùng model lịch sử (apps.get_model)
    chứ không import code ứng dụng, để migration không vỡ khi model sau này đổi.
    """
    Repository = apps.get_model("catalog", "Repository")
    StarSnapshot = apps.get_model("catalog", "StarSnapshot")

    rows = Repository.objects.values_list("id", "stars", "last_seen_at").iterator(chunk_size=BATCH_SIZE)
    batch = []
    for repository_id, stars, last_seen_at in rows:
        batch.append(
            StarSnapshot(
                repository_id=repository_id,
                day=timezone.localdate(last_seen_at),
                stars=stars,
                captured_at=last_seen_at,
            )
        )
        if len(batch) >= BATCH_SIZE:
            _save(StarSnapshot, batch)
            batch = []
    _save(StarSnapshot, batch)


def _save(StarSnapshot, batch):
    # ignore_conflicts: chạy lại (lùi rồi tiến migration) không được vỡ vì ảnh chụp đã có.
    StarSnapshot.objects.bulk_create(batch, ignore_conflicts=True)


class Migration(migrations.Migration):

    dependencies = [
        ('catalog', '0002_starsnapshot'),
    ]

    operations = [
        migrations.RunPython(seed_snapshots, migrations.RunPython.noop),
    ]
