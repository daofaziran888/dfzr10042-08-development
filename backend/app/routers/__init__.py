"""业务路由汇总：同期群运营圈选为专用路由，其余模块共用一套资源路由。

cohort_ops 必须排在 resource 之前，否则 /api/cohort_analysis/ops/*
会被通用 /api/{module}/{entry_id} 抢先匹配。
"""
from __future__ import annotations

from app.routers import cohort_ops, resource

ROUTERS = [cohort_ops, resource]
