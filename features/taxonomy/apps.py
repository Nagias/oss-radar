from django.apps import AppConfig


class TaxonomyConfig(AppConfig):
    name = "features.taxonomy"
    label = "taxonomy"
    verbose_name = "Phân loại repo"

    def ready(self) -> None:
        # Chỉ đăng ký bước kiểm `manage.py check`; không chạy việc nền nào ở đây.
        from features.taxonomy import checks  # noqa: F401
