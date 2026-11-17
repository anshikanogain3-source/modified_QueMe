from assessment_fixtures import grounded_json
import io
import json
import socket
import tempfile
import unittest
from urllib.error import HTTPError, URLError
from unittest.mock import patch

from queme import create_app
from queme.services.llm import _check_model_available, _evaluation_json_schema, _evaluation_token_budget, _evaluation_validation_error, _generate, _generate_json, _ollama_process_lock, evaluate_answer, generate_followup, generate_questions


class LocalOllamaTests(unittest.TestCase):
    def setUp(self):
        self.instance_dir = tempfile.TemporaryDirectory()
        self.app = create_app({
            "TESTING": True,
            "SECRET_KEY": "test-secret-key-that-is-long-enough-for-tests",
            "SQLALCHEMY_DATABASE_URI": "sqlite://",
            "STORAGE_BACKEND": "local",
            "JWT_EXP_HOURS": 24,
            "FRONTEND_ORIGIN": "http://localhost:5173",
            "OLLAMA_BASE_URL": "http://localhost:11434",
            "OLLAMA_MODEL": "qwen3:1.7b",
            "OLLAMA_KEEP_ALIVE": "30m",
            "OLLAMA_TIMEOUT": 120,
            "OLLAMA_TEMPERATURE": 0.2,
            "OLLAMA_NUM_CTX": 4096,
        })
        self.app.instance_path = self.instance_dir.name
        self.ctx = self.app.app_context()
        self.ctx.push()

    def tearDown(self):
        self.ctx.pop()
        self.instance_dir.cleanup()

    def test_chat_request_uses_local_endpoint_and_configured_controls(self):
        response = io.BytesIO(json.dumps({
            "message": {"content": "{\"ok\":true}"},
            "load_duration": 1_000_000,
            "prompt_eval_duration": 2_000_000,
            "eval_duration": 4_000_000_000,
            "total_duration": 4_003_000_000,
            "prompt_eval_count": 20,
            "eval_count": 4,
        }).encode())
        response.__enter__ = lambda: response
        response.__exit__ = lambda *_args: None
        with patch("queme.services.llm.urlopen", return_value=response) as urlopen:
            with self.assertLogs("queme.services.llm", level="INFO") as captured:
                self.assertEqual(_generate(
                    "return JSON", num_predict=55,
                    operation="answer_evaluation", correlation_id="answer_job:42",
                ), '{"ok":true}')
        timing_logs = "\n".join(captured.output)
        self.assertIn("Ollama lock wait started", timing_logs)
        self.assertIn("Ollama lock acquired", timing_logs)
        self.assertIn("Ollama request started", timing_logs)
        self.assertIn("Ollama request completed", timing_logs)
        self.assertIn("correlation_id=answer_job:42", timing_logs)
        self.assertIn("load_ms=1.0", timing_logs)
        self.assertIn("prompt_eval_ms=2.0", timing_logs)
        self.assertIn("generation_ms=4000.0", timing_logs)
        self.assertIn("generated_tokens=4", timing_logs)
        self.assertIn("tokens_per_second=1.0", timing_logs)
        request = urlopen.call_args.args[0]
        body = json.loads(request.data)
        self.assertEqual(request.full_url, "http://localhost:11434/api/chat")
        self.assertEqual(body["model"], "qwen3:1.7b")
        self.assertEqual(body["format"], "json")
        self.assertFalse(body["think"])
        self.assertEqual(body["keep_alive"], "30m")
        self.assertEqual(body["options"], {"temperature": 0.2, "num_predict": 55, "num_ctx": 4096})
        self.assertEqual(urlopen.call_args.kwargs["timeout"], 120)

    def test_chat_request_accepts_json_schema_without_changing_generation_controls(self):
        response = io.BytesIO(json.dumps({"message": {"content": "{}"}}).encode())
        response.__enter__ = lambda: response
        response.__exit__ = lambda *_args: None
        schema = _evaluation_json_schema(["Correctness"])
        with patch("queme.services.llm.urlopen", return_value=response) as urlopen:
            _generate("return JSON", num_predict=755, operation="answer_evaluation", format_schema=schema)
        request = urlopen.call_args.args[0]
        body = json.loads(request.data)
        self.assertEqual(body["format"], schema)
        self.assertEqual(body["model"], "qwen3:1.7b")
        self.assertEqual(body["options"], {"temperature": 0.2, "num_predict": 755, "num_ctx": 4096})

    def test_evaluation_schema_requires_each_dynamic_criterion(self):
        single = _evaluation_json_schema(["Correctness"])
        self.assertEqual(single["properties"]["criteria_scores"]["required"], ["Correctness"])
        self.assertEqual(single["properties"]["criterion_details"]["required"], ["Correctness"])
        self.assertEqual(
            single["properties"]["criteria_scores"]["properties"]["Correctness"]["type"],
            "number",
        )
        self.assertEqual(single["properties"]["criterion_scores"], single["properties"]["criteria_scores"])
        self.assertEqual(single["anyOf"], [{"required": ["criteria_scores"]}, {"required": ["criterion_scores"]}])
        detail = single["properties"]["criterion_details"]["properties"]["Correctness"]
        self.assertEqual(detail["required"], ["applicable", "explanation", "evidence"])

        names = ["Technical Accuracy", "Structure / Clarity"]
        multiple = _evaluation_json_schema(names)
        for field in ("criteria_scores", "criterion_details"):
            self.assertEqual(multiple["properties"][field]["required"], names)
            self.assertEqual(set(multiple["properties"][field]["properties"]), set(names))

        general = _evaluation_json_schema([])
        self.assertEqual(general["properties"]["criteria_scores"]["additionalProperties"], False)
        self.assertEqual(general["properties"]["criterion_details"]["additionalProperties"], False)
        self.assertEqual(general["properties"]["overall_score"]["type"], "number")
        self.assertNotIn("criterion_scores", general["properties"])
        self.assertNotIn("anyOf", general)
        self.assertEqual(set(general["required"]), set(general["properties"]))
        self.assertIn("correct_explanation", general["required"])
        self.assertIn("overall_evidence", general["required"])

    def test_rubricless_evaluation_uses_explicit_overall_contract_without_invented_criteria(self):
        answer = {
            "criteria_scores": {}, "criterion_details": {}, "overall_score": 7.5,
            "overall_explanation": "The response correctly explains the concept.",
            "overall_evidence": "Lists can be changed in place.",
            "technical_accuracy": "Accurate.", "missing_concepts": [],
            "correct_explanation": "A list can be changed in place.", "strengths": [],
            "weaknesses": [], "feedback": "Good explanation.", "needs_teacher_review": False,
        }
        with patch("queme.services.llm._generate", return_value=grounded_json(answer)) as generate:
            result = evaluate_answer({"transcript": "Lists can be changed in place."})
        self.assertEqual(result["content_score"], 7.5)
        self.assertEqual(result["criteria_scores"], {})
        self.assertEqual(result["criterion_details"], {})
        self.assertFalse(result["needs_teacher_review"])
        self.assertEqual(generate.call_args.kwargs["format_schema"]["properties"]["criteria_scores"]["additionalProperties"], False)
        schema = generate.call_args.kwargs["format_schema"]
        self.assertEqual(set(schema["required"]), set(schema["properties"]))
        self.assertIn('"criteria_scores":{},"criterion_details":{},"overall_score":7', generate.call_args.args[0])
        self.assertIn("Every named field is a member of the JSON root", generate.call_args.args[0])
        self.assertIn("Never put overall or other evaluation fields inside either criterion map", generate.call_args.args[0])

    def test_rubricless_evaluation_rejects_missing_general_score_and_invalid_evidence(self):
        answer = {
            "criteria_scores": {}, "criterion_details": {}, "overall_score": 7,
            "overall_explanation": "Relevant explanation.", "overall_evidence": "not in transcript",
            "technical_accuracy": "Accurate.", "missing_concepts": [],
            "correct_explanation": "A list is mutable.", "strengths": [], "weaknesses": [],
            "feedback": "Good.", "needs_teacher_review": False,
        }
        with patch("queme.services.llm._generate", return_value=grounded_json(answer)) as generate:
            result = evaluate_answer({"transcript": "No matching evidence."})
        self.assertEqual(generate.call_count, 2)
        self.assertIsNone(result["content_score"])
        self.assertTrue(result["needs_teacher_review"])
        self.assertEqual(result["review_reason"], "invalid_assessment")

        del answer["overall_score"]
        self.assertEqual(_evaluation_validation_error(answer, []), "missing_field:overall_score")

    def test_model_check_uses_tags_and_requires_the_configured_model(self):
        response = io.BytesIO(json.dumps({"models": [{"name": "qwen3:1.7b"}]}).encode())
        with patch("queme.services.llm.urlopen", return_value=response) as urlopen:
            _check_model_available()
        request = urlopen.call_args.args[0]
        self.assertEqual(request.full_url, "http://localhost:11434/api/tags")
        self.assertEqual(urlopen.call_args.kwargs["timeout"], 10)

        response = io.BytesIO(json.dumps({"models": [{"name": "other-model:latest"}]}).encode())
        with patch("queme.services.llm.urlopen", return_value=response):
            with self.assertRaisesRegex(RuntimeError, "qwen3:1.7b.*not installed"):
                _check_model_available()

    def test_model_check_reports_connection_and_timeout_errors(self):
        with patch("queme.services.llm.urlopen", side_effect=URLError(ConnectionRefusedError(111, "Connection refused"))):
            with self.assertRaisesRegex(RuntimeError, "Connection refused"):
                _check_model_available()

        with patch("queme.services.llm.urlopen", side_effect=URLError(socket.timeout("timed out"))):
            with self.assertRaisesRegex(RuntimeError, "timed out"):
                _check_model_available()

    def test_json_generation_retries_invalid_content_once(self):
        with patch("queme.services.llm._generate", side_effect=["not json", '{"followup":null}']) as generate:
            with self.assertLogs("queme.services.llm", level="WARNING") as captured:
                result = _generate_json(
                    "prompt", validator=lambda value: isinstance(value, dict),
                    operation="answer_evaluation", correlation_id="answer_job:42",
                )
        self.assertEqual(result, {"followup": None})
        self.assertEqual(generate.call_count, 2)
        self.assertIn("reason=invalid_json retrying=True", "\n".join(captured.output))

    def test_structured_repair_prompt_includes_safe_validation_diagnostic(self):
        with patch("queme.services.llm._generate", side_effect=['{"ok":false}', '{"ok":true}']) as generate:
            result = _generate_json(
                "prompt", validator=lambda value: "missing_field:feedback" if not value.get("ok") else True,
                repair_instruction="Put the named fields at the JSON root.",
            )
        self.assertEqual(result, {"ok": True})
        self.assertIn("missing_field:feedback", generate.call_args_list[1].args[0])
        self.assertIn("Put the named fields at the JSON root", generate.call_args_list[1].args[0])

    def test_structured_repair_is_skipped_when_soft_budget_is_exhausted(self):
        with patch("queme.services.llm._generate", return_value="not json") as generate:
            with self.assertRaisesRegex(ValueError, "invalid structured content"):
                _generate_json("prompt", validator=lambda value: isinstance(value, dict), soft_budget_seconds=0)
        self.assertEqual(generate.call_count, 1)

    def test_evaluation_token_budget_scales_with_rubric_and_is_bounded(self):
        self.assertEqual(_evaluation_token_budget(1), 755)
        self.assertGreater(_evaluation_token_budget(20), _evaluation_token_budget(1))
        self.assertEqual(_evaluation_token_budget(100), 1800)

    def test_shared_ollama_lock_wait_has_a_finite_timeout(self):
        self.app.config["OLLAMA_LOCK_WAIT_TIMEOUT"] = 1
        with patch("queme.services.llm.try_lock", side_effect=BlockingIOError), patch(
            "queme.services.llm.time.monotonic", side_effect=[0, 1, 2]
        ):
            with self.assertRaisesRegex(TimeoutError, "inference lock"):
                with _ollama_process_lock(operation="answer_evaluation"):
                    self.fail("Lock should not have been acquired")

    def test_incomplete_rubric_output_fails_without_returning_partial_scores(self):
        incomplete = {
            "criteria_scores": {"Correctness": 8}, "criterion_details": {},
        }
        with patch("queme.services.llm._generate", return_value=json.dumps(incomplete)) as generate:
            result = evaluate_answer({
                "transcript": "Lists are mutable",
                "rubric": {"criteria": [{"name": "Correctness", "weight": 100}]},
            })
        self.assertEqual(generate.call_count, 2)
        self.assertEqual(result["criteria_scores"], {})
        self.assertIsNone(result["content_score"])
        self.assertTrue(result["needs_teacher_review"])
        self.assertIn("invalid structured content", result["error"])

    def test_missing_fields_wrong_score_type_and_missing_applicable_fail_validation(self):
        valid = {
            "criteria_scores": {"Correctness": 8},
            "criterion_details": {"Correctness": {
                "applicable": True, "explanation": "Correct.", "evidence": "Lists are mutable",
            }},
            "technical_accuracy": "Accurate.", "missing_concepts": [],
            "correct_explanation": "Lists can be changed.", "strengths": [], "weaknesses": [],
            "feedback": "Good answer.", "needs_teacher_review": False,
        }
        cases = {}
        missing_field = json.loads(json.dumps(valid))
        del missing_field["feedback"]
        cases["missing_required_field"] = missing_field
        object_score = json.loads(json.dumps(valid))
        object_score["criteria_scores"]["Correctness"] = {"score": 8}
        cases["incorrect_score_type"] = object_score
        missing_applicable = json.loads(json.dumps(valid))
        del missing_applicable["criterion_details"]["Correctness"]["applicable"]
        cases["missing_applicable"] = missing_applicable

        for case_name, response in cases.items():
            with self.subTest(case=case_name), patch(
                "queme.services.llm._generate", return_value=grounded_json(response)
            ) as generate:
                result = evaluate_answer({
                    "transcript": "Lists are mutable",
                    "rubric": {"criteria": [{"name": "Correctness", "weight": 100}]},
                })
            self.assertEqual(generate.call_count, 2)
            self.assertTrue(all(
                call.kwargs["format_schema"]["properties"]["criteria_scores"]["required"] == ["Correctness"]
                for call in generate.call_args_list
            ))
            self.assertIsNone(result["content_score"])
            self.assertTrue(result["needs_teacher_review"])
            self.assertIn("invalid structured content", result["error"])

    def test_invalid_transcript_evidence_rejects_score_and_requires_teacher_review(self):
        response = {
            "criteria_scores": {"Correctness": 8},
            "criterion_details": {"Correctness": {
                "applicable": True, "explanation": "Correct.", "evidence": "not in transcript",
            }},
            "technical_accuracy": "Accurate.", "missing_concepts": [],
            "correct_explanation": "Lists can be changed.", "strengths": [], "weaknesses": [],
            "feedback": "Good answer.", "needs_teacher_review": False,
        }
        with patch("queme.services.llm._generate", return_value=grounded_json(response)):
            result = evaluate_answer({
                "transcript": "Lists are mutable",
                "rubric": {"criteria": [{"name": "Correctness", "weight": 100}]},
            })
        self.assertIsNone(result["content_score"])
        self.assertTrue(result["needs_teacher_review"])
        self.assertEqual(result["review_reason"], "invalid_assessment")
        self.assertEqual(result["criteria_scores"], {})

    def test_ollama_rejecting_structured_output_preserves_teacher_review_fallback(self):
        error_body = io.BytesIO(b'{"error":"JSON schema is unsupported"}')
        rejected = HTTPError(
            "http://localhost:11434/api/chat", 400, "Bad Request", {}, error_body,
        )
        with patch("queme.services.llm.urlopen", side_effect=rejected) as urlopen:
            result = evaluate_answer({
                "transcript": "Lists are mutable",
                "rubric": {"criteria": [{"name": "Correctness", "weight": 100}]},
            })
        self.assertEqual(urlopen.call_count, 1)
        self.assertIsNone(result["content_score"])
        self.assertTrue(result["needs_teacher_review"])
        self.assertIn("HTTP 400", result["error"])

    def test_twenty_criterion_custom_rubric_keeps_every_score_and_detail(self):
        names = [f"Criterion {index}" for index in range(1, 21)]
        answer = {
            "criteria_scores": {name: 7 for name in names},
            "criterion_details": {
                name: {"applicable": True, "explanation": "Relevant point.", "evidence": "It is a clear answer."}
                for name in names
            },
            "technical_accuracy": "Accurate.", "missing_concepts": [],
            "correct_explanation": "A clear answer demonstrates the concept.",
            "strengths": [], "weaknesses": [], "feedback": "Good work.",
            "needs_teacher_review": False,
        }
        payload = {
            "transcript": "It is a clear answer.",
            "rubric": {"criteria": [{"name": name, "weight": 5} for name in names]},
        }
        with patch("queme.services.llm._generate", return_value=grounded_json(answer)) as generate:
            result = evaluate_answer(payload)
        self.assertEqual(generate.call_args.kwargs["num_predict"], 1800)
        self.assertEqual(set(result["criteria_scores"]), set(names))
        self.assertEqual(set(result["criterion_details"]), set(names))
        self.assertFalse(result["needs_teacher_review"])

    def test_evaluation_timeout_logs_timing_and_preserves_safe_error_result(self):
        answer_text = "private candidate answer text"
        payload = {
            "question": "A safe test question",
            "transcript": answer_text,
            "rubric": {"criteria": [{"name": "Correctness", "weight": 100}]},
        }
        timeout = URLError(socket.timeout("timed out"))
        with patch("queme.services.llm.urlopen", side_effect=timeout):
            with self.assertLogs("queme.services.llm", level="INFO") as captured:
                result = evaluate_answer(payload, correlation_id="answer_job:43")
        timing_logs = "\n".join(captured.output)
        self.assertIn("Answer evaluation started correlation_id=answer_job:43", timing_logs)
        self.assertIn("Ollama request started operation=answer_evaluation", timing_logs)
        self.assertIn("Ollama request timed out operation=answer_evaluation", timing_logs)
        self.assertIn("AI answer evaluation failed correlation_id=answer_job:43", timing_logs)
        self.assertNotIn(answer_text, timing_logs)
        self.assertIsNone(result["content_score"])
        self.assertTrue(result["needs_teacher_review"])
        self.assertIn("timed out", result["error"])

    def test_question_generation_returns_safe_error_when_ollama_is_unavailable(self):
        with patch("queme.services.llm._check_model_available"), patch("queme.services.llm._generate", side_effect=RuntimeError("Local Ollama connection failed.")):
            result = generate_questions("Python", "technical", "easy", count=2)
        self.assertFalse(result["available"])
        self.assertEqual(result["questions"], [])
        self.assertIn("Local Ollama", result["error"])

    def test_question_generation_accepts_qwen_single_object_json(self):
        response = {"question_text": "How do lists and tuples differ?", "question_type": "technical", "difficulty": "easy", "expected_key_points": ["mutable", "immutable"]}
        with patch("queme.services.llm._check_model_available"), patch("queme.services.llm._generate", return_value=grounded_json(response)):
            result = generate_questions("Python", "technical", "easy", count=1)
        self.assertTrue(result["available"])
        self.assertEqual(len(result["questions"]), 1)

    def test_i_dont_know_is_handled_without_a_model_call(self):
        with patch("queme.services.llm._generate") as generate:
            result = evaluate_answer({
                "transcript": "I don't know.",
                "rubric": {"criteria": [{"name": "Correctness", "weight": 100}]},
            })
        generate.assert_not_called()
        self.assertEqual(result["content_score"], 0.0)
        self.assertEqual(result["criteria_scores"], {"Correctness": 0.0})
        self.assertTrue(result["weaknesses"])

    def test_evaluation_returns_validated_learning_feedback(self):
        answer = {
            "criteria_scores": {"Correctness": 7},
            "criterion_details": {"Correctness": {"applicable": True, "explanation": "Mostly correct", "evidence": "Lists are mutable"}},
            "technical_accuracy": "Mostly accurate",
            "missing_concepts": ["Mutation through references"],
            "correct_explanation": "A list can be changed in place.",
            "strengths": ["Identified mutability"], "weaknesses": ["No example"],
            "feedback": "Add a concrete example.", "needs_teacher_review": False,
        }
        with patch("queme.services.llm._generate", return_value=grounded_json(answer)):
            with self.assertLogs("queme.services.llm", level="INFO") as captured:
                result = evaluate_answer({
                    "transcript": "Lists are mutable",
                    "rubric": {"criteria": [{"name": "Correctness", "weight": 100}]},
                }, correlation_id="answer_job:44")
        self.assertEqual(result["content_score"], 7.0)
        self.assertEqual(result["missing_concepts"], ["Mutation through references"])
        self.assertEqual(result["correct_explanation"], "A list can be changed in place.")
        self.assertIn("Answer evaluation completed correlation_id=answer_job:44", "\n".join(captured.output))

    def test_evaluation_normalizes_qwen_singular_criterion_scores_key(self):
        answer = {
            "criterion_scores": {"Correctness": 8},
            "criterion_details": {"Correctness": {"applicable": True, "explanation": "Correct", "evidence": "Lists are mutable"}},
            "technical_accuracy": "Correct.", "missing_concepts": [], "correct_explanation": "Lists can be changed.",
            "strengths": [], "weaknesses": [], "feedback": "Good.", "needs_teacher_review": False,
        }
        with patch("queme.services.llm._generate", return_value=grounded_json(answer)):
            result = evaluate_answer({
                "transcript": "Lists are mutable",
                "rubric": {"criteria": [{"name": "Correctness", "weight": 100}]},
            })
        self.assertEqual(result["criteria_scores"], {"Correctness": 8.0})
        self.assertNotIn("criterion_scores", result)
        self.assertEqual(result["content_score"], 8.0)

    def test_followup_is_one_question_and_invalid_output_degrades_safely(self):
        with patch("queme.services.llm._generate", return_value='{"followup":"Can you explain why?"}'):
            self.assertEqual(generate_followup("Why?", "Because it works", "technical"), "Can you explain why?")
        with patch("queme.services.llm._generate", return_value="invalid"):
            self.assertIsNone(generate_followup("Why?", "Because it works", "technical"))


if __name__ == "__main__":
    unittest.main()
