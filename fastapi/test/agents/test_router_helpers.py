"""Tests for agent router post-processing helpers."""
import json
import pytest

from app.agents.router import (
    _clean_user_response,
    _extract_json_payload,
    _detect_action,
    _extract_target,
    _KNOWN_ACTIONS,
)


class TestCleanUserResponse:
    def test_removes_markdown_links(self):
        text = "点击 [这里](http://example.com/file) 下载"
        cleaned = _clean_user_response(text)
        assert "http://example.com" not in cleaned
        assert "这里" in cleaned

    def test_removes_plain_urls(self):
        text = "访问 http://example.com/path 查看"
        cleaned = _clean_user_response(text)
        assert "http://example.com" not in cleaned

    def test_normalizes_blank_lines(self):
        text = "line1\n\n\n\nline2"
        cleaned = _clean_user_response(text)
        assert cleaned.count("\n\n") <= 1

    def test_empty_string(self):
        assert _clean_user_response("") == ""
        assert _clean_user_response(None) == ""


class TestExtractJsonPayload:
    def test_pure_json(self):
        obj = {"response": "hello", "action": "chat", "data": {}}
        result = _extract_json_payload(json.dumps(obj))
        assert result == obj

    def test_json_in_text(self):
        text = 'Some prefix\n{"response": "ok", "action": "chat", "data": {}}\nSome suffix'
        result = _extract_json_payload(text)
        assert result is not None
        assert result["response"] == "ok"

    def test_invalid_json(self):
        result = _extract_json_payload("not json at all")
        assert result is None

    def test_nested_braces(self):
        text = '{"response": "hello", "data": {"key": "value"}}'
        result = _extract_json_payload(text)
        assert result is not None
        assert result["data"] == {"key": "value"}


class TestDetectAction:
    def test_explicit_action_returned(self):
        assert _detect_action("play", "", "") == "play"

    def test_invalid_action_falls_back(self):
        """Unknown action string falls back to keyword detection."""
        result = _detect_action("unknown_action", "播放电影", "")
        assert result == "play"

    def test_known_actions(self):
        for action in ["play", "download", "file_info", "folder_info", "move", "copy",
                        "search", "document_search", "create_folder", "rename", "delete", "chat"]:
            assert action in _KNOWN_ACTIONS

    @pytest.mark.parametrize("message,expected_action", [
        ("播放电影《阿凡达》", "play"),
        ("在线看蓝色大门", "play"),
        ("下载这个文件", "download"),
        ("新建文件夹 Work", "create_folder"),
        ("重命名 a.txt 为 b.txt", "rename"),
        ("删除 temp 文件夹", "delete"),
        ("打开 Photos 文件夹", "folder_info"),
        ("查看 readme 文件信息", "file_info"),
        ("移动文件到 Documents", "move"),
        ("复制文件到 Backup", "copy"),
        ("搜索所有 PDF 文件", "search"),
        ("这篇论文讲了什么", "document_search"),
        ("你好", "chat"),
    ])
    def test_keyword_detection(self, message, expected_action):
        result = _detect_action(None, message, "")
        assert result == expected_action


class TestExtractTarget:
    def test_chinese_book_marks(self):
        assert _extract_target("播放《蓝色大门》") == "蓝色大门"

    def test_double_quotes(self):
        assert _extract_target('打开"Photos"文件夹') == "Photos"

    def test_single_quotes(self):
        assert _extract_target("查看'readme.txt'信息") == "readme.txt"

    def test_no_markers(self):
        result = _extract_target("帮我找一下那个文件")
        # 文件和找等词被 clean 掉，保留核心词
        assert result == "那个"
