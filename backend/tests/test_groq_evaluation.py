"""Run the shared flow regressions with Groq, plus mocked HTTP transport checks."""
import io
import json
from unittest.mock import patch
from types import SimpleNamespace
from urllib.error import HTTPError, URLError

import test_sequential_evaluation as shared
from queme.extensions import db
from queme.models import InterviewQuestion
from queme.services.assessment import groq_generate, ProviderError
from queme.services.llm import evaluate_answer


class GroqEvaluationTests(shared.SequentialEvaluationTests):
    second_provider = "groq"

    def test_http_request_uses_only_groq_and_saves_both_after_reload(self):
        response = io.BytesIO(json.dumps({"choices": [{"finish_reason": "stop", "message": {
            "content": json.dumps(shared.assessment(self.text, 9))}}]}).encode())
        # run_job normally mocks the second provider; exercise the real adapter here.
        from queme.services.reports import evaluate_interview_answer
        with patch("queme.services.llm._generate", return_value=json.dumps(shared.assessment(self.text))) as local, patch(
            "queme.services.assessment.urlopen", return_value=response
        ) as http, patch("queme.services.assessment.openai_generate", side_effect=AssertionError("OpenAI must not run")):
            evaluate_interview_answer(self.question)
            db.session.commit()
        request = http.call_args.args[0]
        self.assertEqual(request.full_url, "https://api.groq.com/openai/v1/chat/completions")
        body = json.loads(request.data)
        self.assertEqual(body["model"], "openai/gpt-oss-20b")
        self.assertTrue(body["response_format"]["json_schema"]["strict"])
        self.assertEqual(body["messages"][0]["content"], local.call_args.args[0])
        db.session.remove()
        saved = db.session.get(InterviewQuestion, self.question_id).evaluation_json["provider_results"]
        self.assertEqual(set(saved), {"ollama", "groq"})
        for provider, score in (("ollama", 8), ("groq", 9)):
            self.assertEqual(saved[provider]["provider"], provider)
            self.assertEqual(saved[provider]["status"], "COMPLETED")
            self.assertEqual(saved[provider]["content_score"], score)
            self.assertEqual(saved[provider]["credited_concepts"][0]["evidence"], self.text)
        self.assertEqual(saved["ollama"]["model"], "qwen3:1.7b")

    def test_http_failure_classification_and_sanitization(self):
        for status, code, message, reason, retry in [
            (401, "invalid_api_key", "secret", "groq_credentials_invalid", False),
            (429, "insufficient_quota", "private", "groq_quota_exhausted", False),
            (429, "rate_limit_exceeded", "Rate limit reached on tokens per day (TPD)", "groq_quota_exhausted", False),
            (429, "rate_limit_exceeded", "Requests per day (RPD) exhausted", "groq_quota_exhausted", False),
            (429, "rate_limit_exceeded", "Tokens per minute (TPM)", "groq_rate_limit", True),
            (503, "server_error", "raw student text", "groq_request_failed", True),
        ]:
            with self.subTest(reason=reason):
                error = HTTPError("https://api.groq.com", status, "private", {},
                    io.BytesIO(json.dumps({"error": {"code": code, "message": message}}).encode()))
                with patch("queme.services.assessment.urlopen", side_effect=error):
                    with self.assertRaises(ProviderError) as caught:
                        groq_generate("private transcript", format_schema={}, num_predict=700)
                self.assertEqual((str(caught.exception), caught.exception.retryable), (reason, retry))
        with patch("queme.services.assessment.urlopen", side_effect=URLError("private")):
            with self.assertRaises(ProviderError) as caught:
                groq_generate("text", format_schema={}, num_predict=700)
            self.assertTrue(caught.exception.retryable)

    def test_daily_quota_is_persisted_and_report_reopens(self):
        error = HTTPError("https://api.groq.com", 429, "private", {}, io.BytesIO(json.dumps({
            "error": {"code": "rate_limit_exceeded", "message": "Tokens per day (TPD) exhausted"}}).encode()))
        with patch("queme.services.assessment.urlopen", side_effect=error), patch(
            "queme.services.assessment.openai_generate", side_effect=AssertionError("No fallback")
        ):
            from queme.services.answer_jobs import process_job
            self.job.status = "PROCESSING"
            self.job.attempt_count = 1
            db.session.commit()
            with patch("queme.services.answer_jobs.get_storage", return_value=SimpleNamespace(get=lambda key: b"audio")), patch(
                "queme.services.llm._generate", return_value=json.dumps(shared.assessment(self.text))
            ):
                process_job(self.job_id)
        db.session.remove()
        report = self.report()
        saved = report["questions"][0]["evaluation"]["provider_results"]
        self.assertEqual(saved["ollama"]["content_score"], 8)
        self.assertEqual(saved["groq"]["status"], "UNAVAILABLE")
        self.assertEqual(saved["groq"]["review_reason"], "groq_quota_exhausted")
        self.assertIsNone(report["final_score"])

    def test_groq_refusal_incomplete_and_missing_key(self):
        for choice, reason in [
            ({"finish_reason": "length", "message": {}}, "groq_incomplete_response"),
            ({"finish_reason": "stop", "message": {"refusal": "private"}}, "groq_refusal"),
        ]:
            response = io.BytesIO(json.dumps({"choices": [choice]}).encode())
            with patch("queme.services.assessment.urlopen", return_value=response):
                with self.assertRaises(ProviderError) as caught:
                    groq_generate("text", format_schema={}, num_predict=700)
                self.assertEqual(str(caught.exception), reason)
        self.app.config["GROQ_API_KEY"] = ""
        with self.assertRaises(ProviderError) as caught:
            groq_generate("text", format_schema={}, num_predict=700)
        self.assertEqual(str(caught.exception), "groq_missing_key")

    def test_mode_switch_does_not_compare_old_openai_outcome(self):
        self.app.config["EVALUATION_MODE"] = "ollama_openai_sequential"
        with patch("queme.services.llm._generate", return_value=json.dumps(shared.assessment(self.text))), patch(
            "queme.services.assessment.openai_generate", return_value=json.dumps(shared.assessment(self.text))
        ):
            old = evaluate_answer(self.payload)
        self.app.config["EVALUATION_MODE"] = "ollama_groq_sequential"
        with patch("queme.services.llm._generate") as local, patch(
            self.provider_path, return_value=json.dumps(shared.assessment(self.text))
        ), patch("queme.services.assessment.openai_generate", side_effect=AssertionError("No fallback")):
            new = evaluate_answer(self.payload, previous=old)
        local.assert_not_called()
        self.assertEqual(set(new["provider_results"]), {"ollama", "groq"})
