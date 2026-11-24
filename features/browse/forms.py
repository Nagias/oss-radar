"""Form lọc của trang Khám phá (GET). Ô sai thì bỏ qua ô đó (vẫn báo lỗi), trang không hỏng."""

from typing import Any

from django import forms
from django.http import QueryDict

from features.browse.filters import (
    DEFAULT_TAB,
    SORT_LABELS,
    TABS,
    BrowseFilters,
    canonical_query,
)
from features.browse.models import SavedView
from features.taxonomy.services import load_taxonomy


def _choices(axis: str) -> list[tuple[str, str]]:
    taxonomy = load_taxonomy()
    categories = taxonomy.audience if axis == "audience" else taxonomy.aspects
    return [(category.code, category.name) for category in categories]


class BrowseForm(forms.Form):
    tab = forms.ChoiceField(
        label="Tab danh sách", required=False, choices=list(TABS.items()), widget=forms.HiddenInput
    )
    audience = forms.MultipleChoiceField(label="Dành cho ai", required=False, choices=())
    aspects = forms.MultipleChoiceField(label="Làm được gì", required=False, choices=())
    q = forms.CharField(label="Từ khoá", required=False, max_length=100)
    language = forms.CharField(label="Ngôn ngữ", required=False, max_length=100)
    # Giới hạn trên: số quá lớn làm tràn ngày tháng / số nguyên của SQLite (lỗi 500).
    min_stars = forms.IntegerField(
        label="Star tối thiểu", required=False, min_value=0, max_value=10**9
    )
    max_stars = forms.IntegerField(
        label="Star tối đa", required=False, min_value=0, max_value=10**9
    )
    created_days = forms.IntegerField(
        label="Tạo trong (ngày)", required=False, min_value=1, max_value=36500
    )
    commercial = forms.BooleanField(label="Giấy phép cho phép dùng thương mại", required=False)
    unclassified = forms.BooleanField(label="Chỉ repo chưa phân loại", required=False)
    show_suspicious = forms.BooleanField(label="Hiện cả repo nghi star giả", required=False)
    scan = forms.IntegerField(
        label="Lần quét", required=False, min_value=1, max_value=10**9, widget=forms.HiddenInput
    )
    sort = forms.ChoiceField(label="Sắp theo", required=False, choices=list(SORT_LABELS.items()))
    page = forms.IntegerField(
        label="Trang", required=False, min_value=1, max_value=10**6, widget=forms.HiddenInput
    )
    view = forms.IntegerField(
        label="Góc nhìn", required=False, min_value=1, max_value=10**9, widget=forms.HiddenInput
    )

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        # Đọc bộ nhóm lúc tạo form, không lúc import (bộ nhóm được nạp một lần mỗi lần mở app:
        # sửa categories.toml thì khởi động lại app).
        self.fields["audience"].choices = _choices("audience")  # type: ignore[attr-defined]
        self.fields["aspects"].choices = _choices("aspects")  # type: ignore[attr-defined]

    def filters(self) -> BrowseFilters:
        """Bộ lọc từ các ô hợp lệ; ô sai hoặc để trống thì không lọc theo ô đó."""
        if not self.is_bound:
            return BrowseFilters()
        self.is_valid()
        data = self.cleaned_data
        return BrowseFilters(
            tab=data.get("tab") or DEFAULT_TAB,
            audience=tuple(data.get("audience") or ()),
            aspects=tuple(data.get("aspects") or ()),
            q=(data.get("q") or "").strip(),
            language=(data.get("language") or "").strip(),
            min_stars=data.get("min_stars"),
            max_stars=data.get("max_stars"),
            created_days=data.get("created_days"),
            commercial=bool(data.get("commercial")),
            unclassified=bool(data.get("unclassified")),
            show_suspicious=bool(data.get("show_suspicious")),
            scan=data.get("scan"),
            sort=data.get("sort") or "",
            page=data.get("page") or 1,
            view=data.get("view"),
        )


# Giới hạn số góc nhìn: thanh bên còn đọc được, và một người dùng thật hiếm khi cần hơn.
MAX_SAVED_VIEWS = 50
MAX_QUERY_LENGTH = 1000
_BAD_QUERY = "Bộ lọc không hợp lệ ({fields}) — mở lại trang Khám phá, chọn lại bộ lọc rồi lưu."


class SavedViewForm(forms.Form):
    """Lưu / đổi tên / cập nhật góc nhìn. `query` được kiểm bằng `BrowseForm` rồi chuẩn hoá."""

    name = forms.CharField(
        label="Tên góc nhìn",
        max_length=60,
        error_messages={
            "required": "Hãy đặt tên cho góc nhìn.",
            "max_length": "Tên góc nhìn tối đa %(limit_value)d ký tự.",
        },
    )
    query = forms.CharField(label="Bộ lọc", required=False, strip=False)

    def __init__(
        self,
        *args: Any,
        instance: SavedView | None = None,
        rename_only: bool = False,
        **kwargs: Any,
    ) -> None:
        """`rename_only`: chỉ đổi tên — giữ nguyên bộ lọc đã lưu, không kiểm lại.

        Bộ nhóm có thể đổi sau khi lưu (sửa categories.toml): mã cũ thành lạ, nhưng vẫn phải đổi tên
        được; mở góc đó thì trang bỏ mã lạ và gợi ý "Cập nhật".
        """
        super().__init__(*args, **kwargs)
        self.instance = instance
        self.rename_only = rename_only

    def clean_name(self) -> str:
        name: str = self.cleaned_data["name"]
        others = SavedView.objects.all()
        if self.instance is not None:
            others = others.exclude(pk=self.instance.pk)
        # So trong Python: `casefold` hiểu chữ có dấu (SQLite `lower()` chỉ hiểu chữ ASCII).
        if any(
            other.casefold() == name.casefold() for other in others.values_list("name", flat=True)
        ):
            raise forms.ValidationError(f"Đã có góc nhìn tên «{name}» — chọn tên khác.")
        return name

    def clean_query(self) -> str:
        raw: str = self.cleaned_data.get("query") or ""
        if self.rename_only and self.instance is not None:
            return self.instance.query
        if len(raw) > MAX_QUERY_LENGTH:
            raise forms.ValidationError(_BAD_QUERY.format(fields="dài quá 1.000 ký tự"))
        browse = BrowseForm(QueryDict(raw))
        if not browse.is_valid():
            fields = ", ".join(str(browse.fields[name].label or name) for name in browse.errors)
            raise forms.ValidationError(_BAD_QUERY.format(fields=fields))
        canonical = canonical_query(browse.filters())
        if len(canonical) > MAX_QUERY_LENGTH:
            raise forms.ValidationError(_BAD_QUERY.format(fields="dài quá 1.000 ký tự"))
        return canonical

    def clean(self) -> dict[str, Any]:
        data = super().clean() or {}
        if self.instance is None and SavedView.objects.count() >= MAX_SAVED_VIEWS:
            raise forms.ValidationError(
                f"Chỉ lưu được tối đa {MAX_SAVED_VIEWS} góc nhìn — xoá bớt ở trang Góc nhìn đã lưu."
            )
        return data
