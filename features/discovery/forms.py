from django import forms

QUERY_MAX_LENGTH = 256  # Giới hạn độ dài truy vấn của GitHub Search.


class ScanForm(forms.Form):
    """Kiểm tra truy vấn trước khi tốn một lần gọi GitHub. Dùng chung cho trang web và dòng lệnh."""

    query = forms.CharField(
        label="Truy vấn GitHub",
        max_length=QUERY_MAX_LENGTH,
        strip=True,
        help_text="Cú pháp tìm kiếm của GitHub, ví dụ: topic:ai-agent stars:>100 language:python",
        error_messages={
            "required": "Hãy nhập truy vấn tìm kiếm GitHub.",
            "max_length": "Truy vấn dài tối đa %(limit_value)d ký tự (giới hạn của GitHub).",
        },
        widget=forms.TextInput(
            attrs={"placeholder": "topic:ai-agent stars:>100", "autofocus": True}
        ),
    )
