"""同期群未回访成员回查与运营圈选领域服务。

在留存率之外补齐缺席者运营链路：

1. 按观察日 + 渠道从实际入群成员回查未回访成员清单；
2. 运营领取未回访范围，领取边界 = 领取时刻采用的回访批次快照；
3. 只在该批未回访候选内按用户属性圈选并组装运营名单，每轮领取只生成一份；
4. 迟到回访补送并确认后回访批次推进，新领取的范围不再包含已确认回访成员；
5. 每份名单都记录实际采用的回访批次与渠道，可按批次回算来源。

数据为内存实现，确定性优先：逻辑时钟发时间、序号发编号、回访用户去重
（重复回访只算一人）。真实项目里这里会换成数据库访问层。
"""
from __future__ import annotations

import threading
from copy import deepcopy
from datetime import datetime, timedelta
from typing import Any

# 运营圈选条件只允许作用在这些用户属性上
ATTRIBUTE_FIELDS = ["平台", "年龄层", "价值等级"]

# 示例实际入群成员：COHO-0001 群组，2026-11-21 入群。
# A/C 第二日已回访；B/D 第二日未回访且来自活动渠道；B 第一日回访过；
# E 来自自然渠道，用于验证渠道过滤。
DEFAULT_MEMBERS: list[dict[str, Any]] = [
    {"用户ID": "A", "群组编号": "COHO-0001", "入群渠道": "活动渠道", "入群日": "2026-11-21",
     "平台": "ios", "年龄层": "18-25", "价值等级": "高"},
    {"用户ID": "B", "群组编号": "COHO-0001", "入群渠道": "活动渠道", "入群日": "2026-11-21",
     "平台": "android", "年龄层": "26-35", "价值等级": "中"},
    {"用户ID": "C", "群组编号": "COHO-0001", "入群渠道": "活动渠道", "入群日": "2026-11-21",
     "平台": "ios", "年龄层": "18-25", "价值等级": "高"},
    {"用户ID": "D", "群组编号": "COHO-0001", "入群渠道": "活动渠道", "入群日": "2026-11-21",
     "平台": "android", "年龄层": "36-45", "价值等级": "低"},
    {"用户ID": "E", "群组编号": "COHO-0001", "入群渠道": "自然渠道", "入群日": "2026-11-21",
     "平台": "ios", "年龄层": "26-35", "价值等级": "中"},
]

# 示例回访批次：每个批次是某观察日已确认回访用户的全量快照（去重）。
# 迟到回访确认后会生成序号更大的新批次，旧批次保留供名单回算。
DEFAULT_BATCHES: list[dict[str, Any]] = [
    {"回访批次": "RB-COHO0001-D1-001", "群组编号": "COHO-0001", "观察日": 1, "批次序号": 1,
     "已回访用户": ["A", "B", "C"], "已回访人数": 3, "状态": "已确认",
     "确认时间": "2026-11-22T08:00:00"},
    {"回访批次": "RB-COHO0001-D2-001", "群组编号": "COHO-0001", "观察日": 2, "批次序号": 1,
     "已回访用户": ["A", "C"], "已回访人数": 2, "状态": "已确认",
     "确认时间": "2026-11-23T08:00:00"},
]

_CLOCK_BASE = datetime(2026, 11, 23, 9, 0, 0)


def _matches(member: dict[str, Any], conditions: dict[str, str]) -> bool:
    """用户属性精确匹配：条件为空则全部通过。"""
    return all(str(member.get(field, "")) == expected for field, expected in conditions.items())


class CohortOpsService:
    """同期群缺席者回查与运营名单组装。"""

    def __init__(
        self,
        members: list[dict[str, Any]] | None = None,
        batches: list[dict[str, Any]] | None = None,
    ) -> None:
        self._lock = threading.Lock()
        self._members = deepcopy(members if members is not None else DEFAULT_MEMBERS)
        self._batches = deepcopy(batches if batches is not None else DEFAULT_BATCHES)
        self._pending: list[dict[str, Any]] = []  # 已补送、待确认的回访
        self._claims: list[dict[str, Any]] = []
        self._oplists: list[dict[str, Any]] = []
        self._claim_seq = 0
        self._oplist_seq = 0
        self._report_seq = 0
        self._clock_ticks = 0

    # ----------------------------------------------------------
    # 内部工具
    # ----------------------------------------------------------

    def _tick(self) -> str:
        """逻辑时钟：保证生成时间确定且单调。"""
        self._clock_ticks += 1
        return (_CLOCK_BASE + timedelta(minutes=self._clock_ticks)).isoformat()

    def _latest_batch(self, cohort_id: str, observation_day: int) -> dict[str, Any] | None:
        candidates = [
            batch for batch in self._batches
            if batch["群组编号"] == cohort_id and batch["观察日"] == observation_day
        ]
        if not candidates:
            return None
        return max(candidates, key=lambda batch: batch["批次序号"])

    def _cohort_members(self, cohort_id: str, channel: str | None = None) -> list[dict[str, Any]]:
        rows = [m for m in self._members if m["群组编号"] == cohort_id]
        if channel:
            rows = [m for m in rows if m["入群渠道"] == channel]
        return sorted(rows, key=lambda m: m["用户ID"])

    def _member_row(self, member: dict[str, Any], batch: dict[str, Any] | None) -> dict[str, Any]:
        returned = batch is not None and member["用户ID"] in batch["已回访用户"]
        return {
            "用户ID": member["用户ID"],
            "群组编号": member["群组编号"],
            "入群渠道": member["入群渠道"],
            "平台": member["平台"],
            "年龄层": member["年龄层"],
            "价值等级": member["价值等级"],
            "是否已回访": returned,
            "回访批次": batch["回访批次"] if batch else "",
        }

    # ----------------------------------------------------------
    # 按日 + 渠道回查
    # ----------------------------------------------------------

    def actual_members(
        self,
        cohort_id: str,
        observation_day: int,
        channel: str | None = None,
    ) -> dict[str, Any]:
        """按观察日和渠道查询实际入群成员，逐行标注回访状态与采用的回访批次。"""
        batch = self._latest_batch(cohort_id, observation_day)
        members = self._cohort_members(cohort_id, channel)
        rows = [self._member_row(member, batch) for member in members]
        returned = sum(1 for row in rows if row["是否已回访"])
        return {
            "群组编号": cohort_id,
            "观察日": observation_day,
            "渠道": channel or "全部",
            "回访批次": batch["回访批次"] if batch else "",
            "成员基数": len(rows),
            "已回访人数": returned,
            "未回访人数": len(rows) - returned,
            "成员行": rows,
        }

    def absent_members(
        self,
        cohort_id: str,
        observation_day: int,
        channel: str,
    ) -> dict[str, Any]:
        """未回访成员清单：实际成员同时按观察日与渠道检索，缺席者作为候选。

        已回访人数与每一行候选都标出采用的回访批次；某成员第一日回访过，
        只要第二日未回访仍会出现在第二日清单里。
        """
        batch = self._latest_batch(cohort_id, observation_day)
        members = self._cohort_members(cohort_id, channel)
        returned_users = set(batch["已回访用户"]) if batch else set()
        batch_id = batch["回访批次"] if batch else ""
        rows = []
        returned_in_scope = 0
        for member in members:
            if member["用户ID"] in returned_users:
                returned_in_scope += 1
                continue
            rows.append({
                "用户ID": member["用户ID"],
                "群组编号": member["群组编号"],
                "入群渠道": member["入群渠道"],
                "平台": member["平台"],
                "年龄层": member["年龄层"],
                "价值等级": member["价值等级"],
                "回访批次": batch_id,
            })
        return {
            "群组编号": cohort_id,
            "观察日": observation_day,
            "渠道": channel,
            "回访批次": batch_id,
            "已回访人数": returned_in_scope,
            "批次已回访人数": batch["已回访人数"] if batch else 0,
            "候选人数": len(rows),
            "候选行": rows,
        }

    # ----------------------------------------------------------
    # 领取未回访范围（领取边界）
    # ----------------------------------------------------------

    def claim_scope(self, cohort_id: str, observation_day: int, channel: str) -> dict[str, Any]:
        """领取当前未回访范围：快照候选用户与采用的回访批次，作为后续圈选边界。"""
        with self._lock:
            snapshot = self.absent_members(cohort_id, observation_day, channel)
            self._claim_seq += 1
            claim = {
                "领取编号": f"CLM-{self._claim_seq:04d}",
                "群组编号": cohort_id,
                "观察日": observation_day,
                "渠道": channel,
                "回访批次": snapshot["回访批次"],
                "已回访人数": snapshot["已回访人数"],
                "候选用户": [row["用户ID"] for row in snapshot["候选行"]],
                "状态": "已领取",
                "名单编号": None,
                "领取时间": self._tick(),
            }
            self._claims.append(claim)
            return deepcopy(claim)

    def list_claims(self) -> list[dict[str, Any]]:
        return deepcopy(self._claims)

    # ----------------------------------------------------------
    # 运营圈选：只在领取范围内按用户属性过滤，每轮领取只生成一份名单
    # ----------------------------------------------------------

    def generate_oplist(
        self,
        claim_id: str,
        conditions: dict[str, str] | None = None,
    ) -> tuple[dict[str, Any] | None, str]:
        cleaned = {
            str(field): str(value).strip()
            for field, value in (conditions or {}).items()
            if str(value).strip()
        }
        unknown = [field for field in cleaned if field not in ATTRIBUTE_FIELDS]
        if unknown:
            return None, f"圈选条件字段不属于用户属性：{'、'.join(unknown)}"
        with self._lock:
            claim = next((c for c in self._claims if c["领取编号"] == claim_id), None)
            if claim is None:
                return None, f"领取记录 {claim_id} 不存在"
            if claim["状态"] == "已生成名单":
                return None, (
                    f"本轮领取 {claim_id} 已生成运营名单 {claim['名单编号']}，"
                    "并发确认只生成一份，如需重选请重新领取范围"
                )
            members = {
                member["用户ID"]: member
                for member in self._cohort_members(claim["群组编号"], claim["渠道"])
            }
            selected = [
                uid for uid in claim["候选用户"]
                if uid in members and _matches(members[uid], cleaned)
            ]
            self._oplist_seq += 1
            oplist = {
                "名单编号": f"OPL-{self._oplist_seq:04d}",
                "来源领取编号": claim["领取编号"],
                "群组编号": claim["群组编号"],
                "观察日": claim["观察日"],
                "渠道": claim["渠道"],
                "回访批次": claim["回访批次"],
                "圈选条件": cleaned,
                "候选用户": list(claim["候选用户"]),
                "名单成员": selected,
                "成员数": len(selected),
                "状态": "已生成",
                "生成时间": self._tick(),
            }
            claim["状态"] = "已生成名单"
            claim["名单编号"] = oplist["名单编号"]
            self._oplists.append(oplist)
            latest = self._latest_batch(claim["群组编号"], claim["观察日"])
            message = f"运营名单 {oplist['名单编号']} 已生成，圈出 {len(selected)} 人"
            if latest and latest["回访批次"] != claim["回访批次"]:
                message += (
                    f"（领取批次 {claim['回访批次']} 与当前批次 {latest['回访批次']} 有冲突，"
                    "本轮仍按领取边界执行）"
                )
            return deepcopy(oplist), message

    # ----------------------------------------------------------
    # 迟到回访：补送（待确认）→ 确认（批次推进）
    # ----------------------------------------------------------

    def report_revisits(
        self,
        cohort_id: str,
        observation_day: int,
        user_ids: list[str],
    ) -> tuple[list[dict[str, Any]] | None, str]:
        """补送迟到回访，登记为待确认；重复补送同一用户只算一人。"""
        unique_ids = sorted({str(uid).strip() for uid in user_ids if str(uid).strip()})
        if not unique_ids:
            return None, "补送回访至少需要一个用户"
        known = {member["用户ID"] for member in self._cohort_members(cohort_id)}
        outsiders = [uid for uid in unique_ids if uid not in known]
        if outsiders:
            return None, f"用户 {'、'.join(outsiders)} 不是群组 {cohort_id} 的实际入群成员"
        with self._lock:
            records = []
            for uid in unique_ids:
                self._report_seq += 1
                record = {
                    "补送编号": f"RV-{self._report_seq:04d}",
                    "群组编号": cohort_id,
                    "观察日": observation_day,
                    "用户ID": uid,
                    "状态": "待确认",
                    "回访批次": "",
                    "补送时间": self._tick(),
                }
                self._pending.append(record)
                records.append(record)
            return records, f"已补送 {len(records)} 条第 {observation_day} 日回访，等待确认"

    def confirm_revisits(
        self,
        cohort_id: str,
        observation_day: int,
    ) -> tuple[dict[str, Any] | None, str]:
        """确认待确认回访：与上一批次合并去重后生成新批次，回访批次随之推进。"""
        with self._lock:
            pending = [
                record for record in self._pending
                if record["群组编号"] == cohort_id and record["观察日"] == observation_day
            ]
            if not pending:
                return None, f"群组 {cohort_id} 第 {observation_day} 日没有待确认的回访"
            previous = self._latest_batch(cohort_id, observation_day)
            merged = set(previous["已回访用户"]) if previous else set()
            merged.update(record["用户ID"] for record in pending)
            users = sorted(merged)  # 重复回访只算一人
            seq = previous["批次序号"] + 1 if previous else 1
            batch = {
                "回访批次": f"RB-{cohort_id.replace('-', '')}-D{observation_day}-{seq:03d}",
                "群组编号": cohort_id,
                "观察日": observation_day,
                "批次序号": seq,
                "已回访用户": users,
                "已回访人数": len(users),
                "状态": "已确认",
                "确认时间": self._tick(),
            }
            self._batches.append(batch)
            self._pending = [
                record for record in self._pending
                if not (record["群组编号"] == cohort_id and record["观察日"] == observation_day)
            ]
            return deepcopy(batch), (
                f"回访批次 {batch['回访批次']} 已确认，第 {observation_day} 日已回访 {len(users)} 人"
            )

    # ----------------------------------------------------------
    # 名单来源回查与回算
    # ----------------------------------------------------------

    def list_oplists(self) -> list[dict[str, Any]]:
        return deepcopy(self._oplists)

    def oplist_source(self, list_id: str) -> dict[str, Any] | None:
        """回查名单来源：按名单实际采用的回访批次与渠道回算，校验名单一致性。"""
        oplist = next((o for o in self._oplists if o["名单编号"] == list_id), None)
        if oplist is None:
            return None
        batch = next(
            (b for b in self._batches if b["回访批次"] == oplist["回访批次"]), None)
        returned = set(batch["已回访用户"]) if batch else set()
        members = self._cohort_members(oplist["群组编号"], oplist["渠道"])
        recomputed_candidates = [m for m in members if m["用户ID"] not in returned]
        recomputed = [
            m["用户ID"] for m in recomputed_candidates
            if _matches(m, oplist["圈选条件"])
        ]
        return {
            **deepcopy(oplist),
            "批次已回访人数": batch["已回访人数"] if batch else 0,
            "回算候选": [m["用户ID"] for m in recomputed_candidates],
            "回算成员": recomputed,
            "回算一致": recomputed == list(oplist["名单成员"]),
        }


cohort_ops_service = CohortOpsService()
