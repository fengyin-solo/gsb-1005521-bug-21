"""运行配置：端口、跨域、运行环境。"""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

_BACKEND_DIR = Path(__file__).resolve().parent.parent


@dataclass(frozen=True)
class Settings:
    app_name: str = "光伏电站运维管理平台"
    env: str = "local"
    port: int = 8000
    # 措施状态等业务数据落库位置（JSON 文件库），可用环境变量覆盖；
    # 文件不存在时用示例种子数据初始化，重启后状态不丢。
    store_path: Path = field(
        default_factory=lambda: Path(os.environ.get("APP_STORE_PATH", _BACKEND_DIR / "data" / "store.json"))
    )
    allowed_origins: list[str] = field(
        default_factory=lambda: [
            "http://127.0.0.1:5173",
            "http://localhost:5173",
        ]
    )
    page_size_default: int = 20
    page_size_max: int = 200


settings = Settings()
