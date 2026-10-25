from __future__ import annotations

import importlib
import json
from datetime import UTC, datetime
from pathlib import Path

import pytest
from test_secretary import make_plugin

timetable = importlib.import_module("mai_secretary.timetable")
parse_import = timetable.parse_import
parse_weeks = timetable.parse_weeks

def test_cdut_week_expressions_and_html_semantic_fields():
    assert parse_weeks("1-4,6-8(周)[01-02节]") == [1, 2, 3, 4, 6, 7, 8]
    assert parse_weeks("1-7(单)") == [1, 3, 5, 7]
    assert parse_weeks("2-8(双)") == [2, 4, 6, 8]
    html = """<html><table><tr><th>节次</th><th>星期一</th></tr>
      <tr><td>第1-2节</td><td><div class="kbcontent">
      <font>高等数学</font><font title="教师">张老师</font>
      <font title="周次(节次)">1-3(单)[01-02节]</font>
      <font title="教室">A101</font></div></td></tr>
      <tr><td>第九十十一节</td><td><div class="kbcontent1">
      <font title="周次(节次)">2-4(双)</font><font>实验设计</font>
      </div></td></tr></table></html>"""
    courses, source = parse_import(html, 4)
    assert source == "CDUT 教务 HTML"
    assert len(courses) == 2
    assert courses[0].name == "高等数学"
    assert courses[0].weeks == (1, 3)
    assert (courses[0].day_of_week, courses[0].start_section, courses[0].end_section) == (1, 1, 2)
    assert (courses[0].teacher, courses[0].location) == ("张老师", "A101")
    assert courses[1].weeks == (2, 4)
    assert (courses[1].start_section, courses[1].end_section) == (9, 11)

    overlapping = """<table><tr><td>第一二节</td><td><div class="kbcontent">
      <font title="周次(节次)">1-2(周)</font><font>课程甲</font>----------
      <font title="周次(节次)">3-4(周)</font><font>课程乙</font>
      </div></td></tr></table>"""
    courses, _ = parse_import(overlapping, 4)
    assert {course.name: course.weeks for course in courses} == {
        "课程甲": (1, 2), "课程乙": (3, 4),
    }


@pytest.mark.asyncio
async def test_cdut_json_import_preview_commit_replaces_reminders(tmp_path):
    plugin, _ = make_plugin(tmp_path)
    payload = {"courses": [{
        "name": "地质学", "dayOfWeek": 1, "startSection": 1, "endSection": 2,
        "weekList": [1, 3], "location": "A101", "teacher": "李老师",
    }]}
    preview = await plugin.timetable.preview("other-stream", "2030-01-07", 3, json.dumps(payload))
    assert preview["course_count"] == 1
    assert preview["reminder_count"] == 2
    assert not plugin.scheduled.tasks
    result = await plugin.timetable.commit(preview["preview_id"])
    assert result["reminder_count"] == 2
    reminders = sorted(plugin.scheduled.tasks.values(), key=lambda task: task.next_run)
    assert reminders[0].at == "2030-01-07T07:50+08:00"
    assert reminders[1].at == "2030-01-21T07:50+08:00"
    assert all(task.owner_user_id == "__secretary_timetable__" for task in reminders)

    answer = await plugin.timetable.query(stream_id="other-stream", chat_id="other-stream", date="2030-01-07")
    assert answer["week"] == 1
    assert "地质学" in answer["content"]
    assert not (await plugin.timetable.query(stream_id="other-stream", chat_id="another"))["success"]

    payload["courses"][0]["name"] = "岩石学"
    replacement = await plugin.timetable.preview("other-stream", "2030-01-07", 3, json.dumps(payload))
    await plugin.timetable.commit(replacement["preview_id"])
    assert len(plugin.scheduled.tasks) == 2
    assert all("岩石学" in task.instruction for task in plugin.scheduled.tasks.values())
    assert "地质学" not in (await plugin.timetable.query(
        stream_id="other-stream", chat_id="other-stream", date="2030-01-07"
    ))["content"]


@pytest.mark.asyncio
async def test_timetable_config_rebuild_and_disable(tmp_path):
    plugin, proactive = make_plugin(tmp_path)
    payload = {"courses": [{"name": "写作", "dayOfWeek": 1,
                            "startSection": 3, "endSection": 4, "weekList": [1]}]}
    preview = await plugin.timetable.preview("other-stream", "2030-01-07", 2, json.dumps(payload))
    await plugin.timetable.commit(preview["preview_id"])
    task = next(iter(plugin.scheduled.tasks.values()))
    assert task.at == "2030-01-07T09:55+08:00"
    plugin.config.timetable.remind_before_minutes = 45
    plugin.timetable.on_config_update()
    await plugin.timetable.tick(datetime(2029, 12, 1, tzinfo=UTC))
    task = next(iter(plugin.scheduled.tasks.values()))
    assert task.at == "2030-01-07T09:30+08:00"
    plugin.config.timetable.enabled = False
    await plugin.scheduled.tick(datetime.fromtimestamp(task.next_run + 1, UTC))
    assert task.status == "active"
    assert not proactive.calls
    await plugin.timetable.delete("other-stream")
    assert not plugin.scheduled.tasks


def test_timetable_rejects_ambiguous_week_and_invalid_section():
    with pytest.raises(ValueError, match="教学周"):
        parse_weeks("1-30(周)")
    with pytest.raises(ValueError, match="节次"):
        parse_import(json.dumps({"courses": [{"name": "坏课程", "dayOfWeek": 1,
                                               "startSection": 12, "endSection": 12,
                                               "weekList": [1]}]}), 20)

    course = {"name": "地理", "dayOfWeek": 2, "startSection": 1,
              "endSection": 2, "weekList": [1]}
    wrapped = {"success": True, "json": {"courses": [course], "week": None}}
    assert parse_import(json.dumps(wrapped), 20)[0][0].name == "地理"
    fenced = "课表如下\n```json\n" + json.dumps(wrapped) + "\n```"
    assert parse_import(fenced, 20)[0][0].name == "地理"
    wrapped["json"]["week"] = 1
    with pytest.raises(ValueError, match="完整课表"):
        parse_import(json.dumps(wrapped), 20)


def test_webui_declaration_matches_host_limits():
    spec = json.loads((Path(__file__).resolve().parents[1] / "webui.json").read_text(encoding="utf-8"))
    page = next(item for item in spec["pages"] if item["id"] == "timetable")
    assert page["icon"] in {"puzzle", "chart", "settings", "database", "list"}
    content = page["actions"]["preview"]["parameters"]["content"]
    assert content["max_length"] == timetable.MAX_IMPORT_CHARS <= 65_536
