"""Agent tool function unit tests — direct invocation with mocked DB."""
import json
import pytest
from unittest import mock

from app.agents.graph import (
    search_files_tool,
    get_file_info_tool,
    get_folder_info_tool,
    get_play_url_tool,
    get_download_url_tool,
    move_file_tool,
    copy_file_tool,
    create_folder_tool,
    rename_file_tool,
    delete_file_tool,
    search_documents_tool,
)


def _parse(result: str) -> dict:
    return json.loads(result)


def _make_file_node(id=1, name="test.txt", path="test.txt", abs_path="/tmp/test.txt",
                    parent_id=None, is_directory=False, size=100,
                    file_type="txt", mime_type="text/plain", owner_id=None,
                    visibility="private"):
    """Build a mock FileNode for testing."""
    node = mock.MagicMock()
    node.id = id
    node.name = name
    node.path = path
    node.abs_path = abs_path
    node.parent_id = parent_id
    node.is_directory = is_directory
    node.size = size
    node.file_type = file_type
    node.mime_type = mime_type
    node.media_type = None
    node.owner_id = owner_id
    node.visibility = visibility
    node.is_deleted = False
    node.duration = None
    node.thumbnail_path = None
    node._metadata = {}
    node.created_at = None
    node.updated_at = None
    return node


# ═══════════════════════════════════════════════════════════════════
#  Search
# ═══════════════════════════════════════════════════════════════════

class TestSearchFilesTool:
    def test_search_returns_results(self):
        node = _make_file_node(name="readme.txt")
        with mock.patch("app.agents.graph.search_nodes", return_value=[node]):
            result = _parse(search_files_tool.invoke({"keyword": "readme"}))
        assert result["count"] == 1
        assert result["results"][0]["name"] == "readme.txt"

    def test_search_empty(self):
        with mock.patch("app.agents.graph.search_nodes", return_value=[]):
            result = _parse(search_files_tool.invoke({"keyword": "nonexistent"}))
        assert result["count"] == 0

    def test_search_with_user_id_filter(self):
        """user_id should be passed through to search_nodes for permission filtering."""
        node = _make_file_node()
        with mock.patch("app.agents.graph.search_nodes") as mock_search:
            mock_search.return_value = [node]
            search_files_tool.invoke({"keyword": "test", "user_id": 42})
            assert mock_search.call_args[1]["user_id"] == 42


# ═══════════════════════════════════════════════════════════════════
#  File info
# ═══════════════════════════════════════════════════════════════════

class TestGetFileInfoTool:
    def test_found(self):
        node = _make_file_node(name="config.json")
        with mock.patch("app.agents.graph.search_nodes", return_value=[node]):
            with mock.patch("app.agents.graph.choose_best_match", return_value=node):
                result = _parse(get_file_info_tool.invoke({"name": "config"}))
        assert result["ok"] is True
        assert result["file"]["name"] == "config.json"

    def test_not_found(self):
        with mock.patch("app.agents.graph.search_nodes", return_value=[]):
            with mock.patch("app.agents.graph.choose_best_match", return_value=None):
                result = _parse(get_file_info_tool.invoke({"name": "ghost"}))
        assert result["ok"] is False


# ═══════════════════════════════════════════════════════════════════
#  Folder info
# ═══════════════════════════════════════════════════════════════════

class TestGetFolderInfoTool:
    def test_folder_with_children(self):
        folder = _make_file_node(name="Photos", is_directory=True)
        child = _make_file_node(id=2, name="photo1.jpg", parent_id=1, is_directory=False)
        with mock.patch("app.agents.graph.search_nodes", return_value=[folder]):
            with mock.patch("app.agents.graph.choose_best_match", return_value=folder):
                with mock.patch("app.agents.graph.get_children_visible", return_value=[child]):
                    result = _parse(get_folder_info_tool.invoke({"name": "Photos"}))
        assert result["ok"] is True
        assert result["folder"]["name"] == "Photos"
        assert len(result["children"]) == 1
        assert result["children"][0]["name"] == "photo1.jpg"

    def test_folder_not_found(self):
        with mock.patch("app.agents.graph.search_nodes", return_value=[]):
            with mock.patch("app.agents.graph.choose_best_match", return_value=None):
                result = _parse(get_folder_info_tool.invoke({"name": "GhostFolder"}))
        assert result["ok"] is False


# ═══════════════════════════════════════════════════════════════════
#  Create folder
# ═══════════════════════════════════════════════════════════════════

class TestCreateFolderTool:
    def test_create_success(self, tmp_path):
        settings_mock = mock.MagicMock()
        settings_mock.MEDIA_DIR = str(tmp_path)
        settings_mock.AGENT_BASE_APP_URL = "http://localhost:8000"
        with mock.patch("app.agents.graph.get_settings", return_value=settings_mock):
            result = _parse(create_folder_tool.invoke({
                "name": "NewFolder", "user_id": 1,
            }))
        assert result["ok"] is True
        assert result["folder"]["name"] == "NewFolder"
        assert (tmp_path / "NewFolder").exists()

    def test_create_duplicate(self, tmp_path):
        (tmp_path / "Exists").mkdir()
        settings_mock = mock.MagicMock()
        settings_mock.MEDIA_DIR = str(tmp_path)
        with mock.patch("app.agents.graph.get_settings", return_value=settings_mock):
            result = _parse(create_folder_tool.invoke({
                "name": "Exists", "user_id": 1,
            }))
        assert result["ok"] is False

    def test_create_under_parent(self, tmp_path):
        parent = tmp_path / "Parent"
        parent.mkdir()
        parent_node = _make_file_node(id=10, name="Parent", abs_path=str(parent),
                                       path="Parent", is_directory=True)
        settings_mock = mock.MagicMock()
        settings_mock.MEDIA_DIR = str(tmp_path)
        settings_mock.AGENT_BASE_APP_URL = "http://localhost:8000"
        with mock.patch("app.agents.graph.search_nodes", return_value=[parent_node]):
            with mock.patch("app.agents.graph.choose_best_match", return_value=parent_node):
                with mock.patch("app.agents.graph.get_settings", return_value=settings_mock):
                    result = _parse(create_folder_tool.invoke({
                        "name": "Child", "parent_name": "Parent", "user_id": 1,
                    }))
        assert result["ok"] is True
        assert (parent / "Child").exists()


# ═══════════════════════════════════════════════════════════════════
#  Rename
# ═══════════════════════════════════════════════════════════════════

class TestRenameFileTool:
    def test_rename_success(self):
        node = _make_file_node(name="old.txt", abs_path="/tmp/old.txt", path="old.txt")
        with mock.patch("app.agents.graph.search_nodes", return_value=[node]):
            with mock.patch("app.agents.graph.choose_best_match", return_value=node):
                with mock.patch("app.agents.graph.rename_node") as mock_rename:
                    renamed = _make_file_node(name="new.txt", abs_path="/tmp/new.txt", path="new.txt")
                    mock_rename.return_value = renamed
                    result = _parse(rename_file_tool.invoke({
                        "name": "old.txt", "new_name": "new.txt",
                    }))
        assert result["ok"] is True
        assert result["file"]["name"] == "new.txt"
        mock_rename.assert_called_once()

    def test_rename_not_found(self):
        with mock.patch("app.agents.graph.search_nodes", return_value=[]):
            with mock.patch("app.agents.graph.choose_best_match", return_value=None):
                result = _parse(rename_file_tool.invoke({
                    "name": "ghost.txt", "new_name": "whatever.txt",
                }))
        assert result["ok"] is False


# ═══════════════════════════════════════════════════════════════════
#  Delete
# ═══════════════════════════════════════════════════════════════════

class TestDeleteFileTool:
    def test_delete_soft(self):
        node = _make_file_node(name="temp.txt")
        with mock.patch("app.agents.graph.search_nodes", return_value=[node]):
            with mock.patch("app.agents.graph.choose_best_match", return_value=node):
                with mock.patch("app.agents.graph.delete_node") as mock_delete:
                    result = _parse(delete_file_tool.invoke({
                        "name": "temp.txt", "permanent": False,
                    }))
        assert result["ok"] is True
        assert result["action"] == "deleted"
        mock_delete.assert_called_once()

    def test_delete_permanent(self):
        node = _make_file_node(name="junk.txt")
        with mock.patch("app.agents.graph.search_nodes", return_value=[node]):
            with mock.patch("app.agents.graph.choose_best_match", return_value=node):
                with mock.patch("app.agents.graph.delete_node") as mock_delete:
                    result = _parse(delete_file_tool.invoke({
                        "name": "junk.txt", "permanent": True,
                    }))
        assert result["ok"] is True
        mock_delete.assert_called_once_with(mock.ANY, node, permanent=True)

    def test_delete_not_found(self):
        with mock.patch("app.agents.graph.search_nodes", return_value=[]):
            with mock.patch("app.agents.graph.choose_best_match", return_value=None):
                result = _parse(delete_file_tool.invoke({
                    "name": "ghost.txt",
                }))
        assert result["ok"] is False


# ═══════════════════════════════════════════════════════════════════
#  Move
# ═══════════════════════════════════════════════════════════════════

class TestMoveFileTool:
    def test_move_success(self):
        src = _make_file_node(id=1, name="file.txt")
        dest = _make_file_node(id=2, name="TargetFolder", is_directory=True)
        with mock.patch("app.agents.graph.search_nodes", side_effect=[[src], [dest]]):
            with mock.patch("app.agents.graph.choose_best_match", side_effect=[src, dest]):
                with mock.patch("app.agents.graph.move_node") as mock_move:
                    mock_move.return_value = src
                    result = _parse(move_file_tool.invoke({
                        "source_name": "file.txt", "destination_folder": "TargetFolder",
                    }))
        assert result["ok"] is True

    def test_move_source_not_found(self):
        with mock.patch("app.agents.graph.search_nodes", side_effect=[[], []]):
            with mock.patch("app.agents.graph.choose_best_match", side_effect=[None, None]):
                result = _parse(move_file_tool.invoke({
                    "source_name": "ghost", "destination_folder": "TargetFolder",
                }))
        assert result["ok"] is False


# ═══════════════════════════════════════════════════════════════════
#  Copy
# ═══════════════════════════════════════════════════════════════════

class TestCopyFileTool:
    def test_copy_success(self):
        from unittest.mock import MagicMock, PropertyMock
        src = _make_file_node(id=1, name="file.txt")
        dest = _make_file_node(id=2, name="TargetFolder", is_directory=True)

        # Build a mock DB session that survives commit/refresh
        mock_session = MagicMock()
        mock_session.__enter__ = MagicMock(return_value=mock_session)
        mock_session.__exit__ = MagicMock(return_value=False)

        with mock.patch("app.agents.graph._db_session") as mock_db_ctx:
            mock_db_ctx.return_value.__enter__ = MagicMock(return_value=mock_session)
            mock_db_ctx.return_value.__exit__ = MagicMock(return_value=False)

            with mock.patch("app.agents.graph.search_nodes", side_effect=[[src], [dest]]):
                with mock.patch("app.agents.graph.choose_best_match", side_effect=[src, dest]):
                    with mock.patch("app.agents.graph.copy_node") as mock_copy:
                        mock_copy.return_value = src
                        with mock.patch("app.agents.graph.get_settings") as mock_settings:
                            ms = MagicMock()
                            ms.AGENT_BASE_APP_URL = "http://localhost:8000"
                            mock_settings.return_value = ms
                            result = _parse(copy_file_tool.invoke({
                                "source_name": "file.txt", "destination_folder": "TargetFolder",
                            }))
        assert result["ok"] is True


# ═══════════════════════════════════════════════════════════════════
#  Play / Download URL
# ═══════════════════════════════════════════════════════════════════

class TestPlayDownloadTools:
    def test_play_url_video(self):
        node = _make_file_node(name="movie.mp4", mime_type="video/mp4",
                                file_type="mp4", is_directory=False)
        with mock.patch("app.agents.graph.search_nodes", return_value=[node]):
            with mock.patch("app.agents.graph.choose_best_match", return_value=node):
                with mock.patch("app.agents.graph.build_file_urls",
                                return_value={"play_url": "/media/play/1", "download_url": "/media/download/1"}):
                    result = _parse(get_play_url_tool.invoke({"name": "movie"}))
        assert result["ok"] is True
        assert "play_url" in result["urls"]

    def test_play_url_not_video(self):
        node = _make_file_node(name="readme.txt", mime_type="text/plain", is_directory=False)
        with mock.patch("app.agents.graph.search_nodes", return_value=[node]):
            with mock.patch("app.agents.graph.choose_best_match", return_value=node):
                with mock.patch("app.agents.graph.build_file_urls", return_value={"download_url": "/media/download/1"}):
                    result = _parse(get_play_url_tool.invoke({"name": "readme"}))
        assert result["ok"] is False

    def test_download_url(self):
        node = _make_file_node(name="archive.zip", is_directory=False)
        with mock.patch("app.agents.graph.search_nodes", return_value=[node]):
            with mock.patch("app.agents.graph.choose_best_match", return_value=node):
                with mock.patch("app.agents.graph.build_file_urls",
                                return_value={"download_url": "/media/download/1"}):
                    result = _parse(get_download_url_tool.invoke({"name": "archive"}))
        assert result["ok"] is True
        assert "download_url" in result["urls"]

    def test_download_directory_rejected(self):
        node = _make_file_node(name="Photos", is_directory=True)
        with mock.patch("app.agents.graph.search_nodes", return_value=[node]):
            with mock.patch("app.agents.graph.choose_best_match", return_value=node):
                result = _parse(get_download_url_tool.invoke({"name": "Photos"}))
        assert result["ok"] is False


# ═══════════════════════════════════════════════════════════════════
#  Document search
# ═══════════════════════════════════════════════════════════════════

class TestSearchDocumentsTool:
    def test_search_returns_results(self):
        hits = [
            {"text": "AI is ...", "metadata": {"file_name": "ai.pdf"}, "score": 0.95},
        ]
        mock_retrieval = mock.MagicMock()
        mock_retrieval.search.return_value = hits
        # RetrievalService is imported locally inside search_documents_tool
        with mock.patch("app.services.retrieval_service.RetrievalService", return_value=mock_retrieval):
            result = _parse(search_documents_tool.invoke({"query": "AI"}))
        assert result["ok"] is True
        assert result["count"] == 1
        assert result["results"][0]["source"] == "ai.pdf"

    def test_search_empty(self):
        mock_retrieval = mock.MagicMock()
        mock_retrieval.search.return_value = []
        with mock.patch("app.services.retrieval_service.RetrievalService", return_value=mock_retrieval):
            result = _parse(search_documents_tool.invoke({"query": "nothing"}))
        assert result["ok"] is True
        assert result["count"] == 0
