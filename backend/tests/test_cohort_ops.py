"""同期群未回访回查与运营圈选测试。

验收链路：按观察日 + 渠道查询实际成员 → 回查未回访清单 → 领取范围 →
按用户属性圈选生成名单 → 补送并确认 B 的第二日迟到回访 →
首轮名单按领取边界仍含 B、下一轮排除 B → 两份名单按回访批次与渠道回算来源。
"""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor

import pytest

from app.services.cohort_ops import CohortOpsService

COHORT = "COHO-0001"
CHANNEL = "活动渠道"


@pytest.fixture
def service() -> CohortOpsService:
    """每个用例一份全新数据，保证确定性。"""
    return CohortOpsService()


# ============================================================
# 按日 + 渠道查询实际成员
# ============================================================

class TestActualMembers:
    def test_day2_activity_channel(self, service):
        result = service.actual_members(COHORT, 2, CHANNEL)
        assert result["回访批次"] == "RB-COHO0001-D2-001"
        assert result["成员基数"] == 4  # A、B、C、D；E 是自然渠道被过滤
        assert result["已回访人数"] == 2  # A、C
        assert result["未回访人数"] == 2  # B、D
        rows = {row["用户ID"]: row for row in result["成员行"]}
        assert rows["A"]["是否已回访"] is True
        assert rows["C"]["是否已回访"] is True
        assert rows["B"]["是否已回访"] is False
        assert rows["D"]["是否已回访"] is False
        # 每一行都标出采用的回访批次
        assert all(row["回访批次"] == "RB-COHO0001-D2-001" for row in rows.values())

    def test_day1_shows_b_returned(self, service):
        result = service.actual_members(COHORT, 1, CHANNEL)
        rows = {row["用户ID"]: row for row in result["成员行"]}
        assert result["回访批次"] == "RB-COHO0001-D1-001"
        assert rows["B"]["是否已回访"] is True  # B 第一天回访过

    def test_channel_filter_is_applied(self, service):
        activity = service.actual_members(COHORT, 2, CHANNEL)
        natural = service.actual_members(COHORT, 2, "自然渠道")
        assert {row["用户ID"] for row in activity["成员行"]} == {"A", "B", "C", "D"}
        assert {row["用户ID"] for row in natural["成员行"]} == {"E"}


# ============================================================
# 未回访成员清单
# ============================================================

class TestAbsentMembers:
    def test_day2_first_list_contains_b_and_d(self, service):
        result = service.absent_members(COHORT, 2, CHANNEL)
        assert result["回访批次"] == "RB-COHO0001-D2-001"
        assert result["已回访人数"] == 2  # A、C，标出采用批次
        assert result["批次已回访人数"] == 2
        candidates = {row["用户ID"] for row in result["候选行"]}
        # B 第一天回访过，仍应出现在第二日首次列表
        assert candidates == {"B", "D"}
        # 候选行标出采用的回访批次
        assert all(row["回访批次"] == "RB-COHO0001-D2-001" for row in result["候选行"])

    def test_absent_requires_matching_channel(self, service):
        result = service.absent_members(COHORT, 2, "自然渠道")
        assert {row["用户ID"] for row in result["候选行"]} == {"E"}


# ============================================================
# 领取边界与运营圈选
# ============================================================

class TestClaimAndGenerate:
    def test_claim_snapshots_boundary(self, service):
        claim = service.claim_scope(COHORT, 2, CHANNEL)
        assert claim["领取编号"] == "CLM-0001"
        assert claim["回访批次"] == "RB-COHO0001-D2-001"
        assert claim["候选用户"] == ["B", "D"]
        assert claim["状态"] == "已领取"

    def test_generate_filters_attributes_within_candidates(self, service):
        claim = service.claim_scope(COHORT, 2, CHANNEL)
        # A、C 是 ios 且高价值，但已回访不在候选里，圈选只作用于 B、D
        oplist, message = service.generate_oplist(claim["领取编号"], {"平台": "ios"})
        assert oplist is not None, message
        assert oplist["名单成员"] == []
        oplist2_claim = service.claim_scope(COHORT, 2, CHANNEL)
        oplist2, _ = service.generate_oplist(oplist2_claim["领取编号"], {"价值等级": "低"})
        assert oplist2["名单成员"] == ["D"]

    def test_generate_rejects_unknown_attribute(self, service):
        claim = service.claim_scope(COHORT, 2, CHANNEL)
        oplist, message = service.generate_oplist(claim["领取编号"], {"未知字段": "x"})
        assert oplist is None
        assert "用户属性" in message

    def test_one_oplist_per_claim(self, service):
        claim = service.claim_scope(COHORT, 2, CHANNEL)
        first, _ = service.generate_oplist(claim["领取编号"], {})
        second, message = service.generate_oplist(claim["领取编号"], {})
        assert first is not None
        assert second is None
        assert "只生成一份" in message
        assert len(service.list_oplists()) == 1

    def test_concurrent_generate_only_one_oplist(self, service):
        claim = service.claim_scope(COHORT, 2, CHANNEL)
        with ThreadPoolExecutor(max_workers=8) as pool:
            results = list(pool.map(
                lambda _: service.generate_oplist(claim["领取编号"], {}), range(16)))
        successes = [oplist for oplist, _ in results if oplist is not None]
        assert len(successes) == 1  # 并发确认本轮只生成一份运营名单
        assert len(service.list_oplists()) == 1


# ============================================================
# 迟到回访：补送与确认
# ============================================================

class TestLateRevisit:
    def test_report_and_confirm_advances_batch(self, service):
        records, message = service.report_revisits(COHORT, 2, ["B"])
        assert records is not None and records[0]["状态"] == "待确认"
        batch, message = service.confirm_revisits(COHORT, 2)
        assert batch is not None
        assert batch["回访批次"] == "RB-COHO0001-D2-002"
        assert batch["已回访用户"] == ["A", "B", "C"]
        assert batch["已回访人数"] == 3

    def test_duplicate_revisit_counts_once(self, service):
        # 重复回访只算一人：同一用户重复补送、且补送已回访用户都不重复计数
        service.report_revisits(COHORT, 2, ["B", "B", "A"])
        service.report_revisits(COHORT, 2, ["B"])
        batch, _ = service.confirm_revisits(COHORT, 2)
        assert batch["已回访用户"] == ["A", "B", "C"]
        assert batch["已回访人数"] == 3

    def test_report_rejects_non_member(self, service):
        records, message = service.report_revisits(COHORT, 2, ["Z"])
        assert records is None
        assert "实际入群成员" in message

    def test_confirm_without_pending(self, service):
        batch, message = service.confirm_revisits(COHORT, 2)
        assert batch is None
        assert "没有待确认" in message


# ============================================================
# 验收链路：首轮含 B → 补送确认 → 下一轮排除 B → 来源回算
# ============================================================

class TestAcceptanceFlow:
    def test_full_flow(self, service):
        # 1. 按日和渠道查询实际成员
        members = service.actual_members(COHORT, 2, CHANNEL)
        assert members["已回访人数"] == 2
        assert members["未回访人数"] == 2

        # 2. 回查未回访清单并领取首查范围
        absent = service.absent_members(COHORT, 2, CHANNEL)
        assert {row["用户ID"] for row in absent["候选行"]} == {"B", "D"}
        claim1 = service.claim_scope(COHORT, 2, CHANNEL)

        # 3. 首次申请生成名单（运营圈选只从这批候选里按属性过滤）
        oplist1, message1 = service.generate_oplist(claim1["领取编号"], {"平台": "android"})
        assert oplist1 is not None
        assert oplist1["名单成员"] == ["B", "D"]
        assert oplist1["回访批次"] == "RB-COHO0001-D2-001"

        # 4. 第二日 B 的迟到回访补送并完成确认
        service.report_revisits(COHORT, 2, ["B"])
        batch, _ = service.confirm_revisits(COHORT, 2)
        assert batch["回访批次"] == "RB-COHO0001-D2-002"

        # 5. 已领取范围与当前观察期冲突：首轮名单随领取边界仍包含 B
        source1 = service.oplist_source(oplist1["名单编号"])
        assert source1["名单成员"] == ["B", "D"]
        # 本轮已生成名单，不能重复生成
        again, message = service.generate_oplist(claim1["领取编号"], {})
        assert again is None

        # 6. 下一次实际圈选：新查询、新领取都不含已确认回访的 B
        absent2 = service.absent_members(COHORT, 2, CHANNEL)
        assert absent2["回访批次"] == "RB-COHO0001-D2-002"
        assert absent2["已回访人数"] == 3
        assert {row["用户ID"] for row in absent2["候选行"]} == {"D"}
        claim2 = service.claim_scope(COHORT, 2, CHANNEL)
        assert claim2["候选用户"] == ["D"]
        oplist2, _ = service.generate_oplist(claim2["领取编号"], {"平台": "android"})
        assert oplist2["名单成员"] == ["D"]
        assert "B" not in oplist2["名单成员"]

        # 7. 回查两次名单的来源：都可按实际采用的第二日回访批次和渠道回算
        source1 = service.oplist_source(oplist1["名单编号"])
        assert source1["来源领取编号"] == claim1["领取编号"]
        assert source1["回访批次"] == "RB-COHO0001-D2-001"
        assert source1["渠道"] == CHANNEL
        assert source1["批次已回访人数"] == 2
        assert source1["回算成员"] == ["B", "D"]
        assert source1["回算一致"] is True

        source2 = service.oplist_source(oplist2["名单编号"])
        assert source2["来源领取编号"] == claim2["领取编号"]
        assert source2["回访批次"] == "RB-COHO0001-D2-002"
        assert source2["渠道"] == CHANNEL
        assert source2["批次已回访人数"] == 3
        assert source2["回算成员"] == ["D"]
        assert source2["回算一致"] is True

    def test_stale_claim_message_marks_conflict(self, service):
        claim = service.claim_scope(COHORT, 2, CHANNEL)
        service.report_revisits(COHORT, 2, ["B"])
        service.confirm_revisits(COHORT, 2)
        # 领取后才确认：名单仍按领取边界含 B，并在消息里标出批次冲突
        oplist, message = service.generate_oplist(claim["领取编号"], {})
        assert oplist is not None
        assert "B" in oplist["名单成员"]
        assert "冲突" in message
        assert "领取边界" in message

    def test_oplist_source_unknown_id(self, service):
        assert service.oplist_source("OPL-9999") is None
