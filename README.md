# QueMe

QueMe is a campus virtual interview assistant. The backend is a Flask REST API. SQLite is the default database; PostgreSQL can be selected with `DATABASE_URL`.

## Development Setup & Running Commands

These instructions use Windows PowerShell and the current project defaults. For the implementation overview, see [README2.md](README2.md).

### A. Initial setup

1. Open an existing checkout, or clone the repository using your repository URL. The commands below assume it is at `$HOME\Documents\QueMe`:

   ```powershell
   Set-Location "$HOME\Documents\QueMe"
   ```

2. Create the root `.env` from the template if you do not already have one. Generate a secret and put it in `.env` as `SECRET_KEY`:

   ```powershell
   if (-not (Test-Path .\.env)) { Copy-Item .\backend\.env.example .\.env }
   py -3 -c "import secrets; print(secrets.token_urlsafe(48))"
   ```

   The application loads the repository root `.env` first, then `backend/.env` as a fallback for unset values. If both files define the same variable, the root `.env` takes precedence. The template omits `DATABASE_URL`, so the default is `backend/queme.db` (SQLite). To use PostgreSQL, set `DATABASE_URL` to a reachable PostgreSQL database URL.

   The default Ollama settings are `OLLAMA_BASE_URL=http://localhost:11434` and `OLLAMA_MODEL=qwen3:1.7b`. Set either in `.env` only if your server or model differs. Keep `ADMIN_EMAIL` and `ADMIN_PASSWORD` private; the initial admin password must be at least 12 characters.

3. Create and install the backend environment. Python 3.10 or newer is required:

   ```powershell
   Set-Location .\backend
   py -3 -m venv .venv
   .\.venv\Scripts\Activate.ps1
   python -m pip install -r requirements.txt
   ```

   Activate the virtual environment in each backend PowerShell terminal before running backend commands.

4. Install the Ollama Windows application if it is not already installed. Start Ollama if it is not already running, then pull and list the configured default model:

   ```powershell
   ollama pull qwen3:1.7b
   ollama list
   ```

   Verify the model using the same local chat API and `think:false` setting QueMe sends:

   ```powershell
   $body = @{
     model = 'qwen3:1.7b'
     messages = @(@{ role = 'user'; content = 'Reply with READY only.' })
     think = $false
     stream = $false
     options = @{ num_predict = 32 }
   } | ConvertTo-Json -Depth 5
   Invoke-RestMethod -Uri 'http://localhost:11434/api/chat' -Method Post -ContentType 'application/json' -Body $body
   ```

   A successful response has a `message.content` value of `READY`. If you configured another `OLLAMA_MODEL`, pull and test that exact model tag instead. Ollama is a separate local service; the default Ollama address is `http://localhost:11434`.

5. Apply the checked-in database migrations and seed initial data from `backend/`:

   ```powershell
   python -m flask --app run.py db upgrade
   python -m flask --app run.py seed
   ```

   These commands update the configured database schema and create baseline data. Run `seed` for initial setup; it does not reset an existing admin password. Migrations are tracked in `backend/migrations/versions/`; do not run `db init`.

6. Install frontend dependencies once:

   ```powershell
   Set-Location ..\frontend
   npm install
   ```

### B. Daily startup

Use separate terminals. Start Ollama if it is not already running, then start the answer worker and Flask API separately, followed by Vite.

**Terminal 1 — Answer worker:** From the repository root:

```powershell
Set-Location .\backend
.\.venv\Scripts\Activate.ps1
python -m flask --app run.py process-answer-jobs
```

The worker polls the durable answer queue and runs continuously. Do not start a second worker while one is already running.

**Terminal 2 — Flask API:** From the repository root:

```powershell
Set-Location .\backend
.\.venv\Scripts\Activate.ps1
python -m flask --app run.py --debug run
```

The API normally serves `http://127.0.0.1:5000`.

**Terminal 3 — Frontend:**

```powershell
Set-Location .\frontend
npm run dev
```

Vite normally serves `http://127.0.0.1:5173` and proxies `/api` requests to Flask on port 5000. If that port is busy, Vite may select another port; use the address printed in its terminal.

### C. Manual worker commands

Run the worker in its own terminal, separately from the API:

```powershell
Set-Location .\backend
.\.venv\Scripts\Activate.ps1
python -m flask --app run.py process-answer-jobs
```

The worker runs continuously. To process at most one available job and exit, add `--once`:

```powershell
python -m flask --app run.py process-answer-jobs --once
```

Do not start a second worker; the existing worker lock rejects duplicate workers. `--once` is an operating command: it may claim and process a real queued answer.

### D. Health and verification

These commands are read-only diagnostics unless noted otherwise.

**Check the backend and worker:**

```powershell
Invoke-RestMethod -Uri 'http://127.0.0.1:5000/api/health'
```

The response includes database status and a `worker` object. `healthy` means the worker is processing; `inactive` means it is running and idle; `failing` means repeated database failures; `unhealthy` means it is starting, retrying, or has a stale heartbeat; `not_running` means no worker holds the host lock. The response also includes heartbeat age, consecutive failures, and the last processed job ID/time.

**Check Ollama and the installed models:**

```powershell
ollama list
Invoke-RestMethod -Uri 'http://localhost:11434/api/tags'
```

Use the chat smoke test in Initial setup to verify an actual model response. `ollama list` and `/api/tags` verify availability and installed tags, but do not run an inference.

**Inspect running processes and listening ports:**

```powershell
Get-CimInstance Win32_Process |
  Where-Object { $_.CommandLine -match 'flask|vite|ollama' } |
  Select-Object ProcessId, Name, CommandLine
Get-NetTCPConnection -State Listen |
  Where-Object { $_.LocalPort -in 5000, 5173, 11434 } |
  Select-Object LocalAddress, LocalPort, OwningProcess
```

**Inspect backend logs** (defaults to `backend/logs`; `LOG_DIR` can override it):

```powershell
Get-Content .\backend\logs\queme.log -Tail 100
Get-Content .\backend\logs\queme.log -Wait
Select-String -Path .\backend\logs\queme.log -Pattern 'worker|answer|ollama|error'
```

**Run verification commands:**

```powershell
Set-Location .\backend
.\.venv\Scripts\Activate.ps1
python -m unittest discover -s tests -v
```

To verify the frontend production build:

```powershell
Set-Location .\frontend
npm run build
```

The backend tests use temporary/in-memory test databases and mock external inference; they do not process your live interview queue. `npm run build` writes generated frontend output under `frontend/dist`.

### E. Shutdown

- In the answer-worker terminal and the API terminal, press **Ctrl+C** to stop each process.
- In the frontend terminal, press **Ctrl+C** to stop Vite.
- Leave Ollama running or stop it using its Windows application/service controls.
- Check for remaining processes with the PowerShell process command above. If a process remains, identify its PID and stop only that process with `Stop-Process -Id <PID>` after confirming it is safe to stop.

### F. Troubleshooting

1. **Worker is not running:** Check `/api/health`. Start the worker with the PowerShell command in section C. If startup reports that a worker is already running, inspect processes first; do not delete `backend/instance/answer-processing-worker.lock`. The file can remain after shutdown—the OS lock, not file existence, indicates a running worker.
2. **Answers remain `QUEUED` or `PROCESSING`:** Check the `worker` status from `/api/health`, then inspect `backend/logs/queme.log` and `backend/logs/errors.log`. Confirm the worker process is present and that database status is `ok`. A fresh `inactive` worker is polling an empty queue; persistent queued jobs with that status warrant checking the worker logs and database connectivity. On restart, the worker's recovery code resumes interrupted jobs from their recorded stage.
3. **Heartbeat is stale or worker is `unhealthy`:** Check the process list and logs. A worker may be doing a long transcription or model request; inspect recent activity before stopping it. If it is no longer making progress, stop it gracefully and restart it using the PowerShell command in section C. The status endpoint uses the lock and heartbeat together; an old heartbeat alone does not mean a worker is running.
4. **Ollama is unavailable:** Run `ollama list` and `Invoke-RestMethod -Uri 'http://localhost:11434/api/tags'`. If the server is down, start the Ollama Windows application. Check `OLLAMA_BASE_URL` in the active `.env` if Ollama uses a different address.
5. **Configured model is not installed:** The default is `qwen3:1.7b`. Run `ollama pull qwen3:1.7b`, then confirm it appears in `ollama list`. If `OLLAMA_MODEL` is overridden, pull that exact configured tag instead.
6. **Database connection errors:** Check `/api/health` and `DATABASE_URL` in the active `.env`. With no `DATABASE_URL`, QueMe uses SQLite at `backend/queme.db`; with PostgreSQL, confirm the server, database name, credentials, and network access. From `backend/` with the virtual environment activated, `python -m flask --app run.py db upgrade` applies schema migrations and changes the database schema; use the configured database deliberately. Do not delete the database to fix a connection error.
7. **Port already in use:** Use `Get-NetTCPConnection -State Listen` above to identify the owning PID and service. Stop only the process you intend to stop using Ctrl+C or `Stop-Process -Id <PID>`. Flask defaults to port 5000, Vite to 5173, and Ollama to 11434. Vite may choose a different free port and prints the actual URL.
8. **Backend starts but worker fails:** Read the terminal output and `backend/logs/errors.log`. Check that `.venv` exists, migrations have been applied to the same database used by the API, and no other worker holds the lock. Migrations are not run automatically at startup.
9. **Worker unexpectedly exits:** Inspect the process list and latest worker/database log entries. Temporary SQLAlchemy database errors use bounded retry backoff while the worker process remains alive. If the worker process died, restart it; the startup recovery requeues interrupted jobs and preserves completed evaluations. Keep the database and answer files intact during recovery.

**Diagnostic vs state-changing commands:** `Invoke-RestMethod`, `ollama list`, `/api/tags`, `Get-CimInstance`, `Get-NetTCPConnection`, `Get-Content`, and `Select-String` only inspect state. `ollama pull` downloads a model; `npm install` installs dependencies; `db upgrade` changes the database schema; `seed` may add initial records; and starting the worker can update queued answer jobs. None of the documented troubleshooting steps deletes interview data.

## Backend configuration reference

### Environment variables

| Variable | Required | Purpose |
| --- | --- | --- |
| `SECRET_KEY` | Yes | Random token signing key, at least 32 characters. |
| `DATABASE_URL` | No | Omit to use SQLite at `backend/queme.db`; set a PostgreSQL connection URL to use PostgreSQL. |
| `ADMIN_EMAIL`, `ADMIN_PASSWORD` | First seed | Initial active admin credentials; password must have at least 12 characters. |
| `ADMIN_FULL_NAME` | No | Display name for the initial admin. |
| `FRONTEND_ORIGIN` | No | Allowed browser origin; defaults to `http://localhost:5173`. |
| `OLLAMA_BASE_URL` | No | Local Ollama API base; defaults to `http://localhost:11434`. |
| `OLLAMA_MODEL` | No | Local chat model; defaults to `qwen3:1.7b`. |
| `SMTP_HOST`, `SMTP_FROM` | For password reset | SMTP server and sender address used to deliver reset links. |
| `SMTP_PORT` | No | SMTP port; defaults to 587 (STARTTLS). Set `SMTP_USE_SSL=true` for implicit TLS. |
| `SMTP_USERNAME`, `SMTP_PASSWORD` | No | SMTP credentials when authentication is required. |
| `JWT_EXP_HOURS` | No | Token lifetime; defaults to 24 hours. |
| `WHISPER_MODEL` | No | faster-whisper model name; defaults to `base`. |
| `STORAGE_BACKEND` | No | `local` by default, or `s3`/`r2` for object storage. |
| `STORAGE_LOCAL_DIR` | No | Local answer storage directory; defaults to `backend/uploads`. |
| `R2_ACCOUNT_ID`, `R2_ACCESS_KEY_ID`, `R2_SECRET_ACCESS_KEY`, `R2_BUCKET_NAME` | Only for R2 | Cloudflare R2 account, credentials, and bucket. |

Question drafting, answer evaluation, and follow-up generation use the configured local Ollama server. If Ollama is unavailable, the interview can still finish and the report may request teacher review. `faster-whisper` is included in `backend/requirements.txt`; its configured model may download on first use. Local storage is the code default; S3 and R2 are also supported. With `STORAGE_BACKEND=r2`, the four R2 settings above are required, and private answer playback is served through the authenticated API.

## Frontend and browser behavior

For dependency installation and daily frontend startup commands, see [Daily startup](#b-daily-startup) above. Open the local Vite address (normally `http://127.0.0.1:5173`). Vite proxies `/api` requests to Flask on port 5000. Use a current Chrome, Edge, or Firefox browser and allow microphone access. Question speech uses the browser's speech synthesis; question text remains visible if speech synthesis is unavailable.

### Role dashboards

- Students see assigned interviews, continue sessions, and view completed reports and their saved recordings.
- Teachers see their assigned sessions and can open completed reports to score answers, add per-question or overall remarks, and set per-question or overall score overrides.
- Admins can approve/reject and filter student/teacher accounts, review campus analytics and reports needing review, adjust score weights, open recent reports, and download per-report or all-report exports.

## Account and admin endpoints

- `POST /api/auth/register` accepts `full_name`, `email`, `password`, `role` (`student` or `teacher`), `course_id`, `semester` (`1st`–`8th`), and `academic_year`. Course and class group are required for both roles; `roll_number` and `employee_id` are optional. New accounts are always `PENDING`.
- `POST /api/auth/login` returns a bearer token only for `ACTIVE` accounts. `GET /api/auth/me` returns the authenticated account.
- `POST /api/auth/forgot-password` accepts an email and sends a reset link when an account exists. Configure `SMTP_HOST` and `SMTP_FROM` (and SMTP credentials if needed) to enable delivery. Links expire after 30 minutes. `POST /api/auth/reset-password` accepts the link's `token` and a new password of at least 12 characters.
- `GET /api/admin/courses` lists BCA, MCA, and BSC IT; `GET /api/admin/semesters` lists configured course-semester-academic-year class groups. These are public for registration. Admins create class groups with `POST /api/admin/semesters` and `{ "course_id": 1, "semester": "1st", "academic_year": "2026–27" }`. The legacy department/batch table names remain internal compatibility names; teacher batch assignments now mean exact course-semester-year groups.
- Admin-only account routes: `GET /api/admin/pending-users`, `GET /api/admin/users` (optional `role` and `account_status` filters), and `POST /api/admin/users/<user_id>/status` with `{"account_status":"ACTIVE"}` or `{"account_status":"REJECTED"}`.
- Admin-only settings route: `GET` or `PATCH /api/admin/settings` with `content_weight` and/or `delivery_weight`. Values must be between 0 and 1 and sum to 1.0.
- `GET /api/admin/analytics` and `GET /api/admin/reports.xlsx` are admin-only.
- `GET /api/admin/reports` lists up to 100 recent reports for the admin dashboard; individual reports also have PDF and Excel downloads.

API errors use a JSON object with an `error` message and a stable `code` field. Admin requests require `Authorization: Bearer <token>`.

## Student interview endpoints

- `GET /api/interviews` lists interviews assigned to the signed-in student.
- `GET /api/interviews/<id>` returns the current session state and question.
- `POST /api/interviews/<id>/start` requires `{"consent": true}` and moves a scheduled interview into progress.
- `POST /api/interviews/<id>/questions/<interview_question_id>/answer` accepts multipart form data with an `audio` file, stores it through the configured storage provider, and queues background transcription, audio analysis, and evaluation. Usable transcripts are evaluated against the assigned rubric with the configured local Ollama model. Unavailable transcription or Ollama leaves the session usable and may flag the answer for teacher review.
- `POST /api/interviews/<id>/advance` accepts `{"intent":"REPEAT"}`, `{"intent":"SKIP"}`, or `{"intent":"DONE"}` for explicit controls. `REPEAT` keeps the current question, `SKIP` advances one question, and `DONE` ends the interview immediately. Spoken commands are recognized only when the entire transcript matches a supported command phrase.
- `GET /api/interviews/<id>/questions/<interview_question_id>/audio` streams a stored answer only to the student, assigned teacher, or admin with an active bearer token.
- After all queued answers are processed or marked for teacher review, the worker finalizes the interview report. `GET /api/interviews/<id>/report` returns scores, feedback, review flags, and answer details to the student, assigned teacher, or admin. `PATCH` on the same route lets the assigned teacher or admin add remarks and question or overall score overrides.
- `GET /api/interviews/<id>/report.pdf` and `GET /api/interviews/<id>/report.xlsx` export an individual report for its student, assigned teacher, or admin. `GET /api/admin/reports.xlsx` exports all reports to admins.

Reports state that QueMe’s AI feedback supports practice and learning. It is decision support, not a final placement decision, and should be considered alongside teacher review. The notice appears on the report screen, in PDFs, and on the Guidance worksheet in Excel exports.

Answer uploads are limited to 25 MB. Reports use `NEEDS_REVIEW` when an answer lacks a usable transcript, automated rubric evaluation is unavailable, an answer was skipped, or no score could be calculated. Teacher overrides become the final score and appear in both exports.

## Teacher authoring endpoints

All authoring routes require an active teacher bearer token.

- Teacher workspace routes: `GET /api/teacher/analytics` returns teacher-scoped interview, student, review, and average-score counts; `GET /api/teacher/students?batch_id=<id>` lists active students in the selected class group for assignment.
- `GET/POST /api/questions` list/create questions; `GET/PUT/PATCH/DELETE /api/questions/<id>` read or manage a teacher-owned question. Use `POST /api/questions/generate` with `topic`, `question_type`, and `difficulty` to request up to 10 drafts from the configured local Ollama model. In Create interview, teachers review/edit and select drafts; adding selected drafts calls `POST /api/questions/commit-drafts`, which saves them to that teacher's reusable question bank and reuses an existing question when normalized text matches. The returned question IDs are added to the template selection; removing them from that template does not delete library records. If Ollama is unavailable, the endpoint returns `manual_fallback: true` and manual CRUD remains available.
- `GET/POST /api/rubrics` list/create rubrics; `GET/PUT/PATCH/DELETE /api/rubrics/<id>` read or manage teacher-owned rubrics. The four admin-seeded rubrics are available for use but read-only.
- `GET/POST /api/templates` list/create templates. A template body includes `title`, optional `description` and `duration_minutes`, and an ordered `questions` array such as `[{"question_id": 12, "rubric_id": 3}]`. Array order becomes question order. Read, update, and delete with `GET/PUT/PATCH/DELETE /api/templates/<id>`.
- `POST /api/interviews` assigns a teacher-owned template. Send `template_id` and exactly one of `student_id` or `batch_id` (the selected course-semester-year class group); optional `scheduled_at` is ISO-8601. Class-group assignment creates one scheduled interview per active student and copies the ordered template questions and rubrics into each interview. `GET /api/interviews` lists the signed-in teacher's assignments or the signed-in student's assigned interviews.
- A teacher can cancel a scheduled assignment with `POST /api/interviews/<id>/cancel`. Interviews already in progress or completed cannot be cancelled. Completed sessions link to the existing authorized report/review and PDF/Excel export routes.

Questions, rubrics, and templates already used in interviews are protected from edits/deletion that could change historical records. Deactivate an old question instead of deleting it.

## Optional sequential answer evaluation

The default `EVALUATION_MODE=ollama` keeps evaluation local. Set
`EVALUATION_MODE=ollama_openai_sequential` to evaluate answers with Ollama first,
then independently with OpenAI. Configure backend `OPENAI_API_KEY`,
`OPENAI_EVALUATION_MODEL` (default `gpt-5.4-mini`), and `OPENAI_EVALUATION_TIMEOUT`
(default 120 seconds). Existing `OLLAMA_*` settings still apply. Restart API and worker
processes after configuration changes. This mode sends question, transcript, rubric and
reference guidance as text to OpenAI using Responses Structured Outputs with `store=False`;
recordings and delivery metrics are not sent. No Gemini provider is used.

From the repository root install dependencies with:
`backend\.venv\Scripts\python.exe -m pip install -r backend\requirements.txt`.

Both providers must pass the same concept/evidence validation. Agreement means the same
accuracy category and a score difference strictly below 2 points; the Ollama score is then
used provisionally, without averaging. Disagreement, uncertainty, or an unavailable provider
requires teacher review, with no aggregate content/combined score. Individual valid scores
remain visible for comparison. Teacher overrides retain precedence. SDK retries are disabled;
the durable worker retries transient failures only, preserving checkpointed provider outcomes.
Invalid structured assessments get at most one repair attempt. Existing saved reports are
not re-evaluated or rewritten. Concept relevance still requires model judgment and teacher
review; exact transcript matches alone do not prove understanding.

### Ollama then Groq

The opt-in `ollama_groq_sequential` mode uses the same validator, checkpoint storage,
and agreement policy described above. It makes calls only to local Ollama and Groq's
chat completions endpoint; it has no Gemini, OpenAI API, or paid-provider fallback.
The existing `ollama_openai_sequential` mode remains available separately.

Set these backend environment values (root `.env` takes precedence over `backend/.env`):

```dotenv
EVALUATION_MODE=ollama_groq_sequential
OLLAMA_MODEL=qwen3:1.7b
GROQ_API_KEY=your-groq-key
GROQ_EVALUATION_MODEL=openai/gpt-oss-20b
GROQ_EVALUATION_TIMEOUT=120
```

Keep the key private. No OpenAI key is needed for this mode. The default GPT-OSS model
uses strict JSON-schema output. Other documented strict-capable Groq models also use
strict output; the safeguard model uses best-effort schema output, and other model
names use JSON-object output followed by the same backend validation. See
[Groq Structured Outputs](https://console.groq.com/docs/structured-outputs).
No additional dependency is needed for Groq: its adapter uses Python's standard HTTP
library, with retries owned by the existing worker and structured-repair loop.

Each finished provider step is committed to the answer's `evaluation_json.provider_results`
under `ollama` or `groq`, including provider/model/status, validated assessment, or a sanitized
unavailability reason. Completed results survive worker retry/restart for the same answer.
Reports, student feedback, PDF and Excel expose the saved outcomes without re-evaluating
historical interviews. Daily token/request quota exhaustion goes directly to teacher review;
transient rate limits and connection errors use bounded worker retries. No migration is required.

From the repository root, install the existing dependencies if needed:

```powershell
backend\.venv\Scripts\python.exe -m pip install -r backend\requirements.txt
```

After changing configuration, press **Ctrl+C** in the existing worker and API terminals.
Start each again in a separate terminal; do not run a second worker alongside the first:

```powershell
Set-Location C:\Users\2525201\Desktop\QueMe\backend
.\.venv\Scripts\python.exe -m flask --app run.py process-answer-jobs
```

```powershell
Set-Location C:\Users\2525201\Desktop\QueMe\backend
.\.venv\Scripts\python.exe -m flask --app run.py --debug run
```

For the frontend, if it is not already running:

```powershell
Set-Location C:\Users\2525201\Desktop\QueMe\frontend
npm run dev
```

These startup commands process real queued answers. Automated verification uses mocked
providers and isolated databases/storage; a live smoke test is a separate step.
