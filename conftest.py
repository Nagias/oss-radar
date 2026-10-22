"""Cấu hình pytest dùng chung cho toàn dự án."""

from collections.abc import Iterator

import pytest
import respx

from tests.fakes import FakeTime


@pytest.fixture
def fake_time() -> FakeTime:
    """Đồng hồ giả: truyền `fake_time.sleep`/`.monotonic`/`.time` vào code thay cho đồng hồ thật."""
    return FakeTime()


@pytest.fixture
def http_mock() -> Iterator[respx.MockRouter]:
    """Bộ giả lập HTTP của test hiện tại.

    Khai báo phản hồi giả cho dịch vụ ngoài, ví dụ:
        http_mock.get("https://api.github.com/search/repositories").respond(json=...)
    Request nào không khớp route đã khai báo sẽ làm test lỗi ngay, không lọt ra Internet.
    """
    with respx.mock(assert_all_called=False, assert_all_mocked=True) as router:
        yield router


@pytest.fixture(autouse=True)
def _block_real_http(request: pytest.FixtureRequest) -> None:
    """Mọi test đều chạy trong http_mock, trừ test đánh dấu @pytest.mark.live (gọi dịch vụ thật)."""
    if request.node.get_closest_marker("live") is None:
        request.getfixturevalue("http_mock")
