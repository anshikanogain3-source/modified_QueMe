import copy
import json
import unittest
from types import SimpleNamespace
from unittest.mock import patch

import test_answer_jobs as job_fixtures
from queme.authz import make_token
from queme.extensions import db
from queme.models import AnswerProcessingJob, Interview, InterviewQuestion, Report
from queme.services.answer_jobs import process_job, _restore_interrupted_job, latest_completed_evaluation
from queme.services.assessment import ProviderError, openai_generate
from queme.services.llm import evaluate_answer


def assessment(transcript, score=8, category="partial", concept="Identifies a row uniquely"):
    return {
        "criteria_scores": {}, "criterion_details": {}, "overall_score": score,
        "overall_explanation": "Provider prose", "overall_evidence": transcript,
        "technical_accuracy": category, "missing_concepts": [],
        "correct_explanation": "A primary key uniquely identifies a row.",
        "strengths": [], "weaknesses": [], "feedback": "Provider prose",
        "needs_teacher_review": False, "accuracy_category": category,
        "credited_concepts": [{"criterion": "Overall", "concept": concept,
            "explanation": "The excerpt demonstrates the question's identification concept.",
            "evidence": transcript, "points": score}] if score else [],
    }


class SequentialEvaluationTests(unittest.TestCase):
    second_provider = "openai"

    @property
    def provider_path(self):
        return "queme.services.assessment." + self.second_provider + "_generate"

    def setUp(self):
        job_fixtures.AnswerJobTests.setUp(self)
        job_fixtures.AnswerJobTests._prepare_evaluation_job(self)
        self.app.config.update(EVALUATION_MODE=f"ollama_{self.second_provider}_sequential", OPENAI_API_KEY="test-only", GROQ_API_KEY="test-groq")
        self.text = self.question.transcript
        self.payload = {"question": "Explain a primary key.", "transcript": self.text}

    def tearDown(self):
        job_fixtures.AnswerJobTests.tearDown(self)

    def run_job(self, local, remote):
        job = db.session.get(AnswerProcessingJob, self.job_id)
        job.status = "PROCESSING"
        job.attempt_count += 1
        db.session.commit()
        storage = SimpleNamespace(get=lambda key: b"test audio")
        with patch("queme.services.answer_jobs.get_storage", return_value=storage), patch(
            "queme.services.llm._generate", return_value=json.dumps(local)
        ) as ollama, patch(self.provider_path,
                          side_effect=remote if isinstance(remote, Exception) else None,
                          return_value=json.dumps(remote) if not isinstance(remote, Exception) else None) as openai:
            process_job(self.job_id)
        q = db.session.get(InterviewQuestion, self.question_id)
        return q, ollama, openai

    def report(self):
        interview = db.session.get(Interview, self.interview_id)
        token = make_token(interview.teacher)
        response = self.app.test_client().get(f"/api/interviews/{self.interview_id}/report",
                                              headers={"Authorization": "Bearer " + token})
        self.assertEqual(response.status_code, 200)
        return response.json

    def test_order_independence_and_agreed_ollama_score(self):
        order, prompts, states = [], [], []
        def local(prompt, **kw):
            order.append("ollama"); prompts.append(prompt)
            return json.dumps(assessment(self.text, 8))
        def remote(prompt, **kw):
            order.append(self.second_provider); prompts.append(prompt)
            self.assertIn("ollama", states[-1]["provider_results"])
            return json.dumps(assessment(self.text, 9))
        with patch("queme.services.llm._generate", side_effect=local), patch(self.provider_path, side_effect=remote):
            result = evaluate_answer(self.payload, checkpoint=lambda state: states.append(copy.deepcopy(state)))
        self.assertEqual(order, ["ollama", self.second_provider])
        self.assertEqual(prompts[0], prompts[1])
        self.assertEqual(result["content_score"], 8)
        self.assertFalse(result["needs_teacher_review"])

    def test_worker_agreement_report_and_teacher_override(self):
        q, _, _ = self.run_job(assessment(self.text), assessment(self.text, 9))
        self.assertEqual(q.content_score, 8)
        self.assertEqual(float(q.final_ai_score), 7.7)
        self.assertEqual(q.processing_job.outcome, "EVALUATED")
        report = self.report()
        self.assertIn("Demonstrated", report["questions"][0]["evaluation"]["feedback"])
        token = make_token(db.session.get(Interview, self.interview_id).teacher)
        response = self.app.test_client().patch(f"/api/interviews/{self.interview_id}/report",
            headers={"Authorization": "Bearer " + token}, json={"teacher_score": 9.25, "teacher_remark": "Reviewed"})
        self.assertEqual(response.json["final_score"], 9.25)
        self.assertEqual(response.json["score_source"], "TEACHER")
        self.assertEqual(self.report()["teacher_remark"], "Reviewed")

    def test_disagreement_is_excluded_from_totals_and_adaptation(self):
        q, _, _ = self.run_job(assessment(self.text, 8), assessment(self.text, 6))
        self.assertIsNone(q.content_score)
        self.assertIsNone(q.final_ai_score)
        self.assertEqual(q.processing_job.status, "NEEDS_REVIEW")
        self.assertEqual(latest_completed_evaluation(q.interview), (None, None))
        report = self.report()
        self.assertIsNone(report["final_score"])
        self.assertEqual(report["questions"][0]["evaluation"]["review_reason"], "provider_disagreement")
        self.assertEqual(report["questions"][0]["evaluation"]["provider_results"]["ollama"]["content_score"], 8)

    def test_accuracy_difference_requires_review_even_with_equal_scores(self):
        q, _, _ = self.run_job(assessment(self.text, 8, "correct"), assessment(self.text, 8))
        self.assertEqual(q.evaluation_json["review_reason"], "provider_disagreement")

    def test_quota_keeps_local_assessment_and_ends_in_review(self):
        q, _, _ = self.run_job(assessment(self.text), ProviderError(self.second_provider + "_quota_exhausted"))
        self.assertEqual(q.processing_job.status, "NEEDS_REVIEW")
        self.assertEqual(q.evaluation_json["provider_results"]["ollama"]["content_score"], 8)
        self.assertIsNone(self.report()["final_score"])

    def test_retry_reuses_committed_provider_and_restart_resumes(self):
        q, local, _ = self.run_job(assessment(self.text), ProviderError(self.second_provider + "_rate_limit", True))
        self.assertEqual(q.processing_job.status, "RETRY_WAIT")
        self.assertEqual(local.call_count, 1)
        q.processing_job.status = "PROCESSING"
        _restore_interrupted_job(q.processing_job)
        self.assertEqual(q.processing_job.status, "QUEUED")
        q, local, _ = self.run_job(assessment(self.text), assessment(self.text))
        local.assert_not_called()
        self.assertEqual(q.processing_job.status, "COMPLETED")

    def test_checkpoint_survives_interruption_before_second_provider(self):
        from queme.services.reports import evaluate_interview_answer
        with patch("queme.services.llm._generate", return_value=json.dumps(assessment(self.text))), patch(
            self.provider_path, side_effect=KeyboardInterrupt
        ):
            with self.assertRaises(KeyboardInterrupt):
                evaluate_interview_answer(self.question)
        db.session.rollback()
        db.session.expire_all()
        q = db.session.get(InterviewQuestion, self.question_id)
        self.assertTrue(q.evaluation_json["evaluation_in_progress"])
        self.assertEqual(q.evaluation_json["provider_results"]["ollama"]["content_score"], 8)
        _restore_interrupted_job(q.processing_job)
        self.assertEqual(q.processing_job.status, "QUEUED")
        q, local, _ = self.run_job(assessment(self.text), assessment(self.text))
        local.assert_not_called()
        self.assertEqual(q.processing_job.status, "COMPLETED")

    def test_retry_retains_second_provider_when_ollama_was_unavailable(self):
        with patch("queme.services.llm._generate", side_effect=RuntimeError("Local Ollama connection failed.")), patch(
            self.provider_path, return_value=json.dumps(assessment(self.text))
        ):
            first = evaluate_answer(self.payload)
        self.assertTrue(first["retryable"])
        with patch("queme.services.llm._generate", return_value=json.dumps(assessment(self.text))), patch(
            self.provider_path
        ) as remote:
            second = evaluate_answer(self.payload, previous=first)
        remote.assert_not_called()
        self.assertEqual(second["content_score"], 8)

    def test_existing_report_and_override_are_read_without_re_evaluation(self):
        from queme.services.reports import generate_interview_report
        self.question.content_score = 6
        self.question.final_ai_score = 6.3
        self.question.teacher_score = 9
        self.question.teacher_remark = "Saved teacher assessment"
        self.question.evaluation_json = {"overall_explanation": "Legacy feedback", "content_score": 6}
        self.interview.status = "COMPLETED"
        generate_interview_report(self.interview)
        db.session.commit()
        with patch("queme.services.llm._generate") as local, patch(self.provider_path) as remote:
            report = self.report()
        local.assert_not_called(); remote.assert_not_called()
        self.assertEqual(report["final_score"], 9)
        self.assertEqual(report["questions"][0]["evaluation"]["overall_explanation"], "Legacy feedback")
        self.assertEqual(report["questions"][0]["teacher_remark"], "Saved teacher assessment")

    def test_saved_failure_shapes_rejected_without_concept_support(self):
        self.app.config["EVALUATION_MODE"] = "ollama"
        cases = [("This time you can manipulate the sequence of the series now.", 6),
                 ("I'm not sure. 45.", 3), ("Assending order is used in math 1, 2, 3, 4.", 4)]
        for text, score in cases:
            value = assessment(text, score)
            value.pop("credited_concepts"); value.pop("accuracy_category")
            value["overall_explanation"] = "The answer is mostly accurate."
            with patch("queme.services.llm._generate", return_value=json.dumps(value)) as provider:
                result = evaluate_answer({"question": "SQL question", "transcript": text})
            self.assertEqual(provider.call_count, 2)
            self.assertIsNone(result["content_score"])
            self.assertEqual(result["strengths"], [])

    def test_audited_cases_through_worker_and_report(self):
        # Each subcase uses a fresh isolated database; this test's initial fixture is first.
        cases = [
            ("This time you can manipulate the sequence of the series now.", 0, "uncertain", None),
            ("I'm not sure. 45.", 0, "not_answered", 0),
            ("Ascending order is used in math 1, 2, 3, 4.", 0, "off_topic", 0),
            ("It fetches requested data from tables.", 10, "correct", 10),
            ("INNER JOIN returns matching rows.", 5, "partial", 5),
        ]
        for index, (transcript, score, category, expected) in enumerate(cases):
            with self.subTest(category=category):
                if index:
                    self.tearDown(); self.setUp()
                self.question.question.question_text = [
                    "What is the purpose of SELECT in SQL?",
                    "What is the difference between INNER JOIN and OUTER JOIN?",
                    "How do you sort SQL query results in ascending order?",
                    "What is the purpose of SELECT in SQL?",
                    "What is the difference between INNER JOIN and OUTER JOIN?",
                ][index]
                self.question.analysis.transcript = transcript
                self.question.transcript = transcript
                db.session.commit()
                value = assessment(transcript, score, category, "Retrieves table data" if index == 3 else "INNER JOIN returns matching rows")
                value["correct_explanation"] = [
                    "SELECT retrieves requested data from database tables.",
                    "INNER JOIN returns matches; outer joins also retain unmatched rows from the designated side.",
                    "Use ORDER BY column ASC.",
                    "SELECT retrieves requested data from database tables.",
                    "INNER JOIN returns matches; outer joins also retain unmatched rows from the designated side.",
                ][index]
                q, _, _ = self.run_job(value, value)
                self.assertEqual(q.content_score, expected)
                report = self.report()
                ev = report["questions"][0]["evaluation"]
                self.assertNotIn("mostly accurate", ev["feedback"])
                if expected is None:
                    self.assertIsNone(report["final_score"])
                    self.assertEqual(q.processing_job.status, "NEEDS_REVIEW")
                else:
                    self.assertEqual(q.processing_job.status, "COMPLETED")
                    self.assertEqual(ev["accuracy_category"], category)
                    if not expected:
                        self.assertEqual(ev["strengths"], [])

    def test_contradiction_and_legacy_unsupported_output_are_rejected_after_repair(self):
        bad = assessment(self.text, 4)
        bad.update(technical_accuracy="Incorrect", overall_explanation="The answer is mostly accurate.")
        q, local, remote = self.run_job(bad, bad)
        self.assertEqual(local.call_count, 2)
        self.assertEqual(remote.call_count, 2)
        self.assertIsNone(q.content_score)
        self.assertEqual(q.evaluation_json["provider_results"]["ollama"]["review_reason"], "contradictory_assessment")
        self.assertNotIn("mostly accurate", self.report()["questions"][0]["evaluation"]["feedback"])

    def test_direction_credit_requires_a_supported_criterion(self):
        text = "Ascending means 1, 2, 3, 4."
        response = assessment(text, 1, "partial", "Ascending direction")
        response.update(criteria_scores={"Direction": 10, "SQL method": 0}, criterion_details={
            "Direction": {"applicable": True, "explanation": "Shows increasing values", "evidence": text},
            "SQL method": {"applicable": True, "explanation": "Not demonstrated", "evidence": None},
        })
        for key in ("overall_score", "overall_evidence", "overall_explanation"):
            response.pop(key)
        response["credited_concepts"][0].update(criterion="Direction", points=10)
        payload = {"question": "How do you sort SQL results ascending?", "transcript": text,
                   "rubric": {"criteria": [{"name": "Direction", "weight": 10}, {"name": "SQL method", "weight": 90}]}}
        with patch("queme.services.llm._generate", return_value=json.dumps(response)), patch(self.provider_path, return_value=json.dumps(response)):
            result = evaluate_answer(payload)
        self.assertEqual(result["content_score"], 1)
        self.assertEqual(result["criteria_scores"]["SQL method"], 0)
        self.assertEqual(result["strengths"], ["Ascending direction"])

    def test_sdk_request_and_terminal_response_states(self):
        from queme.services.assessment import assessment_schema
        from queme.services.llm import _evaluation_json_schema
        with patch("openai.OpenAI") as sdk:
            response = sdk.return_value.__enter__.return_value.responses.create
            response.return_value = SimpleNamespace(output=[], status="completed", output_text="{}")
            openai_generate("scoring text", format_schema=assessment_schema(_evaluation_json_schema([])), num_predict=700)
            self.assertEqual(sdk.call_args.kwargs["max_retries"], 0)
            self.assertFalse(response.call_args.kwargs["store"])
            self.assertTrue(response.call_args.kwargs["text"]["format"]["strict"])
            for status, output, code in [("incomplete", [], "openai_incomplete_response"),
                ("completed", [SimpleNamespace(content=[SimpleNamespace(type="refusal")])], "openai_refusal")]:
                response.return_value = SimpleNamespace(output=output, status=status)
                with self.assertRaises(ProviderError) as caught:
                    openai_generate("text", format_schema={}, num_predict=700)
                self.assertEqual(caught.exception.code, code)

    def test_sdk_error_classification(self):
        import httpx
        from openai import APIStatusError, APITimeoutError
        request = httpx.Request("POST", "https://api.openai.com/v1/responses")
        for status, code, expected, retryable in [
            (401, "invalid_api_key", "openai_credentials_invalid", False),
            (429, "insufficient_quota", "openai_quota_exhausted", False),
            (429, "rate_limit_exceeded", "openai_rate_limit", True),
            (500, "server_error", "openai_request_failed", True),
        ]:
            error = APIStatusError("private body", response=httpx.Response(status, request=request), body={"code": code})
            with patch("openai.OpenAI") as sdk:
                sdk.return_value.__enter__.return_value.responses.create.side_effect = error
                with self.assertRaises(ProviderError) as caught:
                    openai_generate("text", format_schema={}, num_predict=700)
                self.assertEqual((caught.exception.code, caught.exception.retryable), (expected, retryable))
        with patch("openai.OpenAI") as sdk:
            sdk.return_value.__enter__.return_value.responses.create.side_effect = APITimeoutError(request=request)
            with self.assertRaises(ProviderError) as caught:
                openai_generate("text", format_schema={}, num_predict=700)
            self.assertTrue(caught.exception.retryable)
        self.app.config["OPENAI_API_KEY"] = ""
        with self.assertRaises(ProviderError) as caught:
            openai_generate("text", format_schema={}, num_predict=700)
        self.assertEqual(caught.exception.code, "openai_missing_key")
