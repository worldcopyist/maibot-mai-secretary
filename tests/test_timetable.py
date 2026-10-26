from __future__ import annotations

import base64
import importlib
import io
import json
from datetime import UTC, datetime
from pathlib import Path

import pytest
from test_secretary import make_plugin

timetable = importlib.import_module("mai_secretary.timetable")
parse_import = timetable.parse_import
parse_weeks = timetable.parse_weeks

def test_week_expressions_in_supported_xls():
    assert parse_weeks("1-4,6-8(周)[01-02节]") == [1, 2, 3, 4, 6, 7, 8]
    assert parse_weeks("1-7(单)") == [1, 3, 5, 7]
    assert parse_weeks("2-8(双)") == [2, 4, 6, 8]


@pytest.mark.asyncio
async def test_xls_import_preview_commit_replaces_reminders(tmp_path):
    plugin, _ = make_plugin(tmp_path)
    preview = await plugin.timetable.preview("other-stream", "2030-01-07", 3,
                                             _one_course_xls_base64("地质学"))
    assert preview["course_count"] == 1
    assert preview["reminder_count"] == 2
    assert not plugin.scheduled.tasks
    result = await plugin.timetable.commit(preview["preview_id"])
    assert result["reminder_count"] == 2
    reminders = sorted(plugin.scheduled.tasks.values(), key=lambda task: task.next_run)
    assert reminders[0].at == "2030-01-07T07:50+08:00"
    assert reminders[1].at == "2030-01-21T07:50+08:00"
    assert all(task.owner_user_id == "__secretary_timetable__" for task in reminders)
    assert (await plugin.secretary_tasks_list())["tasks"] == []
    listed = await plugin.timetable.list_profiles()
    assert listed["profiles"][0]["reminder_count"] == 2
    assert [item["course_name"] for item in listed["reminders"]] == ["地质学", "地质学"]
    assert (await plugin.secretary_tasks_cancel(reminders[0].id))["error"] == "课表提醒请在课表页面管理"

    answer = await plugin.timetable.query(stream_id="other-stream", chat_id="other-stream", date="2030-01-07")
    assert answer["week"] == 1
    assert "地质学" in answer["content"]
    assert not (await plugin.timetable.query(stream_id="other-stream", chat_id="another"))["success"]

    replacement = await plugin.timetable.preview("other-stream", "2030-01-07", 3,
                                                 _one_course_xls_base64("岩石学"))
    await plugin.timetable.commit(replacement["preview_id"])
    assert len(plugin.scheduled.tasks) == 2
    assert all("岩石学" in task.instruction for task in plugin.scheduled.tasks.values())
    assert "地质学" not in (await plugin.timetable.query(
        stream_id="other-stream", chat_id="other-stream", date="2030-01-07"
    ))["content"]


@pytest.mark.asyncio
async def test_timetable_config_rebuild_and_disable(tmp_path):
    plugin, proactive = make_plugin(tmp_path)
    preview = await plugin.timetable.preview("other-stream", "2030-01-07", 2,
                                             _one_course_xls_base64("写作", weeks="1", sections="03-04"))
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


def test_timetable_rejects_invalid_imports_and_sections():
    with pytest.raises(ValueError, match="教学周"):
        parse_weeks("1-30(周)")
    with pytest.raises(ValueError, match="节次"):
        parse_import(_one_course_xls_base64("坏课程", sections="21-22"), 20)
    for content in ('{"courses": []}', '<table><tr><td>课程</td></tr></table>'):
        with pytest.raises(ValueError, match="请从课表页面上传"):
            parse_import(content, 20)
    with pytest.raises(ValueError, match="缺少明确的教学周"):
        timetable.Course.from_mapping({"name": "坏课程", "day_of_week": 1,
                                       "start_section": 1, "end_section": 2,
                                       "weeks": []}, 20)


def test_legacy_profile_source_is_normalized_without_changing_courses(tmp_path):
    plugin, _ = make_plugin(tmp_path)
    course = {"name": "旧课程", "day_of_week": 1, "start_section": 1,
              "end_section": 2, "weeks": [1], "location": "", "teacher": ""}
    plugin.timetable.load_state({"timetables": {
        "first": {"source": "旧版 Excel 标签", "courses": [course]},
        "second": {"source": "旧版网页标签", "courses": [course]},
    }})
    assert plugin.timetable.source_migrated
    assert plugin.timetable.profiles["first"]["source"] == timetable.IMPORT_SOURCE
    assert plugin.timetable.profiles["second"]["source"] == "旧版课表数据"
    assert plugin.timetable.profiles["first"]["courses"] == [course]


def test_webui_declaration_matches_host_limits():
    spec = json.loads((Path(__file__).resolve().parents[1] / "webui.json").read_text(encoding="utf-8"))
    page = next(item for item in spec["pages"] if item["id"] == "timetable")
    assert page["icon"] in {"puzzle", "chart", "settings", "database", "list"}
    content = page["actions"]["preview"]["parameters"]["content"]
    assert content["max_length"] == timetable.MAX_IMPORT_CHARS <= 65_536


def test_xls_export_week_expressions():
    assert parse_weeks("3-5,7-16([周])[01-02节]") == [3, 4, 5, 7, 8, 9, 10, 11, 12, 13, 14, 15, 16]
    assert parse_weeks("2-5,9,11-17([周])[01-02节]") == [2, 3, 4, 5, 9, 11, 12, 13, 14, 15, 16, 17]
    assert parse_weeks("18([周])[01-02节]") == [18]


def _sample_xls_base64() -> str:
    xlwt = pytest.importorskip("xlwt")
    book = xlwt.Workbook()
    sheet = book.add_sheet("Sheet1")
    sheet.write(0, 0, "学生个人课表")
    sheet.write(1, 0, "学年学期：2026-2027-1        班级：示例班")
    for col, name in enumerate(["", "星期一", "星期二", "星期三", "星期四", "星期五", "星期六", "星期日"]):
        if name:
            sheet.write(2, col, name)
    sheet.write(3, 0, "第一二节")
    sheet.write(3, 2, "\n高等数学（B）（1）\n万会芳\n2-5,9,11-17([周])[01-02节]\n（宜）乙205\n"
                      "\n软件工程\n林杰\n12-16([周])[01-02节]\n（宜）乙210\n")
    sheet.write(3, 6, "\n实践训练计划\n刘同\n7-8([周])[01-02-03-04节]\n（宜）综B202（计算机）\n")
    sheet.write(4, 0, "中午")
    sheet.write(5, 0, "第三四节")
    sheet.write(5, 1, "\n计算机视觉实训\n罗俊松\n2([周])[03-04节]\n(宜）综B201（计算机）\n")
    sheet.write(6, 1, "：劳动教育 林杰 1-20周;实践训练计划 刘同;")
    buffer = io.BytesIO()
    book.save(buffer)
    return base64.b64encode(buffer.getvalue()).decode()


def _one_course_xls_base64(name: str, *, weeks: str = "1,3", sections: str = "01-02") -> str:
    xlwt = pytest.importorskip("xlwt")
    book = xlwt.Workbook()
    sheet = book.add_sheet("Sheet1")
    sheet.write(0, 0, "学生个人课表")
    sheet.write(1, 1, "星期一")
    sheet.write(2, 0, "第一二节")
    sheet.write(2, 1, f"\n{name}\n示例老师\n{weeks}([周])[{sections}节]\nA101\n")
    buffer = io.BytesIO()
    book.save(buffer)
    return timetable.XLS_BASE64_PREFIX + base64.b64encode(buffer.getvalue()).decode()


def test_xls_import_parses_grid_and_course_blocks():
    courses, source = parse_import(timetable.XLS_BASE64_PREFIX + _sample_xls_base64(), 18)
    assert source == timetable.IMPORT_SOURCE
    assert len(courses) == 4
    math = next(course for course in courses if course.name == "高等数学（B）（1）")
    assert (math.day_of_week, math.start_section, math.end_section) == (2, 1, 2)
    assert math.weeks == (2, 3, 4, 5, 9, 11, 12, 13, 14, 15, 16, 17)
    assert (math.teacher, math.location) == ("万会芳", "乙205")
    practice = next(course for course in courses if course.name == "实践训练计划")
    assert (practice.day_of_week, practice.start_section, practice.end_section) == (6, 1, 4)
    assert practice.weeks == (7, 8)
    assert practice.location == "综B202（计算机）"
    training = next(course for course in courses if course.name == "计算机视觉实训")
    assert (training.day_of_week, training.start_section, training.end_section) == (1, 3, 4)
    assert training.location == "综B201（计算机）"
    assert all("：劳动教育" not in course.name for course in courses)

    with pytest.raises(ValueError, match="不是可识别"):
        parse_import(timetable.XLS_BASE64_PREFIX + base64.b64encode(b"not an excel").decode(), 18)


def _file_content(suffix: str, data: bytes) -> str:
    return f"TIMETABLE-FILE:{suffix}:" + base64.b64encode(data).decode()


def test_structured_csv_weeks_and_parity():
    data = ("课程名称,星期,节次,周次,教师,教室\n"
            "高等数学,星期一,1-2,1-8(单),陈老师,A101\n"
            "物理,周三,3-4,2-8(双),王老师,B202\n").encode()
    courses, source = parse_import(_file_content("csv", data), 10)
    assert source == "课表 CSV 文件"
    assert [(c.name, c.day_of_week, c.weeks) for c in courses] == [
        ("高等数学", 1, (1, 3, 5, 7)), ("物理", 3, (2, 4, 6, 8))]
    with pytest.raises(ValueError, match="无法识别教学周"):
        parse_import(_file_content("csv", data.replace(b"1-8(\xe5\x8d\x95)", b"1-8(foo)")), 10)


def test_date_rows_only_schedule_their_own_week():
    data = ("课程名称,上课日期,节次,周次\n"
            "艺术,2030-01-07,5-6,1-16周\n").encode()
    courses, _ = parse_import(_file_content("csv", data), 16, "2030-01-07")
    assert courses[0].weeks == (1,)
    with pytest.raises(ValueError, match="日期不在"):
        parse_import(_file_content("csv", data.replace(b"1-16", b"3-16")), 16,
                     "2030-01-07")


def test_xlsx_structured_table_and_html_disguised_as_xls():
    openpyxl = pytest.importorskip("openpyxl")
    book = openpyxl.Workbook()
    sheet = book.active
    sheet.append(["课程名称", "星期", "节次", "开始周", "结束周", "单双周", "教室"])
    sheet.append(["数据结构", "星期二", "9-10", 1, 16, "双周", "C301"])
    output = io.BytesIO()
    book.save(output)
    courses, source = parse_import(_file_content("xlsx", output.getvalue()), 16)
    assert source == "课表 XLSX 文件"
    assert courses[0].weeks == tuple(range(2, 17, 2))
    assert courses[0].start_section == 9
    html = ('<table><tr><th>节次</th><th>星期一</th></tr>'
            '<tr><td>1-2节</td><td>写作 {第1-16周 教室:A101</td></tr>'
            '<tr><td>课程说明</td><td>劳动教育 1-16周</td></tr></table>').encode()
    courses, source = parse_import(_file_content("xls", html), 16)
    assert source == "课表 HTML 文件"
    assert len(courses) == 1
    assert courses[0].name == "写作"
    assert courses[0].weeks == tuple(range(1, 17))


def test_html_multiple_course_blocks_and_gb18030_csv():
    html = ('<table><tr><th>节次</th><th>周1</th></tr>'
            '<tr><td>1-2节</td><td><div>高数 第1-8周</div>'
            '<div>语文 第9-16周</div></td></tr></table>').encode()
    courses, _ = parse_import(_file_content("htm", html), 16)
    assert {item.name: item.weeks[0] for item in courses} == {"高数": 1, "语文": 9}
    csv_data = "课程名称;星期;节次;周次\n物理;周五;3-4;2-4周\n".encode("gb18030")
    courses, _ = parse_import(_file_content("csv", csv_data), 4)
    assert courses[0].weeks == (2, 3, 4)


@pytest.mark.asyncio
async def test_preview_refuses_unconfigured_period_without_replacing_schedule(tmp_path):
    plugin, _ = make_plugin(tmp_path)
    first = await plugin.timetable.preview("other-stream", "2030-01-07", 3,
                                          _one_course_xls_base64("原课"))
    await plugin.timetable.commit(first["preview_id"])
    before = dict(plugin.scheduled.tasks)
    with pytest.raises(ValueError, match="只配置了 11 节"):
        await plugin.timetable.preview("other-stream", "2030-01-07", 3,
                                       _one_course_xls_base64("新课", sections="12-13"))
    assert plugin.scheduled.tasks == before
