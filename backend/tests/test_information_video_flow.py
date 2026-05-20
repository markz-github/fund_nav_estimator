from __future__ import annotations

from datetime import date, datetime, timedelta
from pathlib import Path
import sys
import unittest
from unittest.mock import Mock, patch

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

import app.models  # noqa: F401
from app.database import Base
from app.modules.information.models.summary_document import InformationSummaryDocumentItem
from app.modules.information.models.summary_document import InformationSummaryDocument
from app.modules.information.models.task_log import TaskLog
from app.modules.information.models.video import InformationVideo
from app.modules.information.models.video_note import InformationVideoNote
from app.modules.information.models.video_source import InformationVideoSource
from app.modules.information.schemas.video import VideoSourceCreate
from app.modules.information.services.bilinote_client import BilinoteClient
from app.modules.information.services.information_settings_service import InformationSettingsService
from app.modules.information.services.hermes_client import HermesRunResult
from app.modules.information.services.hermes_client import HermesClient
from app.modules.information.services.video_information_service import VideoInformationService
from app.modules.information.services.video_source_adapters import (
    BilibiliVideoSourceAdapter,
    VideoSnapshot,
)
from app.modules.information.services.wechat_push_client import WechatPushClient


class InformationVideoFlowTests(unittest.TestCase):
    def setUp(self) -> None:
        engine = create_engine("sqlite:///:memory:")
        Base.metadata.create_all(bind=engine)
        self.SessionLocal = sessionmaker(bind=engine)
        self.db = self.SessionLocal()

    def tearDown(self) -> None:
        self.db.close()

    def test_bilibili_source_id_normalizes_uid_and_space_url(self) -> None:
        adapter = BilibiliVideoSourceAdapter()

        self.assertEqual(adapter.normalize_source_id("12345"), "12345")
        self.assertEqual(adapter.normalize_source_id("https://space.bilibili.com/67890/video"), "67890")
        self.assertEqual(adapter.normalize_source_id("https://www.bilibili.com/?mid=24680"), "24680")

    def test_bilibili_adapter_sends_configured_cookie(self) -> None:
        adapter = BilibiliVideoSourceAdapter()
        source = InformationVideoSource(
            id=7,
            platform="bilibili",
            source_name="测试账号",
            external_source_id="12345",
            enabled=1,
        )
        response = Mock()
        response.status_code = 200
        response.json.return_value = {"code": 0, "data": {"list": {"vlist": []}}}

        with patch("app.modules.information.services.video_source_adapters.requests.get", return_value=response) as get:
            snapshots = adapter.fetch_latest_videos(source, bilibili_cookie="SESSDATA=test; bili_jct=abc")

        self.assertEqual(snapshots, [])
        headers = get.call_args.kwargs["headers"]
        self.assertEqual(headers["Cookie"], "SESSDATA=test; bili_jct=abc")

    def test_bilibili_adapter_parses_article_dynamic_items(self) -> None:
        adapter = BilibiliVideoSourceAdapter()
        source = InformationVideoSource(
            id=7,
            platform="bilibili",
            source_name="皓哥论股",
            external_source_id="307610125",
            enabled=1,
        )
        arc_response = Mock()
        arc_response.status_code = 200
        arc_response.json.return_value = {"code": 0, "data": {"list": {"vlist": []}}}
        dynamic_response = Mock()
        dynamic_response.status_code = 200
        dynamic_response.json.return_value = {
            "code": 0,
            "data": {
                "items": [
                    {
                        "id_str": "123456",
                        "type": "DYNAMIC_TYPE_DRAW",
                        "modules": {
                            "module_author": {"pub_ts": 1779252000},
                            "module_dynamic": {
                                "major": {
                                    "type": "MAJOR_TYPE_OPUS",
                                    "opus": {
                                        "opus_id": "987654",
                                        "title": "今天市场观察",
                                        "summary": {"text": "核心观点：控制仓位。"},
                                        "jump_url": "//www.bilibili.com/opus/987654",
                                    },
                                },
                                "desc": {"text": "补充观点：等待确认信号。"},
                            },
                        },
                    },
                    {"type": "DYNAMIC_TYPE_AV", "modules": {"module_dynamic": {"major": {"type": "MAJOR_TYPE_ARCHIVE"}}}},
                ]
            },
        }

        with patch(
            "app.modules.information.services.video_source_adapters.requests.get",
            side_effect=[arc_response, dynamic_response],
        ):
            snapshots = adapter.fetch_latest_videos(source)

        self.assertEqual(len(snapshots), 1)
        self.assertEqual(snapshots[0].content_type, "article")
        self.assertEqual(snapshots[0].external_video_id, "article_987654")
        self.assertEqual(snapshots[0].video_url, "https://www.bilibili.com/opus/987654")
        self.assertEqual(snapshots[0].published_at, datetime.fromtimestamp(1779252000))
        self.assertIn("控制仓位", snapshots[0].content_text or "")

    def test_bilibili_adapter_uses_article_ctime_as_publish_time_fallback(self) -> None:
        adapter = BilibiliVideoSourceAdapter()
        source = InformationVideoSource(source_name="测试账号", external_source_id="12345")

        snapshot = adapter._article_snapshot_from_dynamic_item(
            source,
            {
                "id_str": "123456",
                "ctime": 1779252100,
                "modules": {
                    "module_dynamic": {
                        "major": {
                            "type": "MAJOR_TYPE_OPUS",
                            "opus": {
                                "opus_id": "987654",
                                "title": "图文标题",
                                "summary": {"text": "图文正文"},
                            },
                        },
                    },
                },
            },
        )

        self.assertIsNotNone(snapshot)
        self.assertEqual(snapshot.published_at, datetime.fromtimestamp(1779252100))

    def test_bilibili_adapter_accepts_string_article_publish_timestamp(self) -> None:
        published_at = BilibiliVideoSourceAdapter._published_at_from_article_item(
            {"basic": {"pub_ts": "1779252200"}},
            {},
            {},
            {},
            {},
        )

        self.assertEqual(published_at, datetime.fromtimestamp(1779252200))

    def test_scan_sources_inserts_new_videos_once(self) -> None:
        service = VideoInformationService(self.db)
        source = service.create_source(
            VideoSourceCreate(
                platform="bilibili",
                source_name="测试账号",
                external_source_id="12345",
            )
        )
        adapter = Mock()
        adapter.normalize_source_id.side_effect = lambda value: value
        adapter.fetch_latest_videos.return_value = [
            VideoSnapshot(
                platform="bilibili",
                external_video_id="BV1xx",
                title="测试视频",
                video_url="https://www.bilibili.com/video/BV1xx",
                author_name="测试账号",
                published_at=datetime(2026, 5, 18, 10, 0, 0),
                raw_response={"bvid": "BV1xx"},
            )
        ]

        with patch(
            "app.modules.information.services.video_information_service.get_video_source_adapter",
            return_value=adapter,
        ):
            first_count = service.scan_sources(source_id=source.id)
            second_count = service.scan_sources(source_id=source.id)

        self.assertEqual(first_count, 1)
        self.assertEqual(second_count, 0)
        self.assertEqual(self.db.query(InformationVideo).count(), 1)

    def test_article_note_uses_hermes_without_settings_instruction(self) -> None:
        service = VideoInformationService(self.db)
        InformationSettingsService(self.db).update_settings({"hermes_summary_instruction": "系统设置里的笔记汇总说明"})
        source = service.create_source(
            VideoSourceCreate(
                platform="bilibili",
                source_name="皓哥论股",
                external_source_id="307610125",
            )
        )
        adapter = Mock()
        adapter.normalize_source_id.side_effect = lambda value: value
        adapter.fetch_latest_videos.return_value = [
            VideoSnapshot(
                platform="bilibili",
                external_video_id="article_987654",
                title="今天市场观察",
                video_url="https://www.bilibili.com/opus/987654",
                author_name="皓哥论股",
                published_at=datetime(2026, 5, 20, 10, 0, 0),
                raw_response={"id_str": "987654"},
                content_type="article",
                content_text="核心观点：控制仓位。",
            )
        ]
        hermes = Mock()
        hermes.start_run.return_value = HermesRunResult(
            run_id="run-article",
            status="running",
            document_text=None,
            raw_response={"id": "run-article", "status": "running"},
        )

        with patch(
            "app.modules.information.services.video_information_service.get_video_source_adapter",
            return_value=adapter,
        ), patch(
            "app.modules.information.services.video_information_service.HermesClient",
            return_value=hermes,
        ):
            created = service.scan_sources(source_id=source.id)
            result = service.submit_pending_note_task()

        self.assertEqual(created, 1)
        self.assertEqual(result["started"], 1)
        article = self.db.query(InformationVideo).one()
        self.assertEqual(article.content_type, "article")
        self.assertEqual(article.status, "note_running")
        self.assertEqual(self.db.query(InformationSummaryDocument).count(), 0)
        note = self.db.query(InformationVideoNote).one()
        self.assertEqual(note.provider, "hermes")
        self.assertEqual(note.status, "running")
        self.assertEqual(note.external_task_id, "run-article")
        prompt = hermes.start_run.call_args.args[0]
        self.assertIn("B站图文投稿", prompt)
        self.assertIn("核心观点：控制仓位。", prompt)
        self.assertNotIn("系统设置里的笔记汇总说明", prompt)

    def test_article_note_retry_reuses_failed_note(self) -> None:
        service = VideoInformationService(self.db)
        source = service.create_source(
            VideoSourceCreate(
                platform="bilibili",
                source_name="皓哥论股",
                external_source_id="307610125",
            )
        )
        article = InformationVideo(
            source_id=source.id,
            platform="bilibili",
            external_video_id="article_retry",
            title="重试图文",
            video_url="https://www.bilibili.com/opus/article_retry",
            content_type="article",
            content_text="核心观点：等待确认。",
            status="note_failed",
        )
        self.db.add(article)
        self.db.commit()
        failed_note = InformationVideoNote(
            video_id=article.id,
            provider="hermes",
            status="failed",
            error_message="上次失败",
            external_task_id="old-run",
        )
        self.db.add(failed_note)
        self.db.commit()
        hermes = Mock()
        hermes.start_run.return_value = HermesRunResult(
            run_id="new-run",
            status="running",
            document_text=None,
            raw_response={"id": "new-run", "status": "running"},
        )

        with patch(
            "app.modules.information.services.video_information_service.HermesClient",
            return_value=hermes,
        ):
            result = service.submit_pending_article_note_task(video_ids=[article.id])

        self.assertEqual(result["started"], 1)
        self.assertEqual(result["note_id"], failed_note.id)
        self.assertEqual(self.db.query(InformationVideoNote).filter_by(video_id=article.id).count(), 1)
        self.db.refresh(failed_note)
        self.assertEqual(failed_note.status, "running")
        self.assertEqual(failed_note.external_task_id, "new-run")
        self.assertIsNone(failed_note.error_message)

    def test_scan_sources_can_target_selected_sources(self) -> None:
        service = VideoInformationService(self.db)
        first_source = service.create_source(
            VideoSourceCreate(
                platform="bilibili",
                source_name="账号一",
                external_source_id="111",
            )
        )
        second_source = service.create_source(
            VideoSourceCreate(
                platform="bilibili",
                source_name="账号二",
                external_source_id="222",
            )
        )
        adapter = Mock()
        adapter.normalize_source_id.side_effect = lambda value: value
        adapter.fetch_latest_videos.return_value = [
            VideoSnapshot(
                platform="bilibili",
                external_video_id="BV-selected",
                title="选中账号视频",
                video_url="https://www.bilibili.com/video/BV-selected",
                author_name="账号二",
                published_at=datetime(2026, 5, 18, 10, 0, 0),
                raw_response={"bvid": "BV-selected"},
            )
        ]

        with patch(
            "app.modules.information.services.video_information_service.get_video_source_adapter",
            return_value=adapter,
        ):
            created_count = service.scan_sources(source_ids=[second_source.id])

        self.assertEqual(created_count, 1)
        adapter.fetch_latest_videos.assert_called_once()
        self.assertEqual(adapter.fetch_latest_videos.call_args.args[0].id, second_source.id)
        self.assertNotEqual(adapter.fetch_latest_videos.call_args.args[0].id, first_source.id)

    def test_scan_next_source_scans_only_one_oldest_enabled_source(self) -> None:
        service = VideoInformationService(self.db)
        first_source = service.create_source(
            VideoSourceCreate(
                platform="bilibili",
                source_name="账号一",
                external_source_id="111",
            )
        )
        second_source = service.create_source(
            VideoSourceCreate(
                platform="bilibili",
                source_name="账号二",
                external_source_id="222",
            )
        )
        first_source.last_scanned_at = datetime(2026, 5, 18, 10, 0, 0)
        second_source.last_scanned_at = datetime(2026, 5, 17, 10, 0, 0)
        self.db.commit()
        adapter = Mock()
        adapter.normalize_source_id.side_effect = lambda value: value
        adapter.fetch_latest_videos.return_value = [
            VideoSnapshot(
                platform="bilibili",
                external_video_id="BV-next",
                title="轮询账号视频",
                video_url="https://www.bilibili.com/video/BV-next",
                author_name="账号二",
                published_at=datetime(2026, 5, 18, 10, 0, 0),
                raw_response={"bvid": "BV-next"},
            )
        ]

        with patch(
            "app.modules.information.services.video_information_service.get_video_source_adapter",
            return_value=adapter,
        ):
            result = service.scan_next_source()

        self.assertEqual(result, {"source_id": second_source.id, "created": 1})
        adapter.fetch_latest_videos.assert_called_once()
        self.assertEqual(adapter.fetch_latest_videos.call_args.args[0].id, second_source.id)

    def test_failed_scan_updates_last_scanned_at_to_avoid_immediate_retry_loop(self) -> None:
        service = VideoInformationService(self.db)
        source = service.create_source(
            VideoSourceCreate(
                platform="bilibili",
                source_name="风控账号",
                external_source_id="333",
            )
        )
        adapter = Mock()
        adapter.normalize_source_id.side_effect = lambda value: value
        adapter.fetch_latest_videos.side_effect = RuntimeError("Bilibili API returned code=-799")

        with patch(
            "app.modules.information.services.video_information_service.get_video_source_adapter",
            return_value=adapter,
        ), patch(
            "app.modules.information.services.video_information_service.log_fetch_error",
        ):
            created = service.scan_sources(source_id=source.id)

        self.assertEqual(created, 0)
        self.db.refresh(source)
        self.assertIsNotNone(source.last_scanned_at)

    def test_generate_notes_requires_bilinote_provider_and_model(self) -> None:
        source = InformationVideoSource(
            platform="bilibili",
            source_name="测试账号",
            external_source_id="12345",
            enabled=1,
        )
        self.db.add(source)
        self.db.commit()
        self.db.add(
            InformationVideo(
                source_id=source.id,
                platform="bilibili",
                external_video_id="BV2xx",
                title="待总结视频",
                video_url="https://www.bilibili.com/video/BV2xx",
                status="note_pending",
            )
        )
        self.db.commit()

        with self.assertRaises(ValueError):
            VideoInformationService(self.db).generate_pending_notes()

    def test_submit_pending_note_task_returns_error_message_when_bilinote_fails(self) -> None:
        InformationSettingsService(self.db).update_settings(
            {
                "bilinote_provider_id": "provider-1",
                "bilinote_model_name": "model-1",
            }
        )
        source = InformationVideoSource(
            platform="bilibili",
            source_name="测试账号",
            external_source_id="12345",
            enabled=1,
        )
        self.db.add(source)
        self.db.commit()
        self.db.add(
            InformationVideo(
                source_id=source.id,
                platform="bilibili",
                external_video_id="BV-error-message",
                title="失败信息视频",
                video_url="https://www.bilibili.com/video/BV-error-message",
                status="note_pending",
            )
        )
        self.db.commit()
        client = Mock()
        client.generate_note.side_effect = RuntimeError("bilinote unavailable")

        with patch(
            "app.modules.information.services.video_information_service.BilinoteClient",
            return_value=client,
        ), patch(
            "app.modules.information.services.video_information_service.log_fetch_error",
        ):
            result = VideoInformationService(self.db).submit_pending_note_task()

        self.assertEqual(result["failed"], 1)
        self.assertIn("bilinote unavailable", str(result["error_message"]))

    def test_submit_pending_note_task_reuses_failed_note_on_retry(self) -> None:
        InformationSettingsService(self.db).update_settings(
            {
                "bilinote_provider_id": "provider-1",
                "bilinote_model_name": "model-1",
            }
        )
        source = InformationVideoSource(
            platform="bilibili",
            source_name="测试账号",
            external_source_id="12345",
            enabled=1,
        )
        self.db.add(source)
        self.db.commit()
        video = InformationVideo(
            source_id=source.id,
            platform="bilibili",
            external_video_id="BV-retry-note",
            title="重试视频",
            video_url="https://www.bilibili.com/video/BV-retry-note",
            status="note_failed",
        )
        self.db.add(video)
        self.db.commit()
        failed_note = InformationVideoNote(
            video_id=video.id,
            provider="bilinote",
            status="failed",
            error_message="上次失败",
            raw_response='{"old": true}',
            external_task_id="old-task",
        )
        self.db.add(failed_note)
        self.db.commit()
        client = Mock()
        client.generate_note.return_value = Mock(
            task_id="new-task",
            note_text=None,
            raw_response={"task_id": "new-task", "status": "running"},
            error_message=None,
        )

        with patch(
            "app.modules.information.services.video_information_service.BilinoteClient",
            return_value=client,
        ):
            result = VideoInformationService(self.db).submit_pending_note_task(video_ids=[video.id])

        self.assertEqual(result["started"], 1)
        self.assertEqual(result["note_id"], failed_note.id)
        self.assertEqual(self.db.query(InformationVideoNote).filter_by(video_id=video.id).count(), 1)
        self.db.refresh(failed_note)
        self.assertEqual(failed_note.status, "running")
        self.assertEqual(failed_note.external_task_id, "new-task")
        self.assertIsNone(failed_note.error_message)

    def test_bilinote_client_reads_nested_taskid_from_generate_response(self) -> None:
        response = Mock()
        response.json.return_value = {"data": {"taskid": "bilinote-task-1", "status": "running"}}

        with patch("app.modules.information.services.bilinote_client.requests.post", return_value=response):
            result = BilinoteClient("http://bilinote.local").generate_note(
                "https://www.bilibili.com/video/BV-task",
                "bilibili",
                "fast",
                "model-1",
                "provider-1",
            )

        self.assertEqual(result.task_id, "bilinote-task-1")

    def test_bilinote_client_reads_nested_status_and_markdown_from_task_status(self) -> None:
        response = Mock()
        response.json.return_value = {
            "code": 0,
            "msg": "success",
            "data": {
                "status": "SUCCESS",
                "result": {
                    "markdown": "这是一段 Bilinote 总结。",
                },
            },
        }

        with patch("app.modules.information.services.bilinote_client.requests.get", return_value=response):
            result = BilinoteClient("http://bilinote.local").poll_task_once("task-1")

        self.assertEqual(result.status, "done")
        self.assertEqual(result.note_text, "这是一段 Bilinote 总结。")

    def test_poll_running_notes_returns_error_message_when_external_task_fails(self) -> None:
        source = InformationVideoSource(
            platform="bilibili",
            source_name="测试账号",
            external_source_id="12345",
            enabled=1,
        )
        self.db.add(source)
        self.db.commit()
        video = InformationVideo(
            source_id=source.id,
            platform="bilibili",
            external_video_id="BV-poll-failed",
            title="轮询失败视频",
            video_url="https://www.bilibili.com/video/BV-poll-failed",
            status="note_running",
        )
        self.db.add(video)
        self.db.commit()
        note = InformationVideoNote(
            video_id=video.id,
            provider="bilinote",
            external_task_id="task-failed",
            status="running",
        )
        self.db.add(note)
        self.db.commit()
        client = Mock()
        client.poll_task_once.return_value = Mock(
            task_id="task-failed",
            status="failed",
            note_text=None,
            raw_response={"status": "failed", "error": "Bilinote 外部失败"},
            error_message="Bilinote 外部失败",
        )

        with patch(
            "app.modules.information.services.video_information_service.BilinoteClient",
            return_value=client,
        ):
            result = VideoInformationService(self.db).poll_running_notes(video_ids=[video.id])

        self.assertEqual(result["failed"], 1)
        self.assertEqual(result["error_message"], "Bilinote 外部失败")
        self.db.refresh(note)
        self.assertEqual(note.status, "failed")
        self.assertEqual(note.error_message, "Bilinote 外部失败")

    def test_bilinote_client_normalizes_escaped_ordered_list_markers(self) -> None:
        response = Mock()
        response.json.return_value = {
            "data": {
                "status": "SUCCESS",
                "result": {
                    "markdown": "盘面特征：\n    1\\. 阴线实体变小。\n    2\\. 成交量萎缩。\n\n### 1\\. 证券",
                },
            },
        }

        with patch("app.modules.information.services.bilinote_client.requests.get", return_value=response):
            result = BilinoteClient("http://bilinote.local").poll_task_once("task-escaped-list")

        self.assertEqual(result.status, "done")
        self.assertIn("    1. 阴线实体变小。", result.note_text or "")
        self.assertIn("### 1. 证券", result.note_text or "")
        self.assertNotIn("1\\.", result.note_text or "")

    def test_hermes_client_supports_configurable_auth_header(self) -> None:
        auth_response = Mock()
        auth_response.json.return_value = {"id": "run-auth", "document": "ok"}
        key_response = Mock()
        key_response.json.return_value = {"id": "run-key", "document": "ok"}

        with patch("app.modules.information.services.hermes_client.requests.post", return_value=auth_response) as post:
            HermesClient("http://hermes.local", api_key="secret").start_run("prompt", "title")

        self.assertEqual(post.call_args.kwargs["headers"], {"Authorization": "Bearer secret"})

        with patch("app.modules.information.services.hermes_client.requests.post", return_value=key_response) as post:
            HermesClient(
                "http://hermes.local",
                api_key="secret",
                auth_header_name="X-API-Key",
            ).start_run("prompt", "title")

        self.assertEqual(post.call_args.kwargs["headers"], {"X-API-Key": "secret"})

    def test_hermes_client_uses_runs_api_without_fallback(self) -> None:
        response = Mock()
        response.status_code = 405
        response.raise_for_status.side_effect = RuntimeError("405")

        with patch("app.modules.information.services.hermes_client.requests.post", return_value=response) as post:
            with self.assertRaises(RuntimeError):
                HermesClient("http://hermes.local", run_path="/v1/runs").start_run("prompt", "title")

        post.assert_called_once()
        self.assertEqual(post.call_args.args[0], "http://hermes.local/v1/runs")
        self.assertEqual(
            post.call_args.kwargs["json"],
            {"model": "hermes-agent", "input": "prompt", "instructions": "title"},
        )

    def test_wechat_push_client_sends_markdown_format_payload(self) -> None:
        response = Mock()
        response.json.return_value = {"ok": True, "sent": 1}

        with patch("app.modules.information.services.wechat_push_client.requests.post", return_value=response) as post:
            WechatPushClient("http://wechat.local/api/wechat/push").push_summary(
                title="每日汇总",
                content="## 要点\n- 内容",
                summary_date="2026-05-19",
                platform="bilibili",
                document_id=12,
            )

        post.assert_called_once()
        self.assertEqual(
            post.call_args.kwargs["json"],
            {
                "text": "# 每日汇总\n\n## 要点\n- 内容",
                "format_markdown": True,
            },
        )

    def test_list_videos_filters_and_orders_by_published_at_desc(self) -> None:
        first_source = InformationVideoSource(
            platform="bilibili",
            source_name="账号一",
            external_source_id="111",
            enabled=1,
        )
        second_source = InformationVideoSource(
            platform="bilibili",
            source_name="账号二",
            external_source_id="222",
            enabled=1,
        )
        self.db.add_all([first_source, second_source])
        self.db.commit()
        old_video = InformationVideo(
            source_id=first_source.id,
            platform="bilibili",
            external_video_id="BV-old",
            title="旧视频",
            video_url="https://www.bilibili.com/video/BV-old",
            published_at=datetime(2026, 5, 10, 10, 0, 0),
            status="note_pending",
        )
        latest_video = InformationVideo(
            source_id=first_source.id,
            platform="bilibili",
            external_video_id="BV-latest",
            title="新视频",
            video_url="https://www.bilibili.com/video/BV-latest",
            published_at=datetime(2026, 5, 18, 10, 0, 0),
            status="note_pending",
        )
        failed_video = InformationVideo(
            source_id=second_source.id,
            platform="bilibili",
            external_video_id="BV-failed",
            title="失败视频",
            video_url="https://www.bilibili.com/video/BV-failed",
            published_at=datetime(2026, 5, 17, 10, 0, 0),
            status="note_failed",
        )
        self.db.add_all([old_video, latest_video, failed_video])
        self.db.commit()

        videos = VideoInformationService(self.db).list_videos(
            source_id=first_source.id,
            status="note_pending",
            published_from=date(2026, 5, 15),
        )

        self.assertEqual([video.external_video_id for video in videos], ["BV-latest"])

        videos_by_id = VideoInformationService(self.db).list_videos(video_id=failed_video.id)

        self.assertEqual([video.external_video_id for video in videos_by_id], ["BV-failed"])

    def test_generate_notes_can_target_selected_videos(self) -> None:
        InformationSettingsService(self.db).update_settings(
            {
                "bilinote_provider_id": "provider-1",
                "bilinote_model_name": "model-1",
                "bilinote_quality": "fast",
            }
        )
        source = InformationVideoSource(
            platform="bilibili",
            source_name="测试账号",
            external_source_id="12345",
            enabled=1,
        )
        self.db.add(source)
        self.db.commit()
        first_video = InformationVideo(
            source_id=source.id,
            platform="bilibili",
            external_video_id="BV-first",
            title="不生成的视频",
            video_url="https://www.bilibili.com/video/BV-first",
            status="note_pending",
        )
        second_video = InformationVideo(
            source_id=source.id,
            platform="bilibili",
            external_video_id="BV-second",
            title="生成的视频",
            video_url="https://www.bilibili.com/video/BV-second",
            status="note_pending",
        )
        self.db.add_all([first_video, second_video])
        self.db.commit()
        bilinote = Mock()
        bilinote.generate_note.return_value = Mock(
            task_id="task-1",
            status="done",
            note_text="选中视频总结",
            raw_response={"task_id": "task-1", "note": "选中视频总结"},
        )

        with patch(
            "app.modules.information.services.video_information_service.BilinoteClient",
            return_value=bilinote,
        ):
            result = VideoInformationService(self.db).generate_pending_notes(video_ids=[second_video.id])

        self.assertEqual(result["completed"], 1)
        self.assertEqual(result["failed"], 0)
        self.assertEqual(result["running"], 0)
        self.db.refresh(first_video)
        self.db.refresh(second_video)
        self.assertEqual(first_video.status, "note_pending")
        self.assertEqual(second_video.status, "note_done")

    def test_generate_notes_skips_videos_outside_recent_day_window(self) -> None:
        InformationSettingsService(self.db).update_settings(
            {
                "bilinote_provider_id": "provider-1",
                "bilinote_model_name": "model-1",
                "bilinote_quality": "fast",
                "video_note_recent_days": "3",
            }
        )
        source = InformationVideoSource(
            platform="bilibili",
            source_name="测试账号",
            external_source_id="12345",
            enabled=1,
        )
        self.db.add(source)
        self.db.commit()
        old_video = InformationVideo(
            source_id=source.id,
            platform="bilibili",
            external_video_id="BV-old-note-window",
            title="过期视频",
            video_url="https://www.bilibili.com/video/BV-old-note-window",
            published_at=datetime.now() - timedelta(days=10),
            status="note_pending",
        )
        self.db.add(old_video)
        self.db.commit()
        bilinote = Mock()

        with patch(
            "app.modules.information.services.video_information_service.BilinoteClient",
            return_value=bilinote,
        ):
            result = VideoInformationService(self.db).generate_pending_notes(limit=5)

        self.assertEqual(result["total"], 0)
        bilinote.generate_note.assert_not_called()
        self.db.refresh(old_video)
        self.assertEqual(old_video.status, "note_pending")

    def test_generate_notes_keeps_running_task_waiting(self) -> None:
        InformationSettingsService(self.db).update_settings(
            {
                "bilinote_provider_id": "provider-1",
                "bilinote_model_name": "model-1",
                "bilinote_quality": "fast",
            }
        )
        source = InformationVideoSource(
            platform="bilibili",
            source_name="测试账号",
            external_source_id="12345",
            enabled=1,
        )
        self.db.add(source)
        self.db.commit()
        video = InformationVideo(
            source_id=source.id,
            platform="bilibili",
            external_video_id="BV-running",
            title="运行中的视频",
            video_url="https://www.bilibili.com/video/BV-running",
            status="note_pending",
        )
        self.db.add(video)
        self.db.commit()
        bilinote = Mock()
        bilinote.generate_note.return_value = Mock(
            task_id="task-running",
            status="running",
            note_text=None,
            raw_response={"task_id": "task-running", "status": "running"},
            error_message=None,
        )
        bilinote.poll_task_once.return_value = Mock(
            task_id="task-running",
            status="running",
            note_text=None,
            raw_response={"task_id": "task-running", "status": "running"},
            error_message=None,
        )

        with patch(
            "app.modules.information.services.video_information_service.BilinoteClient",
            return_value=bilinote,
        ):
            result = VideoInformationService(self.db).generate_pending_notes(video_ids=[video.id])

        self.assertEqual(result["completed"], 0)
        self.assertEqual(result["failed"], 0)
        self.assertEqual(result["running"], 1)
        self.db.refresh(video)
        note = self.db.query(InformationVideoNote).filter_by(video_id=video.id).one()
        self.assertEqual(video.status, "note_running")
        self.assertEqual(note.status, "running")
        self.assertEqual(note.external_task_id, "task-running")

    def test_generate_notes_starts_only_one_bilinote_task_at_a_time(self) -> None:
        InformationSettingsService(self.db).update_settings(
            {
                "bilinote_provider_id": "provider-1",
                "bilinote_model_name": "model-1",
                "bilinote_quality": "fast",
            }
        )
        source = InformationVideoSource(
            platform="bilibili",
            source_name="测试账号",
            external_source_id="12345",
            enabled=1,
        )
        self.db.add(source)
        self.db.commit()
        first_video = InformationVideo(
            source_id=source.id,
            platform="bilibili",
            external_video_id="BV-one",
            title="第一个视频",
            video_url="https://www.bilibili.com/video/BV-one",
            status="note_pending",
        )
        second_video = InformationVideo(
            source_id=source.id,
            platform="bilibili",
            external_video_id="BV-two",
            title="第二个视频",
            video_url="https://www.bilibili.com/video/BV-two",
            status="note_pending",
        )
        self.db.add_all([first_video, second_video])
        self.db.commit()
        bilinote = Mock()
        bilinote.generate_note.return_value = Mock(
            task_id="task-one",
            status="running",
            note_text=None,
            raw_response={"task_id": "task-one", "status": "running"},
            error_message=None,
        )
        bilinote.poll_task_once.return_value = Mock(
            task_id="task-one",
            status="running",
            note_text=None,
            raw_response={"task_id": "task-one", "status": "running"},
            error_message=None,
        )

        with patch(
            "app.modules.information.services.video_information_service.BilinoteClient",
            return_value=bilinote,
        ):
            result = VideoInformationService(self.db).generate_pending_notes(limit=5)

        self.assertEqual(result["running"], 1)
        bilinote.generate_note.assert_called_once()
        self.db.refresh(first_video)
        self.db.refresh(second_video)
        self.assertEqual(
            len([video for video in (first_video, second_video) if video.status == "note_running"]),
            1,
        )
        self.assertEqual(
            len([video for video in (first_video, second_video) if video.status == "note_pending"]),
            1,
        )

    def test_generate_notes_does_not_submit_new_task_while_one_is_running(self) -> None:
        InformationSettingsService(self.db).update_settings(
            {
                "bilinote_provider_id": "provider-1",
                "bilinote_model_name": "model-1",
                "bilinote_quality": "fast",
            }
        )
        source = InformationVideoSource(
            platform="bilibili",
            source_name="测试账号",
            external_source_id="12345",
            enabled=1,
        )
        self.db.add(source)
        self.db.commit()
        running_video = InformationVideo(
            source_id=source.id,
            platform="bilibili",
            external_video_id="BV-running",
            title="运行中视频",
            video_url="https://www.bilibili.com/video/BV-running",
            status="note_running",
        )
        pending_video = InformationVideo(
            source_id=source.id,
            platform="bilibili",
            external_video_id="BV-pending",
            title="等待视频",
            video_url="https://www.bilibili.com/video/BV-pending",
            status="note_pending",
        )
        self.db.add_all([running_video, pending_video])
        self.db.commit()
        self.db.add(
            InformationVideoNote(
                video_id=running_video.id,
                provider="bilinote",
                external_task_id="task-running",
                status="running",
            )
        )
        self.db.commit()
        bilinote = Mock()
        bilinote.poll_task_once.return_value = Mock(
            task_id="task-running",
            status="running",
            note_text=None,
            raw_response={"task_id": "task-running", "status": "running"},
            error_message=None,
        )

        with patch(
            "app.modules.information.services.video_information_service.BilinoteClient",
            return_value=bilinote,
        ):
            result = VideoInformationService(self.db).generate_pending_notes(limit=5)

        self.assertEqual(result["running"], 1)
        bilinote.generate_note.assert_not_called()
        self.db.refresh(pending_video)
        self.assertEqual(pending_video.status, "note_pending")

    def test_mark_video_notes_failed_updates_video_and_note(self) -> None:
        source = InformationVideoSource(
            platform="bilibili",
            source_name="测试账号",
            external_source_id="12345",
            enabled=1,
        )
        self.db.add(source)
        self.db.commit()
        video = InformationVideo(
            source_id=source.id,
            platform="bilibili",
            external_video_id="BV-manual-failed",
            title="手动失败视频",
            video_url="https://www.bilibili.com/video/BV-manual-failed",
            status="note_running",
        )
        self.db.add(video)
        self.db.commit()

        count = VideoInformationService(self.db).mark_video_notes_failed([video.id], "人工终止")

        self.assertEqual(count, 1)
        self.db.refresh(video)
        note = self.db.query(InformationVideoNote).filter_by(video_id=video.id).one()
        self.assertEqual(video.status, "note_failed")
        self.assertEqual(note.status, "failed")
        self.assertEqual(note.error_message, "人工终止")

    def test_note_detail_omits_raw_response_and_raw_endpoint_loads_it(self) -> None:
        source = InformationVideoSource(
            platform="bilibili",
            source_name="测试账号",
            external_source_id="12345",
            enabled=1,
        )
        self.db.add(source)
        self.db.commit()
        video = InformationVideo(
            source_id=source.id,
            platform="bilibili",
            external_video_id="BV-raw",
            title="Raw 测试视频",
            video_url="https://www.bilibili.com/video/BV-raw",
            status="note_done",
        )
        self.db.add(video)
        self.db.commit()
        note = InformationVideoNote(
            video_id=video.id,
            provider="bilinote",
            status="done",
            note_text="正文",
            raw_response='{"large": true}',
            generated_at=datetime.now(),
        )
        self.db.add(note)
        self.db.commit()

        service = VideoInformationService(self.db)
        detail = service.get_note_detail(note.id)
        raw = service.get_note_raw_response(note.id)

        self.assertIsNotNone(detail)
        self.assertNotIn("raw_response", detail or {})
        self.assertEqual(raw, {"id": note.id, "raw_response": '{"large": true}'})

    def test_list_notes_includes_video_title(self) -> None:
        source = InformationVideoSource(
            platform="bilibili",
            source_name="测试账号",
            external_source_id="12345",
            enabled=1,
        )
        self.db.add(source)
        self.db.commit()
        video = InformationVideo(
            source_id=source.id,
            platform="bilibili",
            external_video_id="BV-note-title",
            title="带标题的视频",
            video_url="https://www.bilibili.com/video/BV-note-title",
            published_at=datetime(2026, 5, 19, 10, 30, 0),
            status="note_done",
        )
        self.db.add(video)
        self.db.commit()
        note = InformationVideoNote(
            video_id=video.id,
            provider="bilinote",
            status="done",
            note_text="正文",
            generated_at=datetime.now(),
        )
        self.db.add(note)
        self.db.commit()

        notes = VideoInformationService(self.db).list_notes()

        self.assertEqual(notes[0]["video_title"], "带标题的视频")
        self.assertEqual(notes[0]["video_id"], video.id)
        self.assertEqual(notes[0]["source_id"], source.id)
        self.assertEqual(notes[0]["source_name"], "测试账号")
        self.assertEqual(notes[0]["video_published_at"], datetime(2026, 5, 19, 10, 30, 0))
        self.assertEqual(notes[0]["video_url"], "https://www.bilibili.com/video/BV-note-title")

    def test_list_sources_includes_video_and_note_counts(self) -> None:
        source = InformationVideoSource(
            platform="bilibili",
            source_name="测试账号",
            external_source_id="12345",
            enabled=1,
        )
        self.db.add(source)
        self.db.commit()
        video = InformationVideo(
            source_id=source.id,
            platform="bilibili",
            external_video_id="BV-source-count",
            title="计数视频",
            video_url="https://www.bilibili.com/video/BV-source-count",
            status="note_done",
        )
        self.db.add(video)
        self.db.commit()
        self.db.add_all(
            [
                InformationVideoNote(
                    video_id=video.id,
                    provider="bilinote",
                    status="done",
                    note_text="正文",
                    generated_at=datetime.now(),
                ),
                InformationVideoNote(
                    video_id=video.id,
                    provider="bilinote",
                    status="failed",
                    error_message="失败",
                ),
                InformationVideoNote(
                    video_id=video.id,
                    provider="bilinote",
                    status="running",
                ),
            ]
        )
        self.db.commit()

        sources = VideoInformationService(self.db).list_sources()

        self.assertEqual(sources[0]["video_count"], 1)
        self.assertEqual(sources[0]["note_count"], 1)

    def test_list_notes_can_filter_by_source(self) -> None:
        first_source = InformationVideoSource(
            platform="bilibili",
            source_name="账号一",
            external_source_id="111",
            enabled=1,
        )
        second_source = InformationVideoSource(
            platform="bilibili",
            source_name="账号二",
            external_source_id="222",
            enabled=1,
        )
        self.db.add_all([first_source, second_source])
        self.db.commit()
        first_video = InformationVideo(
            source_id=first_source.id,
            platform="bilibili",
            external_video_id="BV-note-first",
            title="账号一视频",
            video_url="https://www.bilibili.com/video/BV-note-first",
            status="note_done",
        )
        second_video = InformationVideo(
            source_id=second_source.id,
            platform="bilibili",
            external_video_id="BV-note-second",
            title="账号二视频",
            video_url="https://www.bilibili.com/video/BV-note-second",
            status="note_done",
        )
        self.db.add_all([first_video, second_video])
        self.db.commit()
        self.db.add_all(
            [
                InformationVideoNote(video_id=first_video.id, provider="bilinote", status="done", note_text="一"),
                InformationVideoNote(video_id=second_video.id, provider="bilinote", status="done", note_text="二"),
            ]
        )
        self.db.commit()

        notes = VideoInformationService(self.db).list_notes(source_id=second_source.id)

        self.assertEqual([note["source_name"] for note in notes], ["账号二"])

        filtered_by_date = VideoInformationService(self.db).list_notes(
            published_from=date(2026, 5, 19),
            published_to=date(2026, 5, 19),
        )

        self.assertEqual(filtered_by_date, [])

    def test_daily_summary_submits_hermes_run_and_saves_document(self) -> None:
        InformationSettingsService(self.db).update_settings(
            {
                "hermes_base_url": "http://hermes.local",
                "hermes_run_path": "/api/runs",
                "hermes_status_path_template": "/api/runs/{run_id}",
            }
        )
        source = InformationVideoSource(
            platform="bilibili",
            source_name="测试账号",
            external_source_id="12345",
            enabled=1,
        )
        self.db.add(source)
        self.db.commit()
        video = InformationVideo(
            source_id=source.id,
            platform="bilibili",
            external_video_id="BV3xx",
            title="已总结视频",
            video_url="https://www.bilibili.com/video/BV3xx",
            published_at=datetime.combine(date.today(), datetime.min.time()),
            status="note_done",
        )
        self.db.add(video)
        self.db.commit()
        self.db.add(
            InformationVideoNote(
                video_id=video.id,
                provider="bilinote",
                status="done",
                note_text="这是一段视频总结。",
                generated_at=datetime.now(),
            )
        )
        self.db.commit()
        hermes = Mock()
        hermes.start_run.return_value = HermesRunResult(
            run_id="run-1",
            status="running",
            document_text=None,
            raw_response={"id": "run-1", "status": "running"},
        )

        with patch(
            "app.modules.information.services.video_information_service.HermesClient",
            return_value=hermes,
        ):
            document = VideoInformationService(self.db).create_daily_summary()

        self.assertIsNotNone(document)
        self.assertEqual(document.status, "running")
        self.assertEqual(document.hermes_run_id, "run-1")
        self.assertIsNone(document.document_text)
        self.assertEqual(self.db.query(InformationSummaryDocumentItem).count(), 1)
        hermes.poll_run_once.assert_not_called()

    def test_custom_summary_uses_selected_done_notes(self) -> None:
        InformationSettingsService(self.db).update_settings(
            {
                "hermes_base_url": "http://hermes.local",
                "hermes_run_path": "/api/runs",
                "hermes_status_path_template": "/api/runs/{run_id}",
            }
        )
        source = InformationVideoSource(
            platform="bilibili",
            source_name="测试账号",
            external_source_id="12345",
            enabled=1,
        )
        self.db.add(source)
        self.db.commit()
        video = InformationVideo(
            source_id=source.id,
            platform="bilibili",
            external_video_id="BV-custom",
            title="自定义汇总视频",
            video_url="https://www.bilibili.com/video/BV-custom",
            status="note_done",
        )
        self.db.add(video)
        self.db.commit()
        done_note = InformationVideoNote(
            video_id=video.id,
            provider="bilinote",
            status="done",
            note_text="自定义汇总输入",
            generated_at=datetime.now(),
        )
        failed_note = InformationVideoNote(
            video_id=video.id,
            provider="bilinote",
            status="failed",
            note_text="不应进入汇总",
        )
        self.db.add_all([done_note, failed_note])
        self.db.commit()
        hermes = Mock()
        hermes.start_run.return_value = HermesRunResult(
            run_id="run-custom",
            status="running",
            document_text=None,
            raw_response={"id": "run-custom", "status": "running"},
        )

        with patch(
            "app.modules.information.services.video_information_service.HermesClient",
            return_value=hermes,
        ):
            document = VideoInformationService(self.db).create_custom_summary([done_note.id, failed_note.id])

        self.assertEqual(document.status, "running")
        self.assertTrue(document.platform.startswith("custom_"))
        self.assertEqual(document.hermes_run_id, "run-custom")
        self.assertIsNone(document.document_text)
        self.assertEqual(
            self.db.query(InformationSummaryDocumentItem).filter_by(document_id=document.id).count(),
            1,
        )

    def test_custom_summary_can_use_user_title(self) -> None:
        source = InformationVideoSource(
            platform="bilibili",
            source_name="测试账号",
            external_source_id="12345",
            enabled=1,
        )
        self.db.add(source)
        self.db.commit()
        video = InformationVideo(
            source_id=source.id,
            platform="bilibili",
            external_video_id="BV-custom-title",
            title="自定义标题视频",
            video_url="https://www.bilibili.com/video/BV-custom-title",
            status="note_done",
        )
        self.db.add(video)
        self.db.commit()
        note = InformationVideoNote(
            video_id=video.id,
            provider="bilinote",
            status="done",
            note_text="正文",
            generated_at=datetime.now(),
        )
        self.db.add(note)
        self.db.commit()
        hermes = Mock()
        hermes.start_run.return_value = HermesRunResult(
            run_id="run-custom-title",
            status="running",
            document_text=None,
            raw_response={"id": "run-custom-title"},
        )

        with patch(
            "app.modules.information.services.video_information_service.HermesClient",
            return_value=hermes,
        ):
            document = VideoInformationService(self.db).create_custom_summary([note.id], title="我的汇总名称")

        self.assertEqual(document.title, "我的汇总名称")

    def test_retry_custom_summary_can_recover_notes_from_task_log(self) -> None:
        source = InformationVideoSource(
            platform="bilibili",
            source_name="测试账号",
            external_source_id="12345",
            enabled=1,
        )
        self.db.add(source)
        self.db.commit()
        video = InformationVideo(
            source_id=source.id,
            platform="bilibili",
            external_video_id="BV-retry-custom",
            title="历史失败自定义汇总视频",
            video_url="https://www.bilibili.com/video/BV-retry-custom",
            status="note_done",
        )
        self.db.add(video)
        self.db.commit()
        note = InformationVideoNote(
            video_id=video.id,
            provider="bilinote",
            status="done",
            note_text="可恢复的历史笔记",
            generated_at=datetime.now(),
        )
        self.db.add(note)
        self.db.commit()
        document = InformationSummaryDocument(
            platform="custom_20260519090000",
            summary_date=date(2026, 5, 19),
            title="历史失败自定义汇总",
            status="failed",
            error_message="old failure",
        )
        self.db.add(document)
        self.db.commit()
        self.db.add(
            TaskLog(
                task_name="手动生成自定义视频笔记汇总",
                task_type="generate_information_custom_summary",
                target_type="note",
                target_id=str(note.id),
                status="failed",
                started_at=datetime.now(),
                message=f"document_id={document.id};status=failed",
            )
        )
        self.db.commit()
        hermes = Mock()
        hermes.start_run.return_value = HermesRunResult(
            run_id="run-retry-custom",
            status="running",
            document_text=None,
            raw_response={"id": "run-retry-custom", "status": "running"},
        )

        with patch(
            "app.modules.information.services.video_information_service.HermesClient",
            return_value=hermes,
        ):
            retried = VideoInformationService(self.db).retry_summary_document(document.id)

        self.assertIsNotNone(retried)
        self.assertEqual(retried.status, "running")
        self.assertEqual(retried.hermes_run_id, "run-retry-custom")
        self.assertEqual(
            self.db.query(InformationSummaryDocumentItem).filter_by(document_id=document.id, note_id=note.id).count(),
            1,
        )

    def test_poll_running_summary_document_saves_result_without_changing_video_status(self) -> None:
        source = InformationVideoSource(
            platform="bilibili",
            source_name="测试账号",
            external_source_id="12345",
            enabled=1,
        )
        self.db.add(source)
        self.db.commit()
        video = InformationVideo(
            source_id=source.id,
            platform="bilibili",
            external_video_id="BV-summary-poll",
            title="轮询汇总视频",
            video_url="https://www.bilibili.com/video/BV-summary-poll",
            status="note_done",
        )
        self.db.add(video)
        self.db.commit()
        note = InformationVideoNote(
            video_id=video.id,
            provider="bilinote",
            status="done",
            note_text="待汇总笔记",
            generated_at=datetime.now(),
        )
        self.db.add(note)
        self.db.commit()
        document = InformationSummaryDocument(
            platform="bilibili",
            summary_date=date.today(),
            title="每日汇总",
            status="running",
            hermes_run_id="run-poll",
        )
        self.db.add(document)
        self.db.commit()
        self.db.add(InformationSummaryDocumentItem(document_id=document.id, note_id=note.id))
        self.db.commit()
        hermes = Mock()
        hermes.poll_run_once.return_value = HermesRunResult(
            run_id="run-poll",
            status="done",
            document_text="轮询得到的汇总文档",
            raw_response={"id": "run-poll", "result": "轮询得到的汇总文档"},
        )

        with patch(
            "app.modules.information.services.video_information_service.HermesClient",
            return_value=hermes,
        ):
            result = VideoInformationService(self.db).poll_running_summary_documents()

        self.assertEqual(result["completed"], 1)
        self.db.refresh(document)
        self.db.refresh(video)
        self.assertEqual(document.status, "done")
        self.assertEqual(document.document_text, "轮询得到的汇总文档")
        self.assertEqual(video.status, "note_done")

    def test_summary_prompt_includes_configured_instruction(self) -> None:
        source = InformationVideoSource(
            platform="bilibili",
            source_name="观点作者",
            external_source_id="12345",
            enabled=1,
        )
        self.db.add(source)
        self.db.commit()
        video = InformationVideo(
            source_id=source.id,
            platform="bilibili",
            external_video_id="BV-prompt",
            title="提示词视频",
            video_url="https://www.bilibili.com/video/BV-prompt",
            published_at=datetime(2026, 5, 19, 9, 30, 0),
            status="note_done",
        )
        self.db.add(video)
        self.db.commit()
        note = InformationVideoNote(
            video_id=video.id,
            provider="bilinote",
            status="done",
            note_text="笔记正文",
        )
        self.db.add(note)
        self.db.commit()

        prompt = VideoInformationService(self.db)._build_summary_prompt(
            "custom",
            date(2026, 5, 19),
            [note],
            "请优先输出基金相关观点。",
        )

        self.assertIn("补充说明", prompt)
        self.assertIn("请优先输出基金相关观点。", prompt)
        self.assertIn("作者：观点作者", prompt)
        self.assertIn("标题：提示词视频", prompt)
        self.assertIn("发布时间：2026-05-19 09:30:00", prompt)
        self.assertIn("链接：https://www.bilibili.com/video/BV-prompt", prompt)

    def test_summary_prompt_requires_markdown_output_by_default(self) -> None:
        prompt = VideoInformationService(self.db)._build_summary_prompt(
            "bilibili",
            date(2026, 5, 19),
            [],
        )

        self.assertIn("请以 Markdown 格式输出", prompt)
        self.assertIn("使用 #、##、### 组织标题层级", prompt)
        self.assertIn("重点标注要求", prompt)
        self.assertIn("**重点：...**", prompt)
        self.assertIn("不要输出 HTML", prompt)
        self.assertIn("不要把正文包裹在 ```markdown 代码块中", prompt)


if __name__ == "__main__":
    unittest.main()
