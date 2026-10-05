"""任务复用、查询权限及审计记录响应的回归测试。"""

from datetime import datetime

from delivery_note.web.models import AuditLog, Batch, Job
from tests.support.web_api import WebApiCase


class JobRouteTests(WebApiCase):
    def setUp(self) -> None:
        super().setUp()
        self.headers = self.login("admin", "admin-pass")
        self.upload_active_versions(self.headers)
        response = self.client.post(
            "/api/batches", headers=self.headers, json={"name": "任务契约测试"}
        )
        self.assertEqual(response.status_code, 201, response.text)
        self.batch_id = response.json()["id"]

    def test_compute_reuses_active_and_succeeded_jobs_without_new_audit(self) -> None:
        with self.app.state.database.session() as session:
            job = Job(batch_id=self.batch_id, kind="compute", attempts=2)
            session.add(job)
            session.commit()
            job_id = job.id
            audit_count = session.query(AuditLog).count()
        for job_status in ("queued", "running", "succeeded"):
            with self.subTest(status=job_status):
                with self.app.state.database.session() as session:
                    session.get(Job, job_id).status = job_status
                    session.get(Batch, self.batch_id).status = job_status
                    session.commit()
                for _ in range(2):
                    response = self.client.post(
                        f"/api/batches/{self.batch_id}/compute", headers=self.headers
                    )
                    self.assertEqual(response.status_code, 202, response.text)
                    result = response.json()
                    self.assertEqual(result["id"], job_id)
                    self.assertEqual(result["status"], job_status)
                    self.assertEqual(result["attempts"], 2)
                queried = self.client.get(f"/api/jobs/{job_id}", headers=self.headers)
                self.assertEqual(queried.status_code, 200, queried.text)
                self.assertEqual(queried.json(), result)
                with self.app.state.database.session() as session:
                    self.assertEqual(
                        session.query(Job).filter_by(batch_id=self.batch_id).count(), 1
                    )
                    self.assertEqual(session.query(AuditLog).count(), audit_count)
                    self.assertEqual(
                        session.get(Batch, self.batch_id).status, job_status
                    )

    def test_job_queries_and_audit_logs_enforce_access(self) -> None:
        for path in ("/api/jobs/999999", "/api/audit-logs"):
            with self.subTest(path=path):
                self.assertEqual(self.client.get(path).status_code, 401)
        self.create_operator(self.headers)
        operator_headers = self.login("operator", "operator-pass")
        missing = self.client.get("/api/jobs/999999", headers=operator_headers)
        self.assertEqual(missing.status_code, 404)
        self.assertEqual(missing.json(), {"detail": "任务不存在"})
        self.assertEqual(
            self.client.get("/api/audit-logs", headers=operator_headers).status_code,
            403,
        )

    def test_audit_logs_return_latest_200_with_details_and_utc_dates(self) -> None:
        created_at = datetime(2026, 10, 5, 0, 0, 0)
        with self.app.state.database.session() as session:
            logs = [
                AuditLog(
                    user_id=1,
                    action="queue_compute",
                    entity_type="job",
                    entity_id=str(index),
                    details={"index": index},
                    created_at=created_at,
                )
                for index in range(201)
            ]
            session.add_all(logs)
            session.flush()
            expected_ids = [log.id for log in reversed(logs[-200:])]
            session.commit()
        response = self.client.get("/api/audit-logs", headers=self.headers)
        self.assertEqual(response.status_code, 200, response.text)
        records = response.json()
        self.assertEqual([record["id"] for record in records], expected_ids)
        self.assertEqual(
            records[0],
            {
                "id": expected_ids[0],
                "user_id": 1,
                "action": "queue_compute",
                "entity_type": "job",
                "entity_id": "200",
                "details": {"index": 200},
                "created_at": "2026-10-05T00:00:00Z",
            },
        )
