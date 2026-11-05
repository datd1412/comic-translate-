from __future__ import annotations

from urllib.parse import urlparse
from fastapi import HTTPException, status

from config import settings


def validate_callback_uri(
    uri: str | None,
    allowed_extension_ids: set[str] | None = None,
    allow_localhost: bool | None = None,
) -> str | None:
    """
    Kiểm tra nghiêm ngặt `desktop_callback_uri` / `redirect_uri`:
    - Nếu `uri` là None: trả về None (đăng nhập trực tiếp trên web, không redirect về app/extension).
    - Nếu `uri` được truyền vào nhưng là chuỗi rỗng hoặc bất hợp lệ: ném HTTPException 400.
    - Sử dụng `urllib.parse.urlparse` và so khớp CHÍNH XÁC `scheme` + `hostname` (không bao giờ dùng `startswith`).
    - Chỉ chấp nhận:
      1) `http://127.0.0.1:<port>/...` hoặc `http://localhost:<port>/...` (khi `allow_localhost=True` và `<port>` hợp lệ 1..65535).
      2) `https://<EXTENSION_ID>.chromiumapp.org/...` với `<EXTENSION_ID>` nằm trong danh sách `allowed_extension_ids`.
    - Chặn tuyệt đối userinfo (`127.0.0.1@evil.com`), subdomain giả mạo (`127.0.0.1.evil.com`, `abc.chromiumapp.org.evil.com`),
      `javascript:`, `data:`, hoặc chuỗi rỗng `""`.
    """
    if uri is None:
        return None

    if not isinstance(uri, str):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Callback URI không hợp lệ.",
        )

    cleaned = uri.strip()
    if not cleaned or cleaned.lower() in {"none", "null", "undefined"}:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Callback URI không được để trống.",
        )

    try:
        parsed = urlparse(cleaned)
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Không thể phân tích Callback URI.",
        ) from exc

    # Chặn URL chứa thông tin đăng nhập (ví dụ: http://127.0.0.1@evil.com)
    if parsed.username is not None or parsed.password is not None or "@" in (parsed.netloc or ""):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Callback URI không được chứa thông tin userinfo (@).",
        )

    scheme = (parsed.scheme or "").lower()

    # Trường hợp 1: Mobile Deep Link callback (Expo Go 'exp' hoặc Mobile App 'comictranslate')
    if scheme in {"exp", "comictranslate"}:
        return cleaned

    hostname = (parsed.hostname or "").lower()

    if not scheme or not hostname:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Callback URI thiếu scheme hoặc hostname.",
        )

    use_allow_localhost = (
        settings.ALLOW_LOCALHOST_CALLBACK if allow_localhost is None else allow_localhost
    )
    ext_ids = (
        settings.allowed_extension_ids_set
        if allowed_extension_ids is None
        else {x.strip().lower() for x in allowed_extension_ids if x.strip()}
    )

    # Trường hợp 1: Localhost loopback cho phép HTTP với cổng hợp lệ
    if scheme == "http" and use_allow_localhost:
        if hostname in {"127.0.0.1", "localhost"}:
            try:
                port = parsed.port
            except ValueError as exc:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="Cổng (port) của localhost callback không hợp lệ.",
                ) from exc
            if port is None or not (1 <= int(port) <= 65535):
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="Localhost callback bắt buộc phải chỉ định port hợp lệ (1-65535).",
                )
            return cleaned

    # Trường hợp 2: Chrome Extension callback qua https://<EXTENSION_ID>.chromiumapp.org
    if scheme == "https":
        try:
            port = parsed.port
        except ValueError as exc:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Cổng (port) trong Callback URI không hợp lệ.",
            ) from exc
        if port is not None and port != 443:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Chromiumapp callback không cho phép port tùy chỉnh.",
            )
        if "*" in ext_ids:
            return cleaned
        allowed_hosts = {f"{ext_id}.chromiumapp.org" for ext_id in ext_ids if ext_id}
        if hostname in allowed_hosts:
            return cleaned

    raise HTTPException(
        status_code=status.HTTP_400_BAD_REQUEST,
        detail=f"Callback URI không nằm trong danh sách cho phép: {hostname}",
    )
