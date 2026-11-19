# QueMe

QueMe is a campus virtual interview assistant. The backend is a Flask REST API. SQLite is the default database; PostgreSQL can be selected with `DATABASE_URL`.

## Development Setup & Running Commands

QueMe runs on **Windows and Linux**. Use 64-bit Python **3.11** for the simplest setup; the compatibility workflow covers Python 3.10, 3.11, and 3.12 on both systems. Use Node.js 22 LTS and npm for the frontend. The current pinned NumPy/audio stack is intended for Python 3.10-3.12; use one of those versions rather than Python 3.13+.

The backend uses portable `pathlib` paths, CPU/int8 transcription, and native OS locks (`msvcrt` on Windows, `fcntl` on Linux). You do not need CUDA to run transcription. Install dependencies separately on each operating system; virtual environments and `node_modules` cannot be copied between Windows and Linux. The frontend uses browser APIs on both platforms. For the implementation overview, see [README2.md](README2.md).

### A. Initial setup

Start in your cloned repository's root directory. Choose the commands for your shell.

**Windows PowerShell - create configuration and the backend environment:**

```powershell
if (-not (Test-Path ./.env)) { Copy-Item ./backend/.env.example ./.env }
py -3.11 -c "import secrets; print(secrets.token_urlsafe(48))"
cd backend
py -3.11 -m venv .venv
./.venv/Scripts/Activate.ps1
python -m pip install -r requirements.txt
```

If PowerShell blocks activation, use `./.venv/Scripts/python.exe` in place of `python` for backend commands; activation is optional.

**Linux Bash - create configuration and the backend environment:**

Install Python 3.11 with its `venv` support, Node.js 22, npm, and curl using your distribution's packages or the official installers. On Ubuntu/Debian the virtual-environment package is `python3.11-venv` when using Python 3.11; the distribution's default Python 3.10-3.12 can also be used with its matching venv package. Replace `python3.11` below with that interpreter if needed.

```bash
[ -f .env ] || cp backend/.env.example .env
python3.11 -c "import secrets; print(secrets.token_urlsafe(48))"
cd backend
python3.11 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
```

Activate the environment in every backend terminal. On Linux, `.venv/bin/python` also works without activation. PyAV wheels bundle FFmpeg for audio decoding; no separate FFmpeg installation is needed for the standard wheel-based setup. See the [faster-whisper requirements](https://github.com/SYSTRAN/faster-whisper#requirements).

**Configuration - both platforms:**

Edit the root `.env` and set `SECRET_KEY` to the generated secret, plus `ADMIN_EMAIL` and `ADMIN_PASSWORD` (at least 12 characters). Keep these private. Root `.env` is loaded first, then `backend/.env` supplies any unset values; existing process environment variables take precedence.

With no `DATABASE_URL`, the database is `backend/queme.db`. PostgreSQL is optional. Relative `STORAGE_LOCAL_DIR` and `LOG_DIR` values resolve from `backend/`, regardless of your terminal's current directory. Prefer portable relative paths such as `uploads` and `logs`. For absolute paths, use the current machine's path, for example `/srv/queme/uploads` on Linux or `C:/QueMe/uploads` on Windows. Do not reuse Windows drive-letter paths on Linux.

**Ollama - install separately on each machine:**

- Windows: install and start the [Ollama Windows application](https://ollama.com/download/windows).
- Linux: follow the [official Linux installation guide](https://docs.ollama.com/linux). Start the installed service with `sudo systemctl start ollama`, or run `ollama serve` in a separate terminal if you are not using a service. Start only one Ollama server.

With Ollama running, these commands work in both shells:

```text
ollama pull qwen3:1.7b
ollama list
```

The defaults are `OLLAMA_BASE_URL=http://localhost:11434` and `OLLAMA_MODEL=qwen3:1.7b`. If overridden, pull that exact model tag. The Whisper model may download on its first transcription.

**Initialize the database - both platforms, from `backend/` with the environment active:**

```text
python -m flask --app run.py db upgrade
python -m flask --app run.py seed
```

Migrations are checked in under `backend/migrations/versions/`; do not run `db init`. Seed creates baseline data and does not reset an existing admin password.

**Install frontend dependencies - both platforms, from `backend/`:**

```text
cd ../frontend
npm ci
```

### B. Daily startup

Start Ollama, then use three separate terminals opened at the repository root.

**Terminal 1 - Answer worker:**

Windows PowerShell:

```powershell
cd backend
./.venv/Scripts/Activate.ps1
python -m flask --app run.py process-answer-jobs
```

Linux Bash:

```bash
cd backend
source .venv/bin/activate
python -m flask --app run.py process-answer-jobs
```

The worker continuously polls the durable queue. Run only one worker per installation; an OS lock rejects duplicate workers. `--once` processes at most one available job and exits, and can change real queued answers.

**Terminal 2 - Flask API:**

Windows PowerShell:

```powershell
cd backend
./.venv/Scripts/Activate.ps1
python -m flask --app run.py --debug run
```

Linux Bash:

```bash
cd backend
source .venv/bin/activate
python -m flask --app run.py --debug run
```

The development API serves `http://127.0.0.1:5000`.

**Terminal 3 - Frontend, both platforms:**

```text
cd frontend
npm run dev
```

Open `http://127.0.0.1:5173` (or the URL Vite prints if the port is busy). Vite proxies `/api` to Flask on port 5000. Allow microphone access; speech synthesis voices depend on the operating system and browser. A remotely hosted interview room requires HTTPS for microphone access.

### C. Run the API without Flask's development server

[Waitress](https://docs.pylonsproject.org/projects/waitress/en/stable/) is installed on both platforms. From `backend/`, with the virtual environment active, replace the Flask API command with:

```text
python -m waitress --listen=127.0.0.1:5000 --max-request-body-size=33554432 run:app
```

Keep the answer worker running separately. This serves the backend API; the frontend still needs Vite during development or separate static hosting for `frontend/dist` after `npm run build`. Gunicorn remains available on Linux and is skipped when installing on Windows. Use a reverse proxy and HTTPS when deploying for remote browser access.

### D. Health and verification

**Windows PowerShell - inspect health, models, processes, ports, and logs from the root:**

```powershell
Invoke-RestMethod -Uri 'http://127.0.0.1:5000/api/health'
Invoke-RestMethod -Uri 'http://localhost:11434/api/tags'
Get-CimInstance Win32_Process |
  Where-Object { $_.CommandLine -match 'flask|waitress|vite|ollama' } |
  Select-Object ProcessId, Name, CommandLine
Get-NetTCPConnection -State Listen |
  Where-Object { $_.LocalPort -in 5000, 5173, 11434 } |
  Select-Object LocalAddress, LocalPort, OwningProcess
Get-Content ./backend/logs/queme.log -Tail 100
Get-Content ./backend/logs/queme.log -Wait
```

**Linux Bash - equivalent diagnostics from the root:**

```bash
curl -fsS http://127.0.0.1:5000/api/health
curl -fsS http://localhost:11434/api/tags
ps -ef | grep -E 'flask|waitress|vite|ollama'
ss -ltnp
tail -n 100 backend/logs/queme.log
tail -f backend/logs/queme.log
```

The health response includes database status and worker state: `healthy` means processing, `inactive` means running and idle, `failing` means repeated database failures, `unhealthy` means starting/retrying/stale heartbeat, and `not_running` means no worker holds the host lock. Heartbeat age, failure count, and last job ID/time are also included. `ollama list` and `/api/tags` check availability, not inference. To test an actual model response in either shell:

```text
ollama run qwen3:1.7b "Reply with READY only."
```

**Automated verification - either platform, active backend environment:**

```text
cd backend
python -m unittest discover -s tests -v
```

Run from the root in another terminal to check the frontend:

```text
cd frontend
npm run build
```

Tests use isolated databases/storage and mock external inference. Native audio imports/decoding and cross-process file locks are checked without downloading models. `.github/workflows/compatibility.yml` runs installation, backend tests, database migrations/seed, and a frontend build on Windows and Ubuntu. CI does not perform live Ollama inference. The frontend build writes `frontend/dist`.

### E. Shutdown

Press **Ctrl+C** in each worker, API, and frontend terminal. For Ollama, use Windows application controls, Ctrl+C for a foreground Linux server, or `sudo systemctl stop ollama` for the Linux service. Inspect processes before stopping a remaining PID; use `Stop-Process -Id <PID>` on Windows or `kill <PID>` on Linux.

### F. Troubleshooting and moving between platforms

- **Worker missing or stuck:** Check `/api/health`, the process list, and `backend/logs/queme.log` / `errors.log`. Start or gracefully restart the worker with the commands above. Do not delete the worker lock file: it can remain after shutdown, and only the OS lock indicates a running worker. Recovery resumes interrupted jobs from their saved stage.
- **Ollama unavailable/model missing:** Check `/api/tags`, start Ollama, and pull the configured model. A long transcription or inference can make the heartbeat stale; inspect activity before restarting.
- **Database errors:** Verify `DATABASE_URL`, keep existing database files intact, and apply migrations to the same database used by the API. Migrations do not run automatically.
- **Ports busy:** Inspect ports using the commands above, then stop only the intended process. Defaults are API 5000, Vite 5173, and Ollama 11434.
- **Linux install errors:** Use a supported 64-bit Python 3.10-3.12 and a fresh virtual environment. Install the matching venv package if creation fails. If your distribution cannot use the SoundFile wheel, install its system `libsndfile` package (for example `libsndfile1` on Debian/Ubuntu). Minimal containers or other CPU architectures may require additional native libraries or builds.
- **Moving an existing installation:** Stop the API and worker before copying data. Recreate `.venv` and run `npm ci` on the destination. Transfer the configured database and local uploads together, or reconnect to the same PostgreSQL/object storage services. Update machine-specific paths and credentials in `.env`. Keep upload directory names and storage keys unchanged; Linux paths are case-sensitive. Host lock/heartbeat files and logs are runtime artifacts, not migration data. Never run workers on two hosts against the same queue: the lock is local to a host.

Health checks, model listing, process/port inspection, and log reads only inspect state. Dependency installation, model pulls, migrations, seeding, and running the answer worker change state.

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

From `backend/` with the platform-specific virtual environment activated, install dependencies with `python -m pip install -r requirements.txt`.

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

From `backend/` with the platform-specific virtual environment activated:

```text
python -m pip install -r requirements.txt
```

After changing configuration, press **Ctrl+C** in the existing worker and API terminals, then restart each using [Daily startup](#b-daily-startup). Those instructions cover Windows PowerShell and Linux Bash. Keep only one answer worker running. Start the frontend with `npm run dev` from `frontend/` if needed.

These startup commands process real queued answers. Automated verification uses mocked
providers and isolated databases/storage; a live smoke test is a separate step.
