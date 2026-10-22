from django.db import migrations

# Danh sách theo dõi gợi ý (thiết kế F-005 mục 2): (nhãn mảng, truy vấn), đúng thứ tự. Không có
# `topic:llm` (quá rộng) — chủ dự án tự thêm ở trang Theo dõi nếu muốn.
SUGGESTED = [
    ("AI Agent", "topic:ai-agent"),
    ("AI Agent", "topic:ai-agents"),
    ("AI Agent", "topic:agentic-ai"),
    ("AI Agent", "topic:mcp-server"),
    ("Vibe code", "topic:vibe-coding"),
    ("Vibe code", "topic:claude-code"),
    ("Video AI", "topic:ai-video"),
    ("Video AI", "topic:text-to-video"),
    ("Video AI", "topic:video-generation"),
    ("Ảnh AI", "topic:comfyui"),
    ("Ảnh AI", "topic:image-generation"),
    ("Marketing", "topic:marketing-automation"),
    ("Marketing", "topic:ai-marketing"),
    ("Marketing", "topic:seo"),
    ("Doanh nghiệp một người", "topic:solopreneur"),
    ("Doanh nghiệp một người", "topic:indie-hacker"),
]


def seed_watch_queries(apps, schema_editor):
    """Tạo sẵn 16 truy vấn gợi ý: mức Sâu 300, từ 10 star, đang bật.

    Dùng model lịch sử (apps.get_model) chứ không import code ứng dụng, để migration không vỡ khi
    model sau này đổi. Truy vấn đã có thì bỏ qua: chạy lại (lùi rồi tiến migration) không tạo trùng.
    """
    WatchQuery = apps.get_model("rising", "WatchQuery")
    for position, (label, query) in enumerate(SUGGESTED, start=1):
        if WatchQuery.objects.filter(query=query).exists():
            continue
        WatchQuery.objects.create(
            label=label,
            query=query,
            min_stars=10,
            max_stars=None,
            budget=300,
            enabled=True,
            position=position,
        )


class Migration(migrations.Migration):

    dependencies = [
        ('rising', '0001_initial'),
    ]

    operations = [
        # Lùi migration không xoá gì: dòng có thể đã được chủ dự án sửa trên trang Theo dõi.
        migrations.RunPython(seed_watch_queries, migrations.RunPython.noop),
    ]
