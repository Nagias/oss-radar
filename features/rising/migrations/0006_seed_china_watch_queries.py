from django.db import migrations
from django.db.models import Max

# Truy vấn theo dõi tiếng Trung (thiết kế bộ luật 2026-11-28, Luật D): (nhãn mảng, truy vấn), đúng thứ
# tự. 16 truy vấn đầu đều là topic tiếng Anh nên chỉ ~10% kho có dấu hiệu Trung Quốc. Không viết
# `pushed:` vào truy vấn (ngày sẽ cũ dần) — độ mới do luật lọc kết quả kém lo.
CHINA = [
    ("Trung Quốc · AI Agent", "智能体"),
    ("Trung Quốc · AI Agent", "大模型"),
    ("Trung Quốc · AI Agent", "提示词"),
    ("Trung Quốc · AI Agent", "topic:deepseek"),
    ("Trung Quốc · AI Agent", "topic:qwen"),
    ("Trung Quốc · Video AI", "短视频"),
    ("Trung Quốc · Video AI", "数字人"),
    ("Trung Quốc · Marketing", "抖音"),
    ("Trung Quốc · Marketing", "小红书"),
    ("Trung Quốc · Công cụ làm việc", "飞书"),
]
MIN_STARS = 20  # truy vấn chữ rộng hơn truy vấn theo topic → ngưỡng cao hơn 10 của nhóm đầu
BUDGET = 50  # mức Vừa: đo 2026-11-28, truy vấn lớn nhất ~1.000 kết quả từ 50 star (~11 lượt gọi)


def seed_china_watch_queries(apps, schema_editor):
    """Thêm 10 truy vấn tiếng Trung vào cuối danh sách theo dõi.

    Truy vấn đã có thì giữ nguyên (chủ dự án có thể đã tự thêm, sửa hoặc tắt). Vị trí nối tiếp sau
    số lớn nhất đang có để không chen vào thứ tự chủ dự án đã sắp.
    """
    WatchQuery = apps.get_model("rising", "WatchQuery")
    position = WatchQuery.objects.aggregate(largest=Max("position"))["largest"] or 0
    for label, query in CHINA:
        if WatchQuery.objects.filter(query=query).exists():
            continue
        position += 1
        WatchQuery.objects.create(
            label=label,
            query=query,
            min_stars=MIN_STARS,
            max_stars=None,
            budget=BUDGET,
            enabled=True,
            position=position,
        )


class Migration(migrations.Migration):

    dependencies = [
        ('rising', '0005_trending'),
    ]

    operations = [
        # Lùi migration không xoá gì: dòng có thể đã được chủ dự án sửa trên trang Theo dõi.
        migrations.RunPython(seed_china_watch_queries, migrations.RunPython.noop),
    ]
