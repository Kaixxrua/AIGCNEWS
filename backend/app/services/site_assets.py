"""站点公开素材树（/api/media/site 匿名静态挂载）的内容寻址落盘。

仅存放可公开的站点图片：联系合作页二维码、正文插图、站长推荐网站的图标。
"""

from __future__ import annotations

import hashlib
import os
import tempfile

from backend.app.core.config import settings
from backend.app.services.chat.attachment_policy import image_extension


def store_site_image(data: bytes, mime_type: str) -> str:
    """内容寻址落盘到公开站点素材树，返回站内媒体 URL（同内容重传自然去重）。

    mime_type 必须是已校验过的栅格图片类型（jpeg/png/gif/webp）。
    """
    digest = hashlib.sha256(data).hexdigest()[:32]
    name = f"{digest}{image_extension(mime_type)}"
    target_dir = settings.site_assets_storage_dir
    os.makedirs(target_dir, exist_ok=True)
    target = os.path.join(target_dir, name)
    if not os.path.exists(target):
        # 同目录临时文件 + os.replace 保证原子发布，并发上传同内容也不会撕裂
        fd, tmp_path = tempfile.mkstemp(dir=target_dir, prefix=f".{digest}.", suffix=".tmp")
        try:
            with os.fdopen(fd, "wb") as fh:
                fh.write(data)
            os.replace(tmp_path, target)
        except BaseException:
            try:
                os.unlink(tmp_path)
            except OSError:
                pass
            raise
    return f"/api/media/site/{name}"
