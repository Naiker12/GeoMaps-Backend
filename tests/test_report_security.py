"""Propiedad de reportes, sesión del trabajo y PDF fuera del event loop."""

import json
import tempfile
import threading
import unittest
import uuid
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, patch

from backend_test_environment import configure_test_environment
configure_test_environment()

from fastapi import BackgroundTasks, FastAPI
from fastapi.testclient import TestClient
with patch("supabase.create_client"):
    from app.api.v1.endpoints import report_router as reports
from app.services.export.typst_service import TypstPDFService
from app.schemas.report_schemas import ReportRequest


class ReportAccessTests(unittest.TestCase):
    def setUp(self):
        self.owner = SimpleNamespace(id=uuid.uuid4(), is_active=True)
        self.report_id = uuid.uuid4()
        self.info = {"id": str(self.report_id), "user_id": str(self.owner.id), "status": "processing", "progress": 10}
        self.app = FastAPI()
        self.app.include_router(reports.router, prefix="/reports")
        self.app.dependency_overrides[reports.get_current_active_user] = lambda: self.owner
        self.redis = AsyncMock()

    def request(self, path):
        self.redis.get.return_value = json.dumps(self.info)
        with patch.object(reports, "redis_client", self.redis), TestClient(self.app) as client:
            return client.get(path)

    def test_owner_can_read_status(self):
        response = self.request(f"/reports/status/{self.report_id}")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["report_id"], str(self.report_id))

    def test_other_users_and_ownerless_legacy_reports_are_hidden(self):
        for owner_id in (str(uuid.uuid4()), None):
            self.info["user_id"] = owner_id
            for kind in ("status", "download"):
                self.assertEqual(self.request(f"/reports/{kind}/{self.report_id}").status_code, 404)

    def test_owner_can_download_ready_pdf(self):
        with tempfile.TemporaryDirectory(prefix="geomaps-report-test-") as folder:
            path = Path(folder) / "report.pdf"
            path.write_bytes(b"%PDF-test")
            self.info.update(status="completed", pdf_path=str(path))
            response = self.request(f"/reports/download/{self.report_id}")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.content, b"%PDF-test")

    def test_invalid_report_id_does_not_query_cache(self):
        self.assertEqual(self.request("/reports/status/not-a-uuid").status_code, 422)
        self.redis.get.assert_not_awaited()


class ReportBackgroundTests(unittest.IsolatedAsyncioTestCase):
    async def test_generation_stores_owner_and_does_not_pass_request_database_to_job(self):
        tasks = BackgroundTasks()
        owner_id = uuid.uuid4()
        redis = AsyncMock()
        request = ReportRequest(message="Generar un reporte de prueba")
        with patch.object(reports, "redis_client", redis):
            response = await reports.generate_report(request, tasks, SimpleNamespace(id=owner_id))
        state = json.loads(redis.setex.call_args.args[2])
        self.assertEqual(state["user_id"], str(owner_id))
        self.assertTrue(state["created_at"].endswith("+00:00"))
        self.assertEqual(tasks.tasks[0].args, (response.report_id, request, str(owner_id)))

    async def test_background_job_owns_and_closes_its_session(self):
        session = AsyncMock()
        db = Mock()
        session.__aenter__.return_value = db
        request = ReportRequest(message="Generar un reporte de prueba")
        with patch.object(reports, "SessionLocal", return_value=session), patch.object(
            reports, "_generate_report_in_session", new_callable=AsyncMock
        ) as generate:
            await reports._generate_pdf_background("report", request, "user")
        generate.assert_awaited_once_with("report", request, db, "user")
        session.__aexit__.assert_awaited_once()

    async def test_pdf_generation_is_in_worker_on_every_platform(self):
        loop_thread = threading.get_ident()
        threads = []

        def generate(*args):
            threads.append(threading.get_ident())
            return "report.pdf"

        with tempfile.TemporaryDirectory(prefix="geomaps-pdf-test-") as folder:
            service = TypstPDFService(folder)
            with patch.object(service, "_generate_pdf_sync", side_effect=generate):
                self.assertEqual(await service.generate_pdf("report", {}), "report.pdf")
        self.assertNotEqual(threads[0], loop_thread)


if __name__ == "__main__":
    unittest.main()
